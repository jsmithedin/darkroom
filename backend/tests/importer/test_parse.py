from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.importer.parse import (
    OPENING_DATE,
    ParseError,
    parse_bulk,
    parse_date,
    parse_dev_time_refs,
    parse_films,
    parse_format,
    parse_length_mm,
    parse_lens,
    parse_lists,
    parse_pence,
    parse_purchases,
    parse_tracker,
)

FIXTURES = Path(__file__).parent / "fixtures"


def write(tmp_path: Path, text: str, name: str = "sheet.csv") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# --- cell parsers ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("19/04/2026", date(2026, 4, 19)),
        ("1/2/2026", date(2026, 2, 1)),  # day first, not month first
        ("05/11/2026", date(2026, 11, 5)),
        (" 29/02/2028 ", date(2028, 2, 29)),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_parse_date(text: str | None, expected: date | None) -> None:
    assert parse_date(text) == expected


@pytest.mark.parametrize("text", ["2026-04-19", "31/02/2026", "13/13/2026", "yesterday", "19/4/26"])
def test_parse_date_rejects_nonsense(text: str) -> None:
    with pytest.raises(ValueError):
        parse_date(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("120", "120"),
        ("35", "35mm"),
        ("35mm", "35mm"),
        ("35 mm", "35mm"),
        ("35MM", "35mm"),
        ("110", "110"),
        ("  120 ", "120"),
        ("4x5", "4x5"),  # left alone, so the loader can report it as unknown
    ],
)
def test_format_numeric_and_text(text: str, expected: str) -> None:
    assert parse_format(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [("£12.50", 1250), ("12.5", 1250), ("12", 1200), ("0", 0), ("1,200.00", 120000), ("", None)],
)
def test_parse_pence_is_exact(text: str, expected: int | None) -> None:
    assert parse_pence(text) == expected


@pytest.mark.parametrize("text", ["12.505", "-3", "free"])
def test_parse_pence_rejects(text: str) -> None:
    with pytest.raises(ValueError):
        parse_pence(text)


def test_length_units() -> None:
    assert parse_length_mm("17000", "mm", "length") == 17000
    assert parse_length_mm("17", "m", "length") == 17000
    assert parse_length_mm("7.3", "m", "length") == 7300
    assert parse_length_mm("", "m", "length") is None
    with pytest.raises(ValueError):
        parse_length_mm("1.5", "mm", "length")


@pytest.mark.parametrize("text", ["", "  ", "N/A", "n/a", "NA", "-", None])
def test_lens_na_and_blank_are_none(text: str | None) -> None:
    assert parse_lens(text) is None


# --- Tracker ---------------------------------------------------------------------------


def test_tracker_ignores_calculated_columns() -> None:
    rows = parse_tracker(FIXTURES / "tracker.csv")
    first = rows[0]
    # Year 1999, Month 13, Type Colour, Box ISO 64 and Stops +9 in the file are all nonsense,
    # and none of them appears in the row: they are recalculated by the app.
    assert not {"year", "month", "type", "box_iso", "stops"} & set(vars(first))
    assert first.dev_date == date(2026, 4, 19)
    assert (first.camera, first.lens, first.format, first.film) == (
        "Nikon FM2",
        "50mm f/1.8",
        "35mm",
        "Tri-X",
    )
    assert first.ei == Decimal("400")
    assert (first.developer, first.dev_time_min, first.filter) == (
        "HC-110",
        Decimal("9.5"),
        "Yellow",
    )
    assert (first.subject, first.notes, first.source) == ("Harbour", "Pushed", "factory")


def test_tracker_finds_the_header_below_a_title_row_and_skips_empty_rows() -> None:
    rows = parse_tracker(FIXTURES / "tracker.csv")
    assert len(rows) == 4  # the two formula-only rows are ignored
    assert [r.line for r in rows] == [3, 4, 5, 6]


def test_blank_cells_become_none() -> None:
    rows = parse_tracker(FIXTURES / "tracker.csv")
    xa = rows[1]
    assert xa.lens is None  # N/A
    assert (xa.dev_time_min, xa.filter, xa.subject, xa.notes) == (None, None, None, None)
    assert xa.format == "35mm"


def test_identical_rows_are_all_kept() -> None:
    rows = parse_tracker(FIXTURES / "tracker.csv")
    assert rows[1] == rows[2].__class__(**{**vars(rows[2]), "line": rows[1].line})
    assert rows[1].line != rows[2].line


def test_tracker_decimal_ei_and_blank_lens() -> None:
    rows = parse_tracker(FIXTURES / "tracker.csv")
    assert rows[3].ei == Decimal("12.5")
    assert rows[3].format == "120"
    assert rows[3].lens == "80mm"


def test_tracker_columns_found_by_name_not_position(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "Developer,Film,EI,Format,Camera,Dev Date,Source\n"
        "Rodinal,HP5,400,120,Mamiya,01/06/2026,Bulk\n",
    )
    (row,) = parse_tracker(path)
    assert (row.developer, row.film, row.camera, row.source) == ("Rodinal", "HP5", "Mamiya", "bulk")
    assert row.lens is None  # no Lens column at all


def test_tracker_reports_every_problem_at_once(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "Dev date,Camera,Lens,Format,Film,EI,Developer\n"
        "19/04/2026,Nikon,50mm,35,Tri-X,fast,HC-110\n"
        "32/04/2026,Nikon,50mm,35,Tri-X,400,HC-110\n"
        "19/04/2026,,50mm,35,Tri-X,400,HC-110\n"
        "19/04/2026,Nikon,50mm,35,Tri-X,0,HC-110\n"
        "19/04/2026,Nikon,50mm,35,Tri-X,400.125,HC-110\n"
        "19/04/2026,Nikon,50mm,35,Tri-X,400,HC-110\n",
    )
    with pytest.raises(ParseError) as err:
        parse_tracker(path)
    problems = err.value.problems
    assert len(problems) == 5  # the good last row is not a problem
    assert any(p.startswith("line 2:") and "EI" in p for p in problems)
    assert any(p.startswith("line 3:") and "real date" in p for p in problems)
    assert any(p.startswith("line 4:") and "no camera" in p for p in problems)
    assert any(p.startswith("line 5:") for p in problems)
    assert any(p.startswith("line 6:") for p in problems)


def test_tracker_missing_columns_says_what_was_found(tmp_path: Path) -> None:
    path = write(tmp_path, "Date,Cam,Stock\n01/01/2026,x,y\n")
    with pytest.raises(ParseError) as err:
        parse_tracker(path)
    text = " ".join(err.value.problems)
    assert "could not find a header row" in text
    assert "'Cam'" in text  # shows the headers it did see


def test_bad_source_and_dev_time(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "Dev date,Camera,Format,Film,EI,Developer,Dev time,Source\n"
        "01/01/2026,A,120,F,100,D,0,factory\n"
        "01/01/2026,A,120,F,100,D,9,mystery\n",
    )
    with pytest.raises(ParseError) as err:
        parse_tracker(path)
    assert len(err.value.problems) == 2


def test_utf8_bom_from_sheets_export(tmp_path: Path) -> None:
    path = tmp_path / "bom.csv"
    path.write_bytes(
        b"\xef\xbb\xbfDev date,Camera,Format,Film,EI,Developer\n01/01/2026,A,120,F,100,D\n"
    )
    assert len(parse_tracker(path)) == 1


# --- Films -----------------------------------------------------------------------------


def test_films_skips_zero_openings() -> None:
    films, openings = parse_films(FIXTURES / "films.csv")
    assert [(f.name, f.type, f.box_iso) for f in films] == [
        ("Tri-X", "bw", 400),
        ("Fomapan 100", "bw", 100),
        ("Portra 160", "colour", 160),
        ("Velvia 50", "slide", 50),
    ]
    assert [(o.film, o.format, o.rolls) for o in openings] == [
        ("Tri-X", "35mm", 10),
        ("Tri-X", "120", 4),
        ("Portra 160", "120", 6),
        ("Velvia 50", "35mm", 2),
    ]
    assert {o.occurred_on for o in openings} == {OPENING_DATE} == {date(2026, 11, 22)}
    # the sheet's own "Stock" columns are calculated and never read
    assert not any(o.film == "Fomapan 100" for o in openings)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("B&W", "bw"),
        ("bw", "bw"),
        ("Black and White", "bw"),
        ("Colour", "colour"),
        ("Color", "colour"),
        ("Colour Neg", "colour"),
        ("Slide", "slide"),
        ("reversal", "slide"),
    ],
)
def test_film_types(tmp_path: Path, text: str, expected: str) -> None:
    path = write(tmp_path, f"Film,Type,Box ISO\nX,{text},100\n")
    (film,), openings = parse_films(path)
    assert film.type == expected
    assert openings == []


def test_films_problems(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "Film,Type,Box ISO,Opening 35mm\n"
        "A,infrared,100,\n"
        "B,bw,0,\n"
        "C,bw,100,-1\n"
        "D,bw,100,1.5\n"
        "E,,100,\n"
        "F,bw,400,3\n",
    )
    with pytest.raises(ParseError) as err:
        parse_films(path)
    assert len(err.value.problems) == 5


# --- Lists -----------------------------------------------------------------------------


def test_lists() -> None:
    data = parse_lists(FIXTURES / "lists.csv")
    assert data.cameras == ["Nikon FM2", "Olympus XA", "Mamiya 645"]  # 'nikon fm2' repeat dropped
    assert data.lenses == ["50mm f/1.8", "35mm f/2", "80mm"]
    assert data.formats == ["35mm", "120", "110"]  # '35' normalised, '35mm' repeat dropped
    assert data.developers == ["HC-110", "Rodinal"]
    assert data.filters == ["Yellow", "Red"]


def test_lists_without_enough_headers(tmp_path: Path) -> None:
    with pytest.raises(ParseError):
        parse_lists(write(tmp_path, "Cameras,Lenses\nA,B\n"))


# --- Bulk ------------------------------------------------------------------------------


def test_bulk_blank_cost_supplier_date_ok() -> None:
    bulk1, bulk2 = parse_bulk(FIXTURES / "bulk.csv")
    assert (bulk1.label, bulk1.film, bulk1.length_mm, bulk1.used_before_mm) == (
        "Bulk 1",
        "Fomapan 100",
        17000,
        9700,
    )
    assert (bulk1.bought_on, bulk1.cost_pence, bulk1.supplier, bulk1.notes) == (
        None,
        None,
        None,
        None,
    )
    assert (bulk2.bought_on, bulk2.cost_pence, bulk2.supplier) == (
        date(2026, 10, 1),
        3000,
        "Analogue Wonderland",
    )


def test_bulk_lengths_in_metres_when_the_header_says_so(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "Bulk,Film,Length (m),Used before (m)\nBulk 1,Fomapan 100,17,9.7\n",
    )
    (row,) = parse_bulk(path)
    assert (row.length_mm, row.used_before_mm) == (17000, 9700)


def test_bulk_needs_length_and_film(tmp_path: Path) -> None:
    path = write(tmp_path, "Bulk,Film,Length\nA,F,0\nB,,100\nC,F,\n")
    with pytest.raises(ParseError) as err:
        parse_bulk(path)
    assert len(err.value.problems) == 3


# --- Purchases -------------------------------------------------------------------------


def test_purchases_kinds() -> None:
    purchase, given, load = parse_purchases(FIXTURES / "purchases.csv")
    assert (purchase.kind, purchase.film, purchase.format, purchase.rolls) == (
        "purchase",
        "Tri-X",
        "35mm",
        5,
    )
    assert (purchase.cost_pence, purchase.supplier) == (2500, "Analogue Wonderland")
    assert (given.kind, given.rolls, given.notes, given.cost_pence) == (
        "given_away",
        -2,
        "Gift",
        None,
    )
    assert (load.kind, load.bulk_label, load.rolls, load.exposures_per_cassette) == (
        "bulk_load",
        "Bulk 1",
        2,
        36,
    )
    assert load.film is None  # the spool decides


def test_purchases_empty_file_with_headers_is_fine(tmp_path: Path) -> None:
    path = write(tmp_path, "Date,Film,Format,Rolls,Cost,Supplier,Bulk roll\n,,,,,,\n")
    assert parse_purchases(path) == []


def test_purchases_problems(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "Date,Film,Format,Rolls,Cost,Bulk roll\n"
        ",Tri-X,35,2,£1,\n"
        "01/01/2026,Tri-X,35,0,£1,\n"
        "01/01/2026,Tri-X,35,2,,\n"
        "01/01/2026,,35,2,£1,\n"
        "01/01/2026,Tri-X,35,-1,,Bulk 1\n",
    )
    with pytest.raises(ParseError) as err:
        parse_purchases(path)
    assert len(err.value.problems) == 5


# --- Dev Times -------------------------------------------------------------------------


def test_dev_time_refs_ignores_logged_block() -> None:
    refs = parse_dev_time_refs(FIXTURES / "dev_times.csv")
    assert [(r.film, r.ei, r.developer, r.minutes) for r in refs] == [
        ("Tri-X", Decimal("400"), "HC-110", Decimal("6.5")),
        ("Tri-X", Decimal("800"), "HC-110", Decimal("8")),
        ("HP5", Decimal("12.5"), "Rodinal", Decimal("11.25")),
    ]
    assert refs[0].notes == "Dil B"
    assert refs[1].notes is None
    assert all(r.minutes != Decimal("9.5") for r in refs)  # the derived logged time


def test_dev_time_refs_problems(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "Film,EI,Developer,Minutes\nA,400,D,\nB,x,D,5\nC,400,D,5.123\nD,400,D,6\n",
    )
    with pytest.raises(ParseError) as err:
        parse_dev_time_refs(path)
    assert len(err.value.problems) == 3


# --- review follow-ups -----------------------------------------------------------------


def test_currency_symbol_alone_is_a_problem_not_a_crash(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no amount"):
        parse_pence("£")
    path = write(tmp_path, "Bulk,Film,Length,Cost\nA,F,100,£\nB,F,100,£5\n")
    with pytest.raises(ParseError) as err:
        parse_bulk(path)
    assert len(err.value.problems) == 1  # row B is fine; row A is reported, not a crash


@pytest.mark.parametrize("text", ["12.50000000000000000000000000001", "0.001", "12.505"])
def test_money_is_never_rounded_into_validity(text: str) -> None:
    with pytest.raises(ValueError):
        parse_pence(text)


def test_lengths_are_never_rounded_into_validity() -> None:
    with pytest.raises(ValueError):
        parse_length_mm("17.00000000000000000000000000001", "m", "length")
    assert parse_length_mm("17.000", "m", "length") == 17000
    with pytest.raises(ValueError):
        parse_length_mm("12.5", "mm", "length")


def test_pence_trailing_zeros_are_fine() -> None:
    assert parse_pence("12.5000") == 1250
    assert parse_pence("£1,200.00") == 120000


def test_one_unreadable_file_does_not_hide_the_others(tmp_path: Path) -> None:
    from app.importer.parse import parse_all

    (tmp_path / "Films.csv").mkdir()  # a directory where a file should be
    with pytest.raises(ParseError) as err:
        parse_all(tmp_path)
    text = "\n".join(err.value.problems)
    assert "Tracker.csv: file not found" in text
    assert "Films.csv: could not read the file" in text
    assert "Lists.csv: file not found" in text  # later files are still checked


def test_unclosed_quote_is_reported_not_swallowed(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "Dev date,Camera,Format,Film,EI,Developer,Notes\n"
        '01/01/2026,A,120,F,100,D,"never closed\n'
        "02/01/2026,A,120,F,100,D,fine\n",
    )
    with pytest.raises(ParseError) as err:
        parse_tracker(path)
    assert "could not read the file" in err.value.problems[0]


def test_multiline_quoted_notes_are_fine(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "Dev date,Camera,Format,Film,EI,Developer,Notes\n"
        '01/01/2026,A,120,F,100,D,"line one\nline two"\n',
    )
    (row,) = parse_tracker(path)
    assert row.notes == "line one\nline two"


def test_tracker_reports_all_bad_fields_in_one_row(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "Dev date,Camera,Format,Film,EI,Developer,Dev time\n32/01/2026,,120,F,fast,D,9.555\n",
    )
    with pytest.raises(ParseError) as err:
        parse_tracker(path)
    (problem,) = err.value.problems
    for expected in ("real date", "no camera", "EI", "development time"):
        assert expected in problem


def test_opening_column_for_any_format_is_read(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "Film,Type,Box ISO,Opening 35mm,Opening 4x5,Opening date\nA,bw,100,0,3,22/11/2026\n",
    )
    _, openings = parse_films(path)
    assert [(o.format, o.rolls) for o in openings] == [("4x5", 3)]  # 'Opening date' is not a count


def test_film_row_with_details_but_no_name_is_reported(tmp_path: Path) -> None:
    path = write(tmp_path, "Film,Type,Box ISO,Opening 35mm\n,bw,400,3\n,,,\nReal,bw,100,\n")
    with pytest.raises(ParseError) as err:
        parse_films(path)
    assert len(err.value.problems) == 1
    assert "line 2" in err.value.problems[0]


def test_lists_header_needs_three_different_lists(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "Camera,Cameras,Camera\nnot,a,header\nCameras,Lenses,Formats\nNikon,50mm,120\n",
    )
    data = parse_lists(path)
    assert (data.cameras, data.lenses, data.formats) == (["Nikon"], ["50mm"], ["120"])


@pytest.mark.parametrize(
    ("header", "value", "expected_mm"),
    [
        ("Length", "17000", 17000),
        ("LengthM", "17", 17000),
        ("Length (m)", "17", 17000),
        ("Length (metres)", "17", 17000),
        ("Length (mm)", "17000", 17000),
        ("LengthMM", "17000", 17000),
    ],
)
def test_bulk_unit_comes_from_the_header_however_it_is_spelt(
    tmp_path: Path, header: str, value: str, expected_mm: int
) -> None:
    (row,) = parse_bulk(write(tmp_path, f"Bulk,Film,{header}\nA,F,{value}\n"))
    assert row.length_mm == expected_mm


def test_bulk_length_in_centimetres_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ParseError):
        parse_bulk(write(tmp_path, "Bulk,Film,Length (cm)\nA,F,1700\n"))


def test_bulk_row_with_details_but_no_label_is_reported(tmp_path: Path) -> None:
    path = write(tmp_path, "Bulk,Film,Length\n,Fomapan,17000\n,,\nOK,Fomapan,17000\n")
    with pytest.raises(ParseError) as err:
        parse_bulk(path)
    assert len(err.value.problems) == 1
    assert "no label" in err.value.problems[0]


def test_bulk_cost_pence_column_is_pence_not_pounds(tmp_path: Path) -> None:
    (row,) = parse_bulk(write(tmp_path, "Bulk,Film,Length,Cost pence\nA,F,100,3000\n"))
    assert row.cost_pence == 3000
    (pounds,) = parse_bulk(write(tmp_path, "Bulk,Film,Length,Cost\nA,F,100,30\n", "b.csv"))
    assert pounds.cost_pence == 3000
    (blank,) = parse_bulk(write(tmp_path, "Bulk,Film,Length,Cost pence\nA,F,100,\n", "c.csv"))
    assert blank.cost_pence is None
    with pytest.raises(ParseError):
        parse_bulk(write(tmp_path, "Bulk,Film,Length,Cost pence\nA,F,100,30.5\n", "d.csv"))


def test_purchase_row_with_data_but_no_date_or_rolls_is_reported(tmp_path: Path) -> None:
    path = write(tmp_path, "Date,Film,Format,Rolls,Cost\n,Tri-X,35,,£25\n,,,,\n")
    with pytest.raises(ParseError) as err:
        parse_purchases(path)
    assert len(err.value.problems) == 1


def test_bulk_load_needs_exposures(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "Date,Rolls,Bulk roll,Exposures\n"
        "01/01/2026,2,Bulk 1,\n"
        "01/01/2026,2,Bulk 1,0\n"
        "01/01/2026,2,Bulk 1,36\n",
    )
    with pytest.raises(ParseError) as err:
        parse_purchases(path)
    assert len(err.value.problems) == 2
    assert "exposures per cassette" in err.value.problems[0]


def test_a_reference_note_starting_with_logged_does_not_end_the_block(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "Notes,Film,EI,Developer,Minutes\n"
        "Logged after test strip,Tri-X,400,HC-110,6\n"
        ",HP5,400,HC-110,7\n"
        ",,,,\n"
        "Logged times,,,,\n"
        ",Tri-X,400,HC-110,99\n",
    )
    refs = parse_dev_time_refs(path)
    assert [(r.film, r.minutes) for r in refs] == [("Tri-X", Decimal("6")), ("HP5", Decimal("7"))]


def test_a_lone_logged_heading_ends_the_block_without_a_blank_row(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "Film,EI,Developer,Minutes\nTri-X,400,HC-110,6\nLogged times,,,\nTri-X,400,HC-110,99\n",
    )
    assert [r.minutes for r in parse_dev_time_refs(path)] == [Decimal("6")]


@pytest.mark.parametrize(
    ("length_header", "used_header", "length", "used", "expected"),
    [
        ("Length", "Used before (millimetres)", "17000", "1000", (17000, 1000)),
        ("Length (millimetres)", "Used before (mm)", "17000", "1000", (17000, 1000)),
        ("Length (metres)", "Used before (metres)", "17", "1.5", (17000, 1500)),
        ("Length (m)", "Used before tracking (mm)", "17", "9700", (17000, 9700)),
        ("Length (mm)", "Used before tracking (m)", "17000", "9.7", (17000, 9700)),
        ("Length", "Used before tracking", "17000", "9700", (17000, 9700)),
    ],
)
def test_bulk_units_for_length_and_used_columns_are_read_independently(
    tmp_path: Path,
    length_header: str,
    used_header: str,
    length: str,
    used: str,
    expected: tuple[int, int],
) -> None:
    path = write(tmp_path, f"Bulk,Film,{length_header},{used_header}\nA,F,{length},{used}\n")
    (row,) = parse_bulk(path)
    assert (row.length_mm, row.used_before_mm) == expected


@pytest.mark.parametrize(
    "header",
    ["Used before (centimetres)", "Used before (cm)", "Used before (kilometres)"],
)
def test_bulk_used_column_in_unsupported_units_is_refused(tmp_path: Path, header: str) -> None:
    with pytest.raises(ParseError):
        parse_bulk(write(tmp_path, f"Bulk,Film,Length,{header}\nA,F,17000,100\n"))


def test_films_side_table_note_is_not_an_opening_count(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "Film,Type,Box ISO,Opening 35mm,Opening 120,,Opening stock counted on,22/11/2026\n"
        "Tri-X,B&W,400,4,0,,Type,35mm in stock\n"
        "HP5,B&W,400,2,1,,B&W,29\n",
    )
    films, openings = parse_films(path)
    assert [f.name for f in films] == ["Tri-X", "HP5"]
    assert [(o.film, o.format, o.rolls) for o in openings] == [
        ("Tri-X", "35mm", 4),
        ("HP5", "35mm", 2),
        ("HP5", "120", 1),
    ]


def test_parse_all_finds_files_named_by_google_sheets(tmp_path: Path) -> None:
    from shutil import copy

    from app.importer.parse import parse_all

    fixtures = Path(__file__).parent / "fixtures"
    for src, name in {
        "tracker.csv": "Tracker.csv",
        "films.csv": "Films.csv",
        "lists.csv": "Lists.csv",
        "bulk.csv": "Bulk.csv",
        "purchases.csv": "Purchases.csv",
        "dev_times.csv": "Dev Times.csv",
    }.items():
        copy(fixtures / src, tmp_path / f"Film Photography Tracker v2 - {name}")
    assert len(parse_all(tmp_path).tracker) == 4
