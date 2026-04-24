# MAXIMISEART-Dad uninstall — removes Task Scheduler task + optionally runtime data.
# NIE usuwa repo (git clone pozostaje).

param(
    [switch]$PurgeRuntime,       # WARNING: deletes vault/, state/, learning/, logs/
    [switch]$PurgeOAuthOnly,     # Remove only Gmail token (re-auth needed)
    [string]$RuntimePath = "$env:USERPROFILE\MAXIMISEART-Dad-runtime",
    [string]$TaskName = "MAXIMISEART-Dad-Daily"
)

Write-Host "Odinstalowywanie MAXIMISEART-Dad..."

# Remove Task
try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "✓ Usunięto Task Scheduler task"
} catch {
    Write-Host "⚠ Task nie istnieje lub nie można go usunąć"
}

if ($PurgeOAuthOnly) {
    $tokenPath = Join-Path $RuntimePath "state\oauth-token.json"
    if (Test-Path $tokenPath) {
        Remove-Item $tokenPath -Force
        Write-Host "✓ Usunięto Gmail OAuth token. Uruchom init_wizard.py --reauth."
    }
    exit 0
}

if ($PurgeRuntime) {
    Write-Warning "UWAGA: usuwam runtime data ($RuntimePath). Vault + logs + learning = stracone."
    $confirm = Read-Host "Wpisz 'TAK' żeby potwierdzić"
    if ($confirm -eq "TAK") {
        Remove-Item -Recurse -Force $RuntimePath
        Write-Host "✓ Runtime purged"
    } else {
        Write-Host "Anulowano. Runtime nietknięty."
    }
}

Write-Host "Done. Repo (kod) pozostaje — usuń ręcznie jeśli chcesz."
