$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$source = Join-Path $root "Flutter\examverify_app\build\windows\x64\runner\Release"
$target = Join-Path $env:USERPROFILE "Desktop\ExamVerify_Desktop_Demo"
$sourceExe = Join-Path $source "examverify_app.exe"
$targetExe = Join-Path $target "examverify_app.exe"
$sourcePayload = Join-Path $source "data\app.so"
$targetPayload = Join-Path $target "data\app.so"
$staging = Join-Path $env:TEMP "ExamVerify_Desktop_Demo_staging"
$venvCache = Join-Path $env:TEMP "ExamVerify_Desktop_Demo_venv"
$launcherSource = Join-Path $root "desktop_launcher"

if (-not (Test-Path -LiteralPath $sourceExe) -or -not (Test-Path -LiteralPath $sourcePayload)) {
    throw "Complete release build not found: $source"
}

Get-Process examverify_app -ErrorAction SilentlyContinue | Stop-Process -Force
foreach ($port in @(8000, 8765)) {
    $matches = netstat -ano | Select-String ":$port\s+.*LISTENING\s+(\d+)$"
    foreach ($match in $matches) {
        $processId = [int]$match.Matches[0].Groups[1].Value
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
}
$desktopRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $env:USERPROFILE "Desktop")
).TrimEnd('\') + '\'
$resolvedTarget = [System.IO.Path]::GetFullPath($target)
if (-not $resolvedTarget.StartsWith($desktopRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to replace a target outside the Desktop directory: $resolvedTarget"
}

foreach ($path in @($staging, $venvCache)) {
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}

if (Test-Path -LiteralPath (Join-Path $target ".venv")) {
    Move-Item -LiteralPath (Join-Path $target ".venv") -Destination $venvCache
}
if (Test-Path -LiteralPath $target) {
    Remove-Item -LiteralPath $target -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $staging | Out-Null
Copy-Item -Path (Join-Path $source "*") -Destination $staging -Recurse -Force

$faceBackend = Join-Path $staging "face_backend"
New-Item -ItemType Directory -Force -Path $faceBackend | Out-Null
foreach ($folder in @("App", "SRC", "Assets", "Models")) {
    $folderSource = Join-Path $root $folder
    if (Test-Path -LiteralPath $folderSource) {
        Copy-Item -LiteralPath $folderSource -Destination $faceBackend -Recurse -Force
    }
}

if (Test-Path -LiteralPath $venvCache) {
    Move-Item -LiteralPath $venvCache -Destination (Join-Path $staging ".venv")
} elseif (Test-Path -LiteralPath (Join-Path $root ".venv")) {
    Copy-Item -LiteralPath (Join-Path $root ".venv") -Destination $staging -Recurse -Force
}

Copy-Item -Path (Join-Path $launcherSource "*") -Destination $staging -Force
Move-Item -LiteralPath $staging -Destination $target

$sourceExeHash = (Get-FileHash -LiteralPath $sourceExe -Algorithm SHA256).Hash
$targetExeHash = (Get-FileHash -LiteralPath $targetExe -Algorithm SHA256).Hash
$sourcePayloadHash = (Get-FileHash -LiteralPath $sourcePayload -Algorithm SHA256).Hash
$targetPayloadHash = (Get-FileHash -LiteralPath $targetPayload -Algorithm SHA256).Hash
if ($sourceExeHash -ne $targetExeHash -or $sourcePayloadHash -ne $targetPayloadHash) {
    throw "Desktop deployment verification failed: release bundle hashes differ."
}

Write-Host "Desktop demo deployed and verified." -ForegroundColor Green
Write-Host $targetExe
