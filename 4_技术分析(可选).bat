@echo off
chcp 65001 >nul
title 技术分析
cd /d "%~dp0"
echo.
echo ============================================
echo   步骤4: 技术分析（可选）
echo ============================================
echo.
set /p ITEM_ID=请输入饰品ID（例如48）: 
echo.
echo [启动] 正在运行脚本，请稍候...
echo.
python -X utf8 analyze_single_asset.py --kline-type daily --item-id %ITEM_ID%
if errorlevel 1 (
    echo.
    echo [错误] 脚本运行出错，错误代码: %errorlevel%
)
echo.
echo [完成] 脚本已结束，按任意键退出。
pause >nul
