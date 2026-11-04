param([ValidateSet('mcp','worker','status')][string]$Mode='mcp')
$ErrorActionPreference='Stop'
$collectorRoot=Split-Path -Parent $MyInvocation.MyCommand.Path
$collectorPython=Join-Path $collectorRoot '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $collectorPython)) { throw 'Run the installation commands in README.md first.' }
$env:PYTHONPATH=$collectorRoot
if (!$env:COLLECTOR_DATA_DIR) { $env:COLLECTOR_DATA_DIR=Join-Path $collectorRoot 'data' }
if ($Mode -eq 'mcp') { & $collectorPython -m dycollector.mcp_server }
elseif ($Mode -eq 'worker') { & $collectorPython -m dycollector.cli worker --limit 20 }
else { & $collectorPython -m dycollector.cli status }
exit $LASTEXITCODE
