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
if ($AppServerOnly -and -not $env:CODEX_APP_SERVER_BINARY) {
  # Agent sessions must use a fresh process. The shared Desktop daemon can retain
  # credentials from an earlier account even when account/read reports the new one.
  $taskCodexBinary = (Get-Command codex.exe -ErrorAction SilentlyContinue).Source
  if (-not $taskCodexBinary) {
    $taskDaemon = Get-CimInstance Win32_Process -Filter "Name = 'codex.exe'" |
      Where-Object { $_.CommandLine -match 'app-server.*--managed-daemon' } |
      Select-Object -First 1
    $taskCodexBinary = $taskDaemon.ExecutablePath
  }
  if (-not $taskCodexBinary -or -not (Test-Path -LiteralPath $taskCodexBinary -PathType Leaf)) {
    throw 'Set CODEX_APP_SERVER_BINARY to codex.exe. Agent mode requires a dedicated App Server process.'
  }
  $env:CODEX_APP_SERVER_BINARY = $taskCodexBinary
}
& node (Join-Path $PSScriptRoot 'server.mjs')
