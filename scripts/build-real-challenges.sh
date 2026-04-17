#!/usr/bin/env bash
# Build and push all real qualification challenge images to DOCR.
# Challenge images go to the 'challenges' repository.
# Base images (web, pwn, misc) go to the same 'challenges' repository.
#
# Usage:
#   bash scripts/build-real-challenges.sh
#   REPO_PATH=/custom/path bash scripts/build-real-challenges.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

REGISTRY="${REGISTRY:-registry.digitalocean.com/infodays-registry}"
REPO_PATH="${REPO_PATH:-$REPO_ROOT/challenges/real}"
REPO_URL="https://github.com/YChahidi/Infodays_2026_Ctf.git"
BRANCH="SaamNoLimits-CTFs"

# ── Clone source repo if not present ──────────────────────────────────────────
if [[ ! -d "$REPO_PATH" ]]; then
  echo "[clone] Cloning $REPO_URL@$BRANCH → $REPO_PATH"
  git clone --depth=1 --branch "$BRANCH" "$REPO_URL" "$REPO_PATH"
else
  echo "[clone] Using existing source at $REPO_PATH"
fi

build_push() {
  local tag="$1" context="$2"
  if [[ ! -d "$context" ]]; then
    echo "  [SKIP] $tag — not found: $context"
    return
  fi
  echo "  [$tag]"
  docker build -q -t "$REGISTRY/challenges:$tag" "$context"
  docker push "$REGISTRY/challenges:$tag"
}

echo ""
echo "=== Building base images ==="
build_push "web" "$REPO_PATH/base/web"
build_push "pwn" "$REPO_PATH/base/pwn"
build_push "misc" "$REPO_PATH/base/misc"

echo ""
echo "=== Building challenge images ==="

# Web
build_push "vip-access"       "$REPO_PATH/challenges/web/VIP_Access_Session_Inspector"
build_push "secret-archive"   "$REPO_PATH/challenges/web/the_secret_archive"
build_push "ping-o-matic"     "$REPO_PATH/challenges/web/ping_o_matic"
build_push "scout-database"   "$REPO_PATH/challenges/web/scout_database"
build_push "var-check-bro"    "$REPO_PATH/challenges/web/var_check_bro"
build_push "stadium-ci"       "$REPO_PATH/challenges/web/stadium_ci"
build_push "referee-decision" "$REPO_PATH/challenges/web/referee_decision_system"
build_push "man-city"         "$REPO_PATH/challenges/web/man_city"
build_push "stadium-defi"     "$REPO_PATH/challenges/web/stadium_defi"

# Pwn
build_push "var-review"       "$REPO_PATH/challenges/pwn/var_review"
build_push "var-replay-buffer" "$REPO_PATH/challenges/pwn/var_replay_buffer"
build_push "shanks"           "$REPO_PATH/challenges/pwn/shanks"

# Misc
build_push "coach-gpt"        "$REPO_PATH/challenges/misc/coach_gpt_jailbreak"
build_push "referee-briefing" "$REPO_PATH/challenges/misc/referee_briefing"
build_push "ait-baha-nuclear" "$REPO_PATH/challenges/misc/ait_baha_nuclear"
build_push "agadir-medport"   "$REPO_PATH/challenges/misc/agadir_medport"

# Forensics
build_push "malware-lab"      "$REPO_PATH/challenges/forensics/malware_lab_stadium"
build_push "stadium-ir"       "$REPO_PATH/challenges/forensics/stadium_ir"
build_push "stadium-soc"      "$REPO_PATH/challenges/forensics/stadium_soc"

# pearl-binary-signature: no Dockerfile in source repo — use override
OVERRIDE_DIR="$REPO_ROOT/challenges/overrides/pearl-binary-signature"
PEARL_SRC="$REPO_PATH/challenges/forensics/pearl_binary_signature"
if [[ -d "$PEARL_SRC" && -d "$OVERRIDE_DIR" ]]; then
  echo "  [pearl-binary-signature] (override Dockerfile)"
  TMPBUILD=$(mktemp -d)
  cp "$OVERRIDE_DIR/Dockerfile" "$TMPBUILD/"
  cp "$OVERRIDE_DIR/entrypoint.sh" "$TMPBUILD/"
  cp "$PEARL_SRC/listener.py" "$TMPBUILD/"
  cp "$PEARL_SRC/agadir_tifo_challenge.png" "$TMPBUILD/" 2>/dev/null || true
  docker build -q -t "$REGISTRY/challenges:pearl-binary-signature" "$TMPBUILD/"
  docker push "$REGISTRY/challenges:pearl-binary-signature"
  rm -rf "$TMPBUILD"
fi

echo ""
echo "=== Done: 3 base + 20 challenge images pushed to $REGISTRY/challenges ==="
