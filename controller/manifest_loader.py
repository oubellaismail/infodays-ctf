"""Challenge manifest loader from YAML files."""

import yaml
import pathlib


def load_manifests(manifest_dir: str = "challenges/manifests") -> list:
    """Load all challenge manifests from YAML files.

    Args:
        manifest_dir: Directory containing manifest YAML files

    Returns:
        List of manifest dictionaries, each with keys:
        - id: Challenge identifier
        - name: Human-readable name
        - category: web, pwn, misc, crypto, forensics, reversing, osint
        - image: DOCR image reference
        - port: Container port
        - type: http or tcp
        - points: Challenge point value
        - memory_limit: Optional memory limit override (default: 128Mi)
    """
    manifests = []
    manifest_path = pathlib.Path(manifest_dir)

    if not manifest_path.exists():
        return []

    # Load all YAML files except schema.yaml
    for yaml_file in sorted(manifest_path.glob("*.yaml")):
        if yaml_file.name == "schema.yaml":
            continue

        with open(yaml_file) as f:
            manifest = yaml.safe_load(f)
            if manifest:
                # Set default memory_limit if not specified
                if "memory_limit" not in manifest:
                    manifest["memory_limit"] = "128Mi"
                manifests.append(manifest)

    return manifests
