"""Challenge manifest loader from YAML files."""

import yaml
import pathlib


def load_manifests(manifest_dir: str = "challenges/manifests") -> list:
    """Load all challenge manifests from YAML files.

    Returns a list of raw manifest dicts (one per YAML file).
    Bundle manifests (multi-flag) are returned as-is with a 'flags' list.
    Use load_flag_entries() to get the flat per-CTFd-challenge view.
    """
    manifests = []
    manifest_path = pathlib.Path(manifest_dir)

    if not manifest_path.exists():
        return []

    for yaml_file in sorted(manifest_path.glob("*.yaml")):
        if yaml_file.name == "schema.yaml":
            continue

        with open(yaml_file) as f:
            manifest = yaml.safe_load(f)
            if manifest:
                if "memory_limit" not in manifest:
                    manifest["memory_limit"] = "128Mi"
                manifests.append(manifest)

    return manifests


def load_flag_entries(manifest_dir: str = "challenges/manifests") -> list:
    """Return a flat list of all CTFd challenge / flag entries.

    Single-flag manifests yield one entry (the manifest itself, with 'id'
    and 'name' at the top level).

    Bundle manifests (those with a top-level 'flags' list) are expanded:
    each item in 'flags' becomes one entry, inheriting the parent's
    'image', 'port', 'type', and 'memory_limit' fields.

    Every returned entry is guaranteed to have:
        id       — unique challenge/flag identifier used as CTFd 'data' field
        name     — CTFd challenge display name
        category — challenge category
        type     — http | tcp | static
    """
    entries = []
    for manifest in load_manifests(manifest_dir):
        if manifest.get("lab") is True and "flags" in manifest:
            # Lab manifest — kept as a single entry. Maps to ONE CTFd challenge
            # with multiple flag rows; import_flags.py handles the multi-flag case.
            entries.append(manifest)
        elif "flags" in manifest:
            # Legacy bundle manifest — expand each flag entry into its own
            # CTFd challenge (old behavior, kept for backward compatibility).
            for flag in manifest["flags"]:
                entry = {
                    "image": manifest.get("image"),
                    "port": manifest.get("port"),
                    "type": manifest.get("type"),
                    "memory_limit": manifest.get("memory_limit", "128Mi"),
                    "extra_ports": manifest.get("extra_ports", []),
                    **flag,
                    "_parent_id": manifest["id"],
                }
                entries.append(entry)
        else:
            entries.append(manifest)
    return entries
