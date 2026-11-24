---
name: darkroom-log-roll
description: Log a developed roll of film in Darkroom. Use when the person says they developed, processed or finished a roll, or asks to log, add or correct a roll in the film log.
---

# Logging developed film

A log entry records a roll that has been developed: date, camera, lens, film, EI, developer, development time and notes. It also uses one roll of stock.

## Tools
- `log_roll`: dev_date, camera, film, ei, developer (all required); format (default 35mm), lens (name, or "none"), dev_time_min, filter, subject, notes, source ("factory", or "bulk" for hand-rolled cassettes).
- `update_roll`: roll_id plus only the fields to change.
- `list_rolls`: find a roll (and the last one for a camera). `get_dev_times`: times used before for a film, EI and developer.
- `get_stock`, `record_purchase`, `record_stock_adjustment`: for stock problems.

## Steps
1. Gather the required details from what the person said. The required ones are the development date, camera, film, EI and developer. Ask for anything missing in one short question, not one at a time.
2. Fill gaps sensibly, and say what you filled in:
   - **Camera usual settings:** call `list_rolls` with that camera and limit 1. Offer its lens and format, and the developer if the person did not give one.
   - **Fixed-lens cameras:** use lens "none".
   - **EI:** if not stated, offer the film's box speed from `list_reference_data` (films), but ask, since pushing and pulling is common.
   - **Development time:** if missing, call `get_dev_times` for the film, EI and developer and offer the most recent logged time or the reference time. Leave it blank if the person says they do not know; never invent one.
   - **Source:** use "bulk" only if the person says the cassette was hand-rolled from bulk.
3. Confirm in one line: "Log Tri-X (35mm) in the FM2 with the 50mm, EI 800, HC-110 for 9 min, developed 2026-11-20?" Then call `log_roll`.
4. Report the result briefly (date, film, camera, and the stops over or under box speed if the tool returns it).

## If the write is refused for stock
The tool names the film and format that has none. Say so, and offer: record a purchase (ask for count and cost) or a recount if the freezer actually has the film (`record_stock_adjustment`, with the counted number). Do not retry the log until stock is fixed.

## Correcting a roll
Find it with `list_rolls` (date, film, camera, or text search), show the match, confirm the change, then `update_roll` with only the changed fields. Use lens "none" to clear a lens. There is no delete; point to the app.

## Example
"Developed a roll of Tri-X yesterday, shot at 800 in the FM2, HC-110" -> work out yesterday's date, get the FM2's last roll for lens and format, look up a time with `get_dev_times`, confirm, then `log_roll`.

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
