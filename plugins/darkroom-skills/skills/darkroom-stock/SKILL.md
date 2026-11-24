---
name: darkroom-stock
description: Show what film is in the freezer and what is running low, using the Darkroom tools. Use when the person asks what film they have, whether they have a particular film or format, how much bulk film is left, or what to reorder.
---

# Film stock

Answer questions about unexposed film on hand.

## Tools
- `get_stock`: rolls on hand per film and format (zero rows left out).
- `get_bulk_rolls`: bulk spools with length used and left, cassettes loaded and exposures left. Spool film is **not** counted in `get_stock` until cassettes are loaded.
- `get_low_stock`: film developed regularly and close to running out.

## How to answer
1. Call `get_stock` (and `get_bulk_rolls` if bulk film is relevant or the question is general).
2. Give the total first ("149 rolls: 61 in 35mm, 88 in 120"), then group by film type (black and white, colour, slide) with 35mm and 120 side by side. Keep it a compact list or table; do not read out every row unless asked.
3. For "do I have X?", answer yes or no with the count per format. If X is not in stock say so, and mention a spool of that film if `get_bulk_rolls` shows one.
4. For "what should I reorder?" or "what is running low?", call `get_low_stock`. Each item says rolls left, rolls developed in the last 90 days and days of stock. If `on_bulk_spool` is true, suggest loading cassettes from the spool instead of buying.
5. A negative count is a data problem, not real stock. Say so and offer a recount (`record_stock_adjustment`, after confirming).
6. Bulk spools: say metres left (millimetres divided by 1000) and exposures left.

## Example
"What 120 film have I got?" -> call `get_stock`, list only the 120 rows grouped by type with counts, and give the 120 total.

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
