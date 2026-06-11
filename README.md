# hot-insight

hot-insight 是一个个人热点洞察站，用于追踪微博热搜，结合 AI 辅助整理事件脉络、关键事实、观点参考和风险提示，并支持将重要热点推送到企业微信与 Telegram 频道。

项目提供响应式网页，适配桌面端和移动端，可用于个人信息看板、热点观察、内容选题和通知订阅。

## 功能特性

- 微博热搜追踪：默认优先使用微博官方公开页面，按热搜标识筛选重点话题，展示标题、排名、热度和更新时间。
- 展示与通知分离：网站可展示 `爆`、`沸`、`热`，通知可只推送更重要的 `爆`、`沸`。
- AI 辅助洞察：为热点生成一句话结论、内容梳理、关键事实、AI 评价、风险提示和参考来源。
- 网站详情页：每个热点都有独立详情页，便于阅读和分享。
- 多渠道通知：支持企业微信应用消息和 Telegram 频道推送。
- 响应式界面：面向桌面端和移动端优化阅读体验。
- Docker 部署：提供 `docker compose` 部署方式，适合个人服务器运行。

## 页面说明

- 首页：展示最新热点和重点洞察。
- 微博热搜：按标识浏览微博热点列表。
- 热点详情：展示微博来源摘要、AI 洞察、关键事实、风险提示和参考来源。
- 关于：说明数据来源、AI 辅助内容和通知订阅能力。

## 技术栈

- 后端：Python、FastAPI、SQLite
- 前端：Next.js、React、TypeScript、Tailwind CSS
- 通知：企业微信应用消息、Telegram Bot API
- 部署：Docker Compose

## 快速开始

### 1. 准备配置

复制环境变量模板：

```bash
cp .env.example .env
```

编辑 `.env`，至少确认以下配置：

```env
PUBLIC_SITE_URL=http://localhost:3000
DATABASE_PATH=data/hot_insight.sqlite3
TRACK_TAGS=爆,沸,热
ALERT_TAGS=爆,沸
TAG_RECURRENCE_HOURS=爆:12,沸:12,热:24
NOTIFY_CHANNELS=wecom,telegram
SCHEDULE_MINUTES=30
MAX_TOPICS_PER_RUN=10
APP_TIME_ZONE=Asia/Shanghai
```

### 2. 安装后端依赖

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
```

### 3. 安装前端依赖

```bash
cd frontend
npm install
```

### 4. 本地启动

启动后端 API：

```powershell
$env:API_SCHEDULER_ENABLED="false"
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

启动前端：

```bash
cd frontend
npm run dev
```

默认访问：

```text
http://localhost:3000
```

## 配置说明

### 基础配置

| 变量 | 说明 | 示例 |
| --- | --- | --- |
| `PUBLIC_SITE_URL` | 网站公开访问地址，用于生成详情页链接 | `https://example.com` |
| `DATABASE_PATH` | SQLite 数据库路径 | `data/hot_insight.sqlite3` |
| `TRACK_TAGS` | 网站展示和 AI 洞察关注的热搜标识，逗号分隔 | `爆,沸,热` |
| `ALERT_TAGS` | 需要推送通知的热搜标识，逗号分隔 | `爆,沸` |
| `TAG_RECURRENCE_HOURS` | 同标题再次出现时视为新热点的时间窗口 | `爆:12,沸:12,热:24` |
| `WEIBO_SOURCE_ORDER` | 微博数据源顺序，默认优先官方公开页面 | `weibo_official,xk,xunjinlu,xxapi,nsuuu` |
| `FETCH_TIMEOUT_SECONDS` | 普通数据源请求超时时间，单位秒 | `15` |
| `WEIBO_OFFICIAL_TIMEOUT_SECONDS` | 微博官方热榜页请求超时时间，单位秒 | `15` |
| `WEIBO_OFFICIAL_VISITOR_TIMEOUT_SECONDS` | 微博游客初始化请求超时时间，单位秒 | `15` |
| `WEIBO_OFFICIAL_REALTIME_TIMEOUT_SECONDS` | 微博官方详情映射页请求超时时间，单位秒 | `15` |
| `WEIBO_OFFICIAL_MAX_RETRIES` | 微博官方热榜页失败后的最大尝试次数 | `2` |
| `SCHEDULE_MINUTES` | 自动更新间隔，单位分钟 | `30` |
| `APP_TIME_ZONE` | 后端日志、数据时间和页面展示使用的时区 | `Asia/Shanghai` |
| `MAX_TOPICS_PER_RUN` | 单次最多处理热点数 | `10` |
| `NOTIFY_CHANNELS` | 启用的通知渠道 | `wecom,telegram` |
| `LOG_LEVEL` | 日志等级 | `INFO` |
| `LOG_FILE_PATH` | 日志文件路径 | `data/logs/hot-insight.log` |
| `NOTIFICATION_DEFAULT_COVER` | 默认通知封面图片路径 | `backend/app/assets/notification-covers/default-cover.png` |

### 企业微信

```env
WECOM_CORP_ID=
WECOM_CORP_SECRET=
WECOM_AGENT_ID=
WECOM_TO_USER=@all
WECOM_MESSAGE_TYPE=mpnews
WECOM_DEFAULT_COVER_NAME=hot.jpeg
WECOM_DEFAULT_COVER_MEDIA_ID=
```

企业微信图文消息会优先使用微博官方详情页的封面图。没有可用封面时，会尝试使用企业微信素材库中名为 `hot.jpeg` 的图片；如果你已经知道素材 `media_id`，也可以直接填写 `WECOM_DEFAULT_COVER_MEDIA_ID`。

### Telegram

```env
TG_BOT_TOKEN=
TG_CHAT_ID=@your_channel
TG_API_BASE_URL=https://api.telegram.org
```

使用 Telegram 频道推送前，需要创建 Bot，并将 Bot 添加为频道管理员。

### AI 洞察

```env
AI_DETAIL_ENABLED=true
AI_DETAIL_BASE_URL=https://your-api.example.com/v1
AI_DETAIL_API_KEY=
AI_DETAIL_MODEL=
AI_DETAIL_WEB_SEARCH_OPTIONS={}
AI_DETAIL_EXTRA_PAYLOAD_JSON={}
```

AI 洞察依赖支持 Chat Completions 协议的 OpenAI 兼容接口。建议选择具备联网搜索能力的模型，以便生成包含来源链接的内容。不同服务商对搜索能力的配置方式可能不同，可通过 `AI_DETAIL_WEB_SEARCH_OPTIONS` 或 `AI_DETAIL_EXTRA_PAYLOAD_JSON` 传递兼容接口要求的附加字段。

## Docker 部署

在服务器创建项目目录并上传代码后执行：

```bash
cd /opt/hot-insight
chmod 600 .env
docker compose build
docker compose up -d
```

查看运行状态：

```bash
docker compose ps
docker compose logs -f --tail=100
```

手动执行一次更新和通知：

```bash
docker compose exec api python -m backend.app.cli run-once
```

建议通过 Nginx、Caddy、宝塔面板或 Cloudflare 为 `web` 服务配置域名和 HTTPS。

## 日志与排障

服务默认同时输出控制台日志和文件日志。控制台日志适合实时查看，文件日志保存在 `data/logs/hot-insight.log`，便于长期排查和备份。

本地查看日志：

```powershell
Get-Content data/logs/hot-insight.log -Tail 100 -Wait
```

Docker 查看日志：

```bash
docker compose logs -f --tail=100 api
```

调整日志等级：

```env
LOG_LEVEL=INFO
LOG_FILE_ENABLED=true
LOG_FILE_PATH=data/logs/hot-insight.log
```

每轮更新会生成独立 `run_id`，可用同一个 `run_id` 串联查看数据源、入库、AI 洞察和通知投递过程。微博官方源会记录榜单页、游客初始化和详情映射的分段耗时，便于判断是否需要调整官方源超时配置。

## 常用命令

后端测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
```

前端检查：

```bash
cd frontend
npm run lint
npm run typecheck
npm run build
```

重启服务：

```bash
docker compose restart
```

更新镜像并重启：

```bash
docker compose up -d --build
```

## 注意事项

- `.env` 包含密钥和 Token，请勿提交到公开仓库。
- `data/` 保存运行数据、数据库文件和排障日志，部署时建议定期备份。
- AI 生成内容仅作辅助参考，不应作为唯一事实来源。
- 企业微信和 Telegram 的实际投递能力取决于对应平台配置和网络可用性。

## License

本项目基于 MIT License 开源，详见 [LICENSE](./LICENSE)。
