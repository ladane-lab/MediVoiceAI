# Start the MediVoice AI FastAPI backend (development mode)
$ErrorActionPreference = "Stop"
$BackendDir = Join-Path $PSScriptRoot "..\backend"
$PythonExe = Join-Path $BackendDir ".venv\Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    Write-Error "Virtual environment not found at $PythonExe. Run 'py -3.14 -m venv backend\.venv' and install backend\requirements.txt first."
    exit 1
}

Set-Location $BackendDir
& $PythonExe run.py
