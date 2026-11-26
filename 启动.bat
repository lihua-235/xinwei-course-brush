@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

set "PY="
where python >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto :findok
where py >nul 2>nul
if not errorlevel 1 set "PY=py"
if defined PY goto :findok

echo ============================================================
echo  [错误] 没有检测到 Python
echo ============================================================
echo  请先安装 Python 3.8 或更高版本：
echo     https://www.python.org/downloads/
echo  安装时务必勾选  "Add Python to PATH"
echo  装完重新双击本文件即可。
echo ============================================================
pause
exit /b 1

:findok
echo 已找到 Python: %PY%

%PY% -c "import requests, brotli" >nul 2>nul
if not errorlevel 1 goto :run

echo 首次运行，正在安装依赖（requests / brotli）...
%PY% -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet
%PY% -c "import requests, brotli" >nul 2>nul
if errorlevel 1 (
    echo [错误] 依赖安装失败，请手动执行:
    echo     %PY% -m pip install -r requirements.txt
    pause
    exit /b 1
)
echo 依赖安装完成。

:run
%PY% main.py %*
pause
