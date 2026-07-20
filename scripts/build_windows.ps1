param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$buildDir = Join-Path $root ".build\pyinstaller"
$releaseDir = Join-Path $root "release"
$icon = Join-Path $root "assets\picbench.ico"
$examples = Join-Path $root "examples"
$entrypoint = Join-Path $root "labauto\ui.py"
New-Item -ItemType Directory -Force -Path $buildDir, $releaseDir | Out-Null

if (-not $SkipInstall) {
    python -m pip install -r requirements-build.txt
}

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name PICBench `
    --workpath $buildDir `
    --specpath (Join-Path $root ".build") `
    --distpath $releaseDir `
    --icon $icon `
    --add-data "$icon;assets" `
    --add-data "$examples;examples" `
    --collect-submodules labauto `
    --collect-submodules scripts `
    --collect-all cv2 `
    --collect-all pyvisa `
    --collect-all clr_loader `
    --hidden-import clr `
    $entrypoint

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

if (-not (Test-Path -LiteralPath "$releaseDir\PICBench.exe")) {
    throw "PICBench.exe was not created"
}

$hash = (Get-FileHash -Algorithm SHA256 "$releaseDir\PICBench.exe").Hash.ToLowerInvariant()
"$hash  PICBench.exe" | Set-Content -Encoding ascii "$releaseDir\PICBench.exe.sha256"

$selfCheck = Start-Process -FilePath "$releaseDir\PICBench.exe" -ArgumentList "--self-check" -WindowStyle Hidden -Wait -PassThru
if ($selfCheck.ExitCode -ne 0) {
    throw "PICBench.exe self-check failed with exit code $($selfCheck.ExitCode)"
}

$moduleCheck = Start-Process -FilePath "$releaseDir\PICBench.exe" -ArgumentList "--run-module scripts.caracterizacion_fotonica --self-test" -WindowStyle Hidden -Wait -PassThru
if ($moduleCheck.ExitCode -ne 0) {
    throw "PICBench.exe module check failed with exit code $($moduleCheck.ExitCode)"
}

Write-Host "Built $releaseDir\PICBench.exe"
