"""CSV export engine (api-contract v0.2 §§3–7).

One pure row generator plus `neutralize_formula()` (§3 rule 5 / DEC-D-2):
no I/O, no framework imports, unit-testable in isolation (C-9). The route in
`app.main` is the only caller; batching the whole body here keeps generation
all-or-nothing (§7, §6 E-8) and `Content-Length` exact (§2).

Byte profile (§3): plain UTF-8 without BOM, comma separators (rule 4), RFC-4180
minimal quoting (rule 6), CRLF after every record incl. the last (rule 3),
records sorted by id ascending (§5.1 / D-11).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from app.data import Report

HEADER_LABELS = ("id", "title", "owner", "rows")
FORMULA_TRIGGERS = ("=", "+", "-", "@")
# §3.1: exactly these four raw lowercase labels, identical for both roles (D-5).
HEADER_BYTES = ",".join(HEADER_LABELS).encode("utf-8") + b"\r\n"


def neutralize_formula(value: str) -> str:
    """Contract v0.2 §3 rule 5: prefix ONE apostrophe iff the first char is = + - @.

    Pure and byte-preserving otherwise: no other position, no whitespace
    skipping, never a second apostrophe. Called only for text columns; the
    apostrophe alone does not trigger quoting (rule 5 runs before rule 6).
    """
    if value[:1] in FORMULA_TRIGGERS:
        return "'" + value
    return value


def _encode_text(value: str) -> bytes:
    field = neutralize_formula(value)
    if any(ch in field for ch in (",", '"', "\r", "\n")):
        field = '"' + field.replace('"', '""') + '"'
    return field.encode("utf-8")


def _encode_int(value: int) -> bytes:
    # §3.1: plain decimal, never neutralized, never locale-formatted (C-5).
    return str(value).encode("utf-8")


def iter_csv_records(reports: Iterable[Report]) -> Iterator[bytes]:
    """Pure row generator (§7 / C-9): Result of list_reports -> CSV records.

    Sorting by id ascending is normative (D-11(b)), not an accident of input
    order; the sort is stable, so equal ids keep input order deterministically.
    """
    for report in sorted(reports, key=lambda r: r.id):
        yield (
            b",".join(
                (
                    _encode_int(report.id),
                    _encode_text(report.title),
                    _encode_text(report.owner),
                    _encode_int(report.rows),
                )
            )
            + b"\r\n"
        )


def render_csv_bytes(reports: Iterable[Report]) -> bytes:
    """Full batch body (§7 / D-14): header + all records; header-only when empty (§6 E-4)."""
    return HEADER_BYTES + b"".join(iter_csv_records(reports))
