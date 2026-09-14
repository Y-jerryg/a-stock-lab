param([Parameter(Mandatory)][ValidateSet('Initialize', 'Scan', 'Export', 'Publish')][string]$Action)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding

function Invoke-Docker([string[]]$Arguments) {
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw "操作未完成（退出码 $LASTEXITCODE），请查看上方具体错误和股票日志。" }
}
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw '请先安装并启动 Docker Desktop。' }
    Invoke-Docker @('info', '--format', '{{.ServerVersion}}')
    if ($Action -eq 'Initialize') {
        Write-Output '正在准备本地数据库和网站，首次构建需要下载依赖……'
        Invoke-Docker @('compose', '--profile', 'trend', 'stop', 'trend-worker')
        Invoke-Docker @('compose', 'build', 'backend', 'frontend')
        Invoke-Docker @('compose', 'up', '-d', 'postgres')
        Invoke-Docker @('compose', 'run', '--rm', 'migrate')
        Invoke-Docker @('compose', 'up', '-d', '--no-deps', 'backend', 'frontend')
        Write-Output '准备完成。点击“开始抓取”，完成后点击“查看结果”。'
    } else {
        Invoke-Docker @('compose', '--profile', 'trend', 'run', '--rm', '--no-deps', 'trend-worker', 'trend-radar', 'health')
        switch ($Action) {
            'Scan' {
                Write-Output '开始抓取热度前 300 的股票（以 .env 参数为准）。耗时取决于行情源，窗口会持续显示日志。'
                Invoke-Docker @('compose', '--profile', 'trend', 'run', '--rm', '--no-deps', 'trend-worker', 'trend-radar', 'scan')
                Write-Output '抓取和本地结果导出完成。本机网页会自动读取新结果；公网更新请点击“发布网站”。'
            }
            'Export' {
                Invoke-Docker @('compose', '--profile', 'trend', 'run', '--rm', '--no-deps', 'trend-worker', 'trend-radar', 'export')
                Write-Output '已从本地数据库重新导出结果，没有重新抓取行情。'
            }
            'Publish' {
                if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw '发布需要 GitHub CLI。安装后执行 gh auth login；详见 docs/trend-radar.md。' }
                & gh auth status
                if ($LASTEXITCODE -ne 0) { throw '请先在终端执行 gh auth login。' }
                Invoke-Docker @('compose', '--profile', 'trend', 'run', '--rm', '--no-deps', 'trend-worker', 'trend-radar', 'bundle')
                # This release stores only the explicit public bundle, never the runtime directory.
                & gh release view trend-radar-data --json tagName 2>$null
                if ($LASTEXITCODE -ne 0) {
                    & gh release create trend-radar-data --target main --title 'Trend Radar public data' --notes 'Public result bundle for the read-only website.' --prerelease
                    if ($LASTEXITCODE -ne 0) { throw '无法创建数据发布，请检查仓库权限和网络。' }
                }
                & gh release upload trend-radar-data (Join-Path $root 'runtime\trend-radar-public.zip') --clobber
                if ($LASTEXITCODE -ne 0) { throw '数据上传失败，网站部署尚未触发。' }
                & gh workflow run pages.yml --ref main -f require_trend_data=true
                if ($LASTEXITCODE -ne 0) { throw '数据已上传，但网站部署触发失败。请在 GitHub Actions 中手动运行 Pages 工作流。' }
                Write-Output '已提交网站部署。请到 GitHub Actions 查看结果；工作流成功后公网网站才会更新。'
            }
        }
    }
    exit 0
} catch {
    Write-Output $_.Exception.Message
    Write-Output '首次使用或更新代码后需要“准备本地环境”；行情接口错误请根据具体日志排查，稍后可重新抓取。'
    exit 1
}
