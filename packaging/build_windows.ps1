# Gera dist\installer\Lume-Setup-<versão>.exe no Windows.
# Pré-requisitos: Python 3.10+ (64 bits) e Inno Setup 6 (https://jrsoftware.org/isdl.php).
# Uso (PowerShell, na raiz do repositório):  .\packaging\build_windows.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements-dev.txt pyinstaller

$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python -m pytest -q
Remove-Item Env:QT_QPA_PLATFORM

.\.venv\Scripts\python packaging\make_icon.py
.\.venv\Scripts\pyinstaller packaging\lume.spec --noconfirm --distpath dist --workpath build

$version = .\.venv\Scripts\python -c "import sys; sys.path.insert(0,'src'); import lume; print(lume.__version__)"
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 não encontrado. Instale em https://jrsoftware.org/isdl.php" }
& $iscc "/DAppVersion=$version" packaging\installer.iss
Write-Host "Instalador gerado em dist\installer\Lume-Setup-$version.exe"
