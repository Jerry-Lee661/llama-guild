#!/usr/bin/env bash
# guild-switch.sh - Hard switch for llama-guild workflow skill triggering (ZCode).
# POSIX counterpart of guild-switch.ps1; uses python3 for lossless JSON edits.
#
# Usage:
#   bash guild-switch.sh status            # per-skill state (user scope)
#   bash guild-switch.sh off               # stop accidental triggering
#   bash guild-switch.sh on                # restore the workflow
#   bash guild-switch.sh off workspace     # write <cwd>/.zcode/config.json instead
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-status}"
SCOPE="${2:-user}"

case "$SCOPE" in
  user)      CONFIG="$HOME/.zcode/cli/config.json" ;;
  workspace) CONFIG="$(pwd)/.zcode/config.json" ;;
  *) echo "[guild-switch] unknown scope: $SCOPE (user|workspace)"; exit 1 ;;
esac

# Functional probe — on Windows, `python3` may be a Store alias that exists but no-ops.
PY=""
for cand in "${PYTHON:-}" python3 python; do
  [ -z "$cand" ] && continue
  if "$cand" -c "import json" >/dev/null 2>&1; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
  echo "[guild-switch] 需要 python3/python（或设置 PYTHON=...）"; exit 1
fi

$PY - "$REPO" "$CONFIG" "$ACTION" "$SCOPE" <<'PY'
import json, os, sys

repo, config_path, action, scope = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
skills_root = os.path.join(repo, "skills")
dirs = sorted(d for d in os.listdir(skills_root)
              if os.path.isdir(os.path.join(skills_root, d)))
if not dirs:
    print(f"[guild-switch] no skills under {skills_root}"); sys.exit(1)

cfg = {}
if os.path.isfile(config_path):
    with open(config_path, encoding="utf-8-sig") as f:
        cfg = json.load(f)
overrides = cfg.setdefault("skillOverrides", {})

def keys_for(d):
    return [d, os.path.join(d, "SKILL.md")]

def is_disabled(d):
    return any(overrides.get(k, {}).get("enable") is False for k in keys_for(d))

if action == "off":
    for d in dirs:
        for k in keys_for(os.path.join(skills_root, d)):
            overrides[k] = {"enable": False}
elif action == "on":
    for d in dirs:
        for k in keys_for(os.path.join(skills_root, d)):
            overrides.pop(k, None)
elif action != "status":
    print(f"[guild-switch] unknown action: {action} (on|off|status)"); sys.exit(1)

os.makedirs(os.path.dirname(config_path), exist_ok=True)
with open(config_path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
    f.write("\n")

if action == "status":
    print(f"[guild-switch] scope={scope} config={config_path}")
    for d in dirs:
        full = os.path.join(skills_root, d)
        state = "DISABLED" if is_disabled(full) else "active  "
        print(f"  [{state}] {d}")
else:
    print(f"[guild-switch] {action.upper()} ({scope} scope): {config_path}")
PY
