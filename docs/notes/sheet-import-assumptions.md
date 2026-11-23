# Sheet import: layout assumptions (Task 4.1)

Date: 2026-11-23. Status: **unverified against the real exports.** The parsers in `backend/app/importer/parse.py` were written from the design spec (section 10) and synthetic fixtures in `backend/tests/importer/fixtures/`, because the real CSV exports were not available. The first run against the real files (Task 4.3's manual check) may need header aliases or layout tweaks. Everything below is what to look at first when a parse fails.

## How matching works
- Columns are found **by header name**, not position. Headers are normalised (lowercase, letters and digits only), so `Dev Time (min)` matches `devtimemin`. Aliases are listed per file in `parse.py` (`TRACKER_REQUIRED`, `FILMS_REQUIRED`, ...).
- The header row is the first row containing every required column, so title rows above it are fine.
- Fully blank rows are skipped. Extra columns are ignored.
- **Every problem in a file is collected and reported together** (`ParseError.problems`, with line numbers), and if a header row can't be found the error prints the first row it did see. Use that output to adjust aliases.
- Files are read as UTF-8 (a BOM from Sheets is fine).

## Per file
| File | Required columns (aliases in code) | Notes |
|---|---|---|
| `Tracker.csv` | Dev date, Camera, Format, Film, EI, Developer | Optional: Lens, Dev time, Filter, Subject, Notes, Source. **Year, Month, Type, Box ISO and Stops are never read.** Rows with no date, camera or film (pre-filled formula rows) are skipped. Lens blank or `N/A` gives no lens. Source defaults to `factory` (`bulk` if the column says so). |
| `Films.csv` | Film, Type, Box ISO | Every `Opening <format>` column (`Opening 35mm`, `Opening 120`) gives an opening-stock row dated 2026-11-22. Zero and blank counts are skipped. Other columns (the sheet's own stock figures) are ignored. Type accepts B&W / bw / Colour / Color / Colour Neg / Slide / reversal. |
| `Lists.csv` | at least three of Cameras, Lenses, Formats, Developers, Filters | One column per list, names running down. Repeats dropped case-insensitively; formats normalised (`35` becomes `35mm`). |
| `Bulk.csv` | Bulk (or Label/ID/Name), Film, Length | Length and "used before" are **millimetres unless the header says metres** (`Length (m)`). Date, cost and supplier optional. |
| `Purchases.csv` | Date, Rolls | Optional: Film, Format, Cost, Supplier, Bulk roll, Exposures, Notes. Negative rolls are given away; a bulk roll id makes a bulk load (film comes from the spool); otherwise a purchase, which needs a cost. Empty is fine. |
| `Dev Times.csv` | Film, EI, Developer, Minutes | Only the first (hand-typed reference) block: it ends at the first blank row or a row starting with "Logged". The derived block of logged times is ignored. |

## Things I could not know
- Whether Tracker has a Source or bulk marker column, and what the Notes/Subject headers are called.
- How Dev Times separates its reference block from the logged block (assumed: a blank row, or a row starting "Logged").
- Whether the Lists tab is one column per list (assumed) or something else.
- Whether Bulk lengths are in mm or m (assumed mm unless the header says otherwise).
- The Purchases layout (the tab is empty today, so only its headers matter).

When the real files are available: run `parse_all(Path("import"))`, read the problems, and update the aliases or the block-detection rules here and in the parser, with a fixture reproducing any new shape.
