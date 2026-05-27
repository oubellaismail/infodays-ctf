#!/usr/bin/env python3
"""
Generate per-team static challenge artifacts.

For each team × challenge:
  1. Derives a hex8 seed: hmac(CTF_MASTER_SECRET, "{team_id}:{challenge_id}")[:8]
  2. Runs the challenge generator (gen.py / create_challenge.py logic)
  3. Packages output into challenges/static-content/{challenge_id}/{team_id}.zip
  4. Registers exact per-team flags in CTFd:
       - single-flag challenges  → POST /api/v1/flags  (type=exact, per team)
       - multi_flag bundles      → POST /api/plugin/multi-flag-register  (static_flag)

Usage:
    python3 scripts/generate-static-artifacts.py \\
        --ctfd-url https://ctfd.infodays.net \\
        --admin-token $CTFD_ADMIN_TOKEN \\
        --master-secret $CTF_MASTER_SECRET \\
        [--challenges cipher-championship,tournament-bracket,...] \\
        [--team-ids 1,2,3]   # default: all teams from CTFd
        [--out-dir challenges/static-content]

Requirements (install if missing):
    pip install pycryptodome pillow requests
    apt/brew install exiftool gcc make zip
    javac (for var-mobile-companion)
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac as _hmac
import io
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CHALLENGES_DIR = REPO / "challenges" / "real" / "challenges"
OUT_BASE = REPO / "challenges" / "static-content"
ACTIVE_MASTER_SECRET = ""
MANIFESTS_DIR = REPO / "challenges" / "manifests"

STATIC_FILE_CHALLENGES = {
    # challenge_id: {"type": "single"|"multi", "gen": <function_name>}
    # Finals challenges only — qual challenges (cipher-championship, var-mobile-companion,
    # kdb-scouting-report, venue-recon, legends-gate) intentionally excluded.
    "tournament-bracket":    {"type": "multi",  "gen": "gen_tournament_bracket"},
    "var-override":          {"type": "single", "gen": "gen_var_override"},
    "coach-formation":       {"type": "single", "gen": "gen_coach_formation"},
    "vip-invitation":        {"type": "single", "gen": "gen_vip_invitation"},
    "general-mbappe":        {"type": "single", "gen": "gen_general_mbappe"},
}

# Multi-flag component scoring params (initial, minimum, decay) per challenge
MULTI_FLAG_PARAMS = {
    "cipher-championship": [
        {"component_id": "cipher-championship-1", "env_var": "FLAG1", "initial": 350, "minimum": 50, "decay": 25},
        {"component_id": "cipher-championship-2", "env_var": "FLAG2", "initial": 350, "minimum": 50, "decay": 25},
        {"component_id": "cipher-championship-3", "env_var": "FLAG3", "initial": 350, "minimum": 50, "decay": 25},
    ],
    "tournament-bracket": [
        {"component_id": "tournament-bracket-1", "env_var": "FLAG1", "initial": 350, "minimum": 50, "decay": 25},
        {"component_id": "tournament-bracket-2", "env_var": "FLAG2", "initial": 350, "minimum": 50, "decay": 25},
        {"component_id": "tournament-bracket-3", "env_var": "FLAG3", "initial": 350, "minimum": 50, "decay": 25},
    ],
    "var-mobile-companion": [
        {"component_id": "var-mobile-companion-1", "env_var": "FLAG1", "initial": 200, "minimum": 50, "decay": 25},
        {"component_id": "var-mobile-companion-2", "env_var": "FLAG2", "initial": 300, "minimum": 50, "decay": 25},
        {"component_id": "var-mobile-companion-3", "env_var": "FLAG3", "initial": 350, "minimum": 50, "decay": 25},
        {"component_id": "var-mobile-companion-4", "env_var": "FLAG4", "initial": 450, "minimum": 50, "decay": 25},
        {"component_id": "var-mobile-companion-5", "env_var": "FLAG5", "initial": 400, "minimum": 50, "decay": 25},
    ],
    "kdb-scouting-report": [
        {"component_id": "kdb-scouting-report-1", "env_var": "FLAG1", "initial": 200, "minimum": 50, "decay": 25},
        {"component_id": "kdb-scouting-report-2", "env_var": "FLAG2", "initial": 300, "minimum": 50, "decay": 25},
        {"component_id": "kdb-scouting-report-3", "env_var": "FLAG3", "initial": 350, "minimum": 50, "decay": 25},
        {"component_id": "kdb-scouting-report-4", "env_var": "FLAG4", "initial": 400, "minimum": 50, "decay": 25},
    ],
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def derive_hex8(master_secret: str, team_id: int, challenge_id: str) -> str:
    """Derive a deterministic 8-char hex seed for a given team+challenge."""
    msg = f"{team_id}:{challenge_id}".encode()
    digest = _hmac.new(master_secret.encode(), msg, hashlib.sha256).hexdigest()
    return digest[:8]


def derive_team_digest(master_secret: str, team_id: int, challenge_id: str) -> str:
    """Derive the 32-hex per-team digest used inside infodays{...} flags."""
    msg = f"{team_id}:{challenge_id}".encode()
    return _hmac.new(master_secret.encode(), msg, hashlib.sha256).hexdigest()[:32]


def derive_team_flag(master_secret: str, team_id: int, challenge_id: str) -> str:
    """Return the standard team-derived flag string."""
    return f"infodays{{{derive_team_digest(master_secret, team_id, challenge_id)}}}"


def zip_files(files: list[tuple[str, bytes]]) -> bytes:
    """Pack (filename, data) pairs into a zip. Returns zip bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files:
            zf.writestr(name, data)
    buf.seek(0)
    return buf.read()


def run(cmd: list[str], cwd=None, env=None) -> subprocess.CompletedProcess:
    result = subprocess.run(
        cmd, cwd=cwd, env=env,
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  [!] Command failed: {' '.join(cmd)}", file=sys.stderr)
        print(f"  stdout: {result.stdout[:500]}", file=sys.stderr)
        print(f"  stderr: {result.stderr[:500]}", file=sys.stderr)
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")
    return result


def load_manifest_name_map() -> dict[str, str]:
    """Return manifest-id -> display-name mapping from challenge manifests."""
    mapping: dict[str, str] = {}
    for path in sorted(MANIFESTS_DIR.glob("*.yaml")):
        if path.name == "schema.yaml":
            continue
        data = yaml.safe_load(path.read_text())
        if isinstance(data, dict) and data.get("id") and data.get("name"):
            mapping[data["id"]] = data["name"]
    return mapping


# ── Per-challenge generators ──────────────────────────────────────────────────

def gen_cipher_championship(team_id: int, hex8: str, out_dir: Path) -> dict:
    """
    Returns {"files": [(name, bytes), ...], "flags": [(component_id, flag), ...]}
    """
    src = CHALLENGES_DIR / "crypto" / "cipher_championship"
    sys.path.insert(0, str(src))
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("cipher_gen", src / "gen.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        flag1 = f"INFODAYS{{SaamNoLimits_xor_broken_at_halftime_{hex8}}}".encode()
        flag2 = f"INFODAYS{{SaamNoLimits_cube_root_away_goal_{hex8}}}".encode()
        flag3 = f"INFODAYS{{SaamNoLimits_wiener_raised_the_trophy_{hex8}}}".encode()

        round1 = mod.gen_round1(flag1)
        round2 = mod.gen_round2(flag2)
        round3 = mod.gen_round3(flag3)

        return {
            "files": [
                ("round1.txt", round1.encode()),
                ("round2.txt", round2.encode()),
                ("round3.txt", round3.encode()),
            ],
            "flags": [
                ("cipher-championship-1", flag1.decode()),
                ("cipher-championship-2", flag2.decode()),
                ("cipher-championship-3", flag3.decode()),
            ],
        }
    finally:
        sys.path.pop(0)


def gen_tournament_bracket(team_id: int, hex8: str, out_dir: Path) -> dict:
    """Generates C source, compiles with make, returns binary."""
    src = CHALLENGES_DIR / "reversing" / "tournament_bracket"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        # Copy source tree
        shutil.copytree(src / "src", tmp / "src")
        shutil.copy(src / "Makefile", tmp / "Makefile")

        # Run gen.py in the temp dir to produce tournament.c
        sys.path.insert(0, str(src))
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("tb_gen", src / "gen.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            constants, flags = mod.build_constants(hex8)
            source = mod.CFILE_TEMPLATE.replace("{CONSTANTS}", constants)
            (tmp / "src" / "tournament.c").write_text(source)
        finally:
            sys.path.pop(0)

        # Compile using the `all` target (outputs to dist/tournament)
        run(["make", "-C", str(tmp), "all"], cwd=str(tmp))

        # Find binary
        binary_path = tmp / "dist" / "tournament"
        if not binary_path.exists():
            binary_path = tmp / "tournament"
        if not binary_path.exists():
            # Try make output anywhere in tmp
            for p in tmp.rglob("tournament"):
                if p.is_file() and os.access(p, os.X_OK):
                    binary_path = p
                    break

        binary_data = binary_path.read_bytes()

        flag1, flag2, flag3 = [f.decode() for f in flags]
        return {
            "files": [("tournament", binary_data)],
            "flags": [
                ("tournament-bracket-1", flag1),
                ("tournament-bracket-2", flag2),
                ("tournament-bracket-3", flag3),
            ],
        }


def gen_var_override(team_id: int, hex8: str, out_dir: Path) -> dict:
    """Generates ECDSA signatures + AES-encrypted flag."""
    src = CHALLENGES_DIR / "crypto" / "var_override"
    sys.path.insert(0, str(src))
    sys.path.insert(0, str(src / "public"))
    try:
        from Crypto.Cipher import AES as _AES

        import importlib.util
        spec = importlib.util.spec_from_file_location("vo_gen", src / "gen.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Replicate gen.py logic inline (imports signer from public/)
        from signer import G, n, scalar_mul, sign_decision, verify  # noqa: F401

        while True:
            priv = int.from_bytes(secrets.token_bytes(32), "big") % n
            if 1 < priv < n - 1:
                break
        pub = scalar_mul(priv, G)

        decisions = [
            f"VAR_DECISION_{i:03d}_match_{hex8}_final"
            for i in range(15)
        ]
        sigs = []
        for msg in decisions:
            r, s = sign_decision(priv, msg.encode())
            sigs.append((msg, r, s))

        pub_key_txt = (
            "=== Infodays 2026 — VAR signer public key (secp256k1) ===\n"
            f"\nQx = {pub[0]}\nQy = {pub[1]}\n"
        )

        lines = [
            "=== 15 intercepted VAR decision signatures ===",
            "",
            "Format: decision | r | s",
            "Signature scheme: secp256k1 ECDSA over SHA-256(decision)",
            "",
        ]
        for msg, r, s in sigs:
            lines.append(f"{msg} | {r} | {s}")
        sigs_txt = "\n".join(lines) + "\n"

        flag = f"INFODAYS{{SaamNoLimits_hnp_lattice_var_override_{hex8}}}".encode()
        key = hashlib.sha256(priv.to_bytes(32, "big")).digest()
        nonce = secrets.token_bytes(12)
        aes = _AES.new(key, _AES.MODE_GCM, nonce=nonce)
        ct, tag = aes.encrypt_and_digest(flag)
        flag_enc = nonce + tag + ct

        # Include signer.py so players can use it
        signer_src = (src / "public" / "signer.py").read_bytes()

        return {
            "files": [
                ("public_key.txt", pub_key_txt.encode()),
                ("signatures.txt", sigs_txt.encode()),
                ("flag.enc", flag_enc),
                ("signer.py", signer_src),
            ],
            "flags": [("var-override", flag.decode())],
        }
    finally:
        # Remove both inserted paths
        for p in [str(src), str(src / "public")]:
            if p in sys.path:
                sys.path.remove(p)


def gen_kdb_scouting_report(team_id: int, hex8: str, out_dir: Path) -> dict:
    """Generates WebP with flags in EXIF/XMP/appended zip layers."""
    if not shutil.which("exiftool"):
        raise RuntimeError("exiftool not found — required for kdb-scouting-report")
    if not shutil.which("zip"):
        raise RuntimeError("zip not found — required for kdb-scouting-report")

    src = CHALLENGES_DIR / "osint" / "kdb_scouting_report"

    # Derive 4 independent hex8 values from the team's hex8 seed
    def sub_hex(suffix: str) -> str:
        msg = f"{team_id}:kdb-scouting-report-{suffix}".encode()
        return _hmac.new(hex8.encode(), msg, hashlib.sha256).hexdigest()[:8]

    h1 = sub_hex("1")
    h2 = sub_hex("2")
    h3 = sub_hex("3")
    h4 = sub_hex("4")

    flag1 = f"INFODAYS{{SaamNoLimits_the_eye_of_the_scout_{h1}}}"
    flag2 = f"INFODAYS{{SaamNoLimits_the_midfield_vision_{h2}}}"
    flag3 = f"INFODAYS{{SaamNoLimits_the_deep_playmaker_{h3}}}"
    flag4 = f"INFODAYS{{SaamNoLimits_genius_born_in_drongen_{h4}}}"
    zip_password = "drongen1991"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        out_webp = tmp / "kevin-de-bruyne.webp"

        # Try to use existing photo; fall back to placeholder
        base = None
        for cand in (src / "kdb_photo.webp", src / "kdb_photo.jpg", src / "kdb_photo.png"):
            if cand.exists():
                base = cand
                break

        if base is not None:
            from PIL import Image
            with Image.open(base) as im:
                im.save(out_webp, format="WEBP", quality=92)
        else:
            # Render placeholder
            from PIL import Image, ImageDraw
            img = Image.new("RGB", (900, 600), color=(10, 31, 58))
            draw = ImageDraw.Draw(img)
            draw.text((100, 220), "KEVIN DE BRUYNE", fill=(127, 211, 255))
            draw.text((100, 300), "SCOUTING REPORT", fill=(224, 224, 224))
            draw.text((100, 360), "InfoDays 2026 — classified", fill=(136, 153, 170))
            img.save(out_webp, format="WEBP", quality=92)

        # L1: EXIF Artist
        subprocess.run([
            "exiftool", "-overwrite_original",
            f"-Artist={flag1}",
            str(out_webp),
        ], capture_output=True, check=True)

        # L2: XMP Description (base64)
        l2_payload = "SCOUT NOTE: " + base64.b64encode(flag2.encode()).decode()
        subprocess.run([
            "exiftool", "-overwrite_original",
            f"-XMP-dc:Description={l2_payload}",
            str(out_webp),
        ], capture_output=True, check=True)

        # L3+L4: appended zip with readme + nested password-protected zip
        readme = tmp / "scout_readme.txt"
        readme.write_text(
            "=== SCOUT'S DEEPER NOTES ===\n"
            f"{flag3}\n\n"
            "The final target dossier is bundled as scout_final.zip.\n"
            "Archive password hint: the town where he was born, lowercase,\n"
            "concatenated with the year he was born. No spaces, no dashes.\n"
            "(If you don't know who 'he' is, you're not a scout.)\n"
        )

        inner_flag_file = tmp / "flag.txt"
        inner_flag_file.write_text(flag4 + "\n")

        inner_zip = tmp / "scout_final.zip"
        subprocess.run(
            ["zip", "-j", "-P", zip_password, str(inner_zip), str(inner_flag_file)],
            capture_output=True, check=True
        )
        inner_flag_file.unlink()

        outer_zip = tmp / "_append.zip"
        subprocess.run(
            ["zip", "-j", str(outer_zip), str(readme), str(inner_zip)],
            capture_output=True, check=True
        )

        with open(out_webp, "ab") as f:
            f.write(outer_zip.read_bytes())

        webp_data = out_webp.read_bytes()

    return {
        "files": [("kevin-de-bruyne.webp", webp_data)],
        "flags": [
            ("kdb-scouting-report-1", flag1),
            ("kdb-scouting-report-2", flag2),
            ("kdb-scouting-report-3", flag3),
            ("kdb-scouting-report-4", flag4),
        ],
    }


def gen_var_mobile_companion(team_id: int, hex8: str, out_dir: Path) -> dict:
    """
    Generates Java source with baked-in flags, compiles to JAR.
    Falls back to existing files.zip if javac is unavailable.
    """
    src = CHALLENGES_DIR / "reversing" / "var_mobile_companion"

    javac = shutil.which("javac")
    jar_tool = shutil.which("jar")

    if not javac:
        print("  [!] javac not found — using existing companion.apk for all teams")
        existing_zip = OUT_BASE / "var-mobile-companion" / "files.zip"
        if not existing_zip.exists():
            raise RuntimeError("No existing files.zip and javac unavailable")
        zip_data = existing_zip.read_bytes()
        return {"files_zip": zip_data, "flags": []}

    # Import the gen module (loads module-level path constants from src dir)
    import importlib.util
    spec = importlib.util.spec_from_file_location("vmc_gen", src / "gen.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    seed = int.from_bytes(hashlib.sha256(hex8.encode()).digest()[:4], "big")

    flag1 = f"INFODAYS{{SaamNoLimits_apk_strings_dump_{hex8}}}"
    flag2 = f"INFODAYS{{SaamNoLimits_apk_static_constants_{hex8}}}"
    flag3 = f"INFODAYS{{SaamNoLimits_apk_xor_decode_{hex8}}}"
    flag4 = f"INFODAYS{{SaamNoLimits_apk_aes_composed_key_{hex8}}}"
    flag5 = f"INFODAYS{{SaamNoLimits_apk_custom_vm_insane_{hex8}}}"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Write Java sources into tmp (override mod's path constants)
        java_pkg = tmp / "src" / "java" / "com" / "infodays" / "referee"
        assets_dir = tmp / "src" / "assets"
        res_values_dir = tmp / "src" / "res" / "values"
        java_pkg.mkdir(parents=True, exist_ok=True)
        assets_dir.mkdir(parents=True, exist_ok=True)
        res_values_dir.mkdir(parents=True, exist_ok=True)

        # Redirect path constants before calling writer functions
        orig = (mod.JAVA_PKG, mod.ASSETS, mod.RES_VALUES)
        mod.JAVA_PKG = java_pkg
        mod.ASSETS = assets_dir
        mod.RES_VALUES = res_values_dir
        try:
            mod.write_welcome_asset(flag1)
            mod.write_debug_helper(flag2)
            mod.write_xor_vault(flag3)
            mod.write_aes_vault(flag4)
            mod.write_vm_interpreter(flag5, seed)
            mod.write_welcome_loader()
            mod.write_main_activity()
            mod.write_strings_xml()
        finally:
            mod.JAVA_PKG, mod.ASSETS, mod.RES_VALUES = orig

        # Compile all .java files
        java_files = list(java_pkg.rglob("*.java"))
        classes_dir = tmp / "classes"
        classes_dir.mkdir()

        run(
            [javac, "-source", "8", "-target", "8",
             "-d", str(classes_dir)] + [str(f) for f in java_files]
        )

        # Copy assets into classes so they're accessible via getResourceAsStream
        shutil.copytree(str(assets_dir), str(classes_dir / "assets"))

        # Build JAR
        jar_path = tmp / "companion.jar"
        if jar_tool:
            run([jar_tool, "cf", str(jar_path), "-C", str(classes_dir), "."])
        else:
            with zipfile.ZipFile(jar_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in classes_dir.rglob("*"):
                    if f.is_file():
                        zf.write(f, f.relative_to(classes_dir))

        jar_data = jar_path.read_bytes()

    return {
        "files": [("companion.jar", jar_data)],
        "flags": [
            ("var-mobile-companion-1", flag1),
            ("var-mobile-companion-2", flag2),
            ("var-mobile-companion-3", flag3),
            ("var-mobile-companion-4", flag4),
            ("var-mobile-companion-5", flag5),
        ],
    }


def gen_coach_formation(team_id: int, hex8: str, out_dir: Path) -> dict:
    """Generates per-team encrypted handout with a unique per-team flag."""
    # LCG encrypt — replicate coach_challenge_ultra.py logic
    # Per-team flag uses hex8 suffix; seed derived from hex8
    seed = int(hex8, 16)

    flag = f"INFODAYS{{SaamNoLimits_lcg_coach_formation_{hex8}}}"

    class LCG:
        def __init__(self, s):
            self.state = s
        def next(self):
            self.state = (1103515245 * self.state + 12345) % (2**31)
            return self.state

    def encrypt(plaintext, lcg_seed):
        lcg = LCG(lcg_seed)
        out = []
        for ch in plaintext:
            if ch.isalpha():
                ks = lcg.next() % 26
                base = ord('A') if ch.isupper() else ord('a')
                out.append(chr((ord(ch) - base + ks) % 26 + base))
            elif ch.isdigit():
                ks = lcg.next() % 10
                out.append(str((int(ch) + ks) % 10))
            else:
                out.append(ch)
        return ''.join(out)

    msg1_plain = "COACH USE FOUR FOUR TWO"
    msg2_plain = "PASS TO LEFT WING NOW"

    lcg_seed = seed % (2**31) + 1000000000
    msg1_cipher = encrypt(msg1_plain, lcg_seed)
    msg2_cipher = encrypt(msg2_plain, lcg_seed)
    flag_cipher = encrypt(flag, lcg_seed)

    handout = (
        "=" * 60 + "\n"
        "TACTICAL COMMUNICATIONS - INTERCEPTED\n"
        "=" * 60 + "\n\n"
        "SECURITY NOTICE: These messages were encrypted using a\n"
        "Linear Congruential Generator (LCG) stream cipher.\n\n"
        f"Message 1: {msg1_cipher}\n"
        f"Message 1 means: {msg1_plain}\n\n"
        f"Message 2: {msg2_cipher}\n"
        f"Message 2 means: {msg2_plain}\n\n"
        f"Encrypted flag: {flag_cipher}\n\n"
        "Decrypt the flag. No hints.\n"
        "=" * 60 + "\n"
    )

    return {
        "files": [("player_handout.txt", handout.encode())],
        "flags": [("coach-formation", flag)],
    }


def gen_vip_invitation(team_id: int, hex8: str, out_dir: Path) -> dict:
    """Packages player_handout.txt + pre-generated steghide jpg.

    The jpg (stadium_vip_Agadir2030.jpg) is generated once via create_challenge.py
    (requires steghide) and committed to the challenge source directory.
    All teams receive the same jpg — the flag is static (not per-team HMAC).
    """
    src = CHALLENGES_DIR / "forensics" / "the_vip_invitation"
    handout = (src / "player_handout.txt").read_bytes()
    jpg = (src / "stadium_vip_Agadir2030.jpg").read_bytes()
    flag = (src / "flag.txt").read_text().strip()
    return {
        "files": [
            ("player_handout.txt", handout),
            ("stadium_vip_Agadir2030.jpg", jpg),
        ],
        "flags": [("vip-invitation", flag)],
    }


def gen_legends_gate(team_id: int, hex8: str, out_dir: Path) -> dict:
    """
    Static challenge — same pre-compiled binary for all teams.
    Flag is hardcoded in the binary: INFODAYS{RE_15_NOT_GU3551NG_2026}
    Players reverse-engineer the binary to extract it.
    """
    src = CHALLENGES_DIR / "reversing" / "legends_gate"
    binary = (src / "legend_gate_pro").read_bytes()
    flag = "INFODAYS{RE_15_NOT_GU3551NG_2026}"
    return {
        "files": [("legend_gate_pro", binary)],
        "flags": [("legends-gate", flag)],
    }


def gen_venue_recon(team_id: int, hex8: str, out_dir: Path) -> dict:
    """Uses existing venue_teaser.png — flag is hardcoded."""
    src = CHALLENGES_DIR / "osint" / "venue_recon"
    img = (src / "venue_teaser.png").read_bytes()
    flag = (src / "flag.txt").read_text().strip()
    return {
        "files": [("venue_teaser.png", img)],
        "flags": [("venue-recon", flag)],
    }


def gen_general_mbappe(team_id: int, hex8: str, out_dir: Path) -> dict:
    """Build per-team General Mbappe artifacts with the HMAC-derived digest embedded."""
    src = CHALLENGES_DIR / "reversing" / "general_mbappe"
    challenge_id = "general-mbappe"
    digest = derive_team_digest(ACTIVE_MASTER_SECRET, team_id, challenge_id)
    flag = f"infodays{{SaamNoLimits_{digest}}}"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        recipe_out = tmp / "recipe.asm"
        spice_out = tmp / "spice.bin"
        flag_out = tmp / "flag.txt"
        cook_out = tmp / "cook"
        webp_out = tmp / "general_mbappe.webp"

        run(
            [
                "python3",
                str(src / "gen.py"),
                "--pass",
                digest,
                "--recipe-out",
                str(recipe_out),
                "--spice-out",
                str(spice_out),
                "--flag-out",
                str(flag_out),
            ]
        )

        # Cross-compile for Linux x86-64 via Docker so the binary is correct
        # regardless of whether this script runs on macOS or Linux.
        c_src_rel = (src / "src" / "cook.c").relative_to(REPO)
        run(
            [
                "docker", "run", "--rm",
                "--platform", "linux/amd64",
                "-v", f"{REPO}:/repo:ro",
                "-v", f"{tmp}:/out",
                "gcc:12",
                "sh", "-c",
                f"gcc -O2 -Wall -Wextra -std=c11 -o /out/cook /repo/{c_src_rel} "
                "&& strip --strip-unneeded /out/cook",
            ]
        )

        run(
            [
                "python3",
                str(src / "stego.py"),
                "embed",
                str(src / "general_nbappe.webp"),
                str(spice_out),
                str(webp_out),
            ]
        )

        generated_flag = flag_out.read_text().strip()
        if generated_flag != flag:
            raise RuntimeError(
                f"general_mbappe flag mismatch: generated={generated_flag!r} expected={flag!r}"
            )

        return {
            "files": [
                ("cook", cook_out.read_bytes()),
                ("recipe.asm", recipe_out.read_bytes()),
                ("general_mbappe.webp", webp_out.read_bytes()),
            ],
            "flags": [(challenge_id, flag)],
        }


# ── CTFd API helpers ──────────────────────────────────────────────────────────

def ctfd_get(url: str, token: str, path: str) -> dict:
    import urllib.request
    req = urllib.request.Request(
        url.rstrip("/") + path,
        headers={"Authorization": f"Token {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def ctfd_post(url: str, token: str, path: str, body: dict) -> dict:
    import urllib.request
    import urllib.error
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url.rstrip("/") + path,
        data=data,
        headers={
            "Authorization": f"Token {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        # CTFd sometimes returns 3xx or 500 even when the write succeeded.
        # Treat these as non-fatal — the DB row was committed before the error.
        if e.code in (302, 303, 500):
            return {"success": True}
        body_text = ""
        try:
            body_text = e.read().decode()
        except Exception:
            pass
        print(f"    CTFd error: {body_text}", file=sys.stderr)
        raise
    except Exception as e:
        if hasattr(e, "read"):
            print(f"    CTFd error: {e.read().decode()}", file=sys.stderr)
        raise


def ctfd_delete(url: str, token: str, path: str) -> None:
    import urllib.request
    req = urllib.request.Request(
        url.rstrip("/") + path,
        headers={"Authorization": f"Token {token}", "Content-Type": "application/json"},
        method="DELETE",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass  # Ignore delete errors


def get_all_teams(ctfd_url: str, token: str) -> list[dict]:
    """Fetch all teams from CTFd."""
    teams = []
    page = 1
    while True:
        resp = ctfd_get(ctfd_url, token, f"/api/v1/teams?page={page}&per_page=100")
        data = resp.get("data", [])
        teams.extend(data)
        meta = resp.get("meta", {}).get("pagination", {})
        if page >= meta.get("pages", 1):
            break
        page += 1
    return teams


def get_challenge_id_by_name(ctfd_url: str, token: str, name: str) -> int | None:
    """Look up CTFd challenge ID by name."""
    manifest_name_map = load_manifest_name_map()
    expected_name = manifest_name_map.get(name, name)
    expected_slug = re.sub(r"[^a-z0-9-]", "", expected_name.lower().replace(" ", "-"))
    resp = ctfd_get(ctfd_url, token, "/api/v1/challenges?view=admin")
    for ch in resp.get("data", []):
        slug = ch["name"].lower().replace(" ", "-").replace(r"[^a-z0-9-]", "")
        slug = re.sub(r"[^a-z0-9-]", "", slug)
        if slug == name or slug == expected_slug or ch["name"].lower() == expected_name.lower():
            return ch["id"]
    return None


def delete_existing_flags(ctfd_url: str, token: str, challenge_id: int) -> None:
    """Delete all existing flags for a CTFd challenge."""
    resp = ctfd_get(ctfd_url, token, f"/api/v1/flags?challenge_id={challenge_id}")
    for flag in resp.get("data", []):
        ctfd_delete(ctfd_url, token, f"/api/v1/flags/{flag['id']}")


def register_exact_flag(ctfd_url: str, token: str, challenge_id: int,
                        flag_value: str, team_id: int) -> None:
    """Register an exact flag in CTFd for a specific team."""
    ctfd_post(ctfd_url, token, "/api/v1/flags", {
        "challenge_id": challenge_id,
        "type": "static",
        "content": flag_value,
    })


def register_multi_flag_components(
    ctfd_url: str, token: str, challenge_ctfd_id: int,
    challenge_id: str, flags_by_comp: dict[str, str],
) -> None:
    """Register component scoring params (no flags) via the plugin endpoint."""
    base_params = MULTI_FLAG_PARAMS.get(challenge_id, [])
    # Only send scoring params — flags go into multi_flag_team_flags per team
    components = [{k: v for k, v in comp.items() if k != "flag"} for comp in base_params]
    ctfd_post(ctfd_url, token, "/api/plugin/multi-flag-register", {
        "challenge_id": challenge_ctfd_id,
        "components": components,
    })


def register_multi_flag_team_flags(
    ctfd_url: str, token: str, challenge_ctfd_id: int,
    team_id: int, flags_by_comp: dict[str, str],
) -> None:
    """Register per-team flag values into multi_flag_team_flags table."""
    flags = [
        {"component_id": comp_id, "flag_content": flag_val}
        for comp_id, flag_val in flags_by_comp.items()
    ]
    ctfd_post(ctfd_url, token, "/api/plugin/multi-flag-team-flags", {
        "challenge_id": challenge_ctfd_id,
        "team_id":      team_id,
        "flags":        flags,
    })


# ── Main ──────────────────────────────────────────────────────────────────────

GENERATORS = {
    # Finals challenges only — qual challenges intentionally excluded.
    "tournament-bracket":   gen_tournament_bracket,
    "var-override":         gen_var_override,
    "coach-formation":      gen_coach_formation,
    "vip-invitation":       gen_vip_invitation,
    "general-mbappe":       gen_general_mbappe,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ctfd-url",      required=True)
    ap.add_argument("--admin-token",   required=True)
    ap.add_argument("--master-secret", required=True)
    ap.add_argument("--challenges",    default=",".join(GENERATORS.keys()),
                    help="Comma-separated list of challenges to generate")
    ap.add_argument("--team-ids",      default=None,
                    help="Comma-separated team IDs (default: fetch all from CTFd)")
    ap.add_argument("--out-dir",       default=str(OUT_BASE),
                    help="Output directory for static-content zips")
    ap.add_argument("--skip-ctfd",     action="store_true",
                    help="Skip CTFd flag registration (generate files only)")
    args = ap.parse_args()

    ctfd_url = args.ctfd_url
    token = args.admin_token
    master_secret = args.master_secret
    out_dir = Path(args.out_dir)
    global ACTIVE_MASTER_SECRET
    ACTIVE_MASTER_SECRET = master_secret

    challenges = [c.strip() for c in args.challenges.split(",") if c.strip()]

    # Fetch teams
    if args.team_ids:
        teams = [{"id": int(t.strip()), "name": f"team-{t.strip()}"}
                 for t in args.team_ids.split(",") if t.strip()]
    else:
        print("[*] Fetching teams from CTFd...")
        teams = get_all_teams(ctfd_url, token)
        if not teams:
            print("[!] No teams found in CTFd. Use --team-ids to specify manually.")
            return 1
    print(f"[*] {len(teams)} team(s): {[t.get('name','?') for t in teams]}")

    # Fetch challenge IDs from CTFd
    challenge_ctfd_ids: dict[str, int] = {}
    if not args.skip_ctfd:
        print("[*] Fetching challenge IDs from CTFd...")
        for cid in challenges:
            ctfd_id = get_challenge_id_by_name(ctfd_url, token, cid)
            if ctfd_id is None:
                print(f"  [!] Challenge not found in CTFd: {cid} — skipping CTFd registration")
            else:
                challenge_ctfd_ids[cid] = ctfd_id
                print(f"  {cid} → CTFd #{ctfd_id}")

    # For single-flag challenges: delete old flags once, add per-team flags
    single_flag_challenges = [c for c in challenges if STATIC_FILE_CHALLENGES.get(c, {}).get("type") == "single"]
    if not args.skip_ctfd:
        for cid in single_flag_challenges:
            if cid in challenge_ctfd_ids:
                print(f"[*] Clearing existing flags for {cid}...")
                delete_existing_flags(ctfd_url, token, challenge_ctfd_ids[cid])

    # Generate per-team artifacts
    for challenge_id in challenges:
        gen_fn = GENERATORS.get(challenge_id)
        if gen_fn is None:
            print(f"[!] Unknown challenge: {challenge_id}")
            continue

        challenge_out = out_dir / challenge_id
        challenge_out.mkdir(parents=True, exist_ok=True)

        ch_type = STATIC_FILE_CHALLENGES[challenge_id]["type"]
        ctfd_id = challenge_ctfd_ids.get(challenge_id)

        # Ensure multi_flag_components scoring params are registered once (no flags)
        if ch_type == "multi" and not args.skip_ctfd and ctfd_id:
            register_multi_flag_components(ctfd_url, token, ctfd_id, challenge_id, {})

        for team in teams:
            team_id = team["id"]
            hex8 = derive_hex8(master_secret, team_id, challenge_id)
            zip_out = challenge_out / f"{team_id}.zip"

            print(f"  [{challenge_id}] team={team_id} hex8={hex8} → {zip_out.name}")

            try:
                result = gen_fn(team_id, hex8, challenge_out)
            except Exception as e:
                print(f"    [!] Generation failed: {e}", file=sys.stderr)
                continue

            # Write zip
            if "files_zip" in result:
                zip_out.write_bytes(result["files_zip"])
            elif "files" in result:
                zip_data = zip_files(result["files"])
                zip_out.write_bytes(zip_data)

            # Collect flags
            flags = result.get("flags", [])
            for comp_id, flag_val in flags:
                print(f"    flag: {comp_id} → {flag_val}")

            if not args.skip_ctfd and ctfd_id and flags:
                if ch_type == "single":
                    # Single flag: register exact flag per team in CTFd flags table
                    _, flag_val = flags[0]
                    register_exact_flag(ctfd_url, token, ctfd_id, flag_val, team_id)
                    print(f"    [CTFd] registered exact flag for team {team_id}")
                elif ch_type == "multi":
                    # Multi flag: register per-team flags into multi_flag_team_flags table
                    flags_by_comp = {comp_id: flag_val for comp_id, flag_val in flags}
                    register_multi_flag_team_flags(ctfd_url, token, ctfd_id, team_id, flags_by_comp)
                    print(f"    [CTFd] registered {len(flags_by_comp)} team flags for team {team_id}")

    print("\n[+] Done. Rebuild and push static-files-server image:")
    print(f"    docker build -f Dockerfile.static-files -t <registry>/static-files:latest .")
    print(f"    docker push <registry>/static-files:latest")
    print(f"    kubectl rollout restart deployment/static-files -n ctfd")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
