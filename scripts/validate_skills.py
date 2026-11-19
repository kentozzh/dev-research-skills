"""Development-only structural/integrity validation; PyYAML is never bundled."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from urllib.parse import unquote, urlsplit

import yaml

SKILLS = ("tool-finding", "skill-finding", "paper-finding")
FORBIDDEN = {"__pycache__", "cache", ".runs", ".git", ".venv", ".aws", "credentials", ".env"}
TOKEN = re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----)")
DEVPATH = re.compile(r"(?:[A-Za-z]:[\\/](?:Users|project)[\\/]|/(?:Users|home)/[^\s/]+/)", re.I)
LINK = re.compile(r"!?\[[^\]]*\]\(\s*(<[^>]+>|[^\s)]+)(?:\s+[^)]*)?\)")
REFERENCE = re.compile(r"^ {0,3}\[([^\]^]+)\]:\s*(<[^>]+>|\S+)", re.M)


def _safe_relative(value):
    return (isinstance(value, str) and bool(value) and "\\" not in value and
            not PurePosixPath(value).is_absolute() and not PureWindowsPath(value).drive and
            all(part not in {"..", ".", ""} for part in value.split("/")))


def validate_bundle(bundle_dir: Path) -> list[str]:
    bundle = Path(bundle_dir).resolve()
    errors, files = [], {}
    try:
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ["manifest.json missing or invalid"]
    if not isinstance(manifest, dict):
        return ["manifest must be an object"]
    if bundle.name not in SKILLS or manifest.get("skill") != bundle.name:
        errors.append("skill name must match bundle directory")
    hashes = manifest.get("files")
    if not isinstance(hashes, dict):
        hashes = {}
        errors.append("manifest files must be an object")
    for name, digest in hashes.items():
        if not _safe_relative(name) or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            errors.append(f"unsafe manifest path/hash: {name}")
    secret_values = [value for key in ("GITHUB_TOKEN", "OPENALEX_API_KEY", "SEMANTIC_SCHOLAR_API_KEY")
                     if len(value := os.environ.get(key, "")) >= 8]
    for path in sorted(bundle.rglob("*")):
        relative = path.relative_to(bundle).as_posix()
        if path.is_symlink():
            errors.append(f"symlink forbidden: {relative}")
            continue
        if any(part in FORBIDDEN or part.startswith(".env") for part in path.relative_to(bundle).parts) or path.suffix in {".pyc", ".pyo"}:
            errors.append(f"runtime/private artifact forbidden: {relative}")
        if not path.is_file():
            continue
        data = path.read_bytes()
        if relative != "manifest.json":
            files[relative] = hashlib.sha256(data).hexdigest()
        try:
            text = data.decode("utf-8")
        except UnicodeError:
            errors.append(f"unexpected binary/non-UTF8 content: {relative}")
            continue
        if TOKEN.search(text) or any(value in text for value in secret_values):
            errors.append(f"credential content forbidden: {relative}")
        if DEVPATH.search(text.replace("\\\\", "\\").replace("\\/", "/")):
            errors.append(f"developer path forbidden: {relative}")
        if path.suffix == ".md":
            targets = [match.group(1) for match in LINK.finditer(text)]
            targets.extend(match.group(2) for match in REFERENCE.finditer(text))
            for raw_target in targets:
                target = unquote(raw_target.strip("<>"))
                try:
                    parsed = urlsplit(target)
                except ValueError:
                    errors.append(f"malformed reference in {relative}: {target}")
                    continue
                if parsed.username is not None or parsed.password is not None:
                    errors.append(f"credential reference forbidden in {relative}")
                    continue
                if parsed.scheme in {"https", "http", "mailto"}:
                    continue
                if parsed.scheme or PureWindowsPath(target).drive or "\\" in target or target.startswith(("/", "//")):
                    errors.append(f"unsafe reference in {relative}: {target}")
                    continue
                if not parsed.path:
                    continue
                linked = (path.parent / parsed.path).resolve()
                if not linked.is_relative_to(bundle):
                    errors.append(f"reference escapes bundle in {relative}: {target}")
                elif not linked.exists():
                    errors.append(f"missing reference in {relative}: {target}")
    if set(files) != set(hashes):
        errors.append("manifest file list differs from bundle files")
    for name, digest in files.items():
        if name in hashes and digest != hashes[name]:
            errors.append(f"hash mismatch: {name}")
    for required in ("SKILL.md", "scripts/finder.py", "scripts/finder_core/__main__.py",
                     "scripts/finder_core/resources/policy-v1.json"):
        if required not in files:
            errors.append(f"required file missing: {required}")
    try:
        skill = (bundle / "SKILL.md").read_text(encoding="utf-8")
        sections = skill.split("---", 2)
        front = yaml.safe_load(sections[1]) if skill.startswith("---\n") and len(sections) == 3 else None
        if not isinstance(front, dict) or front.get("name") != bundle.name:
            errors.append("SKILL frontmatter name must match bundle directory")
        if not isinstance(front, dict) or not isinstance(front.get("description"), str) or not front["description"].strip():
            errors.append("SKILL description must be nonempty")
    except (OSError, ValueError, yaml.YAMLError):
        errors.append("SKILL frontmatter missing or invalid")
    try:
        from .build_skills import core_versions
    except ImportError:
        from build_skills import core_versions
    try:
        versions = core_versions(bundle / "scripts/finder_core")
        policy = json.loads((bundle / "scripts/finder_core/resources/policy-v1.json").read_text(encoding="utf-8"))
        for key, value in versions.items():
            if manifest.get(key) != value:
                errors.append(f"manifest {key} differs from bundled core")
        if policy.get("policy_version") != versions["policy_version"] or policy.get("schema_version") != versions["schema_version"]:
            errors.append("policy version differs from bundled core")
    except (OSError, ValueError, KeyError, SyntaxError):
        errors.append("bundled versions/resources invalid")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    paths = [args.path] if (args.path / "SKILL.md").exists() else [args.path / name for name in SKILLS]
    results = {str(path): validate_bundle(path) for path in paths}
    if len(paths) == 3 and not any(results.values()):
        manifests = [json.loads((path / "manifest.json").read_text(encoding="utf-8")) for path in paths]
        common = [{key: value for key, value in manifest["files"].items() if key.startswith("scripts/")} for manifest in manifests]
        if not common[0] == common[1] == common[2]:
            results["shared_core"] = ["public launcher/core/resources differ between bundles"]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 1 if any(results.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
