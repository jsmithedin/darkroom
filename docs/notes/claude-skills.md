# Claude skills: install routes and verification (issue #86)

The plugin is `plugins/darkroom-skills`; the repo root also holds
`.claude-plugin/marketplace.json`, so the repo is its own marketplace (public since
2026-11-24).

## Decisions
- Several small skills, not one umbrella skill. Skills are matched by their one-line
  description and loaded on demand; narrow ones match plain sentences better and can be
  tested and changed independently.
- The shared rules live in `shared-rules.md` and are copied into each `SKILL.md` between
  markers (`scripts/sync_skill_rules.py`), because each skill must be self-contained when
  uploaded alone as a zip. CI and a test enforce that they match.
- A test checks that every tool a skill lists exists in the MCP server, and that every
  tracker tool is covered by at least one skill.

## Verification status (all manual, not done yet)
| Route | Status |
|---|---|
| Claude Code: `/plugin marketplace add jsmithedin/darkroom` and install | not tried |
| Desktop: Customize, Plugins, Add marketplace from a repository | not tried; there are user reports of failures with private repos, which should not apply now the repo is public |
| Desktop: upload a single skill zip (zip layout: `<skill>/SKILL.md`) | not tried; one community guide says `SKILL.md` should be at the archive root, so try that if the first layout is rejected |
| claude.ai web: upload a skill zip | not tried |
| Do skills installed on Desktop appear on the phone or claude.ai web? | unknown; user reports say they do not sync. Fallback: a short note in the Claude profile to use the Darkroom tools, confirm writes, money in pence |
| Skills run correctly against a scratch database | not run; prompts are in `plugins/darkroom-skills/TESTING.md` |

Record the results here (what worked, exact menu names, any layout change needed).
