# DropBridge Studio

> 作者 / 主要贡献者：**Tomorin**（[@Accelerater-tech](https://github.com/Accelerater-tech)）

Windows 上接收 iPhone「隔空投送」的图形界面控制台。

它不是另起炉灶重写协议，而是给 [DropBridge](https://github.com/ndpyzwy-0w0/DropBridge) 那套
`radio → bridge → netd → awdld → receiver` 后端装了一个真正的驾驶舱：自动按依赖顺序拉起
五个进程、实时把日志解析成指标、链路断了自动重启、体检一键定位问题。

```
DropBridgeStudio/
  app/            控制器（配置 / 链路管理 / 体检 / pywebview js_api / 无头 CLI）
  web/            界面（原生 HTML+CSS+JS，WebView2 渲染）
  assets/         图标、随包驱动（inf / cat / cer）
  tools/          调试与验证脚本（CDP 截图、假发送端、探针、便携版打包）
  runstudio.py    打包/便携版的统一入口
  Run.cmd         双击启动
  Doctor.cmd      双击体检（命令行版，出问题先跑它）
```

## 下载

两种装法，功能完全一致，任选一个：

**① 安装版（推荐）** —— [DropBridge-Studio-Setup-1.0.0.exe](https://github.com/Accelerater-tech/dropbridge-studio/releases/latest)
（约 33 MB，双击安装）

- **安装位置可以自己改**：默认 `%LOCALAPPDATA%\Programs\DropBridge Studio`，
  界面上能直接编辑路径，或点「浏览…」选到 `D:\Apps\...` 之类的地方
- 自动建桌面 + 开始菜单快捷方式
- 控制面板「应用和功能」里能看到，卸载干净（目录、快捷方式、注册表一起清）
- 自带 Python 运行时，不用本机装过 Python

**② 免安装版** —— [DropBridge-Studio-portable.zip](https://github.com/Accelerater-tech/dropbridge-studio/releases/latest)
（约 67 MB，解压即用）

- 解压到任意普通目录，双击 `启动 DropBridge Studio.cmd`（或英文名 `Start DropBridge Studio.cmd`）
- 适合放 U 盘带着走，或者不想在系统里留安装记录

想从源码跑，看下一节。

## 打包成 exe

```bash
python tools/build_exe.py      # 单文件主程序 → ~/dbstudio-build/dist/DropBridge Studio.exe
python tools/build_setup.py    # 安装包 → ~/dbstudio-build/dist/DropBridge-Studio-Setup-1.0.0.exe
```

两个脚本都会自带冒烟测试（冷启动 → 等五节点就绪 → 截图）。
注意构建与试跑都在家目录 `~/dbstudio-build/` 下做，别在 DSH 工作区里跑（见下面那条警告）。

## 免安装版（自带 Python 运行时）

`python tools/make_portable.py` 会在桌面生成 **`DropBridge Studio\`** 目录（约 178 MB），
里面带一份完整的 CPython 3.12 和依赖，双击其中的 `启动 DropBridge Studio.cmd`
或桌面快捷方式即可，**不需要本机装过 Python**。

- 数据仍然写在 `<后端目录>\data\studio\`，与源码运行完全共用设置、时间线和历史记录
- 想换地方放：`python tools/make_portable.py "D:\Apps\DropBridge Studio"`
- 注意：**别把它放在 DSH 工作区路径下运行**（实测 .NET CLR 在从工作区加载
  `Python.Runtime.dll` 时会失败，WebView2 起不来），放到桌面或任意普通目录就正常

## 启动

双击桌面上的 **DropBridge Studio**（或 `Run.cmd`），点右上角「启动接收」。
首次启动会等 40~55 秒：无线网卡要先下载固件、AWDL 链路要逐级握手，这是正常的。

就绪后，在 iPhone 上打开控制中心 →「隔空投送」→ 选中这台电脑，文件会落到
`<安装目录>\data\received`，界面「传输」页即时出现缩略图。

## 它比原版多了什么

| | 原版 DropBridge | Studio |
|---|---|---|
| 启动 | 双击 exe，黑窗口，失败只知道"多次失败已停止" | 一键启动，五节点链路图逐级点亮，每个节点带 PID 与状态 |
| 就绪判断 | 只看日志字符串 | 端口 / 命名管道 / 地址文件 / 日志四重判据，绝不误判 |
| 失败处理 | 放弃并停止 | 自动重启 + 前沿重启（管道丢失时重建 bridge/netd），带退避 |
| 日志 | 目录里翻 txt | 界面内分进程查看、过滤、暂停，失败时保留最后 80 行 |
| 诊断 | 无 | 9 项一键体检：安装目录、后端齐全、WinUSB 绑定、设备在位、端口占用、接收器 python、接收目录、密钥、蓝牙信标 |
| 驱动 | 手动 Zadig | 「修复驱动」按钮一键重新装 WinUSB（内置未损坏的 inf/cat/cer） |
| 接收 | 只落盘 | 缩略图、大小、速率曲线、搜索、清空、打开文件夹 |
| 可观测性 | 无 | 实时解析 radio/netd/awdld/receiver 每一行：帧率、对端数、AWDL 地址、发现/协商计数、信标状态 |
| 排障 | 靠猜 | 手机"来过但没协商"时自动弹出排查卡；诊断报告带全量落盘日志与协议事件统计 |

## 界面

- **概览**：状态、雷达动画、发现/发送请求计数、实时速率、对端设备、在线时长、链路图、最近接收
- **传输**：文件列表（缩略图 / 大小 / 时间 / 打开 / 定位）
- **日志**：radio / bridge / netd / awdld / receiver / beacon 分页，支持过滤与暂停
- **诊断**：一键体检 + **自测接收** + 环境信息 + 导出报告
- **设置**：设备名、机型伪装、信道、带宽、信道序列、flags、接收目录、自动重启、蓝牙信标、trace 日志、关闭窗口留在托盘、开机自动启动

托盘图标常驻：双击显示主窗口，右键可启动/停止接收、打开接收文件夹、退出。

## 自测接收

「诊断」页的**自测接收**会用内置的模拟发送端，自己给本机投一张图：TLS 握手 → Discover →
Ask → Upload → 落盘，五步逐条显示结果。

用途很直接：**它全绿就说明电脑这端完全没问题**，iPhone 那边传不过来是手机/系统侧的事；
它红了，就顺着红的那一步查（连不上 = 链路没就绪；Upload 失败 = 接收目录或磁盘问题）。

## 命令行

```bat
Doctor.cmd                       :: 体检
python -m app.cli run --seconds 90   :: 无头起链路跑 90 秒，实时打印各节点状态
python -m app.cli hold               :: 起链路并常驻（给脚本/Scheduled Task 用）
```

## 常见问题

**只有「启动接收」没有反应？** 先 `Doctor.cmd`。端口被占时它会列出占用进程（多半是上一轮
链路没退干净），点「停止」或重启 Studio 会清理。Studio 每次启动前都会先回收本安装目录下的
残留后端（不会碰别的程序），所以正常情况下不会被上一轮挡住。

**启动后 radio 立刻退出了（链路图 1 号节点红）？** 上一轮如果是被强制结束的，USB 设备可能还
停在旧状态，radio 起来后几十秒内会自己退出。Studio 会自动重启一次链路，实测 60 秒内恢复；
不想等就手动点一次「重启」。

**iPhone 里根本看不到这台电脑？** 蓝牙信标负责"让电脑出现在隔空投送列表里"。设置里
`beacon` 打开；日志页的 beacon 页会显示广播状态。如果 beacon 一直失败，通常是临时目录
写不进去——Studio 已经把 TEMP 指向 `<data>\studio\temp`，正常不会复现。

**iPhone 显示"投送失败"？** 那是 iPhone 侧在拿到接收方身份后主动中止了会话：日志里能看到
`POST /Discover` 200，但后面没有 `POST /Ask`。Studio 默认开启 `--trace`，会把每一步握手
（TLS 版本、请求行、拒绝原因）写进 receiver 日志，右键「日志」页即可看到细节。

一旦出现"有 Discover、没 Ask"，「诊断」页顶部会自动弹出一张排查卡（iOS 版本 / 改成"所有人
10 分钟"做对照 / 别锁屏 / 抓实测）。排障有两档产出，都在「诊断」页右上角：

- **抓一次实测**（推荐）：打成一个 `capture-<时间>.zip`，里面有 `capture.json`（时间线、
  体检结果、协议统计、设置、内存日志）和本次会话六个后端日志的原始文件。手机试完之后点一下，
  把 zip 发出来就够定位了。
- **导出诊断报告**：同一个内容但只写成一个 JSON，适合直接看文本。

`capture.json` 里的 `notable` 会算出 Discover / Ask / Upload 次数、最后一次事件时间、TLS
握手错误和 radio 对端帧数；`events` 是你再熟不过的那条时间线。

**改坏了想恢复原驱动？** `setup\README.txt` 里有说明；Studio 的「修复驱动」只动 MI_02 接口，
MI_00（蓝牙）不受影响。

## 自动留证（不用你记着手动点）

只要「发现请求」计数上涨（说明手机来过），Studio 会在 20 秒后自动把现场打成
`data\studio\captures\capture-<时间>.zip`，时间线上会出现一条「已自动留证」。
一次尝试里手机可能重连很多次，所以 90 秒内只留一份；手动点「抓一次实测」随时可以补一份。

这样即使你忘了点按钮，事后也能把最近这次尝试的完整现场翻出来。

## 事件时间线（排障用）

概览页底部会记下每次交互：链路启动/就绪/停止、手机建立连接、发现请求（Discover）、
发送请求（Ask）、传输中、文件已保存。手机每来一次都会留痕，所以看完就能判断卡在哪一步：

- 有「发现请求」没有「发送请求」→ 手机拿到电脑身份后就中止了（多半是「仅限联系人」限制，
  见下面排查卡）
- 连「发现请求」都没有 → 手机压根没连上这台电脑（链路/信标/距离问题）

时间线只保留最近 240 条，但**会落盘**（`data\studio\timeline.jsonl`）：重启后会把你上次看到的
历史事件读回来（显示得淡一些），所以关掉再开也不会丢「手机某次来过」的痕迹。

## 已验证

- 五节点链路自动拉起并就绪（radio 49876 / netd 49877 / receiver 8771 / bridge 命名管道）
- 模拟发送端完整握手：`Discover 200 → Ask 200 → Upload 200`，文件落盘并出现在界面
- 界面「自测接收」一次跑通五步（TLSv1.3 / AES_256_GCM），文件进「传输」页
- 体检 9/9 通过、日志落盘、失败原因回显、窗口图标与快捷方式
- 统计解析接线：界面上能看到 `tx` 增长、AWDL 地址、信标"已在广播"、发现计数随请求 +1
- 「有 Discover 没 Ask」时诊断页自动弹出排查卡（用假发送端只发 Discover 验证）
- 诊断报告带 `disk_logs`（6 个后端日志尾 400 行）+ `notable` 协议统计 + 传输记录
- 关闭窗口到托盘（窗口隐藏、链路不断）、开机自启（Startup 快捷方式）实测生效
- 事件时间线落盘回放（重启后 `historic 6 / all 7`）、自动留证（Discover 后 20 秒出 zip，90 秒冷却）
- 免安装版（自带 Python 3.12）：桌面目录启动 3 秒出窗口、63 秒五节点就绪、自启开关实测有效

真机 iPhone 的最后一跳（Discover 之后没有 Ask）仍需要一台手机复现，见「常见问题」。

## 发布脚本与 token 保管

`tools/gh_release.py`（发 Release 资源）、`tools/gh_api_push.py`（整树提交）、
`tools/gh_publish.py`（建仓库）都走 GitHub REST API —— 本机 `github.com` 的 git 传输不通，
但 `api.github.com` / `uploads.github.com` 可达。

token 不写在文件里，由 `tools/gh_auth.py` 用 **Windows DPAPI** 加密存在
`%LOCALAPPDATA%\DropBridgeStudio\github.token`，只有当前 Windows 账户能解开；
换台机器、换个账户拷过去都解不开。凭据取用顺序是：`GH_TOKEN` 环境变量 →
加密存档 → 报错提示。

```bash
python tools/gh_auth.py save <token>   # 存一次
python tools/gh_auth.py show           # 只看掩码
python tools/gh_auth.py forget         # 删掉
```

仓库里不放任何 secret，`.gitignore` 也把 `data/`、日志、构建产物挡在外面。

