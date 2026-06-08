$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$api = "https://examverify-cloud-api.onrender.com"
$failed = $false

function Check($name, $passed, $detail) {
    $status = if ($passed) { "PASS" } else { "FAIL" }
    $color = if ($passed) { "Green" } else { "Red" }
    Write-Host ("[{0}] {1}: {2}" -f $status, $name, $detail) -ForegroundColor $color
    if (-not $passed) { $script:failed = $true }
}

Write-Host "ExamVerify Presentation Preflight" -ForegroundColor Cyan
Write-Host "Waking Render free-tier service; this can take about one minute..." -ForegroundColor Yellow

try {
    $health = Invoke-RestMethod -Uri "$api/health" -Method Get -TimeoutSec 90
    Check "Cloud API" ($health.ok -eq $true) "Render service responded"
} catch {
    Check "Cloud API" $false $_.Exception.Message
}

try {
    $ready = Invoke-RestMethod -Uri "$api/health/ready" -Method Get -TimeoutSec 90
    Check "Neon database" ($ready.database -eq "ready") $ready.database
    Check "Production environment" ($ready.environment -eq "production") $ready.environment
    Check "Biometric encryption" ($ready.data_encryption_configured -eq $true) "DATA_ENCRYPTION_KEY configured"
    Check "OTP email provider" ($ready.email_provider_configured -eq $true) "Resend or SMTP configured"
} catch {
    Check "Cloud readiness" $false $_.Exception.Message
}

$desktop = Join-Path $env:USERPROFILE "Desktop\ExamVerify_Desktop_Demo\examverify_app.exe"
Check "Desktop build" (Test-Path -LiteralPath $desktop) $desktop

$flutter = "C:\Users\lapto\development\flutter\bin\flutter.bat"
if (Test-Path -LiteralPath $flutter) {
    $devices = & $flutter devices 2>&1 | Out-String
    Check "Android device" ($devices -match "android-arm64") "Connected Android device detected"
} else {
    Check "Flutter tools" $false "flutter.bat not found"
}

Write-Host ""
if ($failed) {
    Write-Host "Preflight found a problem. Resolve failed checks before presenting." -ForegroundColor Red
    exit 1
}
Write-Host "All presentation-critical checks passed." -ForegroundColor Green
