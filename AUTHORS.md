# 作者与贡献者

## 主要贡献者

**Tomorin**（[@Accelerater-tech](https://github.com/Accelerater-tech)）
—— 项目发起人、产品方向、全部设计决策、需求定义，以及真机测试与问题反馈。

## 实现

本仓库的代码在 Tomorin 的需求、设计约束与逐轮验收下完成，包括：

- 应用架构与全部 Python 模块（`app/`：配置、链路管理、体检、自测、托盘、js_api）
- 前端界面（`web/`：原生 HTML/CSS/JS，暗色玻璃拟态）
- 调试与验证工具链（`tools/`：CDP 截图、假发送端、探针、便携版打包）
- 文档（`README.md`）与打包方案

## 上游致谢

- [DropBridge](https://github.com/ndpyzwy-0w0/DropBridge)（MIT）—— 本项目复用的
  `radio → bridge → netd → awdld → receiver` 后端二进制与驱动包来自上游；
  本项目只做控制器与界面，不重新实现 AirDrop 协议。
- [OpenDrop](https://github.com/seemoo-lab/opendrop) —— `Discover` / `Ask` / `Upload`
  协议的对照实现，用于核对本项目的应答封包。
- [pywebview](https://pywebview.flowrl.com/)、[pystray](https://github.com/moses-palmer/pystray)、
  [psutil](https://github.com/giampaolo/psutil)、[Pillow](https://python-pillow.org/) —— 运行期依赖。
