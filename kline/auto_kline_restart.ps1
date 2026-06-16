# Auto-restart wrapper for K-line crawler (增量模式)
# 2026-06-09 升级: 从 auto_kline_crawler.py 改指 auto_kline_incremental.py
# 旧脚本已 deprecated, 详见 .trae/specs/kline-dual-script-architecture/

# 用法: powershell -ExecutionPolicy Bypass -File kline\auto_kline_restart.ps1

$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

Set-Location 'f:\cursor\cs2-rank-return-prediction-main'

# 启动增量爬取 (输出到 log, 错误也到 log)
# incremental 默认行为: 跳过无 hourly/daily 文件的 item (留 history 脚本), 抓最新 1 页 merge 到现有数据
$proc = Start-Process -FilePath 'python' `
    -ArgumentList 'kline/auto_kline_incremental.py', '--api-delay', '0.3' `
    -WorkingDirectory 'f:\cursor\cs2-rank-return-prediction-main' `
    -RedirectStandardOutput 'data\kline_run_scheduled.log' `
    -RedirectStandardError 'data\kline_run_scheduled.err' `
    -WindowStyle Hidden `
    -PassThru

Write-Host "启动 PID=$($proc.Id) at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
