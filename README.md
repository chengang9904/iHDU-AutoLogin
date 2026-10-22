# iHDU-AutoLogin 杭电校园网自动登录脚本

Forked from [JBNRZ/srun-login](https://github.com/JBNRZ/srun-login)
非常感谢原仓库作者！:)

杭州电子科技大学校园网 Wi-Fi 登录 / 深澜（srun）校园网自动登录脚本

重写互联网上现存的登陆脚本，适应2024年暑假后的网络变化，支持`生活区`和`教学区`的登录认证，同时支持`多用户账号`定时切换登录

## 功能

脚本启动后常驻后台，不会登录一次就退出：

- **掉线自动登录**：定时检测在线状态，不在线时从 `auth.json` 中随机选择账号登录；账号密码错误或账号被禁用时自动换下一个账号
- **检测频率**（按北京时间计算，与系统时区无关）：
  - 平时每 **3 分钟** 检测一次
  - **01:00–02:00** 网关高概率强制下线，期间每 **30 秒** 检测一次
- **定期重新登录**：每 **3 天** 主动下线并重新登录一次；下线后等待 **30 秒** 再登录（门户的注销约 10 秒后才生效，立即登录会被判定为“已在线”）
- **DNS 兜底**：系统 DNS 解析门户失败时，自动通过 `210.32.32.1` 的 DNS/TCP 解析（见 [DNS 故障处理](#dns-故障处理)）
- **日志**：使用北京时间，每天 0 点切分，自动删除 14 天前的日志

## 开始使用

1. clone 本项目到本地：`git clone https://github.com/HankLiu2020/HDU-AutoLogin.git`
2. 为本项目建立 conda 环境：`conda create -n iHDU python=3.10`
3. 安装依赖：`conda activate iHDU`，然后 `pip install -r requirements.txt`
4. 填写上网账号密码：按照 `auth.json.example` 的样例创建 `auth.json`，可以填写多个账号：
   ```json
   [
     {"username": "240000000", "password": "xxx"},
     {"username": "240000001", "password": "yyy"}
   ]
   ```
5. 手动试运行：在项目目录下执行 `python login.py`，看到 `Process started` 和 `check: ok` 即正常，`Ctrl+C` 退出
6. 设置开机自启：Windows 见 [Windows 开机自启](#windows-开机自启计划任务)，Linux 见 [Linux 使用](#linux-使用systemd-自动登录服务)

## 配置项

可调整的参数都在 `login.py` 开头：

| 常量 | 默认值 | 说明 |
|---|---|---|
| `CHECK_INTERVAL_MINUTES` | `3` | 平时的检测间隔（分钟） |
| `BUSY_CHECK_INTERVAL_SECONDS` | `30` | 01:00–02:00 的检测间隔（秒） |
| `REFRESH_INTERVAL_DAYS` | `3` | 主动下线并重新登录的间隔（天），从进程启动时开始计时 |
| `LOGOUT_SETTLE_SECONDS` | `30` | 主动下线后等待多久再登录（秒），应大于门户的 10 秒注销延迟 |
| `SCHEDULE_TIMEZONE` | `"Asia/Shanghai"` | 检测时间表使用的时区 |
| `LOG_TIMEZONE` | UTC+8 | 日志时间使用的时区 |
| `LOG_RETENTION` | `"14 days"` | 日志保留时长，如 `"7 days"`、`"1 month"` |
| `DNS_SERVER` | `210.32.32.1` | DNS/TCP 兜底使用的 DNS，可用环境变量 `IHDU_DNS_SERVER` 覆盖 |

高频检测的时段写在 `main()` 的 `check_trigger` 中：`hour=1` 为高频时段，`hour="0,2-23"` 为其余时段，修改时两处要一起改。

修改后需要重启脚本（或重启计划任务）才会生效。

## Windows 开机自启（计划任务）

仓库提供了计划任务模板 `iHDU-AutoLogin计划任务.xml` 和启动脚本 `login_HDU.bat`。计划任务有两种启动方式：

| 方式 | 计划任务运行的程序 | 说明 |
|---|---|---|
| **A. 直接运行 Python（推荐）** | conda 环境里的 `python.exe login.py` | 不需要 bat 和 `conda activate`；结束任务时会直接结束 Python 进程 |
| B. 运行 bat | `login_HDU.bat` | 模板默认方式 |

> **为什么推荐方式 A**：结束计划任务（`Stop-ScheduledTask` 或在任务计划程序里点“结束”）只会结束任务直接启动的进程。方式 B 中被结束的是 `cmd.exe`，它启动的 `python.exe` 会残留下来继续运行，再次启动任务后就会有两个脚本同时运行（表现为日志里出现两种时间、检测记录重复）。

### 1. 修改 XML

用文本编辑器打开 `iHDU-AutoLogin计划任务.xml`，需要关注以下字段：

| 字段 | 是否必改 | 说明 |
|---|---|---|
| `<UserId>` | **必改** | 运行任务的 Windows 账户 SID，模板里是作者的 SID。在 PowerShell 执行 `whoami /user` 查看自己的 SID 并替换。也可以导入时在界面上点“更改用户或组”重新选择 |
| `<Command>` | **必改** | 要运行的程序，见下方示例 |
| `<Arguments>` | 方式 A 需新增 | 程序参数，方式 A 填 `login.py` |
| `<WorkingDirectory>` | **建议新增** | 起始目录，填项目目录。`auth.json` 和 `srun_login.log` 都按相对路径读写，方式 A 必须填写 |
| `<Author>` | 可选 | 作者，仅用于显示 |
| `<LogonType>` | 按需 | `Password`：未登录 Windows 时也运行，导入时需要输入 Windows 账户密码；`S4U`：未登录时也运行且不保存密码，本脚本只访问网络，适合用这个；`InteractiveToken`：仅在用户登录后运行 |
| `<RunLevel>` | 按需 | 保持 `LeastPrivilege` 即可，脚本不需要管理员权限。如果改成 `HighestAvailable`，之后修改、结束任务都必须在管理员 PowerShell 中操作 |

其余字段一般不需要改，但要知道它们的作用：

| 字段 | 模板值 | 说明 |
|---|---|---|
| `<BootTrigger>` / `<Delay>` | 开机后 30 秒 | 触发时机 |
| `<MultipleInstancesPolicy>` | `IgnoreNew` | 任务已在运行时，新的启动请求会被忽略。如果任务卡住，需要先结束再启动 |
| `<ExecutionTimeLimit>` | `PT0S` | 不限制运行时长。**不要删掉**，否则系统默认 72 小时后会结束脚本 |
| `<RestartOnFailure>` | 5 分钟后重试，最多 3 次 | 任务启动失败时自动重试 |
| `<Hidden>` | `true` | 在任务计划程序中隐藏，需勾选“显示隐藏的任务”才能看到 |

方式 A 的 `<Actions>` 示例（路径换成自己的）：

```xml
  <Actions Context="Author">
    <Exec>
      <Command>C:\Users\你的用户名\.conda\envs\iHDU\python.exe</Command>
      <Arguments>login.py</Arguments>
      <WorkingDirectory>D:\path\to\iHDU-AutoLogin</WorkingDirectory>
    </Exec>
  </Actions>
```

conda 环境中 `python.exe` 的路径可以这样查：

```powershell
conda activate iHDU
python -c "import sys; print(sys.executable)"
```

方式 B 的 `<Actions>` 示例：

```xml
  <Actions Context="Author">
    <Exec>
      <Command>D:\path\to\iHDU-AutoLogin\login_HDU.bat</Command>
      <WorkingDirectory>D:\path\to\iHDU-AutoLogin</WorkingDirectory>
    </Exec>
  </Actions>
```

> **注意编码**：XML 文件是 UTF-16 LE 编码（文件头声明了 `encoding="UTF-16"`），修改后要按原编码保存。VS Code 中可以点右下角的编码 →“通过编码保存”→ `UTF-16 LE`。编码不对时，导入会提示 XML 格式不正确。

### 2. 修改 bat（仅方式 B）

`login_HDU.bat` 内容如下：

```bat
call conda activate iHDU
cd /d "%~dp0"
python "login.py"
```

| 行 | 是否需要修改 | 说明 |
|---|---|---|
| `call conda activate iHDU` | 按需 | `iHDU` 是 conda 环境名，环境名不同时修改。计划任务运行时必须能找到 `conda` 命令；如果 `conda` 不在系统 PATH 中，改为完整路径，例如 `call "D:\Miniconda\condabin\conda.bat" activate iHDU`（用 `where conda` 查看安装位置） |
| `cd /d "%~dp0"` | **不需要修改** | 自动切换到 bat 所在目录，不用写死路径。`/d` 用于跨盘符切换，不能去掉：计划任务默认从 `C:\Windows\System32` 启动，没有 `/d` 时 `cd D:\...` 不会切换到 D 盘，脚本会找不到 `login.py` 和 `auth.json` |
| `python "login.py"` | 不需要 | 也可以写成 conda 环境中 `python.exe` 的完整路径，这样第一行 `conda activate` 可以省略 |

**不要在末尾加 `pause`**：计划任务在后台运行，没有窗口可以按键，`pause` 会让任务一直卡在“正在运行”。只在手动双击调试时临时加上。

### 3. 导入并启动

1. 打开“任务计划程序” → 右侧“导入任务” → 选择修改好的 XML

   ![导入任务](./image.png)

2. 在弹出的窗口中确认运行用户、“操作”页中的程序和起始目录，点“确定”（`LogonType` 为 `Password` 时需要输入 Windows 账户密码）
3. 在任务上右键“运行”，或用 PowerShell 管理（任务名以任务计划程序中显示的为准）：

```powershell
Start-ScheduledTask -TaskName 'iHDU-AutoLogin计划任务'      # 启动
Stop-ScheduledTask  -TaskName 'iHDU-AutoLogin计划任务'      # 结束
Get-ScheduledTask   -TaskName 'iHDU-AutoLogin计划任务' | Get-ScheduledTaskInfo   # 查看上次运行时间和结果
```

`LastTaskResult` 常见取值：`267009` 正在运行；`0` 正常结束；`1` 运行出错（多为路径不对或找不到 conda）。

4. 查看日志确认脚本在运行：`Get-Content .\srun_login.log -Tail 20 -Wait`

### 常见问题

- **日志中同时出现两种时间、检测记录重复**：有多个脚本进程在同时运行，通常是方式 B 结束任务后残留的 `python.exe`。在任务管理器中结束多余的 `python.exe`，或改用方式 A
- **任务显示“正在运行”但日志没有更新**：bat 卡住了，检查 bat 中是否有 `pause`、`conda` 能否找到、起始目录是否正确
- **修改或结束任务时提示“拒绝访问”**：任务的 `RunLevel` 是最高权限，需要在管理员 PowerShell 中操作
- **导入后运行结果为 `1`**：`<Command>` 中的路径不存在，项目目录移动后需要同步修改任务

## 日志

- 日志文件为项目目录下的 `srun_login.log`，记录 DEBUG 级别（包含门户返回的完整内容）；控制台只输出 INFO 及以上级别
- 日志时间为北京时间，与系统时区无关
- 每天北京时间 0 点切分，旧日志改名为 `srun_login.<时间>.log`（文件名中的时间是文件创建时的系统本地时间），超过 14 天的旧日志在切分时自动删除

## Linux 使用（systemd 自动登录服务）

### 1. 创建 systemd 服务文件

```bash
sudo nano /etc/systemd/system/ihdu-login.service
```

```ini
[Unit]
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

```bash
sudo systemctl enable --now ihdu-login
```

### 3. 查看状态

```bash
systemctl status ihdu-login
```

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
