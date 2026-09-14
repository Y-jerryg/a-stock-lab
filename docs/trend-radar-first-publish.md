# 板块 2 第一次发布到 GitHub Pages（Windows）

这份步骤对应 `D:\Dev\a-stock-lab` 和现有 `pages.yml`。本机已经有可查看的候选结果和
K 线详情。首次上线需要安装 GitHub CLI、登录、上传代码、开启 Pages、发布结果。
之后只更新数据时，在电脑窗口点“开始抓取 → 发布网站”即可。

下面采用公开仓库 `a-stock-lab`。GitHub Free 支持公开仓库的 Pages；公开仓库意味着别人也
能看到上传的项目源码。私有仓库的 Pages 需要相应账户套餐。参见
[GitHub Pages 官方说明](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)。

## 1. 安装 GitHub CLI

从 Windows 开始菜单打开 PowerShell，执行：

```powershell
winget install --id GitHub.cli --source winget
```

安装完成后关闭 PowerShell 和已打开的趋势雷达控制窗口，再重新打开 PowerShell，让它们
读取更新后的 PATH。验证：

```powershell
gh --version
```

能显示版本号即可。若没有 winget，使用
[GitHub CLI 官方 Windows 安装说明](https://github.com/cli/cli/blob/trunk/docs/install_windows.md)
中的 MSI 安装方式。

## 2. 登录你的 GitHub 账户

```powershell
gh auth login --hostname github.com --git-protocol https --web --scopes workflow
```

按终端提示进入浏览器，登录并输入终端显示的一次性设备码，完成授权。若询问是否允许 Git
使用 GitHub 凭据，选择 Yes。`workflow` 权限用于上传项目已有的 Actions 工作流文件。
没有 GitHub 账户时先在 GitHub 注册并验证邮箱。

完成后执行：

```powershell
gh auth setup-git
gh auth status
```

看到自己的账户已登录后继续。登录流程见
[GitHub CLI 官方文档](https://cli.github.com/manual/gh_auth_login)。

## 3. 保存本次代码修改

```powershell
Set-Location 'D:\Dev\a-stock-lab'
git status --short
git add .
git diff --cached --name-only
```

最后一条列出待提交文件。项目 `.gitignore` 已排除 `.env`、生成的行情文件、数据库运行
目录和依赖目录。列表中不应出现实际 `.env`、API Key 文件或 `runtime` 下的真实数据；
`.env.example` 和 `.gitkeep` 是允许提交的模板、目录占位文件。不要使用 `git add -f`。

确认是本次项目源码后执行：

```powershell
git commit -m "Publish Trend Radar with candidate charts"
```

若提示 `nothing to commit`，说明本地修改已经提交，可继续。若提示缺少作者身份，只在此
仓库设置自己的提交名字和邮箱，然后重试提交：

```powershell
git config user.name '替换成你的提交名字'
git config user.email '替换成你的提交邮箱'
```

邮箱可以使用 GitHub Settings → Emails 中提供的 noreply 地址。不要原样复制占位文字。

## 4. 创建仓库并上传 main

首次创建仓库、且当前项目尚无 origin 时，执行：

```powershell
gh repo create a-stock-lab --public --source=. --remote=origin
git push -u origin main
gh repo view --web
```

第一条在你登录的账户下创建仓库并关联本地目录；第二条上传当前 `main`；第三条在浏览器
打开该仓库。命令用法见 [GitHub CLI 官方文档](https://cli.github.com/manual/gh_repo_create)。
本项目的分支已经是 `main`，不需要重新执行 `git init`。

如果你已经在网页上创建了空仓库，则用该仓库的实际 HTTPS 地址关联，不再执行创建命令：

```powershell
git remote add origin '替换成仓库页面上的实际 HTTPS Git 地址'
git push -u origin main
gh repo view --web
```

如果 `origin` 已存在，用 `git remote -v` 检查目标。不要重复添加或使用强制推送；已有仓库
若不是空的，需要先处理其历史。上传成功后，网页应能找到 `.github/workflows/pages.yml`
和 `frontend`，以及本次新增的趋势雷达详情页代码。

## 5. 开启 GitHub Pages

在刚打开的 GitHub 仓库网页中进入：

**Settings → 左侧 Pages → Build and deployment → Source → GitHub Actions**

项目已经有 Pages 工作流，无需再创建模板。只发布板块 2 时，无需填写 `VITE_API_BASE_URL`、
数据库密码或 OpenAI Key。Settings 看不到时，确认正在打开自己的仓库并已登录。

首次上传可能在开启 Pages 前自动运行一次工作流。如果它因 Pages 尚未启用而失败，完成
本步骤后，通过下一步“发布网站”触发新的部署即可。

## 6. 发布现有结果和 K 线详情

保持 Docker Desktop 正在运行。重新双击项目中的 `Start-TrendRadar.cmd`，点击 **发布网站**。
本机已构建当前版本并导出 18 只候选股，首次发布这些结果无需重新抓取。

按钮依次从本地数据库生成公开 ZIP、上传到本仓库的 `trend-radar-data` Release 附件、
触发 `main` 分支的 `pages.yml`。它会公开扫描摘要、候选指标和候选股当次保存的日线。
无需手动把 ZIP 或整个 `runtime` 文件夹拖到 GitHub 的代码页面。

## 7. 确认成功并分享网址

打开仓库 **Actions**，选择 **Deploy frontend to GitHub Pages**，打开最新一次运行。
等待 **Build public frontend** 和 **Deploy GitHub Pages artifact** 两个任务均显示绿色成功。
然后到 **Settings → Pages** 复制实际网站地址。

若仓库名为 `a-stock-lab`，板块 2 的地址形式为：

```text
https://你的GitHub用户名.github.io/a-stock-lab/#/trend-radar
```

请使用 Pages 显示的真实域名和路径替换示意地址。打开后核对数据日期和候选数量，点击一只
股票确认 K 线能显示，再把这个网址发给朋友。访客无需安装 Docker、登录 GitHub或填写 Key。

“已提交网站部署”只表示部署请求已发出；以 Actions 成功和实际网页内容为准。部署成功后，
关掉本机 Docker、程序和电脑，别人仍能查看已发布的数据。关机期间不会自动抓取新结果。

## 8. 以后怎样更新

- 只更新行情：开电脑和 Docker → 开始抓取 → 发布网站 → 等 Actions 成功。
- 改了代码：先 `git add`、`git commit`、`git push origin main` 上传修改；本地程序需要时
  点击“准备本地环境”采用新代码，再发布结果。发布按钮只上传结果和触发部署，不上传源码。
- 仅补齐已有 K 线详情：使用当前代码点击“重新导出结果”，再“发布网站”，刷新网页。

## 常见卡点

| 现象 | 处理 |
| --- | --- |
| `gh` 不是命令 | 安装后重开 PowerShell 和控制窗口，先确认 `gh --version` |
| 未登录 / 权限不足 | 执行 `gh auth status`，登录有该仓库写权限的账户 |
| 拒绝更新 workflow 文件 | 执行 `gh auth refresh --hostname github.com --scopes workflow`，浏览器授权后再推送 |
| 找不到 GitHub 仓库 | 在项目目录执行 `git remote -v`，检查 origin 是否指向自己的实际仓库 |
| 找不到 `pages.yml` | 确认已把包括 `.github/workflows/pages.yml` 的代码提交并推送到 `main` |
| Actions 的 Configure GitHub Pages 失败 | 检查本仓库 Settings → Pages 的 Source 已选 GitHub Actions |
| 数据上传成功但部署失败 | 打开最新 Actions 的红色步骤查看具体错误；修复后重新点发布网站 |
| 网站没有候选或没有 K 线 | 确认发布的是本机新结果，并等待最新 Actions 成功后刷新 |

板块 2 通过静态文件运行；板块 1 和 AI 分析需要额外部署后端，参见
[两个板块的使用和分享](usage-and-sharing.md)。
