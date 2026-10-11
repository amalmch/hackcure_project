#!/usr/bin/env bash
# Lance Claude Code en autonomie sur PROMPT.md et le relance jusqu'à DONE.flag.
# À lancer dans un dossier VIDE "Hospital_copilot" contenant PROMPT.md et ce script.
MAX_RUNS=40; mkdir -p logs; LOG=logs/night.log
for i in $(seq 1 $MAX_RUNS); do
  [ -f DONE.flag ] && { echo "=== DONE.flag trouvé, fin. ===" | tee -a "$LOG"; break; }
  echo "=== Session $i - $(date) ===" | tee -a "$LOG"
  if [ "$i" -eq 1 ]; then
    claude -p "$(cat PROMPT.md)" --dangerously-skip-permissions --max-turns 300 >> "$LOG" 2>&1
  else
    claude -p "Reprends le travail autonome selon PROMPT.md : branche feat/platform, lis PROGRESS.md, continue exactement là où tu t'es arrêté, sans poser de question, jusqu'à DONE.flag." \
      --continue --dangerously-skip-permissions --max-turns 300 >> "$LOG" 2>&1
  fi
  code=$?
  [ -d .git ] && git push -u origin feat/platform >> "$LOG" 2>&1
  if [ $code -ne 0 ]; then echo "Erreur ou limite : pause 10 min" | tee -a "$LOG"; sleep 600; else sleep 20; fi
done
echo "=== Fin - $(date) ===" | tee -a "$LOG"
