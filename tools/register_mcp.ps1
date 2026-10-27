$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
$taskServer = Join-Path $taskRoot 'u1_server.py'
$taskEvidence = Join-Path $taskRoot 'validation\bridge-results.json'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'The MCP Python environment is missing. Run the installer first.' }
$taskValidation = Get-Content -LiteralPath $taskEvidence -Raw | ConvertFrom-Json
if ($taskValidation.status -ne 'passed') { throw 'The real MCP validation has not completed successfully.' }
$taskExecutable = 'C:\Program Files\Snapmaker_Orca\snapmaker-orca.exe'
if ((Get-FileHash -LiteralPath $taskExecutable -Algorithm SHA256).Hash.ToLower() -ne $taskValidation.binary_sha256) { throw 'Snapmaker Orca has changed: repeat validation.' }
$taskConfig = Join-Path $env:USERPROFILE '.codex\config.toml'
$taskBackup = Join-Path $taskRoot 'validation\codex-config-before-mcp.toml'
if ((Test-Path -LiteralPath $taskConfig) -and -not (Test-Path -LiteralPath $taskBackup)) { Copy-Item -LiteralPath $taskConfig -Destination $taskBackup }
& codex mcp add snapmaker-u1 -- $taskPython $taskServer
if ($LASTEXITCODE -ne 0) { throw 'The MCP server could not be registered.' }
& codex mcp get snapmaker-u1
if ($LASTEXITCODE -ne 0) { throw 'The MCP registration could not be verified.' }
