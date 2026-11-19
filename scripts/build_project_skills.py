"""Build a project skills ZIP for a coding agent. Extract it at the project root."""
import argparse
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

if __package__:
    from .build_plugin import PLUGIN, ROUTER, SKILLS, validate_plugin
else:
    from build_plugin import PLUGIN, ROUTER, SKILLS, validate_plugin


PROJECT_ROOTS = {
    "codex": ".agents/skills",
    "claude-code": ".claude/skills",
    "cursor": ".cursor/skills",
    "kimi-code": ".kimi/skills",
    "opencode": ".opencode/skills",
    "pi": ".pi/skills",
    "qwen-code": ".qwen/skills",
    "deepseek-harness": ".dsh/skills",
}


def build_archive(plugin: Path, output: Path, host: str = "codex") -> Path:
    """Package all four workflows under the host's project discovery root."""
    if host not in PROJECT_ROOTS:
        raise ValueError(f"unknown project host: {host}")
    plugin = plugin.resolve()
    output = output.resolve()
    if output.suffix.lower() != ".zip" or output.is_relative_to(plugin):
        raise ValueError("choose a .zip destination outside the input plugin")
    errors = validate_plugin(plugin)
    if errors:
        raise ValueError("\n".join(errors))

    prefix = PROJECT_ROOTS[host]
    skills = plugin / "skills"
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as staging:
        archive = Path(staging) / "project.zip"
        with ZipFile(archive, "w") as bundle:
            license_file = Path(__file__).resolve().parents[1] / "LICENSE"
            bundle.writestr(ZipInfo(f"{prefix}/dev-research-skills-LICENSE.txt"),
                            license_file.read_bytes(), ZIP_DEFLATED)
            for file in sorted(skills.rglob("*")):
                if file.is_file():
                    entry = f"{prefix}/{file.relative_to(skills).as_posix()}"
                    bundle.writestr(ZipInfo(entry), file.read_bytes(), ZIP_DEFLATED)
            if host == "codex":
                for name in (ROUTER, *SKILLS):
                    alias = f"{prefix}/{PLUGIN}/{name}"
                    definition = (
                        f"---\nname: {PLUGIN}:{name}\n"
                        f"description: Explicit project entry for the {name} workflow.\n---\n\n"
                        f"Read and follow the [{name} skill](../../{name}/SKILL.md) for this request. "
                        "Resolve its scripts and references relative to that skill's directory.\n"
                    )
                    bundle.writestr(ZipInfo(f"{alias}/SKILL.md"), definition, ZIP_DEFLATED)
                    bundle.writestr(ZipInfo(f"{alias}/agents/openai.yaml"),
                                    "policy:\n  allow_implicit_invocation: false\n", ZIP_DEFLATED)
        archive.replace(output)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", type=Path, default=Path("dist") / PLUGIN,
                        help="validated output of scripts/build_plugin.py")
    parser.add_argument("--host", choices=PROJECT_ROOTS, default="codex")
    parser.add_argument("--output", type=Path, help="override the host-specific ZIP path")
    args = parser.parse_args()
    suffix = "project" if args.host == "codex" else args.host
    output = args.output or Path("dist") / f"{PLUGIN}-{suffix}.zip"
    print(build_archive(args.plugin, output, args.host))
