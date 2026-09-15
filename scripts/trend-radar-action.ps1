param(
    [Parameter(Mandatory)][ValidateSet('Start', 'Initialize', 'Scan', 'Export', 'Publish', 'Status', 'PublicStart', 'PublicStop')][string]$Action,
    [string]$ResultPath
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$env:COMPOSE_IGNORE_ORPHANS = 'true'
$operationState = 'completed'
$operationMessage = '操作完成。'
$scanSummary = $null

function Write-OperationResult([int]$Code, [string]$State, [string]$Message) {
    if ($ResultPath) {
        $record = [ordered]@{action=$Action; exit_code=$Code; state=$State; message=$Message; scan=$scanSummary; finished_at=[DateTimeOffset]::UtcNow.ToString('o')}
        $record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ResultPath -Encoding UTF8
    }
}

function Invoke-Docker([string[]]$Arguments) {
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw "操作未完成（退出码 $LASTEXITCODE），请查看上方具体错误和股票日志。" }
}

# Windows PowerShell 5.1 treats redirected native stderr as a terminating error when
# ErrorActionPreference is Stop. Capture it locally and decide using the process exit code.
function Invoke-GitHub([string[]]$Arguments) {
    $ErrorActionPreference = 'Continue'
    $PSNativeCommandUseErrorActionPreference = $false
    $lines = & $script:githubCli @Arguments 2>&1
    $nativeExit = $LASTEXITCODE
    [pscustomobject]@{
        ExitCode = $nativeExit
        Output = ($lines | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
    }
}

function Assert-GitHubSuccess($Result, [string]$Message) {
    if ($Result.ExitCode -ne 0) { throw "$Message`n$($Result.Output)" }
    if ($Result.Output) { Write-Output $Result.Output }
}
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw '请先安装并启动 Docker Desktop。' }
    Invoke-Docker @('info', '--format', '{{.ServerVersion}}')
    if ($Action -eq 'Status') {
        Invoke-Docker @('compose', 'ps', '-a')
        foreach ($entry in @(
            @{Name='本机尾盘'; Url='http://localhost:8080/api/v1/tail-radar/runs/latest'},
            @{Name='本机趋势'; Url='http://localhost:8080/data/trend-radar/index.json'}
        )) {
            try {
                $data = Invoke-RestMethod $entry.Url -TimeoutSec 10
                if ($entry.Name -eq '本机趋势') { $data = $data.latest; $count = $data.payload.candidate_count } else { $count = $data.candidate_count }
                Write-Output "$($entry.Name)：日期 $($data.trade_date)，状态 $($data.status)，候选 $count 只。"
            } catch { Write-Output "$($entry.Name)：无法读取。先点击“启动本机服务”，再检查 Docker 和日志。" }
        }
        Write-Output 'public-tunnel 为 Exited 时公网尾盘不可用，请点击“启动公网网站”。趋势公网结果还需要“发布网站”。'
        $operationMessage = '检查完成，具体服务状态和结果日期见日志。'
    } elseif ($Action -in @('PublicStart', 'PublicStop')) {
        $publicAction = if ($Action -eq 'PublicStart') { 'Start' } else { 'Stop' }
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'public-website.ps1') -Action $publicAction
        if ($LASTEXITCODE -ne 0) { throw '公网操作未完成，请查看连接或 GitHub 错误；无需重新抓取股票。' }
        $operationMessage = if ($Action -eq 'PublicStart') { '公网连接已建立；等待 GitHub Actions 部署成功后刷新网站。' } else { '公网连接已停止，本机数据仍保留。' }
    } elseif ($Action -in @('Initialize', 'Start')) {
        if ($Action -eq 'Initialize') {
        Write-Output '正在准备本地数据库和网站，首次构建需要下载依赖……'
        Invoke-Docker @('compose', '--profile', 'trend', 'stop', 'trend-worker')
        Invoke-Docker @('compose', 'build', 'backend', 'frontend')
        }
        Invoke-Docker @('compose', 'up', '-d', 'postgres')
        Invoke-Docker @('compose', 'run', '--rm', 'migrate')
        Invoke-Docker @('compose', 'up', '-d', '--no-deps', 'backend', 'frontend', 'worker')
        $operationMessage = '本机两个板块及尾盘定时服务已启动。趋势数据更新请点击“开始抓取”。'
        Write-Output $operationMessage
    } else {
        Invoke-Docker @('compose', '--profile', 'trend', 'run', '--rm', '--no-deps', 'trend-worker', 'trend-radar', 'health')
        switch ($Action) {
            'Scan' {
                Write-Output '开始扫描沪深北全部 A 股，关注度前 300 仅优先高亮（以 .env 参数为准）。全市场抓取耗时更长，窗口会持续显示进度。'
                $scanOutput = @(Invoke-Docker @('compose', '--profile', 'trend', 'run', '--rm', '--no-deps', 'trend-worker', 'trend-radar', 'scan', '--summary'))
                $scanSummary = ($scanOutput | Where-Object { $_ -match '^\{' } | Select-Object -Last 1) | ConvertFrom-Json
                if ($scanSummary.status -notin @('success', 'completed_with_warnings')) { throw '扫描未返回已完成状态，请查看日志。' }
                $operationState = if ($scanSummary.status -eq 'completed_with_warnings') { 'completed_with_warnings' } else { 'completed' }
                $operationMessage = "扫描完成：共 $($scanSummary.requested_count) 只，成功处理 $($scanSummary.successful_count) 只，失败 $($scanSummary.failed_count) 只，候选 $($scanSummary.candidate_count) 只。结果已保存，可查看；公网更新请发布网站。"
                Write-Output $operationMessage
            }
            'Export' {
                Invoke-Docker @('compose', '--profile', 'trend', 'run', '--rm', '--no-deps', 'trend-worker', 'trend-radar', 'export')
                Write-Output '已从本地数据库重新导出结果，没有重新抓取行情。'
                $operationMessage = '已有结果已重新导出，无需重新抓取。'
            }
            'Publish' {
                $ghCommand = Get-Command gh -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
                $script:githubCli = if ($ghCommand) { $ghCommand.Source } else { Join-Path $env:ProgramFiles 'GitHub CLI\gh.exe' }
                if (-not (Test-Path -LiteralPath $script:githubCli)) { throw '发布需要 GitHub CLI。安装后执行 gh auth login；详见 docs/trend-radar.md。' }
                Assert-GitHubSuccess (Invoke-GitHub @('auth', 'status')) '请先在终端执行 gh auth login。'
                $repositoryResult = Invoke-GitHub @('repo', 'view', '--json', 'nameWithOwner', '--jq', '.nameWithOwner')
                if ($repositoryResult.ExitCode -ne 0) { throw "无法确定发布仓库，请检查项目的 origin 地址。`n$($repositoryResult.Output)" }
                $repository = $repositoryResult.Output.Trim()
                if ($repository -notmatch '^[\w.-]+/[\w.-]+$') { throw 'GitHub 返回了无效的仓库名称。' }
                Write-Output "发布目标仓库：$repository"
                Invoke-Docker @('compose', '--profile', 'trend', 'run', '--rm', '--no-deps', 'trend-worker', 'trend-radar', 'bundle')
                $indexPath = Join-Path $root 'runtime\public\trend-radar\index.json'
                if (Test-Path -LiteralPath $indexPath) {
                    $index = Get-Content -Raw -Encoding UTF8 -LiteralPath $indexPath | ConvertFrom-Json
                    $requiredVersion = ($index.attempts | ForEach-Object { $_.payload.configuration_snapshot.rule_version } | Measure-Object -Maximum).Maximum
                    if ($requiredVersion -ge 2) {
                        $versionResult = Invoke-GitHub @('api', "repos/$repository/contents/frontend/public/app-version.json?ref=main", '--jq', '.content')
                        if ($versionResult.ExitCode -ne 0) { throw 'GitHub 上的网页代码尚未支持当前筛选规则。先同步并部署项目代码，再发布结果；本次没有覆盖线上数据。' }
                        $version = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($versionResult.Output.Trim())) | ConvertFrom-Json
                        if ($version.trend_rule_version -lt $requiredVersion) { throw 'GitHub 网页版本落后于结果版本，请先更新代码再发布。' }
                    }
                }
                # This release stores only the explicit public bundle, never the runtime directory.
                $release = Invoke-GitHub @('release', 'view', 'trend-radar-data', '--repo', $repository, '--json', 'tagName')
                if ($release.ExitCode -ne 0) {
                    if ($release.Output.Trim() -ne 'release not found') {
                        throw "无法查询数据发布；尚未上传或触发部署，请检查权限和网络。`n$($release.Output)"
                    }
                    Write-Output '首次发布：正在创建公开数据 Release……'
                    Assert-GitHubSuccess (Invoke-GitHub @('release', 'create', 'trend-radar-data', '--repo', $repository, '--target', 'main', '--title', 'Trend Radar public data', '--notes', 'Public candidate metrics and saved daily bars for the read-only website.', '--prerelease')) '无法创建数据发布，请检查仓库权限和网络。'
                }
                Assert-GitHubSuccess (Invoke-GitHub @('release', 'upload', 'trend-radar-data', (Join-Path $root 'runtime\trend-radar-public.zip'), '--repo', $repository, '--clobber')) '数据上传失败，网站部署尚未触发。'
                Assert-GitHubSuccess (Invoke-GitHub @('workflow', 'run', 'pages.yml', '--repo', $repository, '--ref', 'main', '-f', 'require_trend_data=true')) '数据已上传，但网站部署触发失败。请在 GitHub Actions 中手动运行 Pages 工作流。'
                Write-Output '已提交网站部署。请到 GitHub Actions 查看结果；工作流成功后公网网站才会更新。'
                Write-Output "部署记录：https://github.com/$repository/actions/workflows/pages.yml"
                $operationState = 'submitted'
                $operationMessage = '数据已上传，网站部署已提交。等待 GitHub Actions 成功后，公网网站才会更新；不需要重新抓取。'
            }
        }
    }
    Write-OperationResult 0 $operationState $operationMessage
    exit 0
} catch {
    Write-OperationResult 1 'failed' $_.Exception.Message
    Write-Output $_.Exception.Message
    if ($Action -eq 'Publish') {
        Write-Output '发布失败不会删除本地已抓取数据，无需重新扫描。请根据上方 GitHub、网络或部署错误处理后重试。'
    } else {
        Write-Output '首次使用或更新代码后需要“准备本地环境”；行情接口错误请根据具体日志排查，稍后可重新抓取。'
    }
    exit 1
}
