# 学校阅卷助手 Agent

根据《学校阅卷助手Agent设计规格.md》实现的本地应用。前端 **React + TypeScript + Vite**，后端 **Python + FastAPI**，浏览器适配 **Playwright**，本地存储 **SQLite + Fernet 加密载荷**。

**本地草稿，尚未提交至学校网站。程序没有正式成绩录入、保存、提交、发布或删除接口。**

## 可以直接体验

- 内置 6 份合成答卷：正常、部分作答、错误答案、空白、缺页、提示注入。
- 读取 → 预览最小模型输入 → 生成草稿 → 查看原文/量规/引用行号 → 教师改分、接受或拒绝。
- 分数范围、分项集合、合计与引用校验；未知字段/契约版本拒绝。
- 单任务串行执行、取消、重启后暂停、显式恢复、已完成项跳过。
- 加密本地记录、最小审计、版本保留、过期清理。
- 真实模式适配器和云端网关已实现，但默认关闭；需要校方授权、站点适配和验收。

演示评分器是**确定性关键词模拟器**，会故意暴露“关键词命中不代表语义正确”的限制，不能用于真实学生成绩。合成模式不调用云 API。

## Windows 启动

**教师优先使用免安装便携包**：完整解压 `release/TeacherGradingAssistant-windows.zip` 后双击 `TeacherGradingAssistant.exe`，无需安装 Python、Node.js 或项目依赖。带浏览器内核的包可离线启动演示及已授权的只读浏览器；云模型仍需联网。详见 [教师使用指南](docs/教师使用指南.md)。

源码方式也提供根目录的 `启动阅卷助手.bat` 与 `首次安装.bat`。前者首次运行时自动检查/安装依赖，之后启动服务并自动打开浏览器；关闭启动窗口即可退出；缺少 Python/Node 基础环境时显示明确的安装指引。

需要 Python 3.11+、Node.js 22.12+。在项目目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
cd frontend
npm ci
npm run build
cd ..
.\scripts\start.ps1
```

打开 **http://127.0.0.1:8765**。选择演示任务，点击“开始读取”，再点击“核对输入并生成”。

也可直接启动：

```powershell
.\.venv\Scripts\python.exe -m grading_assistant.main
```

后端固定监听回环地址；不要公开到局域网，不要使用多 worker 或热重载运行真实浏览器任务。进程锁防止多个实例同时写入。

开发前端：

```powershell
# 终端 1：启动上述 Python 后端
# 终端 2：
cd frontend
npm run dev
```

前端开发地址 http://127.0.0.1:5173，API 通过 Vite 代理到本地后端。

`requirements.lock.txt` 记录本次验证使用的 Windows / Python 3.13 依赖版本；重建相同环境可先安装 `pip install -r requirements.lock.txt`，再执行 `pip install -e . --no-deps`。前端精确版本由 `frontend/package-lock.json` 锁定。

## 测试

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Get-Location) ".browsers"
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm run build
```

浏览器测试使用本机临时 HTTP 服务和合成网页，验证实际请求拦截、零成绩写入、跨账号、重复答卷、分页异常和越界重定向。测试专用的 HTTP 配置不会通过真实运行配置的 HTTPS 校验。

如只运行非浏览器测试：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_core.py -q
```

## 目录

```text
frontend/src/                   TypeScript 中文工作台
src/grading_assistant/
  contracts.py                  版本化、严格字段数据契约
  config.py                     默认拒绝的站点/云端授权门
  browser.py                    窄口协议、Playwright 只读快照适配器
  grading.py                    脱敏、模型网关、确定性评分校验
  orchestrator.py                串行状态机、取消、恢复与本地复核
  storage.py                    加密载荷、事务、版本与最小审计
  main.py                       回环 API、本地令牌与来源防护
  demo.py                       合成任务与模拟答卷
config/example.json             不含密钥的禁用配置模板
docs/site-adapter.md            真实学校站点适配契约
docs/architecture.md            实现决策、边界和验收映射
scripts/                       启动和系统凭据设置
tests/                         合成数据单元/集成/安全测试
```

## 接入真实学校网站

教师可以在 **安全与配置 → 模型 API 设置** 填写地址、模型和密钥，点击“测试连接”及“保存 API 设置”。测试只发固定测试句，不读取答卷。密钥存入受保护的系统凭据库，网页和 JSON 不回显。修改地址会解除旧密钥绑定；更换模型或端点不会继承旧外发批准。

页面设置保存到运行数据目录 `model-connection.json`，只覆盖模型连接参数。真实外发还要求维护者的批准配置中 `site.enabled`、`cloud.enabled` 为真，且批准的 endpoint/model 与页面保存值完全一致。学校站点、身份与白名单不能通过这个表单修改。

1. 完成规格文档 P0：校方站点使用授权、教师权限、数据外发政策、API 地域/训练/保留条款、终端存储保留期限、学科评分质量门槛。
2. 阅读 [站点适配文档](docs/site-adapter.md)。当前实现是 `snapshot-v1` DOM 契约，不会猜测任意学校网页的选择器。由维护者基于已获授权的页面样本编写或调整只读适配器并回归测试。
3. 将 `config/example.json` 复制为 `config/local.json`，填写批准记录、精确只读 URL、登录专用 POST URL、教师 ID、任务/量规和预期答卷数量。启用真实站点必须同时指定保留批准记录。
4. 配置 `GRADING_CONFIG` 指向完整本地配置路径。`site.task` 需符合 `GradingTask`，字段示例见 `demo.py`，必须使用实际核验的稳定身份，不能依靠页面顺序分配学生标识。
5. 优先在页面“安全与配置”中保存密钥；维护者也可在本机交互终端运行 `.\.venv\Scripts\python.exe scripts/set_model_key.py`，密钥写入 Windows Credential Manager，不放入 JSON、命令行或日志。
6. 云端仅支持兼容 `messages` / `response_format: json_object` 的 HTTP JSON 服务，`endpoint` 是完整 HTTPS 请求地址。没有工具调用、重定向或代理环境继承。填写审批字段并将 `cloud.enabled` 设为 `true` 才能发送。
7. 启动后选择学校任务，在可见的独立浏览器中手动登录并进入任务页；核对后读取。逐份查看实际外发 JSON，确认脱敏无残留后才生成。
8. 教师在**自己的原站窗口**自行完成正式录入。助手专用浏览器会阻止非白名单和写入请求，不能用来正式提交。

真实环境的登录资源、静态资源、SSO 域名与跳转必须逐项列入精确白名单。只读 GET 是否真的无副作用需要现场核验。未适配页面、附件/OCR、未知分页、缺失身份均停止或转人工处理，不尝试绕过。

## 数据与停用

默认数据目录 `%LOCALAPPDATA%\TeacherGradingAssistant`，可用 `GRADING_DATA_DIR` 指定受控目录。源码与运行数据分开。

- 合成模式：`synthetic.db` + `synthetic-only.key`，仅适用于合成数据。
- 真实模式：独立 `school.db`，加密密钥在受保护的系统凭据存储，无明文回退。SQL 行中只留下随机 run ID 与更新时间，答卷/草稿/审计载荷加密。
- 默认保留 7 天，启动及新建任务时清理；真实模式必须设置批准的期限。开启 SQLite `secure_delete`，但不宣称能擦除 SSD、操作系统备份或外部备份中的副本，终端应启用磁盘加密与访问控制。
- 系统密钥丢失后无法解密历史草稿；备份方案必须由校方管理。
- 取消立即阻止后续读取/模型请求，并关闭浏览器。已发送的在途云请求可能已被服务商处理，取消不能撤回服务商接收的数据。
- 应急停用：取消任务并关闭服务，将站点/云端开关关闭后重启；撤销泄漏密钥及学校登录会话。

## 已知限制与上线前工作

这是可运行、可测试的 v1 工程基线，不是已经通过校方验收的生产阅卷系统。尚无真实学校 URL/DOM、云服务商批准配置或教师标注数据，因此没有真实站点连通性和评分质量验收结论。附件/OCR、人工空白卷录分、导出、MCP 和正式成绩写入均未开放。

自由文本自动脱敏只能覆盖已提取标识、常见邮箱、长数字与链接，不保证识别所有间接个人信息；真实外发必须人工预览。模型引用校验能保证行号存在，不能证明语义推理正确。未通过学科质量门槛的题型不得启用。

## 维护者生成 Windows 分发包

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/build_windows.ps1 -IncludeBrowser
```

构建机需已安装项目依赖并构建前端；脚本自动安装 PyInstaller。生成 `release/TeacherGradingAssistant-windows.zip`，包含可执行程序、Python 运行时、前端和浏览器内核。教师完整解压后双击 exe 即可；保持运行窗口，关闭窗口退出。省略 `-IncludeBrowser` 可生成体积较小的演示包。

打包只复制默认配置模板与教师指南，不分发 `config/local.json`、API 密钥、数据库、运行日志或浏览器会话。学校配置通过受控渠道单独下发。当前构建为 Windows x64，已在本机验证 exe 启动、网页与设置 API 和合成答卷读取；尚未在全新 Windows 设备完成分发验收。源码安装仍需基础 Python/Node 环境，便携包可免除此要求。
