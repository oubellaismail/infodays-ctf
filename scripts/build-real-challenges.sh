#!/usr/bin/env bash
# Build and push all InfoDays 2026 final-round challenge images to DOCR.
# Challenge images go to the 'challenges' repository.
# Base images (web, pwn, misc) go to the same 'challenges' repository.
#
# NOTE: Qualification-round challenges are intentionally excluded — their
# images are already in DOCR from the qualifier push and must not be
# overwritten here:
#   Malware Lab, Pearl Binary Signature, Venue Recon, Shanks, VAR Review,
#   Legends Gate, Secret Archive, Stadium DeFi, VIP Access, Cipher
#   Championship, Stadium IR, Referee Briefing, KDB Scouting Report,
#   VAR Mobile Companion, Man City.
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
  local tag="$1" context="$2" dockerfile="${3:-}"
  if [[ ! -d "$context" ]]; then
    echo "  [SKIP] $tag — not found: $context"
    return
  fi
  echo "  [$tag]"
  if [[ -n "$dockerfile" ]]; then
    docker build -q --platform linux/amd64 -f "$dockerfile" -t "$REGISTRY/challenges:$tag" "$context"
  else
    docker build -q --platform linux/amd64 -t "$REGISTRY/challenges:$tag" "$context"
  fi
  docker push "$REGISTRY/challenges:$tag"
}

echo ""
echo "=== Building base images ==="
build_push "web" "$REPO_PATH/base/web"
build_push "pwn" "$REPO_PATH/base/pwn"
build_push "misc" "$REPO_PATH/base/misc"

echo ""
echo "=== Building challenge images (final round only) ==="

# Web
build_push "ping-o-matic"     "$REPO_PATH/challenges/web/ping_o_matic"
build_push "scout-database"   "$REPO_PATH/challenges/web/scout_database"
build_push "var-check-bro"    "$REPO_PATH/challenges/web/var_check_bro"
build_push "stadium-ci"       "$REPO_PATH/challenges/web/stadium_ci"
build_push "referee-decision" "$REPO_PATH/challenges/web/referee_decision_system"
build_push "yami-sukehiro"    "$REPO_ROOT/challenges/real/challenges/web/yami_sukehiro"
build_push "batistuta"        "$REPO_ROOT/challenges/real/challenges/web/batistuta"

# Pwn
build_push "var-replay-buffer" "$REPO_PATH/challenges/pwn/var_replay_buffer"
build_push "shanks-v2"         "$REPO_ROOT/challenges/real/challenges/pwn/shanks_v2"

# Misc
build_push "coach-gpt"        "$REPO_PATH/challenges/misc/coach_gpt_jailbreak"
build_push "ait-baha-nuclear" "$REPO_PATH/challenges/misc/ait_baha_nuclear"
build_push "agadir-medport"   "$REPO_PATH/challenges/misc/agadir_medport"

# Forensics
build_push "stadium-soc"      "$REPO_PATH/challenges/forensics/stadium_soc"

# Crypto (new)
build_push "kdb"     "$REPO_ROOT/challenges/real/challenges/crypto/kdb"     "$REPO_ROOT/challenges/real/challenges/crypto/kdb/src/Dockerfile"
build_push "neymar"  "$REPO_ROOT/challenges/real/challenges/crypto/neymar"

# Pwn (new)
build_push "leonel-messi" "$REPO_ROOT/challenges/real/challenges/pwn/leonel_messi"

# Reversing (new)
build_push "cr7"       "$REPO_ROOT/challenges/real/challenges/reversing/cr7"       "$REPO_ROOT/challenges/real/challenges/reversing/cr7/src/Dockerfile"
build_push "formation" "$REPO_ROOT/challenges/real/challenges/reversing/formation"

# Web (new)
build_push "haaland" "$REPO_ROOT/challenges/real/challenges/web/haaland"

echo ""
echo "=== Done: 3 base + 16 challenge images pushed to $REGISTRY/challenges ==="
