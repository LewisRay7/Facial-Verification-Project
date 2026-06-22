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
    Check "Cloud database mode" ($ready.database_mode -eq "neon-postgresql") $ready.database_mode
    Check "Production environment" ($ready.environment -eq "production") $ready.environment
    Check "Biometric encryption" ($ready.data_encryption_configured -eq $true) "DATA_ENCRYPTION_KEY configured"
    Check "OTP email provider" ($ready.email_provider_configured -eq $true) "Resend or SMTP configured"
} catch {
    Check "Cloud readiness" $false $_.Exception.Message
}

$desktop = Join-Path $env:USERPROFILE "Desktop\ExamVerify_Desktop_Demo\examverify_app.exe"
Check "Desktop build" (Test-Path -LiteralPath $desktop) $desktop

$model = Join-Path $env:USERPROFILE "Desktop\ExamVerify_Desktop_Demo\face_backend\models\mobilefacenet.tflite"
Check "Desktop FaceNet model" (Test-Path -LiteralPath $model) $model
if (Test-Path -LiteralPath $model) {
    Check "Desktop FaceNet model size" ((Get-Item -LiteralPath $model).Length -gt 5000000) "$((Get-Item -LiteralPath $model).Length) bytes"
}

$currentPayload = Join-Path $root "Flutter\examverify_app\build\windows\x64\runner\Release\data\app.so"
$deployedPayload = Join-Path $env:USERPROFILE "Desktop\ExamVerify_Desktop_Demo\data\app.so"
if ((Test-Path -LiteralPath $deployedPayload) -and (Test-Path -LiteralPath $currentPayload)) {
    $deployedHash = (Get-FileHash -LiteralPath $deployedPayload -Algorithm SHA256).Hash
    $currentHash = (Get-FileHash -LiteralPath $currentPayload -Algorithm SHA256).Hash
    Check "Desktop build freshness" ($deployedHash -eq $currentHash) "Deployed application payload matches the latest local release"
} else {
    Check "Desktop build freshness" $false "Build or deployed application payload is missing"
}

$faceHealth = $null
try {
    $faceHealth = Invoke-RestMethod -Uri "http://127.0.0.1:8765/health" -Method Get -TimeoutSec 3
} catch {
    $demoRoot = Join-Path $env:USERPROFILE "Desktop\ExamVerify_Desktop_Demo"
    $facePython = Join-Path $demoRoot ".venv\Scripts\python.exe"
    $faceApi = Join-Path $demoRoot "face_backend\App\backend_api.py"
    if ((Test-Path -LiteralPath $facePython) -and (Test-Path -LiteralPath $faceApi)) {
        Start-Process -FilePath $facePython -ArgumentList @(
            $faceApi,
            "--host",
            "127.0.0.1",
            "--port",
            "8765"
        ) -WorkingDirectory (Split-Path -Parent $faceApi) -WindowStyle Hidden
        for ($attempt = 0; $attempt -lt 60 -and $null -eq $faceHealth; $attempt++) {
            Start-Sleep -Milliseconds 500
            try {
                $faceHealth = Invoke-RestMethod -Uri "http://127.0.0.1:8765/health" -Method Get -TimeoutSec 2
            } catch {
                $faceHealth = $null
            }
        }
    }
}
Check "Desktop face service" ($null -ne $faceHealth -and $faceHealth.ok -eq $true) "Local service responded"
if ($null -ne $faceHealth) {
    Check "Desktop FaceNet warm-up" ($faceHealth.mobilefacenet_ready -eq $true) "TFLite interpreter is loaded before scanning"
}

$flutter = "C:\Users\lapto\development\flutter\bin\flutter.bat"
if (Test-Path -LiteralPath $flutter) {
    $devices = & $flutter devices 2>&1 | Out-String
    Check "Android device" ($devices -match "android-arm64") "Connected Android device detected"
} else {
    Check "Flutter tools" $false "flutter.bat not found"
}

$apk = Join-Path $root "Flutter\examverify_app\build\app\outputs\flutter-apk\app-release.apk"
Check "Android release build" (Test-Path -LiteralPath $apk) $apk
if (Test-Path -LiteralPath $apk) {
    $apkEntries = tar -tf $apk 2>&1 | Out-String
    Check "Android FaceNet model" ($apkEntries -match "assets/models/mobilefacenet.tflite") "MobileFaceNet is bundled in the APK"
}

$adb = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"
if (Test-Path -LiteralPath $adb) {
    $adbDevices = & $adb devices 2>&1 | Out-String
    if ($adbDevices -match "\sdevice(\s|$)") {
        $installedPackages = & $adb shell pm list packages 2>&1 | Out-String
        Check "Phone installation" ($installedPackages -match "package:com.example.examverify_app") "ExamVerify is installed on the connected phone"
        $batteryDump = & $adb shell dumpsys battery 2>&1 | Out-String
        $batteryMatch = [regex]::Match($batteryDump, "(?m)^\s*level:\s*(\d+)")
        if ($batteryMatch.Success) {
            $batteryLevel = [int]$batteryMatch.Groups[1].Value
            Check "Phone battery" ($batteryLevel -ge 30) "$batteryLevel percent"
        }
    }
}

Write-Host ""
if ($failed) {
    Write-Host "Preflight found a problem. Resolve failed checks before presenting." -ForegroundColor Red
    exit 1
}
Write-Host "All presentation-critical checks passed." -ForegroundColor Green
