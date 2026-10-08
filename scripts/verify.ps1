$ErrorActionPreference = 'Stop'
$workspaceRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $workspaceRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Create .venv and install requirements.txt before verification.'
}
Push-Location $workspaceRoot
try {
    & $pythonPath -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Assistant tests failed. Install server/test extras for the complete suite.' }
    & $pythonPath scripts/check_publication.py
    if ($LASTEXITCODE -ne 0) { throw 'The Git publication guard rejected indexed source.' }
    git diff --check
    if ($LASTEXITCODE -ne 0) { throw 'Git whitespace checks failed.' }
} finally {
    Pop-Location
}
