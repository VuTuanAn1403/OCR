param([string]$Python = '.venv/Scripts/python.exe')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    $env:UV_CACHE_DIR = Join-Path $projectRoot '.cache/uv-docling'
    $workerPython = Join-Path $projectRoot '.venv-docling/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $workerPython)) {
        uv venv .venv-docling --python $Python
        if ($LASTEXITCODE -ne 0) { throw 'Creating the Docling environment failed' }
    }
    $locked = Join-Path $projectRoot 'requirements-docling.lock.txt'
    $spec = if (Test-Path -LiteralPath $locked) { $locked } else { Join-Path $projectRoot 'requirements-docling.txt' }
    uv pip install --python $workerPython -r $spec --index https://pypi.org/simple --index https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match
    if ($LASTEXITCODE -ne 0) { throw 'Installing the Docling CPU dependencies failed' }
    Write-Output 'Docling worker installed. Run scripts/smoke_docling_structures.py for a real model check.'
} finally { Pop-Location }
