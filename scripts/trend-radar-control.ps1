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
$script:resultPath = ''
$form = New-Object System.Windows.Forms.Form
$form.Text = 'A股实验室 · 两个雷达的电脑控制'
$form.Size = New-Object System.Drawing.Size(880, 720)
$form.MinimumSize = $form.Size
$form.StartPosition = 'CenterScreen'
$form.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 10)
$hint = New-Object System.Windows.Forms.Label
$hint.Text = '日常先启动本机服务。尾盘自动定时抓取；趋势手动抓取后发布。右下方可打开详细指南。'
$hint.SetBounds(20, 16, 820, 30)
$form.Controls.Add($hint)
$script:buttons = @()
function Add-ActionButton([string]$Label, [int]$Left, [string]$Action, [int]$Top = 58) {
    $button = New-Object System.Windows.Forms.Button
    $button.Text = $Label
    $button.SetBounds($Left, $Top, 154, 40)
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
Add-ActionButton '启动本机服务' 20 'Start' 108
Add-ActionButton '检查运行状态' 185 'Status' 108
Add-ActionButton '启动公网网站' 350 'PublicStart' 108
Add-ActionButton '停止公网网站' 515 'PublicStop' 108
$tailView = New-Object System.Windows.Forms.Button
$tailView.Text = '打开尾盘雷达'
$tailView.SetBounds(680, 108, 154, 40)
$tailView.Add_Click({ Start-Process 'http://localhost:8080/#/tail-radar' })
$form.Controls.Add($tailView)
$guide = New-Object System.Windows.Forms.LinkLabel
$guide.Text = '详细操作指南（离线可读）'
$guide.SetBounds(600, 646, 240, 30)
$guide.Anchor = 'Bottom,Right'
$guide.Add_LinkClicked({ Start-Process (Join-Path $root 'docs\user-guide.html') })
$form.Controls.Add($guide)
$status = New-Object System.Windows.Forms.Label
$status.Text = '就绪。发布网站会上传公开结果并触发 GitHub Pages 部署。'
$status.SetBounds(20, 162, 820, 55)
$form.Controls.Add($status)
$log = New-Object System.Windows.Forms.TextBox
$log.Multiline = $true
$log.ReadOnly = $true
$log.ScrollBars = 'Both'
$log.WordWrap = $false
$log.SetBounds(20, 222, 814, 414)
$log.Anchor = 'Top,Bottom,Left,Right'
$form.Controls.Add($log)

function Start-Operation([string]$Action) {
    if ($script:taskProcess) { return }
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $script:logPath = Join-Path $logDirectory "$stamp-output.log"
    $script:errorPath = Join-Path $logDirectory "$stamp-error.log"
    $script:resultPath = Join-Path $logDirectory "$stamp-result.json"
    $script:taskName = $Action
    $path = Join-Path $PSScriptRoot 'trend-radar-action.ps1'
    $script:taskProcess = Start-Process powershell.exe -WindowStyle Hidden -PassThru -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $path + '"'), '-Action', $Action,
        '-ResultPath', ('"' + $script:resultPath + '"')
    ) -RedirectStandardOutput $script:logPath -RedirectStandardError $script:errorPath
    foreach ($button in $script:buttons) { $button.Enabled = $false }
    $status.Text = '正在执行，请等待。运行日志保存在 runtime\operator。'
    $status.ForeColor = [System.Drawing.Color]::Black
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
        $script:taskProcess.WaitForExit()
        $result = if (Test-Path -LiteralPath $script:resultPath) {
            try { Get-Content -Raw -Encoding UTF8 -LiteralPath $script:resultPath | ConvertFrom-Json } catch { $null }
        } else { $null }
        if ($result) {
            $status.Text = $result.message
            $status.ForeColor = if ($result.exit_code -eq 0) { [System.Drawing.Color]::DarkGreen } else { [System.Drawing.Color]::Firebrick }
        } elseif ($script:taskProcess.ExitCode -eq 0) {
            $status.Text = '操作完成，具体结果请查看日志。'
        } else {
            $status.Text = '进程退出但未得到结果报告。请先检查运行状态；这不代表已保存数据丢失，不要立即重新抓取。'
        }
        $script:taskProcess.Dispose()
        $script:taskProcess = $null
        foreach ($button in $script:buttons) { $button.Enabled = $true }
    } elseif ($script:taskName -eq 'Scan') {
        $progressLine = $lines | Where-Object { $_ -match '"stock_number"' } | Select-Object -Last 1
        if ($progressLine) {
            try {
                $progress = $progressLine | ConvertFrom-Json
                $status.Text = "正在处理 $($progress.stock_number) / $($progress.total)：$($progress.symbol) $($progress.stock_name)。请保持电脑唤醒；个别股票失败会继续处理。"
            } catch { }
        }
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
