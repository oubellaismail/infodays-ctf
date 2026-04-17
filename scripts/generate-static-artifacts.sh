#!/usr/bin/env bash
# Generate per-team static challenge artifacts and pack them into zips.
#
# For challenges that have a gen.py / create_challenge.py script, the script
# is called with the team's derived flag injected via the FLAG env var (or
# FLAG1/FLAG2/... for multi-flag statics). The output files are then zipped
# into challenges/static-content/{challenge_id}/{team_id}.zip.
#
# For challenges with hardcoded flags (no generator), a single default.zip
# is produced and all teams share it.
#
# Requirements:
#   - CTF_MASTER_SECRET env var set
#   - CTFD_ADMIN_TOKEN env var set
#   - CTFD_URL env var set (e.g. https://ctfd.infodays.net)
#   - REPO_PATH pointing to the source repo checkout
#   - Python 3.11+ with Pillow, cryptography libs in source repo's venv
#
# Usage:
#   CTF_MASTER_SECRET=... CTFD_ADMIN_TOKEN=... CTFD_URL=... \
#   REPO_PATH=/tmp/ctf-source bash scripts/generate-static-artifacts.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_PATH="${REPO_PATH:-$REPO_ROOT/challenges/real}"
OUTPUT_DIR="$REPO_ROOT/challenges/static-content"
CONTROLLER_DIR="$REPO_ROOT/controller"

: "${CTF_MASTER_SECRET:?CTF_MASTER_SECRET must be set}"
: "${CTFD_ADMIN_TOKEN:?CTFD_ADMIN_TOKEN must be set}"
: "${CTFD_URL:?CTFD_URL must be set}"

# ── Fetch all teams from CTFd ──────────────────────────────────────────────────
echo "[teams] Fetching team list from CTFd..."
TEAMS_JSON=$(curl -s \
  -H "Authorization: Token $CTFD_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  "$CTFD_URL/api/v1/teams?per_page=100")

mapfile -t TEAM_IDS < <(echo "$TEAMS_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for t in data.get('data', []):
    print(t['id'])
")

echo "[teams] Found ${#TEAM_IDS[@]} teams"

# ── Helper: derive flag for team + challenge ───────────────────────────────────
derive_flag() {
  local team_id="$1" challenge_id="$2"
  CTF_MASTER_SECRET="$CTF_MASTER_SECRET" python3 "$CONTROLLER_DIR/flag.py" \
    --team "$team_id" --challenge "$challenge_id"
}

# ── Helper: zip a directory's contents ────────────────────────────────────────
make_zip() {
  local src_dir="$1" dest_zip="$2"
  mkdir -p "$(dirname "$dest_zip")"
  (cd "$src_dir" && zip -qr "$dest_zip" .)
}

echo ""
echo "=== Static challenges with generators ==="

# ── tournament-bracket (3 flags, gen.py) ──────────────────────────────────────
CHDIR="$REPO_PATH/challenges/reversing/tournament_bracket"
if [[ -f "$CHDIR/gen.py" ]]; then
  echo "[tournament-bracket] Generating per-team ELF binaries..."
  for team_id in "${TEAM_IDS[@]}"; do
    WORK=$(mktemp -d)
    cp -r "$CHDIR/." "$WORK/"

    FLAG1=$(derive_flag "$team_id" "tournament-bracket-1")
    FLAG2=$(derive_flag "$team_id" "tournament-bracket-2")
    FLAG3=$(derive_flag "$team_id" "tournament-bracket-3")

    (cd "$WORK" && FLAG1="$FLAG1" FLAG2="$FLAG2" FLAG3="$FLAG3" \
      python3 gen.py 2>/dev/null && make -s 2>/dev/null) || true

    ARTIFACT="$WORK/dist/tournament"
    if [[ -f "$ARTIFACT" ]]; then
      DEST="$OUTPUT_DIR/tournament-bracket/$team_id"
      mkdir -p "$DEST"
      cp "$ARTIFACT" "$DEST/tournament"
      make_zip "$DEST" "$OUTPUT_DIR/tournament-bracket/${team_id}.zip"
      rm -rf "$DEST"
    else
      echo "  [WARN] tournament binary not found for team $team_id"
    fi
    rm -rf "$WORK"
  done
fi

# ── cipher-championship (3 flags, gen.py) ─────────────────────────────────────
CHDIR="$REPO_PATH/challenges/crypto/cipher_championship"
if [[ -f "$CHDIR/gen.py" ]]; then
  echo "[cipher-championship] Generating per-team text files..."
  for team_id in "${TEAM_IDS[@]}"; do
    WORK=$(mktemp -d)
    cp -r "$CHDIR/." "$WORK/"

    FLAG1=$(derive_flag "$team_id" "cipher-championship-1")
    FLAG2=$(derive_flag "$team_id" "cipher-championship-2")
    FLAG3=$(derive_flag "$team_id" "cipher-championship-3")

    (cd "$WORK" && FLAG1="$FLAG1" FLAG2="$FLAG2" FLAG3="$FLAG3" \
      python3 gen.py 2>/dev/null) || true

    PUB="$WORK/public"
    if [[ -d "$PUB" ]]; then
      make_zip "$PUB" "$OUTPUT_DIR/cipher-championship/${team_id}.zip"
    else
      echo "  [WARN] cipher-championship public/ not found for team $team_id"
    fi
    rm -rf "$WORK"
  done
fi

# ── var-override (1 flag, gen.py) ─────────────────────────────────────────────
CHDIR="$REPO_PATH/challenges/crypto/var_override"
if [[ -f "$CHDIR/gen.py" ]]; then
  echo "[var-override] Generating per-team ECDSA files..."
  for team_id in "${TEAM_IDS[@]}"; do
    WORK=$(mktemp -d)
    cp -r "$CHDIR/." "$WORK/"

    FLAG=$(derive_flag "$team_id" "var-override")

    (cd "$WORK" && FLAG="$FLAG" python3 gen.py 2>/dev/null) || true

    PUB="$WORK/public"
    if [[ -d "$PUB" ]]; then
      make_zip "$PUB" "$OUTPUT_DIR/var-override/${team_id}.zip"
    else
      echo "  [WARN] var-override public/ not found for team $team_id"
    fi
    rm -rf "$WORK"
  done
fi

# ── kdb-scouting-report (4 flags, create_challenge.py) ────────────────────────
CHDIR="$REPO_PATH/challenges/osint/kdb_scouting_report"
if [[ -f "$CHDIR/create_challenge.py" ]]; then
  echo "[kdb-scouting-report] Generating per-team WebP files..."
  for team_id in "${TEAM_IDS[@]}"; do
    WORK=$(mktemp -d)
    cp -r "$CHDIR/." "$WORK/"

    FLAG1=$(derive_flag "$team_id" "kdb-scouting-report-1")
    FLAG2=$(derive_flag "$team_id" "kdb-scouting-report-2")
    FLAG3=$(derive_flag "$team_id" "kdb-scouting-report-3")
    FLAG4=$(derive_flag "$team_id" "kdb-scouting-report-4")

    (cd "$WORK" && FLAG1="$FLAG1" FLAG2="$FLAG2" FLAG3="$FLAG3" FLAG4="$FLAG4" \
      python3 create_challenge.py 2>/dev/null) || true

    ARTIFACT=$(find "$WORK" -maxdepth 1 -name "*.webp" | head -1)
    if [[ -n "$ARTIFACT" ]]; then
      DEST="$OUTPUT_DIR/kdb-scouting-report/$team_id"
      mkdir -p "$DEST"
      cp "$ARTIFACT" "$DEST/kevin-de-bruyne.webp"
      make_zip "$DEST" "$OUTPUT_DIR/kdb-scouting-report/${team_id}.zip"
      rm -rf "$DEST"
    else
      echo "  [WARN] kdb webp not found for team $team_id"
    fi
    rm -rf "$WORK"
  done
fi

# ── vip-invitation (1 flag, create_challenge.py) ──────────────────────────────
CHDIR="$REPO_PATH/challenges/forensics/the_vip_invitation"
if [[ -f "$CHDIR/create_challenge.py" ]]; then
  echo "[vip-invitation] Generating per-team stego images..."
  for team_id in "${TEAM_IDS[@]}"; do
    WORK=$(mktemp -d)
    cp -r "$CHDIR/." "$WORK/"

    FLAG=$(derive_flag "$team_id" "vip-invitation")

    (cd "$WORK" && FLAG="$FLAG" python3 create_challenge.py 2>/dev/null) || true

    ARTIFACT=$(find "$WORK" -maxdepth 1 -name "*.jpg" | head -1)
    if [[ -n "$ARTIFACT" ]]; then
      DEST="$OUTPUT_DIR/vip-invitation/$team_id"
      mkdir -p "$DEST"
      cp "$ARTIFACT" "$DEST/$(basename "$ARTIFACT")"
      make_zip "$DEST" "$OUTPUT_DIR/vip-invitation/${team_id}.zip"
      rm -rf "$DEST"
    else
      echo "  [WARN] vip-invitation image not found for team $team_id"
    fi
    rm -rf "$WORK"
  done
fi

echo ""
echo "=== Static challenges with hardcoded flags (default.zip) ==="

# ── legends-gate (hardcoded ELF) ──────────────────────────────────────────────
CHDIR="$REPO_PATH/challenges/reversing/legends_gate"
if [[ -d "$CHDIR" ]]; then
  echo "[legends-gate] Packing default.zip..."
  DEST="$OUTPUT_DIR/legends-gate"
  mkdir -p "$DEST"
  cp "$CHDIR/legend_gate_pro" "$DEST/legend_gate_pro" 2>/dev/null || true
  make_zip "$DEST" "$OUTPUT_DIR/legends-gate/default.zip"
  rm -f "$DEST/legend_gate_pro"
fi

# ── venue-recon (hardcoded flag in PNG + txt) ─────────────────────────────────
CHDIR="$REPO_PATH/challenges/osint/venue_recon"
if [[ -d "$CHDIR" ]]; then
  echo "[venue-recon] Packing default.zip..."
  DEST=$(mktemp -d)
  cp "$CHDIR/venue_teaser.png" "$DEST/" 2>/dev/null || true
  make_zip "$DEST" "$OUTPUT_DIR/venue-recon/default.zip"
  rm -rf "$DEST"
fi

# pearl-binary-signature: TCP service — no static zip needed.
# agadir_tifo_challenge.png must be uploaded manually as a CTFd file attachment.

# ── coach-formation (Python script players run) ───────────────────────────────
CHDIR="$REPO_PATH/challenges/crypto/coach_formation"
if [[ -d "$CHDIR" ]]; then
  echo "[coach-formation] Packing default.zip..."
  DEST=$(mktemp -d)
  cp "$CHDIR/coach_challenge_ultra.py" "$DEST/" 2>/dev/null || true
  make_zip "$DEST" "$OUTPUT_DIR/coach-formation/default.zip"
  rm -rf "$DEST"
fi

# ── var-mobile-companion (APK, gen.py — requires Android build tools) ─────────
CHDIR="$REPO_PATH/challenges/reversing/var_mobile_companion"
if [[ -f "$CHDIR/gen.py" ]]; then
  echo "[var-mobile-companion] NOTE: APK generation requires Android build tools."
  echo "  Packing pre-built dist/companion.apk as default.zip for now."
  DEST=$(mktemp -d)
  cp "$CHDIR/dist/companion.apk" "$DEST/" 2>/dev/null || true
  make_zip "$DEST" "$OUTPUT_DIR/var-mobile-companion/default.zip"
  rm -rf "$DEST"
fi

echo ""
echo "=== Summary ==="
echo "Output directory: $OUTPUT_DIR"
find "$OUTPUT_DIR" -name "*.zip" | wc -l | xargs -I{} echo "Total zips: {}"
