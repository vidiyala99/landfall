#!/usr/bin/env bash
# Run one Landfall job on an Agent37 lane and push the results to branch lane/<slug>.
# Usage: scripts/lane_run.sh <slug> [mode]   mode: both (default) | do | find | full
set -uo pipefail
SLUG="$1"; MODE="${2:-both}"
cd ~/landfall
export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"
[ -f ~/.claude_token_env ] && . ~/.claude_token_env
. .venv/bin/activate
git fetch -q origin && git checkout -q -B "lane/$SLUG" origin/main
echo "[$(date -u +%H:%M:%S)] start $SLUG $MODE"
if [ "$MODE" = "full" ]; then
  python -c "
import tomllib,sys; sys.path.insert(0,'.')
from landfall.pipeline import Job
s=[x for x in tomllib.load(open('sites/targets.toml','rb'))['site'] if x['slug']=='$SLUG'][0]
Job(s['url'], s.get('goal'), s.get('tasks'), s.get('visibility_query'), name=s.get('name'), slug='$SLUG').run()
"
else
  python -m landfall.agent_run "$MODE" "$SLUG"
fi
echo "[$(date -u +%H:%M:%S)] done $SLUG"
git add -f "runs/$SLUG" && git -c user.name="landfall-lane" -c user.email="lane@landfall.local" \
  commit -qm "lane run: $SLUG ($MODE)" && git push -q -f origin "lane/$SLUG"
echo "[$(date -u +%H:%M:%S)] pushed lane/$SLUG"
