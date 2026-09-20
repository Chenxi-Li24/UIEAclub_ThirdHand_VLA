param(
    [string]$UbuntuHost = "192.168.58.68",
    [string]$UbuntuUser = "nieqingcao",
    [string]$RemoteRoot = "/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA",
    [string]$WebUrl = "http://192.168.58.68:9983/"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command ssh.exe -ErrorAction SilentlyContinue)) {
    throw "Windows OpenSSH client (ssh.exe) is required."
}

$installDirectory = Join-Path $env:LOCALAPPDATA "ThirdHand"
$runnerPath = Join-Path $installDirectory "Start-ThirdHand.cmd"
$desktopPath = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopPath "Start ThirdHand.lnk"
New-Item -ItemType Directory -Force -Path $installDirectory | Out-Null

$runner = @"
@echo off
setlocal
title ThirdHand One-Click Launcher 2026.09.18-3
set "THIRDHAND_LOG=%LOCALAPPDATA%\ThirdHand\last-run.log"
> "%THIRDHAND_LOG%" echo [%DATE% %TIME%] ThirdHand One-Click Launcher 2026.09.18-3 started

echo ThirdHand One-Click Launcher 2026.09.18-3
echo Checking ThirdHand services on ${UbuntuUser}@${UbuntuHost}...
ssh.exe -o BatchMode=yes -o ConnectTimeout=8 ${UbuntuUser}@${UbuntuHost} "cd '${RemoteRoot}' && ./thirdhand ensure --profile manual-control"
set "THIRDHAND_EXIT=%ERRORLEVEL%"
>> "%THIRDHAND_LOG%" echo [%DATE% %TIME%] SSH ensure exit code: %THIRDHAND_EXIT%

if not "%THIRDHAND_EXIT%"=="0" (
    echo.
    echo ThirdHand is only partially ready. Review the feedback above.
    echo Verify this PC's SSH key if authentication failed.
    >> "%THIRDHAND_LOG%" echo [%DATE% %TIME%] Waiting for Enter on failure
    set /p "THIRDHAND_INPUT=Press Enter to close: "
    exit /b %THIRDHAND_EXIT%
)

echo All configured ThirdHand service ports are ready.
>> "%THIRDHAND_LOG%" echo [%DATE% %TIME%] Waiting for Enter before opening browser
set /p "THIRDHAND_INPUT=Press Enter to open ${WebUrl}: "
>> "%THIRDHAND_LOG%" echo [%DATE% %TIME%] Opening ${WebUrl}
start "" "${WebUrl}"
exit /b 0
"@

Set-Content -LiteralPath $runnerPath -Value $runner -Encoding ascii

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $runnerPath
$shortcut.Arguments = ""
$shortcut.WorkingDirectory = $installDirectory
$shortcut.Description = "ThirdHand One-Click Launcher 2026.09.18-3"
$shortcut.Save()

Write-Host "Created: $shortcutPath" -ForegroundColor Green
Write-Host "SSH target: ${UbuntuUser}@${UbuntuHost}"
Write-Host "Each PC must have its own authorized SSH key. No password is stored."
