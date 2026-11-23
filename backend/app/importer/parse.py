"""Parse the CSV exports of the "Film Photography Tracker v2" Google Sheet.

Nothing here touches the database: each parser returns plain rows with names (not ids), so
the loader (Task 4.2) can check every name against the reference tables before writing.

Columns are found by header name, not position, so a re-ordered export still parses. Every
problem found in a file is collected and reported together, so one run shows everything to fix.
"""

import csv
import re
from collections.abc import Callable
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


def scale_exact(value: Decimal, places: int, what: str, shown: str) -> int:
    """`value` times 10**places as an int, or ValueError unless that is a whole, non-negative
    number. Pure integer arithmetic: nothing is ever rounded, however many digits it has."""
    sign, digits, exponent = value.as_tuple()
    if not isinstance(exponent, int) or sign:
        raise ValueError(f"{what} '{shown}' must be a non-negative number")
    n = int("".join(map(str, digits)) or "0")
    shift = exponent + places
    if shift >= 0:
        factor: int = 10**shift
        return n * factor
    divisor: int = 10**-shift
    if n % divisor:
        raise ValueError(f"{what} '{shown}' has too many decimal places")
    return n // divisor


def parse_pence(s: str | None, what: str = "cost") -> int | None:
    """'£12.50', '12.5' or '12' to pence, exactly."""
    text = clean(s)
    if text is None:
        return None
    amount = text.lstrip("£$€").strip()
    if not amount:
        raise ValueError(f"{what} '{text}' has no amount")
    value = parse_decimal(amount, what)
    assert value is not None
    return scale_exact(value, 2, what, text)


def parse_whole_pence(s: str | None, what: str = "cost") -> int | None:
    """A cell that is already in pence ('Cost pence' column): a non-negative whole number."""
    value = parse_int(s, what)
    if value is not None and value < 0:
        raise ValueError(f"{what} '{s}' cannot be negative")
    return value


def parse_length_mm(s: str | None, unit: str, what: str) -> int | None:
    """A length in `unit` ('mm' or 'm') to whole millimetres, exactly."""
    value = parse_decimal(s, what)
    if value is None:
        return None
    return scale_exact(value, 3 if unit == "m" else 0, what, str(s).strip())


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
    """All rows of a CSV file. An unreadable file, bad encoding or an unclosed quote (which would
    otherwise swallow the records after it) becomes a ParseError for that file."""
    try:
        with path.open(newline="", encoding="utf-8-sig") as f:
            return [list(row) for row in csv.reader(f, strict=True)]
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise ParseError(path, [f"could not read the file: {exc}"]) from exc


def attempt[T](errors: list[str], fn: Callable[..., T], *args: object) -> T | None:
    """Run a cell parser; on ValueError record the message and give None, so a row can report
    every bad field at once."""
    try:
        return fn(*args)
    except ValueError as exc:
        errors.append(str(exc))
        return None


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
        errors: list[str] = []
        dev_date = attempt(errors, parse_date, t.cell(row, c["date"]))
        if dev_date is None and not errors:
            errors.append("no development date")
        camera = t.cell(row, c["camera"])
        film = t.cell(row, c["film"])
        fmt = t.cell(row, c["format"])
        developer = t.cell(row, c["developer"])
        for label, value in (
            ("camera", camera),
            ("film", film),
            ("format", fmt),
            ("developer", developer),
        ):
            if value is None:
                errors.append(f"no {label}")
        ei = attempt(errors, parse_decimal, t.cell(row, c["ei"]), "EI")
        if ei is None:
            if not any(e.startswith("EI ") for e in errors):
                errors.append("no EI")
        elif not (ei > 0 and ei < 10_000_000 and ei == round(ei, 2)):
            errors.append(f"EI '{ei}' must be positive with at most 2 decimals")
        minutes = attempt(errors, parse_decimal, t.cell(row, dev_time), "development time")
        if minutes is not None and not (0 < minutes < 1000 and minutes == round(minutes, 2)):
            errors.append(
                f"development time '{minutes}' must be positive minutes, at most 2 decimals"
            )
        src = (t.cell(row, source) or "factory").lower()
        if src not in ("factory", "bulk"):
            errors.append(f"source '{src}' is not factory or bulk")
        if errors:
            problems.append(f"line {line}: " + "; ".join(errors))
            continue
        assert dev_date and camera and film and fmt and developer and ei is not None
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


def _opening_columns(t: Table) -> list[tuple[int, str]]:
    """Every 'Opening <format>' column as (index, normalised format). Any format name counts,
    not just numbers, so 'Opening 4x5' is read (and reported as unknown by the loader) rather
    than silently dropped. An 'Opening date' column is not a count."""
    columns: list[tuple[int, str]] = []
    for i, header in enumerate(t.header):
        m = re.fullmatch(r"\s*opening\s*(.+?)\s*", header, flags=re.IGNORECASE)
        if m and key(m.group(1)) not in ("date", "on", "stockdate"):
            columns.append((i, parse_format(m.group(1))))
    return columns


def parse_films(path: Path) -> tuple[list[FilmRow], list[OpeningRow]]:
    """Films, and an opening-stock row for each 'Opening <format>' column with a count above
    zero (zero and blank counts are skipped: decision 13)."""
    t = find_table(path, FILMS_REQUIRED)
    c = {name: require(t, name, *aliases) for name, aliases in FILMS_REQUIRED.items()}
    opening_cols = _opening_columns(t)
    problems: list[str] = []
    films: list[FilmRow] = []
    openings: list[OpeningRow] = []

    for line, row in t.body:
        name = t.cell(row, c["name"])
        if name is None:
            data_cols = [c["type"], c["box_iso"], *(i for i, _ in opening_cols)]
            if any(t.cell(row, i) for i in data_cols):
                problems.append(f"line {line}: a film row has details but no name")
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

    def lists_named(row: list[str]) -> int:
        """How many different lists this row has a header for (repeats count once)."""
        return sum(any(key(cell) in al for cell in row) for al in LIST_COLUMNS.values())

    header_index = next((i for i, r in enumerate(rows) if lists_named(r) >= 3), None)
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
    "length": (
        "length",
        "lengthmm",
        "lengthm",
        "lengthmillimetres",
        "lengthmillimeters",
        "lengthmetres",
        "lengthmeters",
    ),
}


def _unit(header_key: str) -> str:
    """The length unit named by a normalised header: millimetres unless it says metres.

    Longer unit names are tested first, because 'millimetres' and 'centimetres' end in 'metres'.
    Centimetres and kilometres are refused rather than guessed.
    """
    if header_key.endswith(("millimetres", "millimeters", "mm")):
        return "mm"
    if header_key.endswith(("centimetres", "centimeters", "kilometres", "kilometers", "cm", "km")):
        raise ValueError(f"column '{header_key}' is not in mm or m")
    if header_key.endswith(("metres", "meters")) or re.search(r"(?<!m)m$", header_key):
        return "m"
    return "mm"


def parse_bulk(path: Path) -> list[BulkRow]:
    t = find_table(path, BULK_REQUIRED)
    c = {name: require(t, name, *aliases) for name, aliases in BULK_REQUIRED.items()}
    used = t.column_starting("usedbefore")
    bought = t.column("date", "bought", "boughton", "purchased", "datebought")
    cost = t.column("cost", "price", "costpence", "totalcost")
    supplier = t.column("supplier", "shop", "from")
    notes = t.column("notes")
    try:
        length_unit = _unit(t.keys[c["length"]])
        used_unit = _unit(t.keys[used]) if used is not None else "mm"
    except ValueError as exc:
        raise ParseError(path, [str(exc)]) from exc
    cost_in_pence = cost is not None and t.keys[cost].endswith("pence")
    problems: list[str] = []
    rows: list[BulkRow] = []
    data_columns = [i for i in (*c.values(), used, bought, cost, supplier, notes) if i is not None]

    for line, row in t.body:
        label = t.cell(row, c["label"])
        if label is None:
            if any(t.cell(row, i) for i in data_columns):
                problems.append(f"line {line}: a bulk roll has details but no label")
            continue
        errors: list[str] = []
        film = t.cell(row, c["film"])
        if film is None:
            errors.append(f"bulk roll '{label}' has no film")
        length = attempt(errors, parse_length_mm, t.cell(row, c["length"]), length_unit, "length")
        if (length is None or length <= 0) and not any(e.startswith("length") for e in errors):
            errors.append(f"bulk roll '{label}' needs a positive length")
        used_mm = attempt(errors, parse_length_mm, t.cell(row, used), used_unit, "used before")
        bought_on = attempt(errors, parse_date, t.cell(row, bought))
        cost_text = t.cell(row, cost)
        pence = attempt(errors, parse_whole_pence if cost_in_pence else parse_pence, cost_text)
        if errors:
            problems.append(f"line {line}: " + "; ".join(errors))
            continue
        assert film is not None and length is not None
        rows.append(
            BulkRow(
                line=line,
                label=label,
                film=film,
                length_mm=length,
                used_before_mm=used_mm or 0,
                bought_on=bought_on,
                cost_pence=pence,
                supplier=t.cell(row, supplier),
                notes=t.cell(row, notes),
            )
        )
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

    recognised = [
        i for i in (*c.values(), film, fmt, cost, supplier, bulk, exposures, notes) if i is not None
    ]

    for line, row in t.body:
        if not any(t.cell(row, i) for i in recognised):
            continue  # nothing filled in on this row
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
            per_cassette = parse_int(t.cell(row, exposures), "exposures")
            if kind == "bulk_load" and (per_cassette is None or per_cassette <= 0):
                raise ValueError("a bulk load needs a positive number of exposures per cassette")
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
                    exposures_per_cassette=per_cassette,
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
    the Tracker; that is skipped. The block ends at the first blank row, or a row whose only
    entry starts with 'Logged'; the header is the first row with the required columns."""
    t = find_table(path, DEV_TIMES_REQUIRED)
    c = {name: require(t, name, *aliases) for name, aliases in DEV_TIMES_REQUIRED.items()}
    notes = t.column("notes", "comments")
    problems: list[str] = []
    rows: list[DevTimeRef] = []

    all_rows = read_rows(path)
    start = t.header_index
    for offset, row in enumerate(all_rows[start + 1 :], start=start + 2):
        filled = [cell.strip() for cell in row if cell.strip()]
        if not filled or (len(filled) == 1 and filled[0].lower().startswith("logged")):
            break  # a blank row, or a lone "Logged ..." heading, ends the reference block
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
