# Lance Claude Code en autonomie sur PROMPT.md et le relance jusqu'à DONE.flag.
# À lancer dans un dossier VIDE "Hospital_copilot" contenant PROMPT.md et ce script :
#   Set-ExecutionPolicy -Scope Process Bypass
#   .\run-night.ps1
$MaxRuns = 40
New-Item -ItemType Directory -Force -Path logs | Out-Null
$Log = "logs\night.log"
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0

for ($i = 1; $i -le $MaxRuns; $i++) {
    if (Test-Path "DONE.flag") { "=== DONE.flag trouvé, fin. ===" | Tee-Object -Append $Log; break }
    "=== Session $i - $(Get-Date) ===" | Tee-Object -Append $Log
    if ($i -eq 1) {
        claude -p (Get-Content "PROMPT.md" -Raw) --dangerously-skip-permissions --max-turns 300 *>> $Log
    } else {
        claude -p "Reprends le travail autonome selon PROMPT.md : branche feat/platform, lis PROGRESS.md, continue exactement là où tu t'es arrêté, sans poser de question, jusqu'à DONE.flag." --continue --dangerously-skip-permissions --max-turns 300 *>> $Log
    }
    $code = $LASTEXITCODE
    if (Test-Path ".git") { git push -u origin feat/platform *>> $Log }   # filet de sécurité
    if ($code -ne 0) { "Code $code (limite d'usage ou erreur) : pause 10 min" | Tee-Object -Append $Log; Start-Sleep -Seconds 600 }
    else { Start-Sleep -Seconds 20 }
}
"=== Fin - $(Get-Date) ===" | Tee-Object -Append $Log
