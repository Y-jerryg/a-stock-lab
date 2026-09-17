param([ValidateSet('Start', 'Stop', 'Status')][string]$Action = 'Start')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$statePath = Join-Path $root 'runtime\public-website\state.json'
$state = if (Test-Path -LiteralPath $statePath) { Get-Content -Raw -Encoding UTF8 $statePath | ConvertFrom-Json } else { $null }
$env:PUBLIC_PAGES_ORIGIN = if ($state) { $state.pages_origin } else { 'http://localhost' }
$compose = @('compose', '-f', 'compose.yaml', '-f', 'compose.public.yaml')

function Invoke-External([string]$Executable, [string[]]$Arguments) {
    $ErrorActionPreference = 'Continue'
    $PSNativeCommandUseErrorActionPreference = $false
    $lines = & $Executable @Arguments 2>&1
    $code = $LASTEXITCODE
    $output = ($lines | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
    if ($code -ne 0) { throw "命令执行失败（$Executable，退出码 $code）：`n$output" }
    return $output
}

try {
    if ($Action -eq 'Stop') {
        Write-Output (Invoke-External 'docker' ($compose + @('stop', 'public-tunnel', 'public-api')))
        Write-Output '公网后端已停止。本地数据和趋势雷达已发布结果仍保留。'
        exit 0
    }
    if ($Action -eq 'Status') {
        Write-Output (Invoke-External 'docker' ($compose + @('ps', 'public-api', 'public-tunnel')))
        if ($state) { Write-Output "上次连接的后端：$($state.api_url)`n网站：$($state.pages_url)" }
        exit 0
    }
    $gh = Get-Command gh -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    $ghPath = if ($gh) { $gh.Source } else { Join-Path $env:ProgramFiles 'GitHub CLI\gh.exe' }
    if (-not (Test-Path -LiteralPath $ghPath)) { throw '请先安装 GitHub CLI 并执行 gh auth login。' }
    $repository = (Invoke-External $ghPath @('repo', 'view', '--json', 'nameWithOwner', '--jq', '.nameWithOwner')).Trim()
    if ($repository -notmatch '^[\w.-]+/[\w.-]+$') { throw '无法确定当前 GitHub 仓库。' }
    $pagesUrl = (Invoke-External $ghPath @('api', "repos/$repository/pages", '--jq', '.html_url')).Trim()
    $pagesUri = [Uri]$pagesUrl
    if ($pagesUri.Scheme -ne 'https' -or $pagesUri.Host -notmatch '^[a-zA-Z0-9.-]+$') { throw 'Pages 必须使用有效的 HTTPS 地址。' }
    $env:PUBLIC_PAGES_ORIGIN = $pagesUri.GetLeftPart([UriPartial]::Authority)
    $health = Invoke-RestMethod 'http://localhost:8080/api/v1/health' -TimeoutSec 10
    if ($health.database.status -ne 'available') { throw '本机数据库不可用，请先在趋势雷达窗口准备本地环境。' }
    $availability = Invoke-RestMethod 'http://localhost:8080/api/v1/tail-radar/research-availability' -TimeoutSec 10
    if (-not $availability.enabled) { Write-Output 'AI 分析未开启；公网仍可查看尾盘结果和图表。' }
    Write-Output "正在连接本机后端，访客网站：$pagesUrl"
    Write-Output (Invoke-External 'docker' ($compose + @('up', '-d', '--no-deps', 'public-api')))
    Write-Output (Invoke-External 'docker' ($compose + @('up', '-d', 'public-tunnel')))
    $ready = $false
    for ($round = 0; $round -lt 2 -and -not $ready; $round++) {
        if ($round -eq 1) {
            Write-Output '现有公网连接已失效，正在重建隧道……'
            Write-Output (Invoke-External 'docker' ($compose + @('up', '-d', '--force-recreate', 'public-tunnel')))
        }
        $containerId = (Invoke-External 'docker' ($compose + @('ps', '-q', 'public-tunnel'))).Trim()
        $startedAt = (Invoke-External 'docker' @('inspect', '--format', '{{.State.StartedAt}}', $containerId)).Trim()
        $apiUrl = $null
        for ($attempt = 0; $attempt -lt 40; $attempt++) {
            $tunnelLog = Invoke-External 'docker' @('logs', '--since', $startedAt, $containerId)
            $urls = [regex]::Matches($tunnelLog, 'https://[a-z0-9-]+\.trycloudflare\.com')
            if ($urls.Count) { $apiUrl = $urls[$urls.Count - 1].Value; break }
            Start-Sleep -Seconds 3
        }
        if (-not $apiUrl) { continue }
        Write-Output "正在检查公网连接：$apiUrl"
        $checks = if ($round -eq 0) { 3 } else { 20 }
        for ($attempt = 0; $attempt -lt $checks; $attempt++) {
            try {
                $publicHealth = Invoke-RestMethod "$apiUrl/api/v1/health" -Headers @{Origin=$env:PUBLIC_PAGES_ORIGIN} -TimeoutSec 10
                if ($publicHealth.database.status -eq 'available') { $ready = $true; break }
            } catch { }
            Start-Sleep -Seconds 3
        }
    }
    if (-not $ready) { throw '公网连接暂不可用；没有更改网站的后端地址。稍后重新运行本程序。' }
    $preflight = Invoke-WebRequest -UseBasicParsing -Method Options -Uri "$apiUrl/api/internal/v1/tail-radar/candidates/00000000-0000-0000-0000-000000000000/research" -Headers @{
        Origin=$env:PUBLIC_PAGES_ORIGIN
        'Access-Control-Request-Method'='POST'
        'Access-Control-Request-Headers'='content-type,x-openai-api-key'
    } -TimeoutSec 15
    $allowedHeaders = @(([string]$preflight.Headers['Access-Control-Allow-Headers']).ToLowerInvariant().Split(',') | ForEach-Object { $_.Trim() })
    $allowedMethods = @(([string]$preflight.Headers['Access-Control-Allow-Methods']).ToUpperInvariant().Split(',') | ForEach-Object { $_.Trim() })
    if ($preflight.StatusCode -ne 204 -or $preflight.Headers['Access-Control-Allow-Origin'] -ne $env:PUBLIC_PAGES_ORIGIN -or
        $allowedHeaders -notcontains 'x-openai-api-key' -or $allowedHeaders -notcontains 'content-type' -or $allowedMethods -notcontains 'POST') {
        throw '公网跨域检查失败；没有更改网站配置。'
    }
    $runtimeState = [ordered]@{
        api_url=$apiUrl; pages_url=$pagesUrl; pages_origin=$env:PUBLIC_PAGES_ORIGIN
        repository=$repository; tunnel_started_at=$startedAt; connected_at=[DateTimeOffset]::UtcNow.ToString('o')
    }
    New-Item -ItemType Directory -Force (Split-Path $statePath) | Out-Null
    $runtimeState | ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath $statePath
    Write-Output (Invoke-External $ghPath @('variable', 'set', 'VITE_API_BASE_URL', '--repo', $repository, '--body', $apiUrl))
    Write-Output (Invoke-External $ghPath @('workflow', 'run', 'pages.yml', '--repo', $repository, '--ref', 'main', '-f', 'require_trend_data=true'))
    Write-Output "连接已建立，已触发网站部署。请等待 Actions 成功后刷新：$pagesUrl#/tail-radar"
    Write-Output "部署记录：https://github.com/$repository/actions/workflows/pages.yml"
    Write-Output '电脑、Docker 和网络需要持续运行。测试隧道重启可能换地址，届时重新运行本程序更新网站。'
} catch {
    Write-Output $_.Exception.Message
    Write-Output '本机数据仍保留。检查 Docker、GitHub 登录和网络后重试；停止入口可以关闭公网连接。'
    exit 1
}
