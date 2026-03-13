@echo off
chcp 65001 >nul
title 手动获取饰品数据
cd /d "%~dp0"
echo.
echo ============================================
echo   手动获取饰品数据 - AI_collect_dual_kline
echo ============================================
echo.
echo [启动] 正在运行脚本，请稍候...
echo.
python -X utf8 AI_collect_dual_kline.py
if errorlevel 1 (
    echo.
    echo [错误] 脚本运行出错，错误代码: %errorlevel%
)
echo.
echo [完成] 脚本已结束，按任意键退出。
pause >nul
