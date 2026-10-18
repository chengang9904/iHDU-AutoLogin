# iHDU-AutoLogin 杭电校园网自动登录脚本

Forked from [JBNRZ/srun-login](https://github.com/JBNRZ/srun-login)
非常感谢原仓库作者！:)

杭州电子科技大学校园网 Wi-Fi 登录 / 深澜（srun）校园网自动登录脚本

重写互联网上现存的登陆脚本，适应2024年暑假后的网络变化，支持`生活区`和`教学区`的登录认证，同时支持`多用户账号`定时切换登录

## 修改内容
- 在启动时立即检测网络状态
- 为Windows计划任务添加了`login_HDU.bat`和`iHDU-AutoLogin计划任务.xml`

## 开始使用
- clone本项目到本地：```git clone https://github.com/HankLiu2020/HDU-AutoLogin.git```
- 为本项目建立conda环境：```conda create -n iHDU python=3.10```
- 安装依赖：```pip install -r requirements.txt```
- 修改目录： 笔者使用的目录是`C:\iHDU-AutoLogin`，请在`login_HDU.bat`中酌情修改
- 填写上网账号密码：按照`auth.json.example`的样例创建`auth.json`
- Windows用户请将`iHDU-AutoLogin计划任务.xml`导入到计划任务中。
计划任务将会在系统启动时运行`login_HDU.bat`。
![alt text](./image.png)

## Linux 使用（systemd 自动登录服务）
### 1. 创建 systemd 服务文件
```sudo nano etc/systemd/system/ihdu-login.service```
```[Unit]
Description=iHDU Auto Login
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/iHDU-AutoLogin
ExecStart=/opt/anaconda3/envs/iHDU/bin/python /root/iHDU-AutoLogin/login.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```
### 2. 启动服务
```sudo systemctl enable ihdu-login```
### 3. 查看状态
```systemctl status ihdu-login```

## DNS 故障处理

如果 Windows 使用普通 DNS 查询时提示 `No address (A) records available`，可以对比下面两条命令：

```powershell
Resolve-DnsName login.hdu.edu.cn -Type A -Server 210.32.32.1 -DnsOnly
Resolve-DnsName login.hdu.edu.cn -Type A -Server 210.32.32.1 -DnsOnly -TcpOnly
```

脚本会先使用系统 DNS；失败时自动通过 `210.32.32.1` 的 DNS/TCP 查询门户地址，并在保持原域名 SNI 和证书校验的前提下连接解析出的 IP。可通过环境变量覆盖 DNS 服务器：

```powershell
$env:IHDU_DNS_SERVER = "210.32.32.1"
python login.py
```

如果路由器直接查询上游 DNS 能返回校园网私有地址，但 LAN 设备或路由器本机 DNS 无法返回，通常需要检查路由器上的 DNS 劫持规则和 DNS 重绑定保护。建议只把 `login.hdu.edu.cn`、`portal.hdu.edu.cn` 加入重绑定保护白名单，不要全局关闭该保护。路由器设置变更后，再让 LAN 设备使用路由器地址作为 DNS。

## License

MIT License
