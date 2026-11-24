"""Keep the shared rules identical in every SKILL.md, and check each skill is well formed.

Skills must be self-contained (they are also uploaded one by one as zips), so the rules in
plugins/darkroom-skills/shared-rules.md are copied between marker comments in each skill.

    python scripts/sync_skill_rules.py          # rewrite the marked blocks
    python scripts/sync_skill_rules.py --check  # fail if anything is out of date or invalid
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "darkroom-skills"
START, END = "<!-- shared-rules:start -->", "<!-- shared-rules:end -->"
NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


def block() -> str:
    rules = (PLUGIN / "shared-rules.md").read_text().strip()
    return f"{START}\n{rules}\n{END}"


def problems(skill: Path, text: str) -> list[str]:
    found: list[str] = []
    front = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not front:
        return [f"{skill.name}: missing frontmatter"]
    fields = dict(
        line.split(":", 1) for line in front[1].splitlines() if ":" in line and line[0] != " "
    )
    name = fields.get("name", "").strip()
    description = fields.get("description", "").strip()
    if name != skill.name or not NAME.fullmatch(name):
        found.append(f"{skill.name}: name '{name}' must match the folder name")
    if len(description) < 40 or len(description) > 1024:
        found.append(f"{skill.name}: description must be 40 to 1024 characters")
    if text.count(START) != 1 or text.count(END) != 1:
        found.append(f"{skill.name}: needs exactly one shared-rules block")
    return found


def main() -> int:
    check = "--check" in sys.argv
    wanted = block()
    bad: list[str] = []
    skills = sorted(p.parent for p in (PLUGIN / "skills").glob("*/SKILL.md"))
    if not skills:
        bad.append("no skills found")
    for folder in skills:
        path = folder / "SKILL.md"
        text = path.read_text()
        bad += problems(folder, text)
        if text.count(START) == 1 and text.count(END) == 1:
            pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
            updated = pattern.sub(lambda _: wanted, text)
            if updated != text:
                if check:
                    bad.append(f"{folder.name}: shared rules are out of date")
                else:
                    path.write_text(updated)
                    print(f"updated {folder.name}")
    for message in bad:
        print(message, file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
