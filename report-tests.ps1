[CmdletBinding()]
param(
    [ValidateSet('all', 'order3', 'order15', 'private', 'causal', 'snapshot', 'election', 'unit')]
    [string]$Scenario = 'all',
    [switch]$OpenFolder,
    [switch]$Visual
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectDir

$pythonExe = Join-Path $ProjectDir '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Ambiente virtual não encontrado em $pythonExe. Rode .\setup-windows.ps1 primeiro."
}

Write-Host '=== Testes automatizados para evidências do relatório ===' -ForegroundColor Cyan
Write-Host 'IMPORTANTE: feche antes qualquer execução feita por start.ps1 para liberar as portas 5001-5015.' -ForegroundColor Yellow
Write-Host

$env:PYTHONUTF8 = '1'
$runnerArgs = @((Join-Path $ProjectDir 'report_tests.py'), $Scenario)
if ($Visual) { $runnerArgs += '--visual' }
& $pythonExe @runnerArgs
$exitCode = $LASTEXITCODE

$evidenceDir = Join-Path $ProjectDir 'evidencias_relatorio'
if (Test-Path -LiteralPath $evidenceDir) {
    Write-Host
    Write-Host "Evidências salvas em: $evidenceDir" -ForegroundColor Green
    if (-not $Visual) {
        Write-Host 'Para execução visual pronta para screenshot:' -ForegroundColor Green
        Write-Host '  .\report-tests.ps1 -Scenario order3 -Visual' -ForegroundColor White
    }

    if ($OpenFolder) {
        Start-Process explorer.exe $evidenceDir
    }
}

exit $exitCode
