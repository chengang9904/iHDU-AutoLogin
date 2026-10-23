import socket
import struct
import unittest
from unittest.mock import patch

from requests import Request, Response
from requests.adapters import HTTPAdapter

import login


class FakeSocket:
    def __init__(self, payload: bytes):
        self.payload = bytearray(payload)
        self.sent = b""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def settimeout(self, _):
        pass

    def sendall(self, data):
        self.sent += data

    def recv(self, size):
        data = self.payload[:size]
        del self.payload[:size]
        return bytes(data)


class LoginHelpersTest(unittest.TestCase):
    def test_parse_jsonp(self):
        self.assertEqual(login.parse_jsonp('callback({"error":"ok"})', "callback"), {
            "error": "ok"
        })
        self.assertEqual(login.parse_jsonp('callback({"error":"ok"});', "callback"), {
            "error": "ok"
        })
        self.assertEqual(login.parse_jsonp('{"error":"ok"}', "callback"), {
            "error": "ok"
        })

    def test_parse_jsonp_rejects_invalid_payload(self):
        with self.assertRaisesRegex(ValueError, "invalid JSON/JSONP"):
            login.parse_jsonp("callback(not-json)", "callback")

    def test_tcp_dns_resolver_extracts_a_record(self):
        qname = b"\x05login\x03hdu\x03edu\x02cn\x00"
        question = qname + struct.pack("!HH", 1, 1)
        answer = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 600, 4)
        answer += socket.inet_aton("192.168.112.30")
        message = struct.pack("!HHHHHH", 0x1234, 0x8180, 1, 1, 0, 0)
        message += question + answer
        fake_socket = FakeSocket(struct.pack("!H", len(message)) + message)

        with patch.object(login, "randbits", return_value=0x1234), patch.object(
            socket, "create_connection", return_value=fake_socket
        ):
            result = login.resolve_ipv4_over_tcp(
                "login.hdu.edu.cn", "210.32.32.1"
            )

        self.assertEqual(result, ["192.168.112.30"])
        self.assertGreater(len(fake_socket.sent), 2)

    def test_https_adapter_preserves_hostname_and_restores_request(self):
        adapter = login.ResolvedHTTPSAdapter(
            "login.hdu.edu.cn", "192.168.112.30"
        )
        request = Request("GET", "https://login.hdu.edu.cn/status").prepare()

        def fake_send(_adapter, prepared, **_kwargs):
            self.assertEqual(prepared.url, "https://192.168.112.30/status")
            self.assertEqual(prepared.headers["Host"], "login.hdu.edu.cn")
            response = Response()
            response.status_code = 200
            response.request = prepared
            response.url = prepared.url
            return response

        with patch.object(HTTPAdapter, "send", fake_send):
            response = adapter.send(request)

        self.assertEqual(request.url, "https://login.hdu.edu.cn/status")
        self.assertNotIn("Host", request.headers)
        self.assertEqual(response.url, "https://login.hdu.edu.cn/status")

    def _scheduled_jobs(self, refresh_interval_days):
        with patch.object(login, "REFRESH_INTERVAL_DAYS", refresh_interval_days), patch.object(
            login, "_load_auths", return_value=[{"username": "u", "password": "p"}]
        ), patch.object(login, "logger"), patch.object(
            login, "BlockingScheduler"
        ) as scheduler_class:
            login.main()
        return [call.args[0] for call in scheduler_class.return_value.add_job.call_args_list]

    def test_main_schedules_refresh_by_default(self):
        self.assertEqual(self._scheduled_jobs(3), [login.refresh, login.check])

    def test_main_skips_refresh_when_disabled(self):
        self.assertEqual(self._scheduled_jobs(0), [login.check])


if __name__ == "__main__":
    unittest.main()
