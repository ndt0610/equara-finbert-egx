# Starts the local demo with EODHD News scoped to the article/portfolio flows.
# The API token is prompted as a SecureString and is never written to a file or command-line argument.
[CmdletBinding()]
param([int]$Port = 8124)

$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot
$python = 'C:\equara_tin_gia_env\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'The Equara Python environment was not found.' }

$secret = Read-Host 'EODHD News API token (hidden; used only by article/portfolio tabs)' -AsSecureString
if (-not $secret.Length) { throw 'No key entered. Server not started.' }

$token = ([System.Net.NetworkCredential]::new('', $secret)).Password.Trim()
if (-not $token) { throw 'Empty EODHD News key.' }

$oldListeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
if ($oldListeners.Count) {
    $processTable = @(Get-CimInstance Win32_Process)
    $parent = $processTable | Where-Object {
        $_.ExecutablePath -eq $python -and
        $_.CommandLine -match "-m uvicorn backend\.app:app --host 127\.0\.0\.1 --port $Port(?:\s|$)"
    } | Select-Object -First 1
    if (-not $parent) { throw "Port $Port is occupied by a process that is not this Equara server; it was left untouched." }
    $allowed = @([int]$parent.ProcessId) + @(
        $processTable | Where-Object { $_.ParentProcessId -eq $parent.ProcessId } | ForEach-Object { [int]$_.ProcessId }
    )
    $owners = @($oldListeners | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { [int]$_ })
    if (@($owners | Where-Object { $_ -notin $allowed }).Count) {
        throw "Port $Port has a listener outside the verified Equara process tree; it was left untouched."
    }
    foreach ($listenerPid in ($owners | Where-Object { $_ -ne $parent.ProcessId })) {
        Stop-Process -Id $listenerPid -Force -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $parent.ProcessId -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 400
}

$oldNewsToken = [Environment]::GetEnvironmentVariable('EODHD_NEWS_API_TOKEN', 'Process')
$oldDemoMode = [Environment]::GetEnvironmentVariable('DEMO_MODE', 'Process')
$oldInference = [Environment]::GetEnvironmentVariable('INFERENCE_PROVIDER', 'Process')
Push-Location $project
try {
    $env:EODHD_NEWS_API_TOKEN = $token
    $env:DEMO_MODE = 'live'
    $env:INFERENCE_PROVIDER = 'transformers-local'
    Write-Host "Starting server at http://127.0.0.1:$Port/ with EODHD News scoped to article/portfolio tabs. Ctrl+C stops it."
    & $python -m uvicorn backend.app:app --host 127.0.0.1 --port $Port
} finally {
    [Environment]::SetEnvironmentVariable('EODHD_NEWS_API_TOKEN', $oldNewsToken, 'Process')
    [Environment]::SetEnvironmentVariable('DEMO_MODE', $oldDemoMode, 'Process')
    [Environment]::SetEnvironmentVariable('INFERENCE_PROVIDER', $oldInference, 'Process')
    $token = $null
    $secret.Dispose()
    Pop-Location
}
