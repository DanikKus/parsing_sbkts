@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "VENV=%~dp0.venv"
set "PY=%VENV%\Scripts\python.exe"
set "REQ=%~dp0requirements.txt"
set "REQ_STAMP=%VENV%\requirements.installed"

echo [1/4] Останавливаем старые процессы на порту 5000...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":5000 " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo [2/4] Проверяем виртуальное окружение...
if not exist "%PY%" goto :create_venv
"%PY%" -c "import sys" >nul 2>&1
if errorlevel 1 (
    echo  .venv повреждён или скопирован с другого компьютера - пересоздаём...
    rmdir /s /q "%VENV%"
    goto :create_venv
)
echo  .venv в порядке.
goto :check_req

:create_venv
set "SYS_PY="
py -3 --version >nul 2>&1
if not errorlevel 1 set "SYS_PY=py -3"
if not defined SYS_PY (
    python --version >nul 2>&1
    if not errorlevel 1 set "SYS_PY=python"
)
if not defined SYS_PY (
    echo.
    echo  [ОШИБКА] Python не найден.
    echo  Установите Python 3.13 с https://www.python.org/downloads/
    echo  и при установке отметьте галочку "Add python.exe to PATH".
    echo  Потом запустите run.bat ещё раз.
    echo.
    pause
    exit /b 1
)
echo  Создаём .venv через: %SYS_PY%
%SYS_PY% -m venv "%VENV%"
if errorlevel 1 (
    echo  [ОШИБКА] Не удалось создать .venv
    pause
    exit /b 1
)

:check_req
echo [3/4] Проверяем библиотеки...
if not exist "%REQ_STAMP%" goto :install_req
fc /b "%REQ%" "%REQ_STAMP%" >nul 2>&1
if errorlevel 1 goto :install_req
echo  Библиотеки актуальны.
goto :run

:install_req
echo  Устанавливаем библиотеки из requirements.txt (первый раз это займёт пару минут)...
set "PYTHONUTF8=1"
"%PY%" -m pip install --upgrade pip >nul 2>&1
"%PY%" -m pip install -r "%REQ%"
if errorlevel 1 (
    set "PYTHONUTF8="
    echo  [ОШИБКА] Не удалось установить библиотеки. Проверьте интернет и повторите.
    pause
    exit /b 1
)
set "PYTHONUTF8="
copy /y "%REQ%" "%REQ_STAMP%" >nul

:run
echo [4/4] Запускаем сервер...
echo  Папка: %~dp0
echo  Логи:  %~dp0logs\app.log
echo.
"%PY%" app.py
pause
