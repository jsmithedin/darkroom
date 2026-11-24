---
name: darkroom-purchase
description: Record film purchases and other stock changes in Darkroom: bought rolls, a new bulk spool, cassettes loaded from bulk, or film given away. Use when the person says they bought, ordered, picked up, loaded or gave away film.
---

# Film purchases and stock changes

## Tools
- `record_purchase`: film, occurred_on, rolls, cost_pence (the receipt total for those rolls), optional format (default 35mm), supplier, notes.
- `create_bulk_roll`: a new bulk spool: label, film, length_mm, optional cost_pence, supplier, bought_on.
- `record_bulk_load`: cassettes loaded from a spool: bulk_roll (label), occurred_on, rolls, exposures_per_cassette (default 36).
- `record_given_away`: film, occurred_on, rolls (positive number), optional format.
- `update_bulk_roll`: change a spool (mark it finished, fix its cost, length or notes); pass only what changes.
- `add_reference_item`: add a new film (needs film_type bw, colour or slide, and box_iso).
- `list_reference_data`: check names; `get_stock` / `get_bulk_rolls`: show the result.

## Steps for a purchase
1. Collect: film, number of rolls, format (35mm or 120; ask if not stated and not obvious), total cost, date (default today) and supplier if given. Ask only for what is missing; cost is required, so ask if absent.
2. Check the film exists. If the name does not match, call `list_reference_data` with kind films and offer close matches. If it really is new, offer `add_reference_item`, which needs the type (black and white, colour or slide) and the box ISO; ask for both, do not guess.
3. Convert the cost to pence: £14.50 -> 1450. If the person gives a per-roll price, multiply by the rolls to get the receipt total, and say so.
4. Confirm in one line: "Record 5 x Kodak Portra 160 (35mm), £42.50 total, from Analogue Wonderland, on 2026-11-24?" Then call `record_purchase`.
5. Report the new count by calling `get_stock` (or say what the tool returned).

## Other changes
- **Bulk spool:** convert metres to millimetres (30.5 m -> 30500). Ask for a short label (for example "Bulk 3") if none is given.
- **Spool changes:** to mark a spool used up or correct its details, confirm and call `update_bulk_roll` with the spool label and only the changed fields.
- **Loading cassettes:** name the spool by label. If the person gives film and count but no spool, check `get_bulk_rolls` for a spool of that film. Loaded cassettes become 35mm stock.
- **Given away or lost:** confirm the count; the tool refuses if there are fewer rolls than that.
- Several purchases in one message: confirm the whole list once, then record them one by one and report any that fail.

## If a write is refused
Report what the tool said. For stock shortfalls offer a recount (`record_stock_adjustment`) or a purchase.

## Example
"Bought 3 rolls of HP5 in 120 for £21" -> film Ilford HP5, format 120, rolls 3, cost_pence 2100, date today; confirm, then record.

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
