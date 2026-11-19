"""Build and validate the portable Codex research plugin."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import stat
import sys
from urllib.parse import unquote, urlsplit

import yaml

if __package__:
    from .build_skills import SKILLS, build_skills
    from .validate_skills import DEVPATH, LINK, REFERENCE, TOKEN, validate_bundle
else:
    from build_skills import SKILLS, build_skills
    from validate_skills import DEVPATH, LINK, REFERENCE, TOKEN, validate_bundle

PLUGIN = "dev-research-skill"
ROUTER = "using-dev-research"
SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
PLUGIN_SOURCE = Path("packaging/codex/plugin.json")
ROUTER_FILES = ("SKILL.md", "references/routing.md")
BUILD_MANIFEST = ".build-manifest.json"
BUILD_IDENTITY = {"generator": "scripts/build_plugin.py", "name": PLUGIN}


def _filesystem_path(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    if sys.platform != "win32" or path.drive.startswith("\\\\?\\"):
        return path
    # Nested staging must work without the Windows long-path registry setting.
    text = str(path)
    if text.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + text[2:])
    return Path("\\\\?\\" + text)


def _is_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _require_local(root: Path, relative: Path) -> Path:
    path = root
    for part in relative.parts:
        path /= part
        if _is_link(path):
            raise ValueError(f"linked path forbidden: {relative.as_posix()}")
    return path


def _regular_files(root: Path):
    for path in sorted(root.iterdir()):
        if _is_link(path):
            raise ValueError(f"linked path forbidden: {path}")
        if path.is_dir():
            yield from _regular_files(path)
        elif path.is_file():
            yield path
        else:
            raise ValueError(f"unexpected file type: {path}")


def _read_object(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must be a JSON object")
    return data


def _inventory(root: Path, files) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files if path != root / BUILD_MANIFEST}


def _validate_manifest(root: Path) -> list[str]:
    manifest = _read_object(root / "plugin.json")
    errors = []
    if set(manifest) != {"$schema", "name", "version", "description"}:
        errors.append("plugin.json must contain the portable identity, version and description")
    if manifest.get("$schema") != SCHEMA or manifest.get("name") != PLUGIN:
        errors.append("plugin.json has the wrong portable schema or plugin name")
    version = manifest.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){2}", version):
        errors.append("plugin.json version must be a major.minor.patch release")
    description = manifest.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append("plugin.json description must be nonempty")
    elif _private_content(description):
        errors.append("private content forbidden in plugin.json")
    return errors


def _private_content(text: str) -> bool:
    values = (os.environ.get(key, "") for key in ("GITHUB_TOKEN", "OPENALEX_API_KEY", "SEMANTIC_SCHOLAR_API_KEY"))
    return bool(TOKEN.search(text) or DEVPATH.search(text.replace("\\\\", "\\").replace("\\/", "/"))
                or any(len(value) >= 8 and value in text for value in values))


def _router_reference_error(path: Path, router: Path, raw: str) -> str | None:
    target = unquote(raw.strip("<>"))
    try:
        parsed = urlsplit(target)
    except ValueError:
        return f"malformed reference: {target}"
    if parsed.username is not None or parsed.password is not None:
        return "credential reference forbidden"
    if parsed.scheme in {"https", "http", "mailto"}:
        return None
    if parsed.scheme or PureWindowsPath(target).drive or "\\" in target or target.startswith("/"):
        return f"unsafe reference: {target}"
    if parsed.path:
        linked = (path.parent / parsed.path).resolve()
        if not linked.is_relative_to(router):
            return f"reference escapes router: {target}"
        if not linked.is_file():
            return f"missing reference: {target}"
    return None


def _validate_router(router: Path) -> list[str]:
    errors = []
    if {path.relative_to(router).as_posix() for path in _regular_files(router)} != set(ROUTER_FILES):
        errors.append("router must contain only SKILL.md and references/routing.md")
    for relative in ROUTER_FILES:
        path = router / relative
        if not path.is_file():
            errors.append(f"router is missing {relative}")
            continue
        text = path.read_text(encoding="utf-8")
        if _private_content(text):
            errors.append(f"{relative}: private content forbidden")
        if relative == "SKILL.md":
            sections = text.split("---", 2)
            front = yaml.safe_load(sections[1]) if text.startswith("---\n") and len(sections) == 3 else None
            if not isinstance(front, dict) or front.get("name") != ROUTER:
                errors.append("router SKILL frontmatter name must match its directory")
            if not isinstance(front, dict) or not isinstance(front.get("description"), str) or not front["description"].strip():
                errors.append("router SKILL frontmatter description must be nonempty")
        targets = [match.group(1) for match in LINK.finditer(text)]
        targets.extend(match.group(2) for match in REFERENCE.finditer(text))
        for raw in targets:
            error = _router_reference_error(path, router, raw)
            if error:
                errors.append(f"{relative}: {error}")
    return errors


def validate_plugin(plugin_root: Path) -> list[str]:
    """Validate a built plugin in place, including all bundled skill files."""
    root = _filesystem_path(Path(plugin_root))
    errors = []
    try:
        if _is_link(root):
            return ["plugin root cannot be a linked directory"]
        files = list(_regular_files(root))
        if {path.name for path in root.iterdir()} != {"plugin.json", BUILD_MANIFEST, "skills"}:
            errors.append("plugin root must contain plugin.json, its build manifest and skills/")
        errors.extend(_validate_manifest(root))
        identity = _read_object(root / BUILD_MANIFEST)
        if identity != {**BUILD_IDENTITY, "files": _inventory(root, files)}:
            errors.append("plugin build manifest differs from packaged files")
        skills = root / "skills"
        if {path.name for path in skills.iterdir() if path.is_dir()} != {*SKILLS, ROUTER} or any(
                not path.is_dir() for path in skills.iterdir()):
            errors.append("plugin must contain exactly the four named skill directories")
        for name in SKILLS:
            errors.extend(f"{name}: {error}" for error in validate_bundle(skills / name))
        errors.extend(_validate_router(skills / ROUTER))
    except (OSError, ValueError, AttributeError, yaml.YAMLError) as exc:
        errors.append(f"invalid plugin: {exc}")
    return errors


def _check_target(target: Path) -> None:
    if _is_link(target):
        raise ValueError("plugin output cannot be a linked path")
    if target.exists() and validate_plugin(target):
        raise ValueError(f"refusing to replace unmanaged or modified output: {target}")


def _stage_plugin(source: Path, staged: Path) -> None:
    for relative in ("finder_core", *(f"skills/{name}" for name in SKILLS)):
        list(_regular_files(_require_local(source, Path(relative))))
    plugin_manifest = _require_local(source, PLUGIN_SOURCE)
    build_skills(source, staged / "skills")
    shutil.copyfile(plugin_manifest, staged / "plugin.json")
    for relative in ROUTER_FILES:
        source_file = _require_local(source, Path("skills") / ROUTER / relative)
        target = staged / "skills" / ROUTER / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_file, target)
    inventory = _inventory(staged, _regular_files(staged))
    (staged / BUILD_MANIFEST).write_text(
        json.dumps({**BUILD_IDENTITY, "files": inventory}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    errors = validate_plugin(staged)
    if errors:
        raise ValueError("invalid plugin:\n" + "\n".join(errors))


def build_plugin(source_root: Path, output_root: Path) -> Path:
    """Build and publish the plugin after its staged files pass validation."""
    source, output = Path(source_root).resolve(), Path(output_root).resolve()
    if source.is_relative_to(output) or any(
            output.is_relative_to(source / part) for part in ("finder_core", "skills", "packaging")):
        raise ValueError("output overlaps maintained sources")
    destination = output / PLUGIN
    source, output = _filesystem_path(source), _filesystem_path(output)
    target = output / PLUGIN
    output.mkdir(parents=True, exist_ok=True)
    staging = output / f".{PLUGIN}-build"
    try:
        staging.mkdir()
    except FileExistsError:
        raise ValueError(f"build already in progress or interrupted: {staging}") from None
    staged = staging / PLUGIN
    backup = staging / "previous"
    published = False
    try:
        _check_target(target)
        _stage_plugin(source, staged)
        if os.path.lexists(target):
            target.rename(backup)
        try:
            # Staging may outlast a user edit. Validate the directory we actually moved.
            _check_target(backup)
            if os.path.lexists(target):
                raise FileExistsError(f"plugin output reappeared during publication: {target}")
            staged.rename(target)
        except (OSError, ValueError):
            if os.path.lexists(backup) and not os.path.lexists(target):
                backup.rename(target)
            raise
        published = True
    finally:
        # Hold on to the previous release if the filesystem prevents rollback.
        if published or not os.path.lexists(backup):
            shutil.rmtree(staging)
    return destination


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--output", type=Path, default=Path("dist"))
    action.add_argument("--check", type=Path)
    args = parser.parse_args(argv)
    if args.check is not None:
        errors = validate_plugin(args.check)
        if errors:
            print("\n".join(errors), file=sys.stderr)
            return 1
        print(f"Valid plugin: {args.check}")
        return 0
    try:
        print(build_plugin(Path(__file__).resolve().parents[1], args.output))
    except (OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
