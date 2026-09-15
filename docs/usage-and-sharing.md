# 本机使用与网站分享

完整操作步骤、按钮说明和故障处理见 [两个雷达离线指南](user-guide.html)，也可在项目根目录
双击 `Start-Guide.cmd`。日常开机优先点“启动本机服务”，首次安装或更新代码才需要“准备本地环境”。

## 先在这台电脑使用

打开 Docker Desktop，双击项目根目录 `Start-TrendRadar.cmd`。首次使用或更新代码后点击
**准备本地环境**；日常使用不必重复构建。保持 Docker 和电脑运行，避免扫描中休眠。

| 用途 | 打开地址 / 操作 |
| --- | --- |
| 板块 1：尾盘雷达 | <http://localhost:8080/#/tail-radar> |
| 板块 2：趋势雷达 | <http://localhost:8080/#/trend-radar> |
| 板块 2 更新数据 | 电脑窗口点击 **开始抓取**，完成后点击 **查看结果** |

板块 1：选择扫描记录，打开股票详情，查看分时指标与快照时间。AI 分析在股票详情页输入
自己的 OpenAI API Key，勾选费用确认，再点击分析；失败记录使用明确的重试按钮。
密钥经后端调用 OpenAI，不会保存进浏览器持久存储或网页发布包。不要把密钥写进网址、
聊天消息或 `VITE_*` 变量。目前已验证表单、请求传递和模拟 SDK 调用；真实付费分析仍需
持有有效密钥及相应模型权限的用户完成一次验证。

板块 1 的正式快照在交易日中国时间 14:30 抓取，电脑必须在时间窗口内开着。它与板块 2
的日线逻辑不同：周末不能补造上个交易日 14:30 的市场快照。错过正式抓取时保留旧记录。
需要启用/更新尾盘抓取服务时，在项目根目录执行：

```powershell
docker compose up -d --build worker
docker compose exec -T worker tail-radar worker-health --max-age-seconds 60
```

板块 2：可以在周末或节假日点击抓取，自动使用最近已收盘的交易日。交易日 15:15 中国时间
之前使用上一已完成交易日。热度数据也必须属于该日期，不能将不同日期的数据混在一起。
首次全量扫描逐只请求沪深北全部 A 股行情，日志持续显示股票序号和总数；同日有效缓存可减少
重复请求。关注度前 300 仅优先高亮，不限制扫描范围；最多 2 天反弹且最后收盘创区间新低。
点击候选股名称或 **查看 K 线与数据** 可进入详情：日 K 线、MA5/10/20、成交量、价格、
筛选依据和每日行情表。数据来自这次扫描保存的日线；已有结果可通过 **重新导出结果**
补齐详情，无需重新抓取。网站发布包现在也包含候选股日线，访客点击后即可查看。

“成功处理”包括符合和不符合筛选规则的股票，“趋势候选”才是筛选结果。少量股票失败后
继续扫描，网页明确展示覆盖数量及失败列表；达到全局失败阈值则保留之前已完成的网页结果。
日志在 `runtime/operator/`；临时实测日志在 `runtime/qa/`。详细运行记录可通过以下命令查看：

```powershell
docker compose --profile trend run --rm --no-deps trend-worker trend-radar inspect
```

## 用自己的电脑给网站提供尾盘数据与 AI

无需云服务器。保持 Docker 和电脑运行，双击根目录 `Start-PublicWebsite.cmd`，等待
GitHub Actions 部署成功后分享原来的 Pages 网站。访客可以查看本机尾盘结果，在详情页
输入自己的 OpenAI API Key 做分析。停止时双击 `Stop-PublicWebsite.cmd`。

完整步骤、断线处理及密钥说明见 [自己的电脑作为网站后端](pc-public-website.md)。入口会
通过独立网关开放公开读取和指定 AI 请求，并更新 Pages 的后端地址。
`localhost` 只指访问者自己的电脑，不能把本机地址发给别人使用。

## 长期发布板块 2 的结果网站

第一次操作请照着 [Windows 首次发布步骤](trend-radar-first-publish.md) 完成安装、登录、
代码上传、Pages 配置和结果发布，其中提供本项目可用的 PowerShell 命令。

现有项目已准备 GitHub Pages 工作流。发布后电脑关机，别人也能查看最后一次发布的结果；
更新数据仍由你在电脑端抓取和发布，访客不需要登录，也不能触发扫描。

1. 准备一个你有权限的 GitHub 仓库，将审核后的项目源代码和工作流推送到 `main`。
   本地仓库需要设置指向该仓库的 `origin`；不要提交 `.env`、`runtime/`、数据库和密钥。
2. GitHub 仓库 **Settings → Pages → Source** 选择 **GitHub Actions**。
   这是 [GitHub 官方支持的工作流发布方式](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)。
3. 安装 [GitHub CLI](https://cli.github.com/)，在本机终端运行 `gh auth login` 登录。
4. 在 `Start-TrendRadar.cmd` 窗口完成抓取后，点击 **发布网站**。
5. 等待 GitHub Actions 部署成功，进入仓库 Pages 设置页复制实际网站地址，再分享给别人。

每次更新重复“开始抓取 → 发布网站”。结果 ZIP 上传为公开 Release 附件，不进入 Git 历史。
代码部署和数据上传不是同一件事，单纯复制本机文件不会更新远程网站。

## 长期让两个板块和 AI 都可用

GitHub Pages 只能托管静态网页，不能运行本项目的 Python 后端、数据库和 AI 调用。
可以选择一个有稳定 HTTPS 地址的常驻后端（云服务器，或保持在线的电脑配固定域名隧道），
运行现有 API、PostgreSQL 和尾盘抓取服务，并保留数据库/运行文件的持久存储。

若自行部署后端且网页放在 GitHub Pages：在仓库 Actions Variables 中设置 `VITE_API_BASE_URL` 为实际后端
HTTPS 根地址，并在后端 `CORS_ORIGINS` 中允许 Pages 域名；然后重新部署前端。板块 2 的
静态结果仍通过电脑窗口发布。也可以将前端和后端部署在同一域名，由现有 Nginx 代理 `/api/`。
两种方式都不应把 OpenAI Key 或数据库密码写入前端配置。

本机入口自动设置 `VITE_API_BASE_URL`，并由网关处理 Pages 跨域请求，无需手动修改
本地后端的 `CORS_ORIGINS`。后端部署细节见 [GitHub Pages 部署说明](github-pages.md)。
