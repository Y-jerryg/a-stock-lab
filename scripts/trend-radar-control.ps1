$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$root = Split-Path $PSScriptRoot -Parent
$logDirectory = Join-Path $root 'runtime\operator'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$script:taskProcess = $null
$script:taskName = ''
$script:logPath = ''
$script:errorPath = ''
$form = New-Object System.Windows.Forms.Form
$form.Text = '趋势雷达 · 电脑端控制'
$form.Size = New-Object System.Drawing.Size(880, 650)
$form.MinimumSize = $form.Size
$form.StartPosition = 'CenterScreen'
$form.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 10)
$hint = New-Object System.Windows.Forms.Label
$hint.Text = '首次使用先准备环境，再开始抓取。网页访客只能查看数据。'
$hint.SetBounds(20, 16, 820, 30)
$form.Controls.Add($hint)
$script:buttons = @()
function Add-ActionButton([string]$Label, [int]$Left, [string]$Action) {
    $button = New-Object System.Windows.Forms.Button
    $button.Text = $Label
    $button.SetBounds($Left, 58, 154, 40)
    $button.Tag = $Action
    $button.Add_Click({ Start-Operation $this.Tag })
    $form.Controls.Add($button)
    $script:buttons += $button
}
Add-ActionButton '准备本地环境' 20 'Initialize'
Add-ActionButton '开始抓取' 185 'Scan'
Add-ActionButton '重新导出结果' 350 'Export'
Add-ActionButton '发布网站' 515 'Publish'
$view = New-Object System.Windows.Forms.Button
$view.Text = '查看结果'
$view.SetBounds(680, 58, 154, 40)
$view.Add_Click({ Start-Process 'http://localhost:8080/#/trend-radar' })
$form.Controls.Add($view)
$status = New-Object System.Windows.Forms.Label
$status.Text = '就绪。发布网站会上传公开结果并触发 GitHub Pages 部署。'
$status.SetBounds(20, 112, 820, 40)
$form.Controls.Add($status)
$log = New-Object System.Windows.Forms.TextBox
$log.Multiline = $true
$log.ReadOnly = $true
$log.ScrollBars = 'Both'
$log.WordWrap = $false
$log.SetBounds(20, 158, 814, 420)
$log.Anchor = 'Top,Bottom,Left,Right'
$form.Controls.Add($log)

function Start-Operation([string]$Action) {
    if ($script:taskProcess) { return }
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $script:logPath = Join-Path $logDirectory "$stamp-output.log"
    $script:errorPath = Join-Path $logDirectory "$stamp-error.log"
    $script:taskName = $Action
    $path = Join-Path $PSScriptRoot 'trend-radar-action.ps1'
    $script:taskProcess = Start-Process powershell.exe -WindowStyle Hidden -PassThru -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $path + '"'), '-Action', $Action
    ) -RedirectStandardOutput $script:logPath -RedirectStandardError $script:errorPath
    foreach ($button in $script:buttons) { $button.Enabled = $false }
    $status.Text = '正在执行，请等待。运行日志保存在 runtime\operator。'
}
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 1000
$timer.Add_Tick({
    if (-not $script:taskProcess) { return }
    $lines = @()
    foreach ($path in @($script:logPath, $script:errorPath)) {
        if (Test-Path -LiteralPath $path) { $lines += Get-Content -LiteralPath $path -Encoding UTF8 -Tail 180 }
    }
    $log.Text = $lines -join [Environment]::NewLine
    $log.SelectionStart = $log.TextLength
    $log.ScrollToCaret()
    if ($script:taskProcess.HasExited) {
        if ($script:taskProcess.ExitCode -eq 0) {
            $status.Text = '操作完成。抓取结果可在本机查看；公网发布状态请查看 GitHub Actions。'
        } else { $status.Text = '操作未完成，请查看日志中的原因。原有成功数据会保留。' }
        $script:taskProcess.Dispose()
        $script:taskProcess = $null
        foreach ($button in $script:buttons) { $button.Enabled = $true }
    }
})
$form.Add_FormClosing({
    if ($script:taskProcess -and -not $script:taskProcess.HasExited) {
        $_.Cancel = $true
        $status.Text = '操作仍在运行，请完成后关闭窗口。'
    }
})
$timer.Start()
try { [void]$form.ShowDialog() } finally { $timer.Dispose(); $form.Dispose() }
