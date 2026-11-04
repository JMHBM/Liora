# Runs from LioraSetup.exe. Prints ::progress / ::status / ::done / ::error lines.
param(
  [Parameter(Mandatory = $true)][string]$InstallDir,
  [string]$TokenFile = "",
  [switch]$InstallZluda,
  [switch]$DownloadModel
)

$ErrorActionPreference = "Stop"

function Say([string]$Message) {
  Write-Output "::status $Message"
}

function Progress([int]$Value) {
  Write-Output "::progress $Value"
}

function Download-File([string]$Url, [string]$Dest) {
  Say "Downloading $(Split-Path $Dest -Leaf)"
  $dir = Split-Path $Dest -Parent
  if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
  Invoke-WebRequest -Uri $Url -OutFile $Dest -UseBasicParsing
}

try {
  New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
  Progress 8
  Say "Installing Python 3.11"

  $pySetup = Join-Path $env:TEMP "liora-python-3.11.9-amd64.exe"
  if (-not (Test-Path $pySetup)) {
    Download-File "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" $pySetup
  }
  $pyHome = Join-Path $InstallDir "python"
  Progress 18
  $pyProc = Start-Process -FilePath $pySetup -ArgumentList @(
    "/quiet", "InstallAllUsers=0", "PrependPath=0", "Include_pip=1",
    "Include_launcher=0", "Include_test=0", "Include_doc=0",
    "TargetDir=$pyHome", "Shortcuts=0", "AssociateFiles=0"
  ) -Wait -PassThru
  if ($pyProc.ExitCode -ne 0) { throw "Python installer exited $($pyProc.ExitCode)" }

  $python = Join-Path $pyHome "python.exe"
  if (-not (Test-Path $python)) { throw "Python was not installed to $pyHome" }

  Progress 30
  Say "Creating the virtual environment"
  $venv = Join-Path $InstallDir "venv"
  & $python -m venv $venv
  if ($LASTEXITCODE -ne 0) { throw "venv failed" }
  $py = Join-Path $venv "Scripts\python.exe"

  Progress 38
  Say "Installing PyTorch for CUDA 12.6 (used by ZLUDA)"
  & $py -m pip install --upgrade pip
  & $py -m pip install torch==2.7.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu126
  if ($LASTEXITCODE -ne 0) {
    Say "Pinned torch 2.7.1 was unavailable. Installing the current CUDA 12.6 wheels."
    & $py -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126
    if ($LASTEXITCODE -ne 0) { throw "PyTorch install failed" }
  }

  Progress 68
  Say "Installing Liora and Stable Audio 3"
  & $py -m pip install -r (Join-Path $InstallDir "requirements.txt")
  if ($LASTEXITCODE -ne 0) { throw "requirements install failed" }
  & $py -m pip install "stable-audio-3 @ git+https://github.com/Stability-AI/stable-audio-3.git"
  if ($LASTEXITCODE -ne 0) { throw "stable-audio-3 install failed" }
  & $py -m pip install -e $InstallDir
  if ($LASTEXITCODE -ne 0) { throw "liora install failed" }

  Progress 80
  if ($InstallZluda) {
    Say "Downloading ZLUDA"
    $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/lshqqytiger/ZLUDA/releases/latest" -Headers @{ "User-Agent" = "LioraSetup" }
    $asset = $rel.assets | Where-Object { $_.name -match '\.zip$' -and $_.name -match 'win|windows|amd64' } | Select-Object -First 1
    if (-not $asset) {
      $asset = $rel.assets | Where-Object { $_.name -match '\.zip$' } | Select-Object -First 1
    }
    if (-not $asset) { throw "No ZLUDA zip on the latest release" }
    $zip = Join-Path $env:TEMP $asset.name
    Download-File $asset.browser_download_url $zip
    $zludaDir = Join-Path $InstallDir "zluda"
    New-Item -ItemType Directory -Force -Path $zludaDir | Out-Null
    tar -xf $zip -C $zludaDir
    Say "ZLUDA is in place. AMD Adrenalin is required. HIP SDK is required before the GPU path works."
  }

  Progress 90
  $token = ""
  if ($TokenFile -and (Test-Path $TokenFile)) {
    $token = (Get-Content -Raw -Path $TokenFile).Trim()
    Remove-Item -Force $TokenFile
  }
  if ($DownloadModel) {
    if (-not $token) { throw "A Hugging Face token is required to download the gated weights." }
    Say "Downloading Small-Music weights"
    $env:HF_TOKEN = $token
    $env:HUGGING_FACE_HUB_TOKEN = $token
    & $py -m liora download --model small-music
    if ($LASTEXITCODE -ne 0) { throw "Model download failed. Accept the Stability and Gemma licenses on Hugging Face, then run download again." }
  }

  Progress 96
  Say "Creating shortcuts"
  $cmd = Join-Path $InstallDir "Liora.cmd"
  @"
@echo off
cd /d "%~dp0"
if exist "%~dp0zluda\zluda.exe" (
  "%~dp0zluda\zluda.exe" -- "%~dp0venv\Scripts\python.exe" -m liora serve
) else (
  "%~dp0venv\Scripts\python.exe" -m liora serve
)
"@ | Set-Content -Path $cmd -Encoding ASCII

  $doctor = Join-Path $InstallDir "Liora Doctor.cmd"
  @"
@echo off
cd /d "%~dp0"
if exist "%~dp0zluda\zluda.exe" (
  "%~dp0zluda\zluda.exe" -- "%~dp0venv\Scripts\python.exe" -m liora doctor
) else (
  "%~dp0venv\Scripts\python.exe" -m liora doctor
)
pause
"@ | Set-Content -Path $doctor -Encoding ASCII

  $uninstall = Join-Path $InstallDir "Uninstall.cmd"
  @"
@echo off
echo This removes $InstallDir
choice /M "Uninstall Liora"
if errorlevel 2 exit /b 1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\Liora" /f
cd /d "%TEMP%"
rmdir /s /q "$InstallDir"
"@ | Set-Content -Path $uninstall -Encoding ASCII

  $shell = New-Object -ComObject WScript.Shell
  $start = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Liora.lnk"
  $sc = $shell.CreateShortcut($start)
  $sc.TargetPath = $cmd
  $sc.WorkingDirectory = $InstallDir
  $sc.Description = "Liora instrumental studio"
  $sc.Save()
  $desk = Join-Path ([Environment]::GetFolderPath("Desktop")) "Liora.lnk"
  $sc2 = $shell.CreateShortcut($desk)
  $sc2.TargetPath = $cmd
  $sc2.WorkingDirectory = $InstallDir
  $sc2.Save()

  $reg = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Liora"
  New-Item -Path $reg -Force | Out-Null
  New-ItemProperty -Path $reg -Name DisplayName -Value "Liora" -Force | Out-Null
  New-ItemProperty -Path $reg -Name DisplayVersion -Value "0.2.0" -Force | Out-Null
  New-ItemProperty -Path $reg -Name Publisher -Value "JMHBM" -Force | Out-Null
  New-ItemProperty -Path $reg -Name InstallLocation -Value $InstallDir -Force | Out-Null
  New-ItemProperty -Path $reg -Name UninstallString -Value $uninstall -Force | Out-Null
  New-ItemProperty -Path $reg -Name DisplayIcon -Value $python -Force | Out-Null

  Progress 100
  Say "Installed"
  Write-Output "::done"
} catch {
  Write-Output ("::error " + $_.Exception.Message)
  exit 1
}
