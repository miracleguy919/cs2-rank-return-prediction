@echo off
chcp 65001 >nul
title 清洗数据
cd /d "%~dp0"
echo.
echo ============================================
echo   步骤2: 清洗数据
echo ============================================
echo.
echo [1/2] 清洗小时K线...
python -X utf8 AI_clean_data.py --dir data/hourly
echo.
echo [2/2] 清洗日K线...
python -X utf8 AI_clean_data.py --dir data/daily
echo.
echo [完成] 脚本已结束，按任意键退出。
pause >nul
