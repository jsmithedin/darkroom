"""Build the zips for installs that cannot use the marketplace.

    python scripts/build_skill_zips.py [outdir]    # default: dist/skills

Writes one zip per skill (for claude.ai and Desktop "Upload a skill"; the skill folder is
the top level of the archive) and darkroom-skills-<version>.zip (the whole plugin).
"""

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "darkroom-skills"


def add_tree(archive: zipfile.ZipFile, folder: Path, base: Path) -> None:
    for path in sorted(folder.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            archive.write(path, path.relative_to(base).as_posix())


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "skills"
    out.mkdir(parents=True, exist_ok=True)
    version = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())["version"]
    for skill in sorted((PLUGIN / "skills").iterdir()):
        if (skill / "SKILL.md").is_file():
            with zipfile.ZipFile(out / f"{skill.name}.zip", "w", zipfile.ZIP_DEFLATED) as z:
                add_tree(z, skill, skill.parent)
    with zipfile.ZipFile(out / f"darkroom-skills-{version}.zip", "w", zipfile.ZIP_DEFLATED) as z:
        add_tree(z, PLUGIN, PLUGIN)
    for path in sorted(out.glob("*.zip")):
        print(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)


if __name__ == "__main__":
    main()
