"""Unit tests for the CSV engine in isolation (api-contract v0.2 §3, §5.1, §7, §8).

`neutralize_formula()` is tested on its own first (rule 5), then the pure row
generator's quoting/ordering/encoding profile, with no framework in the loop.
"""

from __future__ import annotations

import pytest

from app.csv_export import HEADER_BYTES, iter_csv_records, neutralize_formula, render_csv_bytes
from app.data import Report

# --- neutralize_formula: §3 rule 5 (DEC-D-2), ONE pure function ---------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("=1+1", "'=1+1"),  # §8 corpus case: exports as '=1+1
        ("+p", "'+p"),
        ("-m", "'-m"),
        ("@r", "'@r"),
        ("=", "'="),
        ("==", "'=="),  # one apostrophe only, never a second
        ("SUM(1,2)", "SUM(1,2)"),  # no trigger char at all
        ("x=y", "x=y"),  # trigger mid-string: first char only
        ("a-b", "a-b"),  # '-' is a trigger only at position 0
        (" =1", " =1"),  # leading whitespace is the first char: no prefix
        ("'dyld", "'dyld"),  # already apostrophe-prefixed: unchanged
        ("", ""),  # empty: no first char
        ("ü=nicode", "ü=nicode"),  # non-ASCII first char: unchanged
    ],
)
def test_neutralize_formula_exact_rule(value: str, expected: str) -> None:
    assert neutralize_formula(value) == expected


def test_neutralize_formula_is_pure_and_single_prefix() -> None:
    # calling twice must not double-prefix (the guard is on the FIRST char,
    # and a leading apostrophe is not a trigger).
    once = neutralize_formula("=cmd|'/c calc'")
    assert neutralize_formula(once) == once == "'=cmd|'/c calc'"


# --- field serialization: rule 5 BEFORE rule 6, interplay untouched -----------


def test_neutralized_apostrophe_never_triggers_quoting_alone() -> None:
    assert render_csv_bytes([Report(1, "=1+1", "ops", 4)]) == (HEADER_BYTES + b"1,'=1+1,ops,4\r\n")


def test_neutralize_then_quote_order_is_normative() -> None:
    # '=a"b contains a quote => quoted as a whole; the apostrophe sits outside.
    body = render_csv_bytes([Report(1, '=a"b', "ops", 0)])
    assert body.endswith(b'1,"\'=a""b",ops,0\r\n')


def test_text_needing_quoting_without_trigger_is_untouched_by_rule5() -> None:
    body = render_csv_bytes([Report(1, '"raw"', "o,wner", 5)])
    assert body == HEADER_BYTES + b'1,"""raw""","o,wner",5\r\n'


def test_integer_columns_are_never_neutralized_or_quoted() -> None:
    # §3.1: ints are plain decimal even when the value stringifies to "-5"
    # (current data never produces negatives; the rule is what is pinned).
    body = render_csv_bytes([Report(-5, "t", "o", -1200)])
    assert body == HEADER_BYTES + b"-5,t,o,-1200\r\n"


def test_crlf_separators_and_embedded_lf_coexist() -> None:
    # §3 rule 8: an embedded LF stays a bare LF inside the quoted field;
    # record terminators remain CRLF.
    body = render_csv_bytes([Report(1, "a\nb\r\nc", "ops", 1)])
    assert body == HEADER_BYTES + b'1,"a\nb\r\nc",ops,1\r\n'
    assert body.endswith(b"\r\n")


def test_blank_text_stays_blank_field() -> None:
    assert render_csv_bytes([Report(1, "", "", 0)]) == HEADER_BYTES + b"1,,,0\r\n"


def test_unicode_is_utf8_as_stored() -> None:
    body = render_csv_bytes([Report(9, "表单 📊", "Ärende", 1)])
    assert body == HEADER_BYTES + "9,表单 📊,Ärende,1\r\n".encode()


# --- pure row generator: §5.1 order, §7 batch shape ---------------------------


def test_empty_input_yields_no_records_and_header_only_21_bytes() -> None:
    assert list(iter_csv_records([])) == []
    assert render_csv_bytes([]) == b"id,title,owner,rows\r\n"
    assert len(render_csv_bytes([])) == 21  # §6 E-4 byte pin


def test_records_sorted_by_id_ascending_not_input_order() -> None:
    reports = [Report(4, "d", "o", 4), Report(1, "a", "o", 1), Report(10, "c", "o", 3)]
    ids = [line.split(b",", 1)[0] for line in iter_csv_records(reports)]
    assert ids == [b"1", b"4", b"10"]  # numeric sort, not lexicographic


def test_real_data_layer_projected_to_contract_3_2_bytes() -> None:
    from app.data import list_reports

    assert render_csv_bytes(list_reports("admin")) == (
        b"id,title,owner,rows\r\n"
        b"1,Monthly usage,ops,1200\r\n"
        b"2,Error budget,sre,48\r\n"
        b"3,Payroll summary,finance,310\r\n"
        b"4,Signup funnel,growth,5200\r\n"
    )
    assert render_csv_bytes(list_reports("viewer")) == (
        b"id,title,owner,rows\r\n"
        b"1,Monthly usage,ops,1200\r\n"
        b"2,Error budget,sre,48\r\n"
        b"4,Signup funnel,growth,5200\r\n"
    )


def test_generation_is_a_pure_function_of_inputs() -> None:
    from app.data import list_reports

    first = render_csv_bytes(list_reports("admin"))
    second = render_csv_bytes(list_reports("admin"))
    assert first == second  # §4 byte determinism at the engine level
