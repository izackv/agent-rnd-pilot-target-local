"""Acceptance-plan §3 (AGEA-16 / W6) — the 17 cell-safety vectors, machine oracle.

Every integrity claim is made by parsing the served bytes with the **real `csv`
module** (strict dialect) and comparing parsed fields structurally against
`tests/fixtures/adversarial_reports.json`; raw-byte matching appears only in the
two §4-authorized byte pins (the adversarial fixture file and the 200-E empty
file). The fixture is injected through the data layer only (contract C-7 — no
production seam).

Contract citations: v0.2 §3 rules 1-8, §3.1, §4, §6 E-4/E-8, §8 adversarial
fixture. Vector ids V-1…V-17 are the acceptance-plan's.
"""

from __future__ import annotations

import csv
import io
import json
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import data
from app.data import Report
from app.main import app

client = TestClient(app)
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

TRIGGER_CHARS = ("=", "+", "-", "@")
RESTRICTED_ROW_FIELD_VALUES = {"3", "Payroll summary", "finance", "310"}
HEADER_LABELS = ["id", "title", "owner", "rows"]


def load_fixture_records() -> list[dict]:
    return json.loads((FIXTURES / "adversarial_reports.json").read_text("utf-8"))["records"]


def expected_api_bytes() -> bytes:
    return (FIXTURES / "adversarial_expected_api.csv").read_bytes()


@pytest.fixture
def adversarial(monkeypatch) -> list[dict]:
    records = load_fixture_records()
    monkeypatch.setattr(
        data,
        "_REPORTS",
        [Report(r["id"], r["title"], r["owner"], r["rows"], r["restricted"]) for r in records],
    )
    return records


def parse(body: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(body.decode("utf-8"), newline=""), strict=True))


def admin_csv(client_: TestClient | None = None) -> bytes:
    c = client_ or client
    r = c.get("/api/reports.csv", headers={"X-Role": "admin"})
    assert r.status_code == 200
    return r.content


# --- the fixture's byte shape (both D-3 paths pinned from one artifact) ------------------


def test_api_bytes_equal_the_fixture_file_no_bom(adversarial) -> None:
    body = admin_csv()
    expected = expected_api_bytes()
    assert body == expected  # §4 byte pin (allowed for fixture bytes)
    assert not body.startswith(b"\xef\xbb\xbf")  # §3 rule 1 / D-3: API path has NO BOM
    assert body.count(b"\xef\xbb\xbf") == 0
    r = client.get("/api/reports.csv", headers={"X-Role": "admin"})
    assert r.headers["content-length"] == str(len(expected))


def test_expected_parsed_cells_match_fixture_field_by_field(adversarial) -> None:
    # V-1…V-13, V-17 across the board: parse == the fixture's documented export text.
    table = {rec[0]: rec for rec in parse(admin_csv())[1:]}
    for entry in adversarial:
        row = table[str(entry["id"])]
        assert len(row) == 4
        assert row[0] == str(entry["id"])
        assert row[1] == entry["export"]["title"], f"V-check id {entry['id']}"
        assert row[2] == entry["export"]["owner"], f"V-check id {entry['id']}"
        assert row[3] == str(entry["rows"])


def test_v17_header_record_is_the_four_ascii_labels(adversarial) -> None:
    header = parse(admin_csv())[0]
    assert header == HEADER_LABELS
    assert all(all(ord(ch) < 128 for ch in field) for field in header)


def test_formula_neutralization_vectors(adversarial) -> None:
    # V-10 (=1+1, +1, -1, @-prefix), V-11 (DDE), V-12 (HYPERLINK): exactly one
    # leading apostrophe, text otherwise identical to the source.
    table = {rec[0]: rec for rec in parse(admin_csv())[1:]}
    raw = {e["id"]: e for e in adversarial}
    for rid in (20, 21, 22, 23, 24, 25):
        exported = table[str(rid)][1]
        source = raw[rid]["title"]
        assert exported == "'" + source
        assert exported.count("'") == source.count("'") + 1  # ONE prefix, never more
    # V-13: TAB-prefixed bypass — first char is TAB, NOT neutralized (rule 5).
    assert table["26"][1] == "\t=1+1"


def test_no_cell_anywhere_starts_with_a_formula_trigger(adversarial) -> None:
    for rec in parse(admin_csv()):
        for field in rec:
            assert not field.startswith(TRIGGER_CHARS), rec


def test_app_text_unchanged_while_export_neutralized(adversarial) -> None:
    # SC-7 deviation note (§3.1): the table/JSON still shows the raw "=1+1".
    listed = {x["id"]: x for x in client.get("/api/reports", headers={"X-Role": "admin"}).json()}
    assert listed[20]["title"] == "=1+1"
    assert "'=1+1" not in json.dumps(listed)


def test_v1_v2_quoting_oracles(adversarial) -> None:
    table = {rec[0]: rec for rec in parse(admin_csv())[1:]}
    assert table["11"][1] == "Signup funnel, weekly"  # V-1: one cell, row not split
    assert table["12"][1] == 'Q3 "peak" load'  # V-2: doubled quotes collapse once
    assert len(table["11"]) == len(table["12"]) == 4


def test_v3_v4_v5_embedded_line_breaks_stay_one_record(adversarial) -> None:
    # Rule 8 "as stored": no silent normalization; record count proves no split.
    records = parse(admin_csv())
    assert len(records) == 1 + len(adversarial)
    table = {rec[0]: rec for rec in records[1:]}
    assert table["13"][1] == "Line1\nLine2"  # V-3 LF
    assert table["14"][1] == "Header\r\nFooter"  # V-4 CRLF inside a quoted cell
    assert table["15"][1] == "A\rB"  # V-5 lone CR


def test_v6_v7_utf8_roundtrip(adversarial) -> None:
    table = {rec[0]: rec for rec in parse(admin_csv())[1:]}
    assert table["16"][1] == "Ärende, Södertälje"
    assert table["16"][2] == "södertälje"
    assert table["17"][1] == "表单 📊"


def test_v8_v9_spaces_and_empty_fields(adversarial) -> None:
    table = {rec[0]: rec for rec in parse(admin_csv())[1:]}
    assert table["18"][1] == "  spaced  "  # byte-unmodified: spaces are not a quote trigger
    assert len(table["19"]) == 4  # V-9: blank fields, all four columns survive
    assert table["19"][1] == "" and table["19"][2] == ""


def test_v14_watcher_int_fields_are_plain_decimals(adversarial) -> None:
    # V-14 is structurally N/A for current data types (contract §3.1 note) — the
    # watcher asserts the serializer emits no leading zeros / separators.
    int_ok = re.compile(r"\A(0|-?[1-9][0-9]*)\Z")
    for rec in parse(admin_csv())[1:]:
        assert int_ok.match(rec[0]) and int_ok.match(rec[3]), rec


def test_fixture_reaches_the_json_source_too(adversarial) -> None:
    # review N6: one mocked source feeds both surfaces — assert once at this layer
    # (same fixture must also reach the rendered page; that half is pinned in e2e).
    csv_ids = sorted(int(rec[0]) for rec in parse(admin_csv())[1:])
    listed = client.get("/api/reports", headers={"X-Role": "admin"}).json()
    assert csv_ids == sorted(x["id"] for x in listed)


def test_viewer_export_has_no_restricted_row_structurally(adversarial) -> None:
    records = parse(client.get("/api/reports.csv").content)
    assert [rec[0] for rec in records[1:]] == [str(i) for i in range(11, 16)] + [
        str(i) for i in range(16, 27)
    ]
    for rec in records:
        assert not set(rec) & RESTRICTED_ROW_FIELD_VALUES  # structural, whole-cell (N1)


def test_record_terminator_profile(adversarial) -> None:
    # §3 rule 3 (D-4a): the separators BETWEEN and AFTER records are CRLF, and
    # nothing follows the last record. Line breaks inside quoted cells (V-3…V-5)
    # are "as stored" (rule 8), so this asserts the profile OUTSIDE quoted fields.
    body = admin_csv()
    assert body.endswith(b"\r\n")
    outside_quoted = re.sub(rb'"[^"]*(?:""[^"]*)*"', b"Q", body)
    assert re.fullmatch(rb"(?:[^\r\n]*\r\n)+", outside_quoted), (
        "every unquoted line break must be a CRLF record terminator"
    )


# --- V-15 / V-16: length and volume boundaries (synthetic, §9 boundary row) --------------


@pytest.mark.parametrize("length", [32767, 32768])
def test_v15_host_cell_limit_bytes_are_not_truncated(monkeypatch, length: int) -> None:
    big = "x" + "y" * (length - 1)  # no trigger char; pure length probe
    monkeypatch.setattr(data, "_REPORTS", [Report(9_100_001, big, "ops", 1)])
    body = admin_csv()
    table = parse(body)
    assert len(table) == 2 and len(table[1]) == 4
    assert len(table[1][1]) == length  # brief §4.6: no silent truncation
    assert big.encode("utf-8") in body


def test_v16_ten_thousand_rows_complete_sorted_deterministic(monkeypatch) -> None:
    n = 10_000
    monkeypatch.setattr(
        data, "_REPORTS", [Report(i, f"Report {i}", "ops", i * 2 % 9973) for i in range(1, n + 1)]
    )
    started = time.monotonic()
    body = admin_csv()
    r2 = client.get("/api/reports.csv", headers={"X-Role": "admin"})
    assert r2.content == body  # §4 determinism, big input
    records = parse(body)
    assert len(records) == n + 1, "all 10k records parse — nothing dropped"
    ids = [int(rec[0]) for rec in records[1:]]
    assert ids == list(range(1, n + 1)), "id-ascending (D-11/b) under volume"
    assert time.monotonic() - started < 5.0, "10k-row export envelope < 5s locally (§9 perf)"


# --- J-05 / E-4: the empty result, both byte profiles pinned (D-10a + D-3) ----------------


def test_j05_empty_export_is_200_header_only_21_bytes(monkeypatch) -> None:
    monkeypatch.setattr(data, "list_reports", lambda role=data.ROLE_VIEWER: [])
    r = client.get("/api/reports.csv", headers={"X-Role": "admin"})
    assert r.status_code == 200
    assert r.content == b"id,title,owner,rows\r\n"  # §4 byte pin for the empty file
    assert len(r.content) == 21
    assert r.headers["content-length"] == "21"
    assert parse(r.content) == [HEADER_LABELS]  # parses to a header-only table
    # download path (D-3/C-10) = BOM + the same 21 bytes = 24 bytes; the live
    # BOM + API equality for non-empty bodies is asserted in tests/e2e.
    assert len(b"\xef\xbb\xbf" + r.content) == 24
