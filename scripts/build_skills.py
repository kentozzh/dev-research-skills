"""Build three self-contained skills from the single maintained public core."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

SKILLS = ("tool-finding", "skill-finding", "paper-finding")
LAUNCHER = '''"""Run only the core shipped inside this skill (Python 3.11+)."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from finder_core.__main__ import entrypoint

if __name__ == "__main__":
    raise SystemExit(entrypoint())
'''


def core_versions(core: Path) -> dict[str, str]:
    values = {}
    for node in ast.parse((core / "__init__.py").read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in {"__version__", "POLICY_VERSION", "SCHEMA_VERSION"}:
                values[node.targets[0].id] = ast.literal_eval(node.value)
    return {"core_version": values["__version__"], "policy_version": values["POLICY_VERSION"],
            "schema_version": values["SCHEMA_VERSION"]}


def _copy_public(source: Path, destination: Path, suffixes: set[str]):
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if any(part.startswith(".") or part in {"__pycache__", "cache"} for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError(f"symlink not allowed in authoring sources: {relative.as_posix()}")
        if path.is_file() and path.suffix in suffixes:
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)


def build_skills(source_root: Path, output_root: Path) -> list[Path]:
    source_root, output_root = Path(source_root).resolve(), Path(output_root).resolve()
    if output_root == source_root or output_root in source_root.parents or any(
            output_root == source_root / part or source_root / part in output_root.parents
            for part in ("finder_core", "skills")):
        raise ValueError("output overlaps maintained sources")
    for name in SKILLS:
        if not (source_root / "skills" / name / "SKILL.md").is_file():
            raise ValueError(f"missing authored skill: {name}")
    core = source_root / "finder_core"
    versions = core_versions(core)
    # Never delete an arbitrary pre-existing directory on rebuild.
    for name in SKILLS:
        target = output_root / name
        if target.is_symlink():
            raise ValueError("output bundle cannot be a symlink")
        if target.exists():
            try:
                prior = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raise ValueError(f"refusing to replace unmanaged output: {name}") from None
            if prior.get("skill") != name:
                raise ValueError(f"refusing to replace unmanaged output: {name}")
    output_root.mkdir(parents=True, exist_ok=True)
    try:
        from .validate_skills import validate_bundle
    except ImportError:
        from validate_skills import validate_bundle
    with tempfile.TemporaryDirectory(prefix=".finder-build-", dir=output_root) as temporary:
        staging = Path(temporary)
        for name in SKILLS:
            bundle = staging / name
            _copy_public(source_root / "skills" / name, bundle, {".md"})
            _copy_public(core, bundle / "scripts/finder_core", {".py", ".json", ".md"})
            (bundle / "scripts/finder.py").write_text(LAUNCHER, encoding="utf-8", newline="\n")
            files = {path.relative_to(bundle).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in sorted(bundle.rglob("*")) if path.is_file()}
            manifest = {"skill": name, **versions, "files": files}
            (bundle / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
            errors = validate_bundle(bundle)
            if errors:
                raise ValueError(f"invalid bundle {name}: " + "; ".join(errors))
        for name in SKILLS:
            target = output_root / name
            if target.exists():
                # Both paths were resolved and overlap/symlink checked above.
                shutil.rmtree(target)
            (staging / name).replace(target)
    return [output_root / name for name in SKILLS]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=Path("dist"))
    args = parser.parse_args(argv)
    try:
        bundles = build_skills(args.source, args.output)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, f"Build failed: {error}\n")
    for bundle in bundles:
        print(bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
