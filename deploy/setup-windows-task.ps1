# MAXIMISEART-Dad — Register Windows Task Scheduler task
# Phase 5 gated deployment helper. Registers Task Scheduler with explicit runtime path.
#
# Usage:
#   .\setup-windows-task.ps1                          # default 06:30
#   .\setup-windows-task.ps1 -RunTime "07:00"         # custom time
#   .\setup-windows-task.ps1 -Uninstall               # remove task

param(
    [string]$RuntimePath = "$env:USERPROFILE\MAXIMISEART-Dad-runtime",
    [string]$ProjectPath = (Split-Path -Parent $PSScriptRoot),
    [string]$RunTime = "06:30",
    [string]$TaskName = "MAXIMISEART-Dad-Daily",
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

if ($Uninstall) {
    Write-Host "Usuwam task '$TaskName'..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Usunięto."
    exit 0
}

# Verify paths
$batFile = Join-Path $ProjectPath "deploy\run-daily.bat"
if (-not (Test-Path $batFile)) {
    Write-Error "Nie znaleziono: $batFile"
    exit 1
}

# Ensure runtime dirs
if (-not (Test-Path $RuntimePath)) {
    New-Item -ItemType Directory -Path $RuntimePath -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $RuntimePath "logs") -Force | Out-Null
}

# Build task
$action = New-ScheduledTaskAction `
    -Execute $batFile `
    -Argument "`"$RuntimePath`"" `
    -WorkingDirectory $ProjectPath

$trigger = New-ScheduledTaskTrigger `
    -Daily `
    -At $RunTime

$settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 15) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

# Register
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "MAXIMISEART-Dad daily email->Excel workflow. Runs $RunTime Europe/Warsaw." `
    -Force | Out-Null

Write-Host "✓ Task zarejestrowany: $TaskName"
Write-Host "  Godzina: $RunTime"
Write-Host "  Runtime: $RuntimePath"
Write-Host "  Projekt: $ProjectPath"
Write-Host ""
Write-Host "Sprawdź task w Task Scheduler UI lub:"
Write-Host "  Get-ScheduledTask -TaskName '$TaskName'"
Write-Host ""
Write-Host "Test uruchomienia (bez czekania do rana):"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
