# 64 bites Python 3.12 kell. A 32 bites Pythonra a Shazam csomag nem települ.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean MusicIDTagger.spec

$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $iscc) {
    Write-Host "Inno Setup nincs telepítve, a dist\MusicIDTagger mappa ettől még kész."
    Write-Host "Telepítő: https://jrsoftware.org/isdl.php majd futtasd újra ezt a scriptet."
    exit 0
}

& $iscc "installer\MusicIDTagger.iss"
if ($LASTEXITCODE -ne 0) { throw "ISCC hiba: $LASTEXITCODE" }
Write-Host "Kész: installer\Output\MusicIDTagger-Setup.exe"
