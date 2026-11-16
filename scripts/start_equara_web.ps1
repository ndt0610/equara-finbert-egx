param(
    [string]$PythonPath = 'C:\equara_tin_gia_env\Scripts\python.exe',
    [int]$Port = 8124
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python environment missing: $PythonPath"
}
if ($Port -lt 1 -or $Port -gt 65535) { throw 'Port must be between 1 and 65535.' }
$url = "http://127.0.0.1:$Port"
$probe = "$url/api/v3/us/universe"
$ready = $false
try {
    $response = Invoke-RestMethod -Uri $probe -TimeoutSec 2
    $ready = $null -ne $response.items
} catch { }
if (-not $ready) {
    $logDir = Join-Path $repoRoot 'artifacts\web'
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $server = Start-Process -FilePath $PythonPath -ArgumentList @('-m', 'uvicorn', 'backend.app:app', '--host', '127.0.0.1', '--port', "$Port") `
        -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logDir 'uvicorn.stdout.log') `
        -RedirectStandardError (Join-Path $logDir 'uvicorn.stderr.log')
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        if ($server.HasExited) { throw "Web server exited early; see $logDir" }
        try {
            $response = Invoke-RestMethod -Uri $probe -TimeoutSec 2
            if ($null -ne $response.items) { $ready = $true; break }
        } catch { }
    }
    if (-not $ready) { throw "Web server did not become ready; see $logDir" }
}
Start-Process $url
Write-Host "Equara web: $url"
