param([switch]$Docker,[switch]$HostOnly)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
$taskPython=Join-Path $taskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Create .venv and install requirements-web.txt before starting.' }
$taskRuntime=Join-Path $taskRoot '.runtime'
New-Item -ItemType Directory -Path $taskRuntime -Force | Out-Null
$taskTokenPath=Join-Path $taskRuntime 'bridge-token'
if (-not (Test-Path -LiteralPath $taskTokenPath)) { Push-Location $taskRoot; try { & $taskPython -c 'from printflow.common import bridge_token; bridge_token()' } finally { Pop-Location } }
$taskSecret=Get-Content -LiteralPath $taskTokenPath -Raw
$taskEnvPath=Join-Path $taskRoot '.env'
if (-not (Test-Path -LiteralPath $taskEnvPath)) { Set-Content -LiteralPath $taskEnvPath -Value "PRINTFLOW_BRIDGE_TOKEN=$($taskSecret.Trim())" -Encoding utf8 }
$taskBind=if($Docker -or $HostOnly){'0.0.0.0'}else{'127.0.0.1'}
function Start-PrintFlowService($taskName,$taskArguments,$taskInterpreter=$taskPython) {
    $taskLog=Join-Path $taskRuntime "$taskName.log"
    $taskError=Join-Path $taskRuntime "$taskName.error.log"
    $taskProcess=Start-Process -FilePath $taskInterpreter -ArgumentList $taskArguments -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $taskLog -RedirectStandardError $taskError
    Set-Content -LiteralPath (Join-Path $taskRuntime "$taskName.pid") -Value $taskProcess.Id
}
if (-not (Get-NetTCPConnection -LocalPort 8841 -State Listen -ErrorAction SilentlyContinue)) { Start-PrintFlowService 'host' "-m uvicorn printflow.host_bridge:app --host $taskBind --port 8841" }
if($HostOnly) { Write-Output 'Windows bridge started on port 8841. Start the container stack from its deployment environment.'; return }
if($Docker) {
    & $taskPython (Join-Path $taskRoot 'tools/printflowctl.py') up
    if($LASTEXITCODE -ne 0) { throw 'Docker Compose could not be started.' }
} else {
    if (-not (Get-NetTCPConnection -LocalPort 8840 -State Listen -ErrorAction SilentlyContinue)) { Start-PrintFlowService 'web' '-m uvicorn printflow.api:app --host 127.0.0.1 --port 8840' }
    if (-not (Get-NetTCPConnection -LocalPort 8842 -State Listen -ErrorAction SilentlyContinue)) { Start-PrintFlowService 'mcp' '-m printflow.portal_mcp' }
    $taskCadPython=Join-Path $taskRoot '.venv-design\Scripts\python.exe'
    if ((Test-Path -LiteralPath $taskCadPython) -and -not (Get-NetTCPConnection -LocalPort 8843 -State Listen -ErrorAction SilentlyContinue)) { Start-PrintFlowService 'design' '-m uvicorn printflow.design_worker:app --host 127.0.0.1 --port 8843' $taskCadPython }
    $taskImagePython=Join-Path $taskRoot '.venv-image3d\Scripts\python.exe'
    if ((Test-Path -LiteralPath $taskImagePython) -and (Test-Path -LiteralPath (Join-Path $taskRoot 'weights/triposr/provenance.json')) -and -not (Get-NetTCPConnection -LocalPort 8844 -State Listen -ErrorAction SilentlyContinue)) {
        $taskOldPythonPath=$env:PYTHONPATH; $taskOldWeights=$env:PRINTFLOW_WEIGHTS_DIR; $taskOldDevice=$env:PRINTFLOW_DEVICE
        try {
            $env:PYTHONPATH=Join-Path $taskRoot '.runtime/TripoSR'; $env:PRINTFLOW_WEIGHTS_DIR=Join-Path $taskRoot 'weights/triposr'; $env:PRINTFLOW_DEVICE='cpu'
            Start-PrintFlowService 'image3d' '-m uvicorn printflow.image3d_worker:app --host 127.0.0.1 --port 8844' $taskImagePython
        } finally { $env:PYTHONPATH=$taskOldPythonPath; $env:PRINTFLOW_WEIGHTS_DIR=$taskOldWeights; $env:PRINTFLOW_DEVICE=$taskOldDevice }
    }
}
Write-Output 'PrintFlow Local: http://127.0.0.1:8840'
