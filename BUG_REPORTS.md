现在有一些 bug 需要你来解决

这是一个校园网自动登录的脚本，请你阅读仓库的内容之后，现在有几个问题需要解决

先讲一下现在的网络拓扑和背景，校园网上网需要登录然后才能上网，我的主机放在办公室中，然后使用路由器接入校园网，校园网侧不定期在某日的凌晨固定1点24分左右会进行一个登录用户的清理，下线；我需要跑一个脚本去登录。另外我还想通过路由器运行 openclash 插件来实现一个透明代理的功能，这个功能好像又和校园网登录有干扰。

校园网登录验证的门户是 "https://login.hdu.edu.cn", 在网页端输入就能够进行一个跳转，通常这个域名解析记录不会被公共 dns 所获取，所以一般需要使用 dhcp 来进行 dns 服务器的设置 (210.32.32.1)

现在陈述问题，一个是我通过 windows 系统终端设备去进行校园网登录时，总是不能够获取 dns 解析，导致打不开页面，使用脚本时，也经常会 tls 握手失败或者获取不到 dns，脚本日志可以参照 "srun_login.log"，奇怪的当前本机应该已经设置好了 dns 服务器的设置，解析还是会失败：

```bash
(iHDU) PS D:\Desktop\projects\iHDU-AutoLogin> nslookup login.hdu.edu.cn
Server:  ns1.hziee.edu.cn
Address:  210.32.32.1

*** No internal type for both IPv4 and IPv6 Addresses (A+AAAA) records available for login.hdu.edu.cn
```

```bash
*** No internal type for both IPv4 and IPv6 Addresses (A+AAAA) records available for login.hdu.edu.cn
(iHDU) PS D:\Desktop\projects\iHDU-AutoLogin> nslookup login.hdu.edu.cn 210.32.32.1
Server:  ns1.hziee.edu.cn
Address:  210.32.32.1

*** No internal type for both IPv4 and IPv6 Addresses (A+AAAA) records available for login.hdu.edu.cn
```

但是我登录到路由器上，进行 dns 解析，发现是可以获取到的

```bash
root@ImmortalWrt:~# nslookup login.hdu.edu.cn 210.32.32.1
Server:         210.32.32.1
Address:        210.32.32.1:53


Name:   login.hdu.edu.cn
Address: 192.168.112.30

root@ImmortalWrt:~# nslookup login.hdu.edu.cn
Server:         127.0.0.1
Address:        127.0.0.1:53



root@ImmortalWrt:~#
```

路由器的一些接口设置如图所示：

![bug_reports-2026-10-17-20-01-17](https://img.cscat.cn/img/bug_reports-2026-10-17-20-01-17.png)

![BUG_REPORTS-2026-10-17-20-02-05](https://img.cscat.cn/img/BUG_REPORTS-2026-10-17-20-02-05.png)

这些都是在 clash 插件没有启用的情况下的测试，clash 打开之后可能产生的问题之后在来考虑

路由器的话，也可以通过 SSH 连接到路由器上进行调试，但是一定不要进行一些高危的操作，只能进行一些设置查看和调试动作，所有的操作都需要我同意或者我手动执行才可以

ip 192.168.6.1 用户名 root 密码 [已隐藏，请勿提交到仓库]

## 处理结果概要

- 已确认 Windows 使用 UDP 查询 `210.32.32.1` 时无法获得门户 A 记录，但 DNS/TCP 可以正常解析 `login.hdu.edu.cn` 为 `192.168.112.30`。问题大概率与路由器侧的 UDP/53 劫持或 DNS 重绑定保护有关。
- 已修改 `login.py`：系统 DNS 失败后自动使用校园 DNS 的 TCP 查询，并在连接解析所得 IP 时保留原域名的 HTTPS SNI 与证书校验。
- 已增加网络请求超时和异常恢复。校园门户短暂不可达时，脚本会延后检查并继续运行，不再启动即退出。
- 已修复 IP 获取和 `ac_id` 尝试中的无上限递归、JSONP 解析不严谨、启动时重复检查、多账号无限重试等问题。
- 已移除后续日志中的明文密码、Challenge 和 Access Token。
- 已增加单元测试；4 项测试全部通过。真实网络测试中，脚本成功通过 DNS/TCP 回退访问门户并取得 `ok` 状态。
- 未连接或修改路由器，未修改 `auth.json`。路由器侧若要永久修复，建议仅将 `login.hdu.edu.cn` 和 `portal.hdu.edu.cn` 加入 DNS 重绑定保护白名单，并检查 OpenClash 或防火墙遗留的 DNS 劫持规则。
