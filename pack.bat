@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem Собирает чистый архив проекта для переноса на другие компьютеры.
rem Без .venv, кэшей, логов и личных токенов/паролей.

for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmm"') do set "STAMP=%%d"
set "OUT_DIR=%~dp0_pack"
set "STAGE=%TEMP%\parsing_skbts_pack_%STAMP%"
set "ZIP=%OUT_DIR%\parsing_skbts_%STAMP%.zip"

echo [1/3] Копируем файлы проекта...
if exist "%STAGE%" rmdir /s /q "%STAGE%"
robocopy "%~dp0." "%STAGE%" /E /NFL /NDL /NJH /NJS /NP ^
  /XD .venv .git .idea .claude __pycache__ logs pts_cache photo_cache debug customs_debug auth_store build dist _pack ^
  /XF .env auth_cache.json techreg_cookies.json *.pem decisions_queue.json decisions_sent.json decisions_dead.json *.zip *.crx *.pyc
if errorlevel 8 (
    echo  [ОШИБКА] Не удалось скопировать файлы.
    pause
    exit /b 1
)

echo [2/3] Упаковываем в zip...
if not exist "%OUT_DIR%" mkdir "%OUT_DIR%"
powershell -NoProfile -Command "Compress-Archive -Path '%STAGE%\*' -DestinationPath '%ZIP%' -Force"
if errorlevel 1 (
    echo  [ОШИБКА] Не удалось создать архив.
    rmdir /s /q "%STAGE%"
    pause
    exit /b 1
)

echo [3/3] Убираем временные файлы...
rmdir /s /q "%STAGE%"

echo.
echo  Готово: %ZIP%
echo  На другом компьютере: распаковать и запустить run.bat
echo.
pause
