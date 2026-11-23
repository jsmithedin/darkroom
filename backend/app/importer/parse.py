"""Parse the CSV exports of the "Film Photography Tracker v2" Google Sheet.

Nothing here touches the database: each parser returns plain rows with names (not ids), so
the loader (Task 4.2) can check every name against the reference tables before writing.

Columns are found by header name, not position, so a re-ordered export still parses. Every
problem found in a file is collected and reported together, so one run shows everything to fix.
"""

import csv
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

# Stock counted in the sheet's Films tab is dated here (decision 2 in the design spec).
OPENING_DATE = date(2026, 11, 22)


class ParseError(Exception):
    """A file could not be read. `problems` lists everything wrong, one line each."""

    def __init__(self, path: Path | str, problems: list[str]) -> None:
        self.path = str(path)
        self.problems = problems
        super().__init__(f"{Path(self.path).name}: " + "; ".join(problems))


# --- rows ------------------------------------------------------------------------------


@dataclass(frozen=True)
class RollRow:
    line: int
    dev_date: date
    camera: str
    lens: str | None  # None means N/A
    format: str
    film: str
    ei: Decimal
    developer: str
    dev_time_min: Decimal | None
    filter: str | None
    subject: str | None
    notes: str | None
    source: str  # "factory" or "bulk"


@dataclass(frozen=True)
class FilmRow:
    line: int
    name: str
    type: str  # bw | colour | slide
    box_iso: int


@dataclass(frozen=True)
class OpeningRow:
    line: int
    film: str
    format: str
    rolls: int
    occurred_on: date


@dataclass(frozen=True)
class ListsData:
    cameras: list[str]
    lenses: list[str]
    formats: list[str]
    developers: list[str]
    filters: list[str]


@dataclass(frozen=True)
class BulkRow:
    line: int
    label: str
    film: str
    length_mm: int
    used_before_mm: int
    bought_on: date | None
    cost_pence: int | None
    supplier: str | None
    notes: str | None


@dataclass(frozen=True)
class PurchaseRow:
    line: int
    kind: str  # purchase | given_away | bulk_load
    occurred_on: date
    film: str | None  # None for a bulk load (the spool decides)
    format: str | None
    rolls: int  # signed: negative for given_away
    cost_pence: int | None
    supplier: str | None
    bulk_label: str | None
    exposures_per_cassette: int | None
    notes: str | None


@dataclass(frozen=True)
class DevTimeRef:
    line: int
    film: str
    ei: Decimal
    developer: str
    minutes: Decimal
    notes: str | None


# --- cell parsers ----------------------------------------------------------------------


def clean(cell: str | None) -> str | None:
    """Trim a cell; blank becomes None."""
    if cell is None:
        return None
    text = cell.strip()
    return text or None


def parse_date(s: str | None) -> date | None:
    """dd/mm/yyyy (day first, as the sheet writes it). Blank gives None; nonsense raises."""
    text = clean(s)
    if text is None:
        return None
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if not m:
        raise ValueError(f"'{text}' is not a date (expected dd/mm/yyyy)")
    day, month, year = (int(g) for g in m.groups())
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise ValueError(f"'{text}' is not a real date") from exc


def parse_format(s: str) -> str:
    """'120' stays '120'; '35', '35mm' and '35 mm' become '35mm'. Anything else is returned
    trimmed, so the loader can report it as an unknown name."""
    text = s.strip()
    m = re.fullmatch(r"(\d{2,3})\s*(?:mm)?", text, flags=re.IGNORECASE)
    if m:
        return "35mm" if m.group(1) == "35" else m.group(1)
    return text


def parse_decimal(s: str | None, what: str) -> Decimal | None:
    text = clean(s)
    if text is None:
        return None
    try:
        value = Decimal(text.replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError(f"{what} '{text}' is not a number") from exc
    if not value.is_finite():
        raise ValueError(f"{what} '{text}' is not a number")
    return value


def parse_int(s: str | None, what: str) -> int | None:
    value = parse_decimal(s, what)
    if value is None:
        return None
    if value != value.to_integral_value():
        raise ValueError(f"{what} '{s}' is not a whole number")
    return int(value)


def parse_pence(s: str | None, what: str = "cost") -> int | None:
    """'£12.50', '12.5' or '12' to pence, exactly."""
    text = clean(s)
    if text is None:
        return None
    value = parse_decimal(text.lstrip("£$€"), what)
    assert value is not None
    pence = value * 100
    if pence != pence.to_integral_value() or pence < 0:
        raise ValueError(f"{what} '{text}' is not a sum of money")
    return int(pence)


def parse_length_mm(s: str | None, unit: str, what: str) -> int | None:
    """A length in `unit` ('mm' or 'm') to whole millimetres, exactly."""
    value = parse_decimal(s, what)
    if value is None:
        return None
    mm = value * (1000 if unit == "m" else 1)
    if mm != mm.to_integral_value() or mm < 0:
        raise ValueError(f"{what} '{s}' is not a length in whole millimetres")
    return int(mm)


FILM_TYPES = {
    "bw": "bw",
    "b&w": "bw",
    "blackandwhite": "bw",
    "blackwhite": "bw",
    "mono": "bw",
    "monochrome": "bw",
    "colour": "colour",
    "color": "colour",
    "colourneg": "colour",
    "colornegative": "colour",
    "colournegative": "colour",
    "slide": "slide",
    "reversal": "slide",
    "transparency": "slide",
}


def parse_film_type(s: str) -> str:
    key = re.sub(r"[^a-z&]", "", s.lower())
    if key not in FILM_TYPES:
        raise ValueError(f"film type '{s.strip()}' is not black and white, colour or slide")
    return FILM_TYPES[key]


NOT_APPLICABLE = {"n/a", "na", "-", "none", "fixed"}


def parse_lens(s: str | None) -> str | None:
    """A blank or 'N/A' lens means a fixed-lens camera."""
    text = clean(s)
    if text is None or text.lower() in NOT_APPLICABLE:
        return None
    return text


# --- reading files ---------------------------------------------------------------------


def key(header: str) -> str:
    """Normalise a header for matching: 'Dev Time (min)' -> 'devtimemin'."""
    return re.sub(r"[^a-z0-9]", "", header.lower())


def read_rows(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [[c for c in row] for row in csv.reader(f)]


def is_blank(row: list[str]) -> bool:
    return all(not c.strip() for c in row)


class Table:
    """A header row plus the rows beneath it, with columns looked up by alias."""

    def __init__(self, path: Path, rows: list[list[str]], header_index: int) -> None:
        self.path = path
        self.header_index = header_index
        self.header = rows[header_index]
        self.keys = [key(h) for h in self.header]
        self.body = [(i + 1, r) for i, r in enumerate(rows) if i > header_index and not is_blank(r)]

    def column(self, *aliases: str) -> int | None:
        for alias in aliases:
            if alias in self.keys:
                return self.keys.index(alias)
        return None

    def column_starting(self, prefix: str) -> int | None:
        """First column whose normalised header starts with `prefix` ('usedbefore...')."""
        return next((i for i, k in enumerate(self.keys) if k.startswith(prefix)), None)

    def cell(self, row: list[str], index: int | None) -> str | None:
        if index is None or index >= len(row):
            return None
        return clean(row[index])


def find_table(path: Path, required: dict[str, tuple[str, ...]]) -> Table:
    """Find the header row: the first row containing every required column. If there is none,
    say which headers the file does have."""
    rows = read_rows(path)
    for i, row in enumerate(rows):
        keys = {key(c) for c in row}
        if all(any(a in keys for a in aliases) for aliases in required.values()):
            return Table(path, rows, i)
    seen = next((r for r in rows if not is_blank(r)), [])
    missing = ", ".join(sorted(required))
    raise ParseError(
        path,
        [
            f"could not find a header row with columns: {missing}",
            f"first row in the file was: {[c.strip() for c in seen]}",
        ],
    )


def require(table: Table, name: str, *aliases: str) -> int:
    index = table.column(*aliases)
    assert index is not None, name  # find_table guaranteed it
    return index


# --- Tracker ---------------------------------------------------------------------------

# Year, Month, Type, Box ISO and Stops vs box are calculated in the sheet. They are never read:
# the app derives them.
TRACKER_REQUIRED = {
    "date": ("devdate", "date", "developed", "dateindeveloped", "developeddate"),
    "camera": ("camera",),
    "format": ("format",),
    "film": ("film",),
    "ei": ("ei", "iso", "exposureindex", "shotat"),
    "developer": ("developer",),
}


def parse_tracker(path: Path) -> list[RollRow]:
    t = find_table(path, TRACKER_REQUIRED)
    c = {name: require(t, name, *aliases) for name, aliases in TRACKER_REQUIRED.items()}
    lens = t.column("lens")
    dev_time = t.column("devtime", "devtimemin", "devtimeminutes", "time", "timemin")
    filt = t.column("filter")
    subject = t.column("subject")
    notes = t.column("notes", "comments")
    source = t.column("source")
    # a column that is a calculated copy of box speed must not be mistaken for EI
    problems: list[str] = []
    rows: list[RollRow] = []

    for line, row in t.body:
        key_cells = [t.cell(row, c[n]) for n in ("date", "camera", "film")]
        if not any(key_cells):
            continue  # a pre-filled formula row with nothing logged
        try:
            dev_date = parse_date(t.cell(row, c["date"]))
            if dev_date is None:
                raise ValueError("no development date")
            camera = t.cell(row, c["camera"])
            film = t.cell(row, c["film"])
            fmt = t.cell(row, c["format"])
            developer = t.cell(row, c["developer"])
            ei = parse_decimal(t.cell(row, c["ei"]), "EI")
            for label, value in (
                ("camera", camera),
                ("film", film),
                ("format", fmt),
                ("developer", developer),
                ("EI", ei),
            ):
                if value is None:
                    raise ValueError(f"no {label}")
            assert camera and film and fmt and developer and ei is not None
            if not (0 < ei < 10_000_000 and ei == round(ei, 2)):
                raise ValueError(f"EI '{ei}' must be positive with at most 2 decimals")
            minutes = parse_decimal(t.cell(row, dev_time), "development time")
            if minutes is not None and not (0 < minutes < 1000):
                raise ValueError(
                    f"development time '{minutes}' must be a positive number of minutes"
                )
            src = (t.cell(row, source) or "factory").lower()
            if src not in ("factory", "bulk"):
                raise ValueError(f"source '{src}' is not factory or bulk")
            rows.append(
                RollRow(
                    line=line,
                    dev_date=dev_date,
                    camera=camera,
                    lens=parse_lens(t.cell(row, lens)),
                    format=parse_format(fmt),
                    film=film,
                    ei=ei,
                    developer=developer,
                    dev_time_min=minutes,
                    filter=_none_if_na(t.cell(row, filt)),
                    subject=t.cell(row, subject),
                    notes=t.cell(row, notes),
                    source=src,
                )
            )
        except ValueError as exc:
            problems.append(f"line {line}: {exc}")
    if problems:
        raise ParseError(path, problems)
    return rows


def _none_if_na(value: str | None) -> str | None:
    return None if value is None or value.lower() in NOT_APPLICABLE else value


# --- Films -----------------------------------------------------------------------------

FILMS_REQUIRED = {
    "name": ("film", "name", "filmname"),
    "type": ("type", "filmtype"),
    "box_iso": ("boxiso", "iso", "boxspeed", "isobox"),
}


def parse_films(path: Path) -> tuple[list[FilmRow], list[OpeningRow]]:
    """Films, and an opening-stock row for each 'Opening <format>' column with a count above
    zero (zero and blank counts are skipped: decision 13)."""
    t = find_table(path, FILMS_REQUIRED)
    c = {name: require(t, name, *aliases) for name, aliases in FILMS_REQUIRED.items()}
    opening_cols = [
        (i, parse_format(m.group(1)))
        for i, k in enumerate(t.keys)
        if (m := re.fullmatch(r"opening(\d+)(?:mm)?", k))
    ]
    problems: list[str] = []
    films: list[FilmRow] = []
    openings: list[OpeningRow] = []

    for line, row in t.body:
        name = t.cell(row, c["name"])
        if name is None:
            continue
        try:
            type_text = t.cell(row, c["type"])
            if type_text is None:
                raise ValueError(f"film '{name}' has no type")
            box = parse_int(t.cell(row, c["box_iso"]), "box ISO")
            if box is None or box <= 0:
                raise ValueError(f"film '{name}' needs a positive box ISO")
            films.append(FilmRow(line, name, parse_film_type(type_text), box))
            for index, fmt in opening_cols:
                count = parse_int(t.cell(row, index), f"opening {fmt} count")
                if count is None or count == 0:
                    continue
                if count < 0:
                    raise ValueError(f"opening {fmt} count for '{name}' is negative")
                openings.append(OpeningRow(line, name, fmt, count, OPENING_DATE))
        except ValueError as exc:
            problems.append(f"line {line}: {exc}")
    if problems:
        raise ParseError(path, problems)
    return films, openings


# --- Lists -----------------------------------------------------------------------------

LIST_COLUMNS = {
    "cameras": ("cameras", "camera"),
    "lenses": ("lenses", "lens"),
    "formats": ("formats", "format"),
    "developers": ("developers", "developer"),
    "filters": ("filters", "filter"),
}


def parse_lists(path: Path) -> ListsData:
    """One column per list, names running down it. Repeats are dropped (case-insensitively)."""
    rows = read_rows(path)
    header_index = next(
        (
            i
            for i, r in enumerate(rows)
            if sum(any(key(c) in al for al in LIST_COLUMNS.values()) for c in r) >= 3
        ),
        None,
    )
    if header_index is None:
        seen = next((r for r in rows if not is_blank(r)), [])
        raise ParseError(
            path,
            [
                "could not find a header row naming at least three of: " + ", ".join(LIST_COLUMNS),
                f"first row in the file was: {[c.strip() for c in seen]}",
            ],
        )
    t = Table(path, rows, header_index)
    out: dict[str, list[str]] = {}
    for name, aliases in LIST_COLUMNS.items():
        index = t.column(*aliases)
        seen_lower: set[str] = set()
        values: list[str] = []
        for _, row in t.body:
            value = t.cell(row, index)
            if value and value.lower() not in seen_lower:
                seen_lower.add(value.lower())
                values.append(value)
        out[name] = values
    out["formats"] = list(dict.fromkeys(parse_format(f) for f in out["formats"]))
    return ListsData(**out)


# --- Bulk ------------------------------------------------------------------------------

BULK_REQUIRED = {
    "label": ("bulk", "label", "bulkroll", "bulkid", "id", "name", "roll"),
    "film": ("film",),
    "length": ("length", "lengthmm", "lengthm", "lengthmetres"),
}


def _unit(header: str) -> str:
    """Lengths are millimetres unless the header says metres ('Length (m)')."""
    h = header.lower()
    if "mm" in h:
        return "mm"
    if re.search(r"\(\s*m\s*\)|metre|meter|\bm\b", h):
        return "m"
    return "mm"


def parse_bulk(path: Path) -> list[BulkRow]:
    t = find_table(path, BULK_REQUIRED)
    c = {name: require(t, name, *aliases) for name, aliases in BULK_REQUIRED.items()}
    used = t.column_starting("usedbefore")
    bought = t.column("date", "bought", "boughton", "purchased", "dateboughtbought")
    cost = t.column("cost", "price", "costpence", "totalcost")
    supplier = t.column("supplier", "shop", "from")
    notes = t.column("notes")
    length_unit = _unit(t.header[c["length"]])
    used_unit = _unit(t.header[used]) if used is not None else "mm"
    problems: list[str] = []
    rows: list[BulkRow] = []

    for line, row in t.body:
        label = t.cell(row, c["label"])
        if label is None:
            continue
        try:
            film = t.cell(row, c["film"])
            if film is None:
                raise ValueError(f"bulk roll '{label}' has no film")
            length = parse_length_mm(t.cell(row, c["length"]), length_unit, "length")
            if length is None or length <= 0:
                raise ValueError(f"bulk roll '{label}' needs a positive length")
            rows.append(
                BulkRow(
                    line=line,
                    label=label,
                    film=film,
                    length_mm=length,
                    used_before_mm=parse_length_mm(t.cell(row, used), used_unit, "used before")
                    or 0,
                    bought_on=parse_date(t.cell(row, bought)),
                    cost_pence=parse_pence(t.cell(row, cost)),
                    supplier=t.cell(row, supplier),
                    notes=t.cell(row, notes),
                )
            )
        except ValueError as exc:
            problems.append(f"line {line}: {exc}")
    if problems:
        raise ParseError(path, problems)
    return rows


# --- Purchases -------------------------------------------------------------------------

PURCHASES_REQUIRED = {
    "date": ("date", "dateofpurchase", "purchasedon"),
    "rolls": ("rolls", "qty", "quantity", "number", "count"),
}


def parse_purchases(path: Path) -> list[PurchaseRow]:
    """Negative rolls are given away; a bulk roll id makes it a bulk load; otherwise a purchase."""
    t = find_table(path, PURCHASES_REQUIRED)
    c = {name: require(t, name, *aliases) for name, aliases in PURCHASES_REQUIRED.items()}
    film = t.column("film")
    fmt = t.column("format")
    cost = t.column("cost", "price", "total", "totalcost")
    supplier = t.column("supplier", "shop", "from")
    bulk = t.column("bulk", "bulkroll", "bulkid", "bulklabel")
    exposures = t.column("exposures", "exposurespercassette", "exp")
    notes = t.column("notes")
    problems: list[str] = []
    rows: list[PurchaseRow] = []

    for line, row in t.body:
        if t.cell(row, c["date"]) is None and t.cell(row, c["rolls"]) is None:
            continue
        try:
            occurred = parse_date(t.cell(row, c["date"]))
            if occurred is None:
                raise ValueError("no date")
            rolls = parse_int(t.cell(row, c["rolls"]), "rolls")
            if not rolls:
                raise ValueError("rolls must be a non-zero whole number")
            film_name = t.cell(row, film)
            format_name = t.cell(row, fmt)
            bulk_label = t.cell(row, bulk)
            if bulk_label:
                if rolls < 0:
                    raise ValueError("a bulk load cannot have negative rolls")
                kind = "bulk_load"
            elif rolls < 0:
                kind = "given_away"
            else:
                kind = "purchase"
            if kind != "bulk_load" and not (film_name and format_name):
                raise ValueError("needs a film and a format")
            pence = parse_pence(t.cell(row, cost))
            if kind == "purchase" and pence is None:
                raise ValueError("a purchase needs a cost")
            rows.append(
                PurchaseRow(
                    line=line,
                    kind=kind,
                    occurred_on=occurred,
                    film=None if kind == "bulk_load" else film_name,
                    format=None if kind == "bulk_load" else parse_format(format_name or ""),
                    rolls=rolls,
                    cost_pence=pence if kind == "purchase" else None,
                    supplier=t.cell(row, supplier) if kind == "purchase" else None,
                    bulk_label=bulk_label,
                    exposures_per_cassette=parse_int(t.cell(row, exposures), "exposures"),
                    notes=t.cell(row, notes),
                )
            )
        except ValueError as exc:
            problems.append(f"line {line}: {exc}")
    if problems:
        raise ParseError(path, problems)
    return rows


# --- Dev Times -------------------------------------------------------------------------

DEV_TIMES_REQUIRED = {
    "film": ("film",),
    "ei": ("ei", "iso"),
    "developer": ("developer",),
    "minutes": ("minutes", "min", "time", "timemin", "devtime", "devtimemin", "devtimeminutes"),
}


def parse_dev_time_refs(path: Path) -> list[DevTimeRef]:
    """Only the hand-typed reference block. The sheet also derives a table of logged times from
    the Tracker; that is skipped: the block ends at the first blank row or a row starting with
    'Logged', and the header is taken from the first matching row."""
    t = find_table(path, DEV_TIMES_REQUIRED)
    c = {name: require(t, name, *aliases) for name, aliases in DEV_TIMES_REQUIRED.items()}
    notes = t.column("notes", "comments")
    problems: list[str] = []
    rows: list[DevTimeRef] = []

    all_rows = read_rows(path)
    start = t.header_index
    for offset, row in enumerate(all_rows[start + 1 :], start=start + 2):
        if is_blank(row) or (row and row[0].strip().lower().startswith("logged")):
            break  # end of the reference block
        try:
            film = t.cell(row, c["film"])
            developer = t.cell(row, c["developer"])
            ei = parse_decimal(t.cell(row, c["ei"]), "EI")
            minutes = parse_decimal(t.cell(row, c["minutes"]), "minutes")
            if not (film and developer) or ei is None or minutes is None:
                raise ValueError("needs a film, EI, developer and minutes")
            if not (ei > 0 and ei == round(ei, 2)):
                raise ValueError(f"EI '{ei}' must be positive with at most 2 decimals")
            if not (0 < minutes < 1000 and minutes == round(minutes, 2)):
                raise ValueError(f"minutes '{minutes}' must be positive with at most 2 decimals")
            rows.append(DevTimeRef(offset, film, ei, developer, minutes, t.cell(row, notes)))
        except ValueError as exc:
            problems.append(f"line {offset}: {exc}")
    if problems:
        raise ParseError(path, problems)
    return rows


def parse_all(folder: Path) -> dict[str, object]:
    """Parse every export in `folder` (Tracker.csv, Films.csv, ...), reporting all files' problems
    together."""
    names = {
        "tracker": ("Tracker.csv", parse_tracker),
        "films": ("Films.csv", parse_films),
        "lists": ("Lists.csv", parse_lists),
        "bulk": ("Bulk.csv", parse_bulk),
        "purchases": ("Purchases.csv", parse_purchases),
        "dev_times": ("Dev Times.csv", parse_dev_time_refs),
    }
    result: dict[str, object] = {}
    problems: list[str] = []
    for name, (filename, fn) in names.items():
        path = folder / filename
        if not path.exists():
            problems.append(f"{filename}: file not found in {folder}")
            continue
        try:
            result[name] = fn(path)
        except ParseError as exc:
            problems.extend(f"{filename}: {p}" for p in exc.problems)
    if problems:
        raise ParseError(folder, problems)
    return result


__all__ = [
    "OPENING_DATE",
    "BulkRow",
    "DevTimeRef",
    "FilmRow",
    "ListsData",
    "OpeningRow",
    "ParseError",
    "PurchaseRow",
    "RollRow",
    "parse_all",
    "parse_bulk",
    "parse_date",
    "parse_dev_time_refs",
    "parse_films",
    "parse_format",
    "parse_lists",
    "parse_purchases",
    "parse_tracker",
]
