import socket
import struct
from datetime import datetime
from hashlib import sha1
from json import JSONDecodeError, dumps, load, loads
from os import getenv
from random import choice, shuffle
from re import compile
from secrets import randbits
from sys import stdout
from time import sleep, time
from urllib.parse import urlsplit, urlunsplit

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from requests import Response, Session
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException
from urllib3 import PoolManager

from utils.base import b64encode
from utils.device import devices
from utils.hash import md5
from utils.xencode import xencode

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 "
        "Safari/537.36 Edg/128.0.0.0"
    )
}
PORTAL_HOSTS = (
    "https://login.hdu.edu.cn",
    "https://portal.hdu.edu.cn",
)
DNS_SERVER = getenv("IHDU_DNS_SERVER", "210.32.32.1")
REQUEST_TIMEOUT = (4, 8)
MAX_AC_ID = 10
# Schedule times are Beijing time; the host clock may be set to another zone.
SCHEDULE_TIMEZONE = "Asia/Shanghai"
REFRESH_INTERVAL_DAYS = 3
# The portal applies a logout about 10 seconds after the request.
LOGOUT_SETTLE_SECONDS = 30
CHECK_INTERVAL_MINUTES = 3
# The gateway often forces users offline between 01:00 and 02:00.
BUSY_CHECK_INTERVAL_SECONDS = 30

auths = []


class PortalUnavailableError(RuntimeError):
    """Raised when none of the campus portal addresses can be reached."""


def _read_exact(stream: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = stream.recv(size - len(data))
        if not chunk:
            raise OSError("DNS server closed the TCP connection early")
        data.extend(chunk)
    return bytes(data)


def _skip_dns_name(packet: bytes, offset: int) -> int:
    """Return the first byte after a possibly compressed DNS name."""
    while True:
        if offset >= len(packet):
            raise ValueError("truncated DNS name")
        length = packet[offset]
        if length & 0xC0 == 0xC0:
            if offset + 1 >= len(packet):
                raise ValueError("truncated DNS compression pointer")
            return offset + 2
        offset += 1
        if length == 0:
            return offset
        offset += length


def resolve_ipv4_over_tcp(hostname: str, dns_server: str, timeout: float = 4) -> list[str]:
    """Resolve A records over DNS/TCP without changing the OS DNS settings."""
    labels = hostname.rstrip(".").encode("idna").split(b".")
    if any(not label or len(label) > 63 for label in labels):
        raise ValueError(f"invalid DNS name: {hostname}")

    transaction_id = randbits(16)
    question_name = b"".join(bytes((len(label),)) + label for label in labels) + b"\0"
    query = struct.pack("!HHHHHH", transaction_id, 0x0100, 1, 0, 0, 0)
    query += question_name + struct.pack("!HH", 1, 1)  # A, IN

    with socket.create_connection((dns_server, 53), timeout=timeout) as stream:
        stream.settimeout(timeout)
        stream.sendall(struct.pack("!H", len(query)) + query)
        response_size = struct.unpack("!H", _read_exact(stream, 2))[0]
        response = _read_exact(stream, response_size)

    if len(response) < 12:
        raise ValueError("truncated DNS response")
    response_id, flags, qd_count, answer_count, _, _ = struct.unpack(
        "!HHHHHH", response[:12]
    )
    if response_id != transaction_id:
        raise ValueError("DNS transaction ID mismatch")
    if flags & 0x000F:
        raise OSError(f"DNS server returned error code {flags & 0x000F}")

    offset = 12
    for _ in range(qd_count):
        offset = _skip_dns_name(response, offset)
        if offset + 4 > len(response):
            raise ValueError("truncated DNS question")
        offset += 4

    addresses = []
    for _ in range(answer_count):
        offset = _skip_dns_name(response, offset)
        if offset + 10 > len(response):
            raise ValueError("truncated DNS answer")
        record_type, record_class, _, data_length = struct.unpack(
            "!HHIH", response[offset:offset + 10]
        )
        offset += 10
        record_data = response[offset:offset + data_length]
        if len(record_data) != data_length:
            raise ValueError("truncated DNS record data")
        offset += data_length
        if record_type == 1 and record_class == 1 and data_length == 4:
            addresses.append(socket.inet_ntoa(record_data))

    if not addresses:
        raise OSError(f"no A record returned for {hostname}")
    return addresses


class ResolvedHTTPSAdapter(HTTPAdapter):
    """Connect to an IP while retaining the hostname for HTTPS SNI and checks."""

    def __init__(self, hostname: str, address: str, **kwargs):
        self.hostname = hostname
        self.address = address
        super().__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["server_hostname"] = self.hostname
        pool_kwargs["assert_hostname"] = self.hostname
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            **pool_kwargs,
        )

    def send(self, request, **kwargs) -> Response:
        original_url = request.url
        original_host = request.headers.get("Host")
        parsed = urlsplit(original_url)
        port = parsed.port
        network_location = self.address
        if ":" in self.address:
            network_location = f"[{self.address}]"
        if port and port != 443:
            network_location = f"{network_location}:{port}"

        request.url = urlunsplit(
            (parsed.scheme, network_location, parsed.path, parsed.query, parsed.fragment)
        )
        request.headers["Host"] = self.hostname if not port else f"{self.hostname}:{port}"
        try:
            response = super().send(request, **kwargs)
            response.url = original_url
            return response
        finally:
            request.url = original_url
            if original_host is None:
                request.headers.pop("Host", None)
            else:
                request.headers["Host"] = original_host


def parse_jsonp(payload: str, callback: str) -> dict:
    text = payload.strip()
    prefix = f"{callback}("
    if text.endswith(";"):
        text = text[:-1].rstrip()
    if text.startswith(prefix) and text.endswith(")"):
        text = text[len(prefix):-1]
    try:
        result = loads(text)
    except JSONDecodeError as exc:
        raise ValueError("portal returned invalid JSON/JSONP") from exc
    if not isinstance(result, dict):
        raise ValueError("portal response is not a JSON object")
    return result


def _safe_result(result: dict) -> dict:
    """Remove short-lived authentication secrets before debug logging."""
    return {
        key: "<redacted>" if key in {"access_token", "challenge"} else value
        for key, value in result.items()
    }


class Manager(Session):

    def __init__(self, username: str = "", password: str = ""):
        super().__init__()
        self.acid: int = 0
        self.n: str = "200"
        self.vtype: str = "1"
        self.enc_ver: str = "srun_bx1"
        self.username = username
        self.password = password
        self.logger = logger
        # Campus authentication must not accidentally use an environment proxy.
        self.trust_env = False
        self.host = self.get_host()
        self.token = None
        self.checksum = None
        self.info = None

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        return super().request(method, url, **kwargs)

    def _probe(self, host: str) -> None:
        self.get(host, headers=HEADERS)

    def get_host(self) -> str:
        failures = []
        for host in PORTAL_HOSTS:
            hostname = urlsplit(host).hostname
            try:
                self._probe(host)
                return host
            except RequestException as exc:
                failures.append(f"{host} via system DNS: {exc}")

            try:
                addresses = resolve_ipv4_over_tcp(hostname, DNS_SERVER)
            except (OSError, ValueError) as exc:
                failures.append(f"{host} via DNS/TCP: {exc}")
                continue

            for address in addresses:
                adapter = ResolvedHTTPSAdapter(hostname, address)
                self.mount(host, adapter)
                try:
                    self._probe(host)
                    self.logger.warning(
                        f"System DNS failed; using {hostname} -> {address} "
                        f"resolved through DNS/TCP {DNS_SERVER}"
                    )
                    return host
                except RequestException as exc:
                    failures.append(f"{host} via {address}: {exc}")

        for failure in failures:
            self.logger.info(f"Portal probe failed: {failure}")
        raise PortalUnavailableError("all campus portal endpoints are unavailable")

    def get_ip(self) -> str:
        response = self.get(self.host + "/srun_portal_pc", headers=HEADERS)
        response.raise_for_status()
        match = compile(
            r"((1\d{2}|25[0-5]|2[0-4]\d|[1-9]?\d)\.){3}"
            r"(25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)"
        ).search(response.text)
        if not match:
            raise PortalUnavailableError("portal page did not contain a client IPv4 address")
        return match.group()

    def get_token(self, client_ip: str) -> str:
        callback = f"jQuery1124015280105355320628_{round(time() * 1000)}"
        params = {
            "callback": callback,
            "username": self.username,
            "ip": client_ip,
            "_": round(time() * 1000)
        }
        response = self.get(
            self.host + "/cgi-bin/get_challenge", headers=HEADERS, params=params
        )
        response.raise_for_status()
        result = parse_jsonp(response.text, callback)
        token = result.get("challenge")
        if not token:
            raise PortalUnavailableError(
                f"portal challenge failed: {result.get('error') or 'missing challenge'}"
            )
        self.logger.debug("Challenge received")
        return token

    def get_info(self, client_ip: str) -> str:
        return "{SRBX1}" + b64encode(xencode(dumps({
            "username": self.username,
            "password": self.password,
            "ip": client_ip,
            "acid": str(self.acid),
            "enc_ver": self.enc_ver,
        }), self.token))

    def get_checksum(self, client_ip: str) -> str:
        checksum = self.token + self.username
        checksum += self.token + md5(self.password, self.token)
        checksum += self.token + str(self.acid)
        checksum += self.token + client_ip
        checksum += self.token + self.n
        checksum += self.token + self.vtype
        checksum += self.token + self.info
        return sha1(checksum.encode()).hexdigest()

    def login(self) -> dict:
        while self.acid <= MAX_AC_ID:
            client_ip = self.get_ip()
            self.token = self.get_token(client_ip)
            self.info = self.get_info(client_ip)
            self.checksum = self.get_checksum(client_ip)
            callback = f"jQuery1124015280105355320628_{round(time() * 1000)}"
            device = choice(devices)
            params = {
                "callback": callback,
                "action": "login",
                "username": self.username,
                "password": "{MD5}" + md5(self.password, self.token),
                "os": device[0],
                "name": device[1],
                "double_stack": "0",
                "chksum": self.checksum,
                "info": self.info,
                "ac_id": str(self.acid),
                "ip": client_ip,
                "n": self.n,
                "type": self.vtype,
                "_": round(time() * 1000),
            }
            response = self.get(
                self.host + "/cgi-bin/srun_portal", headers=HEADERS, params=params
            )
            response.raise_for_status()
            result = parse_jsonp(response.text, callback)
            self.logger.debug(_safe_result(result))
            if result.get("suc_msg"):
                self.logger.success(
                    f"login: {result['suc_msg']} {self.username} "
                    f"{result.get('online_ip')}"
                )
                return result

            error_message = str(result.get("error_msg") or "")
            self.logger.error(f"{result.get('error')}: {error_message}")
            if "BAS" in error_message or "Nas" in error_message:
                self.acid += 1
                if self.acid <= MAX_AC_ID:
                    self.logger.error(
                        f"ac_id error, retrying with ac_id={self.acid} in 5 seconds..."
                    )
                    sleep(5)
                    continue
                raise PortalUnavailableError(
                    f"no working ac_id found in range 0..{MAX_AC_ID}"
                )
            if "E2901" in error_message:
                self.logger.error("username or password error")
                result["error_msg"] = "4xx"
            elif "E2606" in error_message:
                self.logger.error("user is disabled")
                result["error_msg"] = "4xx"
            return result

        raise PortalUnavailableError("login stopped after exhausting ac_id values")

    def logout(self) -> dict:
        callback = f"jQuery112405185119642573086_{round(time() * 1000)}"
        timestamp = round(time())
        status = self.check()
        username = status.get("user_name") or self.username
        client_ip = status.get("online_ip") or self.get_ip()
        params = {
            "callback": callback,
            "username": username,
            "ip": client_ip,
            "time": timestamp,
            "unbind": "1",
            "sign": sha1(
                f"{timestamp}{username}{client_ip}1{timestamp}".encode()
            ).hexdigest(),
            "_": round(time() * 1000)
        }
        response = self.get(
            self.host + "/cgi-bin/rad_user_dm", headers=HEADERS, params=params
        )
        response.raise_for_status()
        result = parse_jsonp(response.text, callback)
        self.logger.debug(_safe_result(result))
        self.logger.info(f'logout: {result.get("error")}')
        return result

    def check(self) -> dict:
        callback = f"jQuery112405185119642573086_{round(time() * 1000)}"
        params = {
            "callback": callback,
            "_": round(time() * 1000)
        }
        response = self.get(
            self.host + "/cgi-bin/rad_user_info", headers=HEADERS, params=params
        )
        response.raise_for_status()
        result = parse_jsonp(response.text, callback)
        self.logger.debug(_safe_result(result))
        self.logger.info(f'check: {result.get("error")}')
        return result


def _login_with_available_account(manager: Manager) -> None:
    candidates = list(auths)
    shuffle(candidates)
    for auth in candidates:
        manager.username = auth["username"]
        manager.password = auth["password"]
        result = manager.login()
        if result.get("error_msg") != "4xx":
            return
        logger.warning("Account rejected; trying the next configured account")
        sleep(2)
    logger.error("All configured accounts were rejected")


def refresh() -> None:
    logger.debug("Try to refresh...")
    try:
        auth = choice(auths)
        manager = Manager(auth["username"], auth["password"])
        manager.logout()
        logger.debug(f"Waiting {LOGOUT_SETTLE_SECONDS}s for logout to take effect...")
        sleep(LOGOUT_SETTLE_SECONDS)
        _login_with_available_account(manager)
    except (PortalUnavailableError, RequestException, OSError, ValueError) as exc:
        logger.error(f"Refresh deferred: {exc}")


def check() -> None:
    logger.debug("Check status...")
    try:
        manager = Manager()
        status = manager.check()
        if status.get("error") != "ok":
            logger.warning(f"{status.get('error')}, try to login...")
            _login_with_available_account(manager)
    except (PortalUnavailableError, RequestException, OSError, ValueError) as exc:
        logger.error(f"Network check deferred: {exc}")


def _load_auths(path: str = "auth.json") -> list[dict]:
    with open(path, "r", encoding="utf-8") as auth_file:
        data = load(auth_file)
    if not isinstance(data, list) or not data:
        raise ValueError("auth.json must contain a non-empty list")
    for item in data:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("username"), str)
            or not item["username"]
            or not isinstance(item.get("password"), str)
            or not item["password"]
        ):
            raise ValueError("each auth.json entry must contain username and password")
    return data


def main() -> None:
    global auths
    logger.remove()
    logger.add(
        "srun_login.log", rotation="10 MB", level="DEBUG",
        format="<g>{time:MM-DD HH:mm:ss}</g> [<lvl>{level}</lvl>] <c><u>srun_login</u></c> | {message}"
    )
    logger.add(
        stdout, level="INFO",
        format="<g>{time:MM-DD HH:mm:ss}</g> [<lvl>{level}</lvl>] <c><u>srun_login</u></c> | {message}"
    )
    try:
        auths = _load_auths()
    except (OSError, JSONDecodeError, ValueError) as exc:
        logger.error(f"{exc}, please check auth.json")
        return
    scheduler = BlockingScheduler()
    scheduler.add_job(
        refresh,
        "interval",
        days=REFRESH_INTERVAL_DAYS,
        coalesce=True,
        max_instances=1,
    )
    # Every 3 minutes, except every 30 seconds from 01:00 to 02:00.
    check_trigger = OrTrigger([
        CronTrigger(
            hour="0,2-23",
            minute=f"*/{CHECK_INTERVAL_MINUTES}",
            timezone=SCHEDULE_TIMEZONE,
        ),
        CronTrigger(
            hour=1,
            second=f"*/{BUSY_CHECK_INTERVAL_SECONDS}",
            timezone=SCHEDULE_TIMEZONE,
        ),
    ])
    scheduler.add_job(
        check,
        check_trigger,
        next_run_time=datetime.now(),
        coalesce=True,
        max_instances=1,
    )
    logger.info("Process started")
    scheduler.start()


if __name__ == "__main__":
    main()
