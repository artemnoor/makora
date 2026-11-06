param([string]$ProjectRoot = $PSScriptRoot, [int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
  if (!(Test-Path '.venv/Scripts/python.exe')) { python -m venv .venv; if ($LASTEXITCODE) { throw 'Python setup failed' } }
  & ./.venv/Scripts/python.exe -m pip install -r requirements.txt
  if ($LASTEXITCODE) { throw 'Python dependencies failed' }
  npm ci
  if ($LASTEXITCODE) { throw 'Node dependencies failed' }
  & ./.venv/Scripts/python.exe scripts/makora.py --project-root $ProjectRoot install --port $Port
  if ($LASTEXITCODE) { throw 'Project installation failed' }
  & ./.venv/Scripts/python.exe scripts/makora.py --project-root $ProjectRoot launch
  if ($LASTEXITCODE) { throw 'Server launch failed' }
} finally { Pop-Location }
