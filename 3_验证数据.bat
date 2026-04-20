@echo off
chcp 65001 >nul
title 验证数据连续性
cd /d "%~dp0"
echo.
echo ============================================
echo   步骤3: 验证数据连续性
echo ============================================
echo.
echo [1/2] 验证小时K线...
python -X utf8 check_item_timestamp_continuity.py --kline-type hourly
echo.
echo [2/2] 验证日K线...
python -X utf8 check_item_timestamp_continuity.py --kline-type daily
echo.
echo [完成] 脚本已结束，按任意键退出。
pause >nul
