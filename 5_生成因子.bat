@echo off
chcp 65001 >nul
title 生成因子
cd /d "%~dp0"
echo.
echo ============================================
echo   步骤5: 生成因子（预处理）
echo ============================================
echo.
echo [1/2] 处理小时K线...
python -X utf8 TBD/preprocess_xgb.py --data-dir data/hourly
echo.
echo [2/2] 处理日K线...
python -X utf8 TBD/preprocess_xgb.py --data-dir data/daily
echo.
echo [完成] 脚本已结束，按任意键退出。
pause >nul
