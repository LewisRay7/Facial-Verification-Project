$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$backendRoot = Join-Path $root "face_backend"
$api = Join-Path $backendRoot "App\backend_api.py"
$stdout = Join-Path $root "face-backend.log"
$stderr = Join-Path $root "face-backend.err"
$healthUrl = "http://127.0.0.1:8765/health"

function Test-FaceBackend {
    try {
        $response = Invoke-RestMethod -Uri $healthUrl -Method Get -TimeoutSec 2
        return (
            $response.ok -eq $true -and
            $response.mobilefacenet_model_available -eq $true
        )
    } catch {
        return $false
    }
}

if (Test-FaceBackend) {
    exit 0
}

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment not found: $python"
}
if (-not (Test-Path -LiteralPath $api)) {
    throw "Face backend not found: $api"
}

Remove-Item -LiteralPath $stdout, $stderr -Force -ErrorAction SilentlyContinue
Start-Process `
    -FilePath $python `
    -ArgumentList @("App\backend_api.py", "--host", "127.0.0.1", "--port", "8765") `
    -WorkingDirectory $backendRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr

for ($attempt = 0; $attempt -lt 60; $attempt++) {
    Start-Sleep -Seconds 1
    if (Test-FaceBackend) {
        exit 0
    }
}

throw "The face backend or bundled MobileFaceNet model did not become healthy. Check face-backend.err."
