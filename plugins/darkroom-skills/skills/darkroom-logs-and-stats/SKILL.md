---
name: darkroom-logs-and-stats
description: Answer questions about the Darkroom film log and statistics: rolls shot or developed over a period, by film, camera or developer, development times, spend, idle cameras and year-on-year comparisons. Use when the person asks how many, when, which or how much about their photography or film use.
---

# Logs and statistics

## Tools
- `list_rolls`: filter by date range, film, camera, developer, source (factory or bulk) and text search in subject and notes; newest development date first; returns a total.
- `get_stats`: roll counts by month for a year and the previous year, year-to-date comparison, and breakdowns for that year by camera, film, developer, format, film type and source.
- `get_spend`: spend per year (purchases and bulk film in pence), rolls developed and cost per roll.
- `get_camera_idle`: each camera and when it was last used.
- `get_dev_times`: development times used for a film, EI and developer.
- `get_bulk_rolls`, `get_stock`: current film on hand.

## How to answer
1. Choose the tool that answers the question directly. Counts and comparisons come from `get_stats` (pass the year), not from counting rows in `list_rolls`. Use the `total` field of `list_rolls` for counts of a filtered set.
2. State the period and basis. Rolls are counted by **development date**, in the UK timezone. For "this year" say the year ("2026 so far, to 24 November").
3. Compare like with like. For year-on-year, use the year-to-date figures, not a full previous year against a part year.
4. Money: convert pence to pounds, and say that cost per roll is the year's spend divided by that year's rolls developed.
5. Lists: give the most useful handful, then offer more ("12 more, want them?"). `list_rolls` returns up to 200 per call; page by narrowing the dates rather than guessing.
6. If a figure is not available from the tools (for example cost of a single roll, or exposures-level detail), say so.

## Corrections
To fix a past roll use the darkroom-log-roll skill's steps (`update_roll` after confirming). This skill does not write anything.

## Examples
- "How many rolls have I shot this year compared to last?" -> `get_stats` for the current year and report the year-to-date comparison.
- "What's my best developing time for HP5 at 1600 in DD-X?" -> `get_dev_times` with those, report recent times and any reference time.
- "Which camera haven't I used for ages?" -> `get_camera_idle`, oldest last-used date first.

<!-- shared-rules:start -->
## Rules that apply to every Darkroom task

- Use the Darkroom tools (the `darkroom` connector). Reads need no confirmation. **Before any write, say exactly what will be recorded and wait for a yes**, unless the person has just given every detail and asked you to go ahead.
- There are no delete tools. Never offer to delete anything; for removing or archiving records, point to the Darkroom app.
- Money is whole pence and lengths are whole millimetres in the tools. Say figures back in pounds and metres (1250 pence is £12.50; 30480 mm is 30.48 m). Never use floating point for either.
- Give films, cameras, lenses, developers, filters and formats by name. If a name does not match, call `list_reference_data` and offer the nearest choices; do not guess.
- Dates are ISO (`2026-11-24`). Work out "today", "yesterday" and "last Friday" from the current date, in the UK timezone, and state the date you used.
- A tool error is information. Tell the person what it says in plain words and suggest the next step. Do not retry the same call.
- If something cannot be done with these tools, say so plainly instead of approximating.
<!-- shared-rules:end -->
