param([ValidateSet('Native','Host','Containers')][string]$Mode='Native',[switch]$WithCad,[switch]$InstallWsl,[switch]$StartAtLogon)
$ErrorActionPreference='Stop'
$taskRoot=$PSScriptRoot
Set-Location -LiteralPath $taskRoot
if($InstallWsl) {
    & wsl.exe --install -d Ubuntu-24.04 --no-launch
    if($LASTEXITCODE -ne 0) { throw 'WSL installation requires Windows prerequisites and may require an elevated PowerShell. Follow the Windows message, then rerun.' }
    Write-Output 'Ubuntu WSL installation requested. Complete its first-run account setup. See INSTALL.md before selecting AMD acceleration.'
    return
}
$taskPython=Join-Path $taskRoot '.venv/Scripts/python.exe'
if(-not (Test-Path -LiteralPath $taskPython)) {
    & python -m venv .venv
    if($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 or newer and add it to PATH first.' }
}
& $taskPython -m pip install -r requirements-web.txt
if($LASTEXITCODE -ne 0) { throw 'Web dependencies could not be installed.' }
& $taskPython -m pip install -e 'vendor/snapmaker-u1-mcp[test]'
if($LASTEXITCODE -ne 0) { throw 'Native bridge dependencies could not be installed.' }
if($WithCad) {
    if(-not (Test-Path -LiteralPath '.venv-design/Scripts/python.exe')) { & $taskPython -m venv .venv-design }
    & .venv-design/Scripts/python.exe -m pip install -r requirements-design.txt
    if($LASTEXITCODE -ne 0) { throw 'CAD dependencies could not be installed.' }
}
& $taskPython tools/printflowctl.py doctor
if($Mode -eq 'Containers') {
    if(-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'For the open-source WSL Docker Engine deployment, select -Mode Host here and run install.sh inside WSL. See INSTALL.md.' }
    & $taskPython tools/printflowctl.py init
    if($LASTEXITCODE -ne 0) { throw 'Container configuration failed.' }
    & tools/start-printflow.ps1 -Docker
} elseif($Mode -eq 'Host') { & tools/start-printflow.ps1 -HostOnly }
else { & tools/start-printflow.ps1 }
if($StartAtLogon) { & tools/set-printflow-startup.ps1 -Mode $Mode }
