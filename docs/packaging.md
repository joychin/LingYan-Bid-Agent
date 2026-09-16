# 多平台打包指引（macOS / Windows / Linux）

> **一句话前提**：Python 侧车用 PyInstaller 冻结，**PyInstaller 无法跨 OS 交叉编译**——
> Windows/Linux/macOS 的产物必须分别在各自 OS 上构建（原生机器、虚拟机或 CI 矩阵）。
> Tauri 壳本身可以交叉编译，但侧车不行，所以实际操作就是：**每个平台各跑同一条流水线**。
>
> 唯一例外：**同 OS 跨架构**（如在 Apple Silicon Mac 上打 x86_64 半边，合成 universal 包）
> 是支持的——脚本会经 uv 安装对应架构的托管 CPython，PyInstaller 在 Rosetta 下运行。

## 0. 流水线总览（所有平台同构）

```
① 冻结侧车   bash sidecar/build_sidecar.sh [--target <triple>]
              → src-tauri/binaries/tender-agent-sidecar-<triple>（尾部自动跑冒烟门）
② 打安装包   npm run tauri build [-- --target <tauri-target>]
              → 前端 build + Rust release + bundler 出 dmg/nsis/deb 等
```

便捷入口（`package.json`）：

| 命令 | 等价于 | 用途 |
|---|---|---|
| `npm run build:sidecar` | ①（本机平台） | 只重建侧车 |
| `npm run build:release` | ① + ② | 本机平台一步出包 |

**出包前必做**：`./check.sh`（sidecar 测试 + 前端 lint/tsc/build + Rust check/clippy 全绿）。
侧车产物没有「过期守卫」——`binaries/` 里的旧产物不会自动失效，**每次出包前重跑 ①**，
冒烟门（10 项：pypdfium2(native)/jieba/FTS5/trafilatura/**python-docx/版式模板**/openai/agent 栈/
server 栈/app.main）会拦住「收集漏了但只静默退化」的问题（如版式模板缺失回落英文默认版式）。

## 1. 各平台一次性环境

| 工具 | macOS | Windows | Linux |
|---|---|---|---|
| Rust（rustup） | ✅ | ✅（MSVC 工具链） | ✅ |
| Node 22（`.nvmrc`） | ✅ | ✅ | ✅ |
| uv | ✅ | ✅ | ✅（`curl -LsSf https://astral.sh/uv/install.sh \| sh`） |
| 构建脚本运行环境 | Terminal | **Git Bash**（装 Git for Windows 自带） | bash |
| 系统依赖 | 无额外 | 无额外（WebView2 Win10+ 需系统有，Win11 自带） | 见 §4 |

仓库克隆后：根目录 `npm install`（前端依赖）即可，`uv sync` 由构建脚本自管独立 venv。

## 2. macOS

### 2a. Apple Silicon 包（默认，覆盖 2020+ 全部 Mac）

```bash
./check.sh && npm run build:release
```

产物：`src-tauri/target/release/bundle/dmg/灵燕智能_0.1.0_aarch64.dmg`（+ `.app`）。

### 2b. Intel / Universal 包（在 Apple Silicon 机上打 x86_64 半边）

Rosetta 必须已装（`softwareupdate --install-rosetta --agree-to-license`，多数开发机已有）：

```bash
bash sidecar/build_sidecar.sh --target x86_64-apple-darwin   # 自动装 x86_64 托管 CPython，冒烟经 Rosetta
npm run tauri build -- --target universal-apple-darwin        # 需两个 triple 的侧车产物都在 binaries/
```

- 跨架构构建环境落 `sidecar/.build-venv-x86_64/`，与本机 `.build-venv/` 互不污染。
- 生态现实：**cryptography 50.x 的 macOS 轮子只发 arm64**（上游放弃 Intel mac），x86_64 侧
  由脚本自动源码编译——首次会经 rustup 装 `x86_64-apple-darwin` 目标库并跑一次 maturin
  编译（几分钟），属一次性成本。
- 若 tauri 报找不到 universal 侧车（老版本行为），退路：`lipo -create` 两个产物合成单个
  `-universal-apple-darwin` 文件再构建。
- 只有 Intel Mac 的话直接 `npm run build:release`（host triple 即 x86_64）。
- 本机 `/bin/bash` 是 3.2（macOS 恒定）：构建脚本已按 3.2 兼容写法维护
  （不用 `$()` 内嵌 case、中文标点前的变量一律 `${}`），改动脚本时保持这两条。

### 2c. macOS 已知边界

- **未签名**：用户首次打开会遇 Gatekeeper——右键→打开，或 `xattr -cr "/Applications/灵燕智能.app"`。
  Developer ID 签名 + 公证 = 后续门（Tauri bundler 届时会对 externalBin 逐个签名公证）。
- 用户数据目录（bundled 模式 `DATA_DIR`）：`~/Library/Application Support/lingyan.ddmdj.com`。

## 3. Windows（2026-09-09 首次真机出包已跑通，v0.1.1 经 GitHub Actions 产出）

环境：Rust（MSVC）+ Node 22 + uv + Git Bash，全部默认安装路径即可。

```bash
./check.sh                      # Git Bash 里跑
npm run build:release
```

产物：`src-tauri/target/release/bundle/` 下 `nsis/*.exe`（推荐分发）与 `msi/*.msi`
（msi 首次构建会自动下载 WiX）。CI 实测产物：setup.exe 94MB / msi 95MB。

- 侧车无控制台窗已接好（spec `console=False`，stderr 由 Rust 侧重定向进 boot 留档）。
- 已知坑备案（AGENTS）：**NSIS 覆盖安装不更新 externalBin**（tauri#15134）——靠版本号
  变化规避，即每次发新版前把 `tauri.conf.json` 的 `version` 抬一位（CI 已从 tag 自动同步）。
- 版本号共五处必须同步：`tauri.conf.json`、`src-tauri/Cargo.toml`、`frontend/package.json`
  （注入设置页 `__APP_VERSION__`）、`sidecar/pyproject.toml`、`sidecar/app/main.py` 的
  `VERSION`。`./check.sh`（all 模式）有一致性守卫，漏抬即红。
- 未签名 exe 杀软误报偏高，正式代码签名证书 = 后续门。
- 用户数据目录：`%APPDATA%\lingyan.ddmdj.com`。
- **实测坑①（已修）**：Windows 的 stdout/stderr 默认 locale 编码（cp1252），
  `run_frozen.py --smoke` 打印含中文的 JSON 结果时 `UnicodeEncodeError` 必炸
  （mac/Linux 默认 UTF-8 复现不了）。修法=`run_frozen.py` 入口统一
  `sys.stdout/stderr.reconfigure(encoding="utf-8", errors="replace")`。
  本地复现验证：`PYTHONIOENCODING=cp1252 .build-venv/bin/python run_frozen.py --smoke`。
- **实测坑②（已修）**：CI changelog 用 `git describe` 找上一个 tag——actions/checkout
  默认 shallow（fetch-depth: 1）拉不到 tag 引用的 commit，describe 必失败走「首次发布」
  分支。修法=checkout 加 `fetch-depth: 0`。

## 4. Linux

系统依赖（Ubuntu/Debian，Tauri v2 官方清单）：

```bash
sudo apt update && sudo apt install -y libwebkit2gtk-4.1-dev build-essential \
  curl wget file libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev
```

```bash
./check.sh && npm run build:release
```

产物：`bundle/` 下 `deb/*.deb`、`appimage/*.AppImage`、`rpm/*.rpm`（`targets: "all"`）。

- 用户数据目录：`~/.local/share/lingyan.ddmdj.com`。
- 已知坑备案：目标机 `/tmp` 挂 noexec 时 one-file 侧车无法自解压——届时的出路是 spec 改
  `runtime_tmpdir` 指向用户数据目录（现在不动，遇到再加）。
- 无 Linux 机器时可用 Tauri 官方 Docker 镜像（`ghcr.io/tauri-apps/tauri`）容器内装 uv 后
  跑同一条流水线；AppImage 在容器内构建需要额外处理 fuse（`--appimage-extract-and-run`），
  首次走通后把命令补记到这里。

## 5. 品牌与 bundle identifier（改名迁移备忘）

2026-09-15 统一为**灵燕智能**：显示名（`productName`／窗口标题／启动画面／聊天助手名／
Word 修订与批注作者）与 `identifier` 全部去掉了旧名。

- `identifier`：`com.tenderagent.app` → **`lingyan.ddmdj.com`**。它决定 bundled 模式的
  数据目录（app_data_dir 按 identifier 派生），**改名会让用户历史数据「消失」**，
  故 `src-tauri/src/sidecar.rs` 内置一次性迁移（`migrate_data_dir_if_legacy`）：
  新目录为空或不存在、且旧目录有内容时才整目录 rename；新目录已有数据不动；
  失败只告警不删（最坏=用户按日志手工搬）。幂等，dev 模式不涉及（数据在仓内 `sidecar/data`）。
  旧路径由新路径父目录 + `LEGACY_BUNDLE_ID` 推导，无需各平台硬编码。
- **不随品牌改的内部标识**（改名会连锁破坏，刻意保留）：侧车二进制名
  `tender-agent-sidecar`（壳 `SIDECAR_BINARY` / 孤儿清扫命令行核验 / 打包脚本 /
  spec 四处耦合）、`localStorage` 键前缀 `tender-agent.*`（改了用户偏好静默重置）、
  契约与 skill 标识符 `tender.*`（改了要迁移存量产物）。
- 升级用户须知（会出现在发版说明里）：macOS 视为**全新应用**（TCC 权限重新申请，
  旧版 `/Applications/Tender Agent.app` 需手工删除，否则磁盘上两个 App）；
  Windows 安装器注册表键变化，旧版不会被覆盖安装，**建议先卸载旧版再装新版**；
  数据由上述迁移自动搬过来。
- Windows 的包名/App 名含非 ASCII 字符（灵燕智能）：本机 macOS 无法验证 NSIS/WiX
  对此的处理，**下次打 tag 时在 CI 产物上确认**（安装器文件名、开始菜单项、卸载项）。

## 6. 产物矩阵速查

| 想要的产物 | 在哪构建 | 命令 |
|---|---|---|
| macOS arm（dmg） | 任意 Mac | `npm run build:release` |
| macOS universal（dmg） | Apple Silicon Mac + Rosetta | 本文 §2b 三条命令 |
| macOS Intel（dmg） | Intel Mac | `npm run build:release` |
| Windows（nsis/msi） | Windows | `npm run build:release` |
| Linux（deb/rpm/AppImage） | Linux | `npm run build:release` |

侧车产物命名（tauri externalBin 规则，脚本自动处理）：

| triple | 产物 |
|---|---|
| `aarch64-apple-darwin` | `tender-agent-sidecar-aarch64-apple-darwin` |
| `x86_64-apple-darwin` | `tender-agent-sidecar-x86_64-apple-darwin` |
| `x86_64-pc-windows-msvc` | `tender-agent-sidecar-x86_64-pc-windows-msvc.exe` |
| `x86_64-unknown-linux-gnu` | `tender-agent-sidecar-x86_64-unknown-linux-gnu` |

## 7. 首次出包人工验收清单

冒烟门只验「依赖收集齐全」，整包行为还需人工过一遍（每个新平台首次出包时）：

1. 安装包装上、应用能打开，侧栏 sidecar 状态点为绿（bundled 冷启动 11–14s 属正常）。
2. 发起一轮对话（需先配好模型 Key），能收到流式回复。
3. 上传一份 docx/pdf 招标文件，解析产物能在面板预览。
4. 新建正文节能产出 docx，且版式是标书基准版式（黑体分级标题/宋体正文/首行缩进——
   版式退化成英文默认模板就是 `app/resources` 收集漏了，冒烟门应已拦住）。
5. 退出应用后无残留 sidecar 进程（`ps aux | grep tender-agent`）。

## 7. 后续门（明确未做，勿在本文找）

代码签名与公证（mac Developer ID / Windows signtool）、CI 矩阵自动出三平台包、
自动更新器（tauri-plugin-updater）。做其中任何一项时，同步更新本文件与 AGENTS.md 打包节。
