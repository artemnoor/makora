param(
  [int]$Port = 4181,
  [string]$CodexDataDirectory = $(if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }),
  [string]$BridgeContextThreadId = $env:CODEX_APP_TOOLS_CONTEXT_THREAD_ID,
  [switch]$AppServerOnly,
  [string]$WorkingDirectory = $PSScriptRoot
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $CodexDataDirectory -PathType Container)) { throw 'Codex data directory does not exist' }
if (-not (Test-Path -LiteralPath $WorkingDirectory -PathType Container)) { throw 'Working directory does not exist' }
if (-not $BridgeContextThreadId -and -not $AppServerOnly) { throw 'BridgeContextThreadId is required unless -AppServerOnly is selected' }
$env:PORT = [string]$Port
$env:CODEX_HOME = (Resolve-Path -LiteralPath $CodexDataDirectory).Path
$env:CODEX_DEFAULT_CWD = (Resolve-Path -LiteralPath $WorkingDirectory).Path
if ($BridgeContextThreadId) { $env:CODEX_APP_TOOLS_CONTEXT_THREAD_ID = $BridgeContextThreadId }
else { Remove-Item Env:CODEX_APP_TOOLS_CONTEXT_THREAD_ID -ErrorAction SilentlyContinue }
$env:CODEX_POWERSHELL_PATH = (Get-Command pwsh -ErrorAction Stop).Source
& node (Join-Path $PSScriptRoot 'server.mjs')
