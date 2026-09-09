[CmdletBinding()]
param(
    [Alias('c')]
    [ValidateRange(1, 2147483647)]
    [int]$Count = 3
)

$ErrorActionPreference = 'Stop'
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectDir

$pythonExe = Join-Path $ProjectDir '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Python virtual environment not found at $pythonExe. Run .\setup-windows.ps1 first."
}

$configPath = Join-Path $ProjectDir 'json\nodes.json'
if (-not (Test-Path -LiteralPath $configPath)) {
    throw "Node configuration not found: $configPath"
}

$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$maxNodes = @($config.nodes).Count
if ($Count -gt $maxNodes) {
    throw "-Count $Count was requested, but nodes.json only defines $maxNodes nodes."
}

$powershellExe = (Get-Command powershell.exe -ErrorAction Stop).Source
$children = @()
$escapedProjectDir = $ProjectDir.Replace("'", "''")
$escapedPythonExe = $pythonExe.Replace("'", "''")

try {
    for ($id = 1; $id -le $Count; $id++) {
        # EncodedCommand avoids quoting problems when the project path contains spaces.
        $childCommand = @"
Set-Location -LiteralPath '$escapedProjectDir'
`$env:PYTHONUTF8 = '1'
`$Host.UI.RawUI.WindowTitle = 'socket-whatsapp-clone - Node $id'
& '$escapedPythonExe' lauch_node.py --id $id --count $Count
`$nodeExitCode = `$LASTEXITCODE
if (`$nodeExitCode -ne 0) {
    Write-Host ''
    Write-Host "Node $id exited with code `$nodeExitCode." -ForegroundColor Red
    Read-Host 'Press Enter to close this window'
}
exit `$nodeExitCode
"@

        $encodedCommand = [Convert]::ToBase64String(
            [Text.Encoding]::Unicode.GetBytes($childCommand)
        )

        $process = Start-Process `
            -FilePath $powershellExe `
            -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $encodedCommand) `
            -WorkingDirectory $ProjectDir `
            -PassThru

        $children += $process
    }

    Write-Host "$Count node PowerShell windows started." -ForegroundColor Green
    Write-Host 'Press Ctrl+C here to stop every node.'

    while ($true) {
        $running = @($children | Where-Object { -not $_.HasExited })
        if ($running.Count -eq 0) {
            break
        }
        Start-Sleep -Milliseconds 300
    }
}
finally {
    $running = @($children | Where-Object { -not $_.HasExited })
    if ($running.Count -gt 0) {
        Write-Host
        Write-Host 'Stopping node processes...' -ForegroundColor Yellow
        foreach ($process in $running) {
            # /T terminates descendants too, matching the process-group cleanup
            # behavior of start.sh on Linux.
            & taskkill.exe /PID $process.Id /T /F 2>$null | Out-Null
        }
    }
}
