# Test prompts for the Darkroom skills

Run these against a **scratch database or a throwaway token**, not the live freezer, in a
client with the Darkroom connector. For each, check the skill is picked and the tool calls
and confirmation match. Record results in `docs/notes/claude-skills.md`.

## darkroom-stock
| Prompt | Expect |
|---|---|
| "What film have I got?" | `get_stock` (and `get_bulk_rolls`); total first, grouped by type, 35mm and 120 side by side |
| "Do I have any Tri-X in 120?" | `get_stock`; a count, or a clear no (mentions a spool if one exists) |
| "What should I reorder?" | `get_low_stock`; rolls left, rolls developed, days of stock; suggests loading cassettes when `on_bulk_spool` |
| "How much bulk film is left?" | `get_bulk_rolls`; metres left and exposures left |

## darkroom-purchase
| Prompt | Expect |
|---|---|
| "Bought 3 rolls of HP5 in 120 for £21" | one-line confirmation (cost 2100 pence), then `record_purchase` only after a yes |
| "Picked up 5 Portra 160" (no cost) | asks for the cost; asks the format if unclear |
| "Bought a roll of Cinestill 800T" (film not in the list) | offers `add_reference_item`, asks for type and box ISO, does not guess |
| "New 30.5 m spool of Fomapan 100, £28" | `create_bulk_roll` with length 30500 and cost 2800 after confirming a label |
| "Loaded 4 cassettes from Bulk 1" | `record_bulk_load`, 36 exposures unless told otherwise |
| "Gave away 2 rolls of FP4 35mm" | `record_given_away` with a positive count; relays any refusal |

## darkroom-log-roll
| Prompt | Expect |
|---|---|
| "Developed a roll of Tri-X yesterday, shot at 800 in the FM2, HC-110" | correct date for yesterday; camera's last roll used for lens and format; `get_dev_times` for a time; confirm, then `log_roll` |
| Same, but the film has no stock | tool error names the film and format; offers a purchase or recount; does not retry |
| "Log a roll" | asks for the missing required details in one message |
| "That last roll was actually EI 400" | `list_rolls`, shows the match, confirms, `update_roll` with only `ei` |
| "Delete that roll" | says there is no delete tool; points to the app |

## darkroom-logs-and-stats
| Prompt | Expect |
|---|---|
| "How many rolls this year compared to last?" | `get_stats`; year-to-date comparison with the date stated |
| "What did I spend on film in 2026?" | `get_spend`; pounds, and how cost per roll is worked out |
| "Which camera haven't I used for ages?" | `get_camera_idle`, oldest first |
| "Show my Tri-X rolls from October" | `list_rolls` with film and dates; a handful plus the total |
| "What's the cost of my last roll?" | says per-roll cost is not available, gives the yearly figure |
