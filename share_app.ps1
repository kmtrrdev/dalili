# Share the Dalili app: start the backend, open a public Cloudflare tunnel to it, and build an APK that uses it.
#
#   .\share_app.ps1              # server + tunnel + APK on the Desktop (Dalili.apk)
#   .\share_app.ps1 -NoBuild     # server + tunnel only (e.g. the link is already in the app's Profile -> Server address)
#
# The quick-tunnel link changes every time the tunnel starts, so run this again (or update the link in the app)
# after a restart. Keep the laptop on while people use the app.
param([switch]$NoBuild)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$dev = "$env:USERPROFILE\dev"
$sdk = "$env:LOCALAPPDATA\Android\Sdk"

# 1. Backend on port 8001 (kept running after this script ends).
$up = $false
try { $up = (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8001/api/health -TimeoutSec 5).StatusCode -eq 200 } catch {}
if (-not $up) {
    Write-Host "Starting the Dalili server..."
    Start-Process -FilePath "$root\.venv\Scripts\python.exe" -ArgumentList "-m", "uvicorn", "travel_agent.api:app", "--port", "8001" `
        -WorkingDirectory $root -WindowStyle Hidden | Out-Null
    for ($i = 0; $i -lt 30 -and -not $up; $i++) {
        Start-Sleep -Seconds 2
        try { $up = (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8001/api/health -TimeoutSec 5).StatusCode -eq 200 } catch {}
    }
    if (-not $up) { throw "The server did not start." }
}
Write-Host "Server: OK (http://127.0.0.1:8001)"

# 2. Public tunnel (http2 works on networks that block QUIC/UDP).
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
$log = "$dev\cloudflared.log"
Remove-Item $log -ErrorAction SilentlyContinue
Start-Process -FilePath "$dev\cloudflared.exe" -ArgumentList "tunnel", "--no-autoupdate", "--protocol", "http2", "--url", "http://localhost:8001", "--logfile", $log `
    -WindowStyle Hidden | Out-Null
$url = $null
for ($i = 0; $i -lt 40 -and -not $url; $i++) {
    Start-Sleep -Seconds 2
    if (Test-Path $log) {
        $m = Select-String -Path $log -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" | Select-Object -First 1
        if ($m) { $url = $m.Matches[0].Value }
    }
}
if (-not $url) { throw "The tunnel did not start. See $log" }
$ok = $false
for ($i = 0; $i -lt 15 -and -not $ok; $i++) {
    Start-Sleep -Seconds 4
    try { $ok = (Invoke-WebRequest -UseBasicParsing "$url/api/health" -TimeoutSec 20).StatusCode -eq 200 } catch {}
}
if (-not $ok) { throw "The tunnel link does not answer yet: $url" }
Set-Content -Path "$root\public_url.txt" -Value $url -Encoding utf8
Write-Host "Public link: $url"

# 3. The APK (release, ~20 MB) with the link built in.
if (-not $NoBuild) {
    $env:JAVA_HOME = "$dev\jdk17"; $env:ANDROID_HOME = $sdk
    $env:Path = "$dev\flutter\bin;$dev\git\cmd;$dev\jdk17\bin;$sdk\platform-tools;" + $env:Path
    Push-Location "$root\mobile"
    try {
        Write-Host "Building the APK (about 2-3 minutes)..."
        cmd /c "flutter build apk --release --split-per-abi --dart-define=DALILI_SERVER=$url 2>&1" | Select-Object -Last 3
        Copy-Item "build\app\outputs\flutter-apk\app-arm64-v8a-release.apk" "$env:USERPROFILE\Desktop\Dalili.apk" -Force
    } finally { Pop-Location }
    Write-Host "Done: Desktop\Dalili.apk (send it on WhatsApp, Telegram...)"
}
Write-Host "Keep this laptop on and connected while people use the app."
