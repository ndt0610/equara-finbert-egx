# Run from PowerShell:  & .\scripts\start_eodhd_demo.ps1
[CmdletBinding()]
param([int]$Port = 8023)
$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot
$python = @(
    (Join-Path $project '.venv/Scripts/python.exe'),
    (Join-Path (Split-Path $project) '_codex_out/venv/Scripts/python.exe')
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (!$python) { throw 'Install the project dependencies using START_HERE.md first.' }
if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
    throw "Port $Port is already in use. Choose another port with -Port."
}
$secret = Read-Host 'EODHD API token (hidden; used only by this server)' -AsSecureString
if (!$secret.Length) { throw 'No key entered. Server not started.' }
$names = 'EODHD_API_TOKEN','DEMO_MODE','INFERENCE_PROVIDER','HF_INFERENCE_URL','HF_HOME'
$old = @{}
foreach ($name in $names) { $old[$name] = [Environment]::GetEnvironmentVariable($name) }
Push-Location $project
try {
    $env:EODHD_API_TOKEN = ([System.Net.NetworkCredential]::new('', $secret)).Password.Trim()
    if (!$env:EODHD_API_TOKEN) { throw 'Empty EODHD key.' }
    $env:DEMO_MODE = 'live'
    $env:INFERENCE_PROVIDER = 'transformers-local'
    $cache = Join-Path (Split-Path $project) '_codex_out/hf'
    if (Test-Path -LiteralPath $cache) { $env:HF_HOME = $cache }
    try {
        $hf = Invoke-RestMethod 'http://127.0.0.1:8021/health' -TimeoutSec 2
        if ($hf.model -eq 'ProsusAI/finbert' -and $hf.revision -eq '0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031') {
            $env:INFERENCE_PROVIDER = 'hf-inference'
            $env:HF_INFERENCE_URL = 'http://127.0.0.1:8021/models/ProsusAI/finbert'
        }
    } catch { Write-Host 'Using local FinBERT.' }
    Write-Host "Inference provider: $env:INFERENCE_PROVIDER"
    Write-Host "Open http://127.0.0.1:$Port/ when startup completes. Ctrl+C stops this server."
    & $python -m uvicorn backend.app:app --host 127.0.0.1 --port $Port
} finally {
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name,$old[$name]) }
    $secret.Dispose()
    Pop-Location
}
