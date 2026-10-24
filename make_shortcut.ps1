# 在桌面创建 PersonalHub 快捷方式。换机器或搬了项目目录，重跑一次即可。
# 用法： powershell -ExecutionPolicy Bypass -File make_shortcut.ps1

$ErrorActionPreference = "Stop"

$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw = Join-Path $project ".venv\Scripts\pythonw.exe"
$entry = Join-Path $project "main.py"

if (-not (Test-Path $pythonw)) {
    Write-Error "找不到 $pythonw，先在 $project 里建好 .venv 并装好 pywebview"
}

$shell = New-Object -ComObject WScript.Shell
$desktop = $shell.SpecialFolders("Desktop")
$shortcut = $shell.CreateShortcut((Join-Path $desktop "PersonalHub.lnk"))
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '"' + $entry + '"'
$shortcut.WorkingDirectory = $project
$shortcut.Description = "PersonalHub 个人管理系统"
$shortcut.Save()

Write-Output "快捷方式已创建：$desktop\PersonalHub.lnk"
Write-Output "指向：$pythonw"
