param(
    [ValidateSet('Native','Host','Containers')][string]$Mode='Native',
    [switch]$Disable
)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
$taskLauncher=Join-Path $PSScriptRoot 'start-printflow.ps1'
$taskStartup=[Environment]::GetFolderPath('Startup')
if (-not $taskStartup) { throw 'The current Windows user has no Startup folder.' }
$taskShortcutPath=Join-Path $taskStartup 'PrintFlow Local.lnk'
$taskShell=New-Object -ComObject WScript.Shell
try {
    if (Test-Path -LiteralPath $taskShortcutPath) {
        $taskExisting=$taskShell.CreateShortcut($taskShortcutPath)
        if (-not $taskExisting.Arguments.Contains('"'+$taskLauncher+'"')) {
            throw 'A PrintFlow startup shortcut belongs to another checkout. Remove it explicitly before registering this installation.'
        }
    }
    if ($Disable) {
        if (Test-Path -LiteralPath $taskShortcutPath) { Remove-Item -LiteralPath $taskShortcutPath }
        Write-Output 'PrintFlow sign-in startup disabled. Running services were not stopped.'
        return
    }
    if (-not (Test-Path -LiteralPath (Join-Path $taskRoot '.venv/Scripts/python.exe'))) {
        throw 'Install PrintFlow before enabling sign-in startup.'
    }
    New-Item -ItemType Directory -Path $taskStartup -Force | Out-Null
    $taskModeArgument=switch($Mode) { 'Host' { ' -HostOnly' }; 'Containers' { ' -Docker' }; default { '' } }
    $taskShortcut=$taskShell.CreateShortcut($taskShortcutPath)
    $taskShortcut.TargetPath=(Get-Command powershell.exe -ErrorAction Stop).Source
    $taskShortcut.Arguments='-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -File "{0}"{1}' -f $taskLauncher,$taskModeArgument
    $taskShortcut.WorkingDirectory=$taskRoot
    $taskShortcut.WindowStyle=7
    $taskShortcut.Description='Start missing PrintFlow services when this Windows user signs in. Does not start or resume prints.'
    $taskShortcut.Save()
    Write-Output "PrintFlow $Mode startup enabled for the current Windows user: $taskShortcutPath"
} finally {
    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($taskShell)
}
