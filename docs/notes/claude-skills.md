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

## Verification status (2026-11-24, reported by the owner)
| Route | Status |
|---|---|
| Desktop: Customize, Plugins, Add marketplace from a repository (`jsmithedin/darkroom`, public repo) | worked; the skills installed and were picked from plain sentences |
| Desktop: Darkroom custom connector (URL `https://film.jamielab.uk/mcp`, register automatically, OAuth) | worked after adding it and enabling it for the chat. Until it was added, the stock skill correctly said it could not reach the tools and did not guess a count |
| Reads (stock, low stock, stats, spend, idle cameras) | worked |
| Writes (purchase, log roll, refusal, correction) | worked |
| Claude Code marketplace install | not reported |
| Single-skill zip upload (claude.ai, Desktop) | not tried |
| claude.ai web and phone: connector and skills | not reported |
| Audit entries show "Connector: ..." for OAuth writes | not reported |
| A week of normal use | not started |

Open follow-ups: record the phone and web results and the exact menu names, and whether the
zip layout (`<skill>/SKILL.md`) was accepted, when they are tried.
