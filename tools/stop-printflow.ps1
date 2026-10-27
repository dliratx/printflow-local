param([switch]$KeepContainers)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
foreach($taskPort in @(8840,8841,8842,8843,8844)) {
    $taskListener=Get-NetTCPConnection -LocalPort $taskPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if($taskListener) {
        $taskInfo=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskListener.OwningProcess)"
        if($taskInfo.CommandLine -match 'printflow\.(api|host_bridge|portal_mcp|design_worker|image3d_worker)') { Stop-Process -Id $taskListener.OwningProcess }
    }
}
if((-not $KeepContainers) -and (Get-Command docker -ErrorAction SilentlyContinue)) { & (Join-Path $taskRoot '.venv/Scripts/python.exe') (Join-Path $taskRoot 'tools/printflowctl.py') stop }
Write-Output 'PrintFlow services stopped. No printer commands were sent.'
