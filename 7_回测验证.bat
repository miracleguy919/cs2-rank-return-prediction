@echo off
chcp 65001 >nul
title 回测验证
cd /d "%~dp0"
echo.
echo ============================================
echo   步骤7: 回测验证
echo ============================================
echo.
echo [启动] 正在运行脚本，请稍候...
echo.
python -X utf8 TBD/backtest_xgb.py
if errorlevel 1 (
    echo.
    echo [错误] 脚本运行出错，错误代码: %errorlevel%
)
echo.
echo [完成] 脚本已结束，按任意键退出。
pause >nul
