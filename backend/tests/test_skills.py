"""The Claude skills in plugins/darkroom-skills must stay valid and match the real tools."""

import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType

from app.config import Settings
from app.mcp.server import build_mcp

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "darkroom-skills"


def load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tools_section(text: str) -> list[str]:
    section = text.split("## Tools", 1)[1].split("\n## ", 1)[0]
    names: list[str] = []
    for line in section.splitlines():
        if line.startswith("- `"):
            names += re.findall(r"`([a-z]+(?:_[a-z]+)+)`", line.split(":", 1)[0])
    return names


async def test_every_tool_a_skill_mentions_exists() -> None:
    mcp = build_mcp(Settings(), lambda: None)  # type: ignore[arg-type,return-value]
    real = {tool.name for tool in await mcp.list_tools()}
    mentioned: set[str] = set()
    for skill in (PLUGIN / "skills").glob("*/SKILL.md"):
        names = tools_section(skill.read_text())
        assert names, f"{skill.parent.name} lists no tools"
        missing = set(names) - real
        assert not missing, f"{skill.parent.name} mentions unknown tools {missing}"
        mentioned |= set(names)
    # Every tool that reads or writes the tracker is covered by at least one skill.
    assert real - {"ping"} - mentioned == set()


def test_skills_are_valid_and_rules_are_in_sync() -> None:
    script = load_script("sync_skill_rules")
    wanted = script.block()
    for skill in sorted((PLUGIN / "skills").glob("*/SKILL.md")):
        text = skill.read_text()
        assert script.problems(skill.parent, text) == []
        assert wanted in text, f"{skill.parent.name}: run scripts/sync_skill_rules.py"


def test_plugin_and_marketplace_manifests_agree() -> None:
    plugin = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    [entry] = market["plugins"]
    assert entry["name"] == plugin["name"]
    assert (ROOT / entry["source"]).resolve() == PLUGIN.resolve()
    assert re.fullmatch(r"\d+\.\d+\.\d+", plugin["version"])
