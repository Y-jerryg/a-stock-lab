# 趋势雷达：电脑端抓取，网站只读

本模块已按新的使用方式移除 Supabase、网站登录、扫描按钮和请求队列。
使用原有本地 PostgreSQL 保存数据，网页只通过 GET 读取公开结果文件。
电脑和手机访问同一个只读页面；电脑端抓取入口是本地程序，不是网页上的隐藏按钮。
架构决定见 [ADR 0016](adr/0016-trend-radar-local-control-static-publication.md)。

## 在电脑上使用

1. 打开 Docker Desktop，等待引擎启动。
2. 双击项目根目录的 `Start-TrendRadar.cmd`。
3. 首次使用或更新代码后，点击 **准备本地环境**。程序构建镜像、启动 PostgreSQL、执行
   Alembic 迁移，然后启动本地 API 和网站。保留原有数据库卷，不创建 Supabase 账户。
   为采用手动抓取默认方式，此操作会停止旧的 trend-worker 定时容器。
4. 点击 **开始抓取**。程序抓取行情、筛选并存储数据，完成后自动导出本机网页所需结果。
   扫描沪深北全部 A 股，关注度前 300 仅用于优先展示和高亮；没有关注度的股票也会扫描。
   全市场耗时比原先 300 只更长，窗口显示实际总数与进度，日志在 `runtime/operator/` 中。
5. 点击 **查看结果**，或打开 `http://localhost:8080/#/trend-radar`。
   网站每 5 秒读取一次结果索引，支持历史记录、7/8/9 日筛选、强缩量筛选及计算详情。
6. 点击候选股票名称或 **查看 K 线与数据**，查看前复权日 K 线、MA5/10/20、成交量、
   开高低收、涨跌幅、筛选指标及每日行情表。图表支持缩放，阴影标记入选的趋势区间。
   返回列表会保留所选扫描。详情使用当次扫描保存的日线，显示交易日期与数据来源。

更新前已经抓取的候选股，点击 **重新导出结果** 即可补齐详情文件，无需重新扫描 300 只。
公网网站需要再点击 **发布网站**。图表只包含扫描当时保存的交易日，不是实时行情。

少量股票抓取失败时继续扫描，页面显示“扫描完成（部分失败）”、成功/失败数量和失败股票。
只有热度、日历、数据库等全局故障，或达到失败阈值时整次扫描失败，保留最近已完成结果。
默认阈值为失败达到请求总数的 20% 或连续失败 10 只，见 `.env.example`。
没有已完成扫描时页面显示暂无数据。成功处理数包含不符合筛选条件的股票，不等于候选数。
“重新导出结果”仅从数据库修复网页文件，不重新访问行情源。
日志中的 `scan_busy` 表示另一抓取正在执行，等待其结束即可。
准备环境不自动抓取趋势或发布公网；它会启动 Tail Radar 的定时服务，便于两个板块共用
电脑控制入口。日常启动可点“启动本机服务”，不必重复构建镜像。

无需配置任何 Supabase URL、Key 或管理员 UUID。已有 `.env` 中其他模块的配置请保留；旧的
Supabase 变量不再被本模块读取，可以移除。系统仍然需要本地 PostgreSQL，由 Docker 管理。

## 本机结果与公网网站

本机抓取完成后，本机网站立即读到新结果。GitHub Pages 是另一份静态网站，电脑上的文件
不会自动出现在公网。首次配置后，通过电脑窗口的 **发布网站** 更新：

1. 将本次代码和 `.github/workflows/pages.yml` 部署到该 GitHub 仓库的 `main` 分支。
   不要提交 `runtime/`、生成的结果文件或 `.env`。
2. 仓库 Settings → Pages → Source 选择 GitHub Actions。
3. 电脑安装 GitHub CLI，在项目目录执行 `gh auth login` 并登录有仓库发布权限的账户。
   这用于部署网站，与访客无关。仅趋势雷达不需要 `VITE_API_BASE_URL`；其他依赖 API 的模块
   如需在公网可用，仍需单独部署其后端并配置该变量。
4. 点击 **发布网站**。程序从本地数据库导出 `runtime/trend-radar-public.zip`，上传至当前
   GitHub 仓库的 `trend-radar-data` 预发布 Release，然后触发 Pages 工作流。
5. GitHub Actions 显示部署成功后，公网网站才更新。窗口显示“已提交网站部署”不是已上线。

发布包包含公开扫描摘要、筛选参数、候选股票指标及候选股当次保存的标准化日线；不含
全量热度股票的行情、SDK 原始响应、数据库密码、用户账户或内部错误详情。它会成为网站
公开内容，范围变更见 [ADR 0019](adr/0019-trend-radar-candidate-charts.md)。
数据存放在 Release 附件中，不进入 Git 历史。
工作流在重新发布代码时也会读取这个数据包，避免新版本覆盖掉已有网站数据。
首次没有数据包时显示空页面；已有数据包损坏、下载失败或明确要求数据却缺失时部署失败，
保留当前线上版本。不要在多个电脑上同时发布同一仓库的数据附件。

使用其他静态服务器时，将发布包解压内容放到网站的 `data/trend-radar/` 路径，先部署
`runs/` 和 `details/` 再替换 `index.json`，或者原子切换整个站点目录。不要公开本地数据库端口。

## 命令行等价操作

在项目根目录执行：

```powershell
# 一次性准备（也可直接使用电脑窗口）
powershell -ExecutionPolicy Bypass -File scripts/trend-radar-action.ps1 -Action Initialize

# 手动抓取；少量失败的完成状态退出码为 0；非零表示忙碌、全局失败或导出失败
powershell -ExecutionPolicy Bypass -File scripts/trend-radar-action.ps1 -Action Scan

# 只重新导出已有数据
powershell -ExecutionPolicy Bypass -File scripts/trend-radar-action.ps1 -Action Export
```

原生 Python 开发方式（本地 PostgreSQL 可达且 `.env` 已配置）：

```powershell
cd backend
uv sync
uv run alembic upgrade head
uv run trend-radar scan
uv run trend-radar inspect
uv run trend-radar export
uv run trend-radar bundle
```

原生 Vite 开发服务器需将 `runtime/public/trend-radar/` 复制到
`frontend/public/data/trend-radar/`，更新后再复制；Compose 开发模式已配置只读目录挂载。
复制目录已被 Git 忽略，禁止加入源代码提交。

## 可选的本地定时抓取

默认只在电脑端操作时抓取。如需每个交易日中国时间 15:45 自动抓取：

```powershell
docker compose --profile trend up -d --build trend-worker
# 停止定时功能
docker compose --profile trend stop trend-worker
```

定时任务每个交易日最多尝试一次，失败后不会每 5 秒重试；可在电脑端手动重试。
电脑关机时不能抓取，恢复后只处理当天到期的任务，不伪造历史热度。
定时任务只更新本机结果，不自动上传公网。`trend-radar worker-health` 检查本地心跳；
`trend-radar health` 只检查本地数据库。

## 数据与故障恢复

- Alembic `20260912_0009` 创建热度、K 线、扫描和候选结果表；`20260913_0010` 增加
  本地定时日期领取表，并保留历史定时扫描身份。共享 ResearchArtifact 仍为版本化输出。
- 手动和定时抓取持有同一个 PostgreSQL advisory lock。进程退出释放锁，下一次扫描会
  将遗留 running 记录标记为 interrupted；完整成功数据不会被失败记录覆盖。
- 先完成数据库事务，再写各次扫描的不可变结果文件，最后原子替换公开索引。
  导出失败不会把成功的数据库结果改为失败；修复权限/磁盘空间后点“重新导出结果”。
- 公开索引保留最近 100 次尝试，并额外保留最近成功结果（即使它更早）。数据库历史不自动删除。
- `runtime/public/trend-radar/index.json` 使用 `schema_version: 2`；结果文件仍为版本 1，路径为
  `runs/<UUID>.json`。新增 `detail_schema_version: 1` 和 `details/<UUID>.json`，详情从候选结果
  的不可变 `input_bars` 导出，不从后来刷新的行情缓存读取。前端检查版本、股票、日期和
  `as_of` 边界，不具备请求扫描的代码或 HTTP 写接口。旧包无详情时提示重新导出。
- Docker 网站只读挂载公开目录，Nginx 对该路径只允许 GET/HEAD，缺失文件返回 404。

## 默认筛选配置

`.env.example` 列出了完整配置。扫描全部 A 股，关注度前 300 优先高亮；截至数据日期检查
最近 9→8→7 个交易日，最多允许 2 天反弹，其余每天收盘严格下降，最后收盘必须低于区间
内所有此前收盘价，不接受平盘或并列最低。默认不限制反弹幅度。基准 20 日、成交量比例
不超过 55% 仅用于“强缩量”标记。决定见 [ADR 0021](adr/0021-all-a-share-closing-low-trends.md)。

`TREND_TOP_N=300` 是高亮阈值，不再限制扫描股票数；`TREND_MAX_PULLBACK_DAYS=2`；
`TREND_MAX_SINGLE_PULLBACK_PCT=null` 表示不限制反弹幅度。旧 `.env` 若显式配置了 3 或 1.5，
请同步修改。更新后先准备本地环境，再重新抓取；仅重新导出旧数据不会改变昨天的筛选结果。
网站按每次扫描保存的规则展示说明，旧记录仍保留其原先的条件。
发布新规则结果前，先把本次代码同步到 GitHub 并部署更新前端；旧前端不支持关闭反弹幅度
限制时的 null 参数。然后再通过电脑窗口“发布网站”更新结果数据。

## Screening semantics

1. Fetch the independent Shanghai/Shenzhen/Beijing A-share list via `stock_info_a_code_name`.
   Scan every listed stock, including those without attention observations. Fetch the complete
   available Eastmoney attention dataset through AKShare `stock_comment_em`.
   Validate A-share symbols, unique records, finite scores and dates. Rank `关注指数` descending, with
   symbol ascending for ties; `TREND_TOP_N` (300) controls priority/highlights, not inclusion.
   Securities whose attention score is null/NaN have no available observation and are excluded
   before ranking, but still participate in price screening via the independent list. Their count
   is logged; unavailable attention displays no rank. Other malformed scores fail validation.
2. Resolve the latest completed exchange session using the real trading calendar, not weekdays.
   Before 15:15 Shanghai, use the previous session. Require heat dates to match that session;
   delayed provider publication fails safely and can be retried manually later.
3. Test the latest 9, then 8, then 7 closing observations. Require final close strictly below all
   previous window closes and ordinary least-squares slope < 0. At most two positive returns are
   allowed, without a default amplitude cap; every other daily return must be negative. Changes
   within `1e-8` percentage points of zero are flat and invalidate a window. N observations produce
   N-1 internal returns, matching the nine-price example in the product specification.
4. Keep the longest valid window. Compare its mean volume with the mean of the immediately previous
   20 sessions. `volume_ratio <= 0.55` produces `strong`; otherwise `normal`. Compute amount means
   and ratio separately; they do not affect highlights. Missing/zero baseline volume excludes the
   candidate; zero baseline amount yields null amount ratio. Never shorten an already valid trend
   simply to obtain a baseline or a stronger ratio.
5. Reject duplicated/malformed/future/out-of-order bars. A missing latest session fails that stock.
   Gaps inside the required lookback are recorded as `nonconsecutive_sessions`. A zero-volume bar in
   the selected trend fails that window. Insufficient new-listing history is an explicit exclusion.
   ST and Beijing are not excluded by strategy; availability depends on upstream coverage.

Use qfq prices, volume in lots and amount in yuan. After exhausted Eastmoney request errors, use
Sina qfq daily bars for the entire lookback, converting Sina shares to lots and retaining its source.
The primary has a five-minute cooldown; each source has bounded retries and a hard process timeout.
Ratios are dimensionless. Fetch the required lookback plus 30 sessions. Refresh a coherent
qfq lookback for each new session vintage rather than mixing pre/post-corporate-action adjustments.
Same-vintage requests reuse bars for six hours. Candidate input bars remain immutable per run even
if the cache is refreshed. `data_as_of` is collection completion; `trade_date` is the completed bar
session. This live scanner is not a historical backtest tool.

容错和日志的完整决定见 [ADR 0018](adr/0018-trend-radar-partial-completion.md)。休市日手动抓取
自动使用真实日历中最近已收盘的交易日，盘中也使用上一已完成交易日；不会生成休市日日线。
每只股票处理后将进度、候选和输入证据保存到数据库，全局失败也保留这些记录。再次抓取时
可复用同一交易日六小时内的有效缓存，但会重新抓热度，不把它称为同一次扫描断点续跑。
日志包含 `trend_provider_attempt_failed`、`trend_scan_stock_failed` 的原始异常类型、消息、
完整堆栈和 URL，以及股票序号、代码、名称、重试次数、run_id。详细日志只保存在电脑端。

