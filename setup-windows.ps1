[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectDir

function Refresh-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machinePath;$userPath"
}

Write-Host '=== socket-whatsapp-clone: Windows setup ===' -ForegroundColor Cyan
Write-Host "Project: $ProjectDir"
Write-Host

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host 'uv was not found. Installing it...' -ForegroundColor Yellow

    if (Get-Command winget.exe -ErrorAction SilentlyContinue) {
        & winget.exe install --id=astral-sh.uv -e --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) {
            throw "winget failed to install uv (exit code $LASTEXITCODE)."
        }
        Refresh-ProcessPath
    }
    else {
        Write-Host 'WinGet was not found; using the official Astral uv installer.' -ForegroundColor Yellow
        powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
        if ($LASTEXITCODE -ne 0) {
            throw "The official uv installer failed (exit code $LASTEXITCODE)."
        }
        Refresh-ProcessPath
        $uvLocalBin = Join-Path $HOME '.local\bin'
        if (Test-Path -LiteralPath $uvLocalBin) {
            $env:Path = "$uvLocalBin;$env:Path"
        }
    }
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv was installed but is not visible in this PowerShell session. Close PowerShell, open it again, and rerun this script.'
}

Write-Host
Write-Host ('uv: ' + (& uv --version)) -ForegroundColor Green

Write-Host 'Installing/ensuring Python 3.12...' -ForegroundColor Cyan
& uv python install 3.12
if ($LASTEXITCODE -ne 0) {
    throw "uv could not install Python 3.12 (exit code $LASTEXITCODE)."
}

Write-Host 'Creating the project virtual environment and installing locked dependencies...' -ForegroundColor Cyan
& uv sync --python 3.12 --locked
if ($LASTEXITCODE -ne 0) {
    throw "uv sync failed (exit code $LASTEXITCODE)."
}

Write-Host 'Checking Python and project dependencies...' -ForegroundColor Cyan
& uv run --python 3.12 python -c "import sys, grpc, prompt_toolkit; print(sys.version); print('grpc:', grpc.__version__); print('prompt-toolkit:', prompt_toolkit.__version__)"
if ($LASTEXITCODE -ne 0) {
    throw "Dependency verification failed (exit code $LASTEXITCODE)."
}

Write-Host
Write-Host 'Setup completed successfully.' -ForegroundColor Green
Write-Host 'Run the project with:' -ForegroundColor Green
Write-Host '  powershell -ExecutionPolicy Bypass -File .\start.ps1 -Count 3'
