param([int]$Port=8124)
$ErrorActionPreference='Stop'
$project=Split-Path $PSScriptRoot
$python='C:\equara_tin_gia_env\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python)) { throw 'Missing Python environment C:\equara_tin_gia_env. See START_HERE.md.' }
Set-Location -LiteralPath $project
try {
    $health=Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
    if ($health.status -eq 'ok') {
        Write-Host "A server already responds at http://127.0.0.1:$Port/. Close its launcher before starting a new version."
        exit 0
    }
} catch { }
$env:DEMO_MODE='live'
$env:INFERENCE_PROVIDER='transformers-local'
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
Write-Host 'Optional EODHD NEWS key for article/portfolio tabs. Press Enter to use RSS.'
$secret=Read-Host 'Key (hidden)' -AsSecureString
if ($secret.Length) { $env:EODHD_NEWS_API_TOKEN=([System.Net.NetworkCredential]::new('', $secret)).Password.Trim() }
Write-Host "Keep this window open. Wait for Application startup complete, then open http://127.0.0.1:$Port/"
try { & $python -m uvicorn backend.app:app --host 127.0.0.1 --port $Port }
finally { Remove-Item Env:EODHD_NEWS_API_TOKEN -ErrorAction SilentlyContinue; $secret.Dispose() }
