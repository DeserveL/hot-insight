# 全局开发配置

## 最重要
- Always reply in Chinese.
- 除非用户明确要求英文，否则所有回复使用简体中文。
- 代码标识符、命令、日志、报错信息保持原始语言；其余解释用中文。

## 项目基线
- 项目统一命名为 `hot-insight`，后端包统一使用 `backend.app`。
- 当前项目是个人热点洞察站，采用两容器部署：`api` 与 `web`。
- `api` 使用 Python/FastAPI，承载采集、AI 分析、通知路由和网站 API。
- `web` 使用 Next.js/React/TypeScript，采用 `output: "standalone"` 生产部署。
- 样式体系使用 Tailwind CSS 与 shadcn/ui 风格组件。
- 当前数据库使用 SQLite，运行数据挂载在 `data/`；默认数据库为 `data/hot_insight.sqlite3`，后续流量增长后再迁移 PostgreSQL。
- `data/` 是持久化业务数据目录，不是可随意删除的缓存目录。
- `data/logs/` 是持久化排障日志目录，可备份保留，不按普通缓存随意清理。

## 安全与配置
- 不要泄露 `.env`、企业微信密钥、AI API Key、Telegram Bot Token。
- 所有凭据只从环境变量读取，不写入源码、README 示例真实值或测试快照。
- 日志必须脱敏，不输出 Cookie、Token、Secret、API Key、Authorization 或平台访问凭据。
- 新增配置必须同步更新 `.env.example` 和 README。
- README 面向 GitHub 外部用户，不写团队讨论、需求调整过程或阶段性决策。
- 前端可见文案面向外部用户，避免技术实现细节、运行规则和团队语境。

## 设计规范
- 页面必须同时适配电脑和手机端。
- 视觉参考 Apple 的留白、排版、质感和克制动效，但不复制 Apple 商标、素材或具体页面。
- 首页直接展示热点洞察内容，不做空泛营销页。
- 前端不得把采集、AI 分析或通知逻辑塞进浏览器端。

## 开发原则
- 改动前先阅读现有实现；当前不保留旧入口和旧包兼容。
- 通知渠道必须互相独立，单个渠道失败不能阻塞其他渠道。
- 企业微信和 Telegram 投递必须按渠道分别去重并记录状态。
- 改动后运行相关后端测试、前端类型检查和构建；无法运行时必须说明原因。
