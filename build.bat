@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo == 打包成单个 exe ==
if not exist ".venv\Scripts\pip.exe" (
    echo 缺少 .venv，先建虚拟环境
    exit /b 1
)

.venv\Scripts\pip.exe install --index-url https://pypi.org/simple pyinstaller
.venv\Scripts\pyinstaller.exe --noconfirm --clean --onefile --windowed ^
    --name PersonalHub ^
    --add-data "src\ui;src\ui" ^
    --add-data "src\migrations;src\migrations" ^
    main.py

echo.
echo 产物在 dist\PersonalHub.exe
echo 想让桌面快捷方式指向 exe，把快捷方式的目标换成 dist\PersonalHub.exe 即可。
