"""Build a project-local Codex skills ZIP. Extract it at the target project root."""
import argparse
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

if __package__:
    from .build_plugin import PLUGIN, ROUTER, SKILLS, validate_plugin
else:
    from build_plugin import PLUGIN, ROUTER, SKILLS, validate_plugin


def build_archive(plugin: Path, output: Path) -> Path:
    """Include complete short-name workflows and explicit Codex namespace entries."""
    plugin = plugin.resolve()
    output = output.resolve()
    if output.suffix.lower() != ".zip" or output.is_relative_to(plugin):
        raise ValueError("choose a .zip destination outside the input plugin")
    errors = validate_plugin(plugin)
    if errors:
        raise ValueError("\n".join(errors))

    prefix = ".agents/skills"
    skills = plugin / "skills"
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as staging:
        archive = Path(staging) / "project.zip"
        with ZipFile(archive, "w") as bundle:
            for file in sorted(skills.rglob("*")):
                if file.is_file():
                    entry = f"{prefix}/{file.relative_to(skills).as_posix()}"
                    bundle.writestr(ZipInfo(entry), file.read_bytes(), ZIP_DEFLATED)
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
    parser.add_argument("--output", type=Path, default=Path("dist") / f"{PLUGIN}-project.zip")
    args = parser.parse_args()
    print(build_archive(args.plugin, args.output))
