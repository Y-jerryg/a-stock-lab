# 自己的电脑作为网站后端

可以保留访客自带 Key 的 AI 分析，无需购买云服务器。GitHub Pages 保存网页和已发布的
趋势结果；尾盘数据及 AI 请求通过 HTTPS 隧道访问你电脑上的后端。

## 第一次使用

1. 打开 Docker Desktop，等待启动完成。双击 `Start-TrendRadar.cmd`，确认本地环境正常；
   需要更新服务时点击 **准备本地环境**。本机尾盘页面应能显示已有扫描记录。
2. 确保已安装 GitHub CLI 并执行过 `gh auth login`，账号有当前仓库写入权限。
   仓库的 Pages Source 应为 **GitHub Actions**，且已成功发布过趋势数据。
3. 双击项目根目录 **`Start-PublicWebsite.cmd`**。它会启动网关和 Cloudflare 隧道，
   检查数据库与跨域访问，然后设置仓库变量 `VITE_API_BASE_URL` 并触发 Pages 部署。
   首次可能需要下载容器镜像；窗口会打印当前进度和部署记录链接。
4. 等待 GitHub Actions 的 Pages 工作流显示成功，再刷新原来的 Pages 网站。
   当前项目地址为 <https://y-jerryg.github.io/a-stock-lab/#/tail-radar>。
5. 打开尾盘候选股详情，访客输入自己的 OpenAI API Key，勾选费用确认，点击 AI 分析。
   Key 需要有效且拥有配置模型的调用权限和可用额度。

电脑、Docker、网络必须持续运行，关闭睡眠功能。启动成功后可以关闭命令窗口，容器仍在
后台运行。需要关闭公网后端时双击 **`Stop-PublicWebsite.cmd`**；它保留本地服务和数据。

## 日常使用和断线

- 电脑重启、Docker 重启或隧道断线后，重新运行 `Start-PublicWebsite.cmd`，等待新的
  Pages 部署成功。临时隧道地址可能变化，脚本会更新网站使用的地址；分享的 Pages 地址不变。
- 尾盘读取本机数据库，不需要额外上传 JSON。电脑关闭时，尾盘数据和 AI 暂时不可访问；
  趋势雷达仍能展示最后一次上传到 Pages 的静态结果和 K 线。
- 更新趋势结果仍使用趋势雷达窗口的 **发布网站**；尾盘正式快照仍在交易日中国时间
  14:30 抓取，电脑需在该时间保持运行。
- 查看状态：在项目目录执行 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File
  scripts/public-website.ps1 -Action Status`。查看连接日志可执行
  `docker logs --tail 80 a-stock-lab-public-tunnel-1`。
- 启动时连接检查失败，不会改动网站后端变量，也不会删除已有数据。若提示部署触发失败，
  检查 GitHub 登录及仓库权限后重新运行入口。

## 访客 Key 与接口范围

Key 经 HTTPS 到达你运行的后端，再由后端调用 OpenAI。它不会写入前端发布包、浏览器
持久存储或应用数据库；访客应信任网站运营者。运营者不必提供自己的 Key，分析费用使用
访客 Key 所属账户。AI 结果依照现有研究记录机制保存，访客不应在分析输入中包含私人信息。

独立网关仅允许公开读取和候选股 AI 分析端点；其他内部操作及 API 文档不对外开放。
AI 请求有全局频率与并发限制，繁忙时可能返回 429，稍后再试。网关访问日志不记录请求头、
请求正文或 URL 查询参数。

已用本地网关验证数据读取、跨域预检、未提供 Key 的错误及频率限制。完整公网连接和真实
付费 AI 调用仍需启动后验证；仅能读到数据不代表某个访客的 Key 一定可调用配置模型。

此入口使用无需账户的 Cloudflare Quick Tunnel，适合试用，没有可用性保证；长期稳定使用
可在同一台电脑上配置固定域名的命名隧道，不要求购买云服务器，但仍依赖电脑在线。
限制见 [Cloudflare 官方说明](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)。

## 2026-09-17 修复与日 K 图

“启动公网网站”现在会检查真实 HTTPS 连接，失效时自动重建一次隧道；容器显示 Running
不再被当作公网可用的依据。仍须等待 Pages 部署成功并刷新网页。未开启 AI 也可公开查看行情。
Quick Tunnel 仍可能断线，电脑和 Docker 须在线；断线后再次点击此按钮恢复。

尾盘详情增加“日 K 线与成交量”，保留原有 5 分钟 K 线。日 K 为快照日期之前的已收盘行情，
最多 120 个交易日，显示 MA5/10/20、成交量和采集时间；第一次打开可能等待数十秒，之后一天内
复用本地缓存。图表作为补充参考，不追写或改变原有时点分析证据。无需 API Key。

两个板块的页码、搜索和筛选条件均保存到页面地址。进入详情后点击返回、浏览器后退或刷新，
可以恢复当前页；改变筛选条件会从第一页显示。
