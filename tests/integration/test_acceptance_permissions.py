"""Acceptance-plan §2 (AGEA-16 / W6) — permission matrix P-1…P-8 and the
restricted-attempt attack list, run against merged `main` (contract v0.2).

The matrix tests the *rule*, not a memory of framework resolution semantics
(acceptance-plan §2): every row asserts CSV-id-set == JSON-id-set for the same
transport AND that the CSV bytes are byte-equal to one of the two frozen byte
sets (viewer/admin). CSV assertions go through the real `csv` module — never
substring matching — with the sole exception of the §4 byte pins the contract
allows (contract v0.2 §4).

G-1 (contract §6 E-1/E-2): no response in this whole suite may be 401 or 403;
that negative is asserted inside the request helper, so every call is covered.
"""

from __future__ import annotations

import csv
import io
import re

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

ADMIN_IDS = [1, 2, 3, 4]
VIEWER_IDS = [1, 2, 4]
RESTRICTED_ROW_FIELD_VALUES = {"3", "Payroll summary", "finance", "310"}

ADMIN_BYTES = (
    b"id,title,owner,rows\r\n"
    b"1,Monthly usage,ops,1200\r\n"
    b"2,Error budget,sre,48\r\n"
    b"3,Payroll summary,finance,310\r\n"
    b"4,Signup funnel,growth,5200\r\n"
)

VIEWER_BYTES = (
    b"id,title,owner,rows\r\n"
    b"1,Monthly usage,ops,1200\r\n"
    b"2,Error budget,sre,48\r\n"
    b"4,Signup funnel,growth,5200\r\n"
)

DISPOSITION_RE = re.compile(r'^attachment; filename="reports(-\d{4}-\d{2}-\d{2})?\.csv"$')


def get_csv(path: str = "/api/reports.csv", **kw):
    """Every CSV-layer response must dodge the two error shapes that do not exist."""
    r = client.get(path, **kw)
    assert r.status_code not in (401, 403), f"G-1 violated: {r.status_code} on {path}"
    return r


def get_json(path: str = "/api/reports", **kw):
    r = client.get(path, **kw)
    assert r.status_code not in (401, 403), f"G-1 violated: {r.status_code} on {path}"
    return r


def parsed_records(body: bytes) -> list[list[str]]:
    """Real csv-module parse (acceptance-plan §3 oracle 1); strict dialect."""
    text = body.decode("utf-8")
    return list(csv.reader(io.StringIO(text, newline=""), strict=True))


def csv_ids(body: bytes) -> list[int]:
    return [int(rec[0]) for rec in parsed_records(body)[1:]]


def assert_csv_headers_200(r) -> None:
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["vary"] == "X-Role"
    assert DISPOSITION_RE.match(r.headers["content-disposition"])
    assert r.headers["content-length"] == str(len(r.content))


# --- §2 permission matrix: (case, csv transport, json transport) -------------------------
# Role-resolution expectations in the acceptance-plan's table are NOT pinned here;
# the frozen rule is "export set ≡ list visibility for the same header" (§5.1, C-2).
# P-8's parenthetical ("FastAPI folds to 'admin, admin' ⇒ viewer") was written at plan
# time; on the installed stack (starlette 1.7.0) duplicated X-Role yields *admin* —
# identically for both routes, which is exactly what the parity rule requires, so the
# plan's own rule ("the matrix tests the rule, not my memory") governs the assertion.

MATRIX_CASES = {
    "P-1-absent": ({}, {}),
    "P-2-viewer": ({"headers": {"X-Role": "viewer"}}, {"headers": {"X-Role": "viewer"}}),
    "P-3-admin": ({"headers": {"X-Role": "admin"}}, {"headers": {"X-Role": "admin"}}),
    "P-4-ADMIN": ({"headers": {"X-Role": "ADMIN"}}, {"headers": {"X-Role": "ADMIN"}}),
    "P-5-trailing-space": ({"headers": {"X-Role": "admin "}}, {"headers": {"X-Role": "admin "}}),
    "P-6-leading-space": ({"headers": {"X-Role": " admin"}}, {"headers": {"X-Role": " admin"}}),
    "P-7-empty-value": ({"headers": {"X-Role": ""}}, {"headers": {"X-Role": ""}}),
    # duplicate-header transport (two raw lines, not a comma-joined single value)
    "P-8-duplicated": (
        {"headers": [("X-Role", "admin"), ("X-Role", "admin")]},
        {"headers": [("X-Role", "admin"), ("X-Role", "admin")]},
    ),
}


@pytest.mark.parametrize("case", sorted(MATRIX_CASES))
def test_permission_matrix_row(case: str) -> None:
    csv_kw, json_kw = MATRIX_CASES[case]
    r_csv, r_json = get_csv(**csv_kw), get_json(**json_kw)

    ids = csv_ids(r_csv.content)
    json_ids = [x["id"] for x in r_json.json()]
    assert set(ids) == set(json_ids), "export visibility must equal list visibility (§5.1)"
    assert ids == sorted(ids) and len(ids) == len(set(ids)), "id-ascending, no dupes (D-11)"

    # both byte sets: whatever the transport resolves to, the bytes are one of the
    # two frozen bodies — never a mix, never an extra or placeholder row.
    if ids == ADMIN_IDS:
        assert r_csv.content == ADMIN_BYTES
    else:
        assert ids == VIEWER_IDS
        assert r_csv.content == VIEWER_BYTES
    assert_csv_headers_200(r_csv)


def test_matrix_case_labels_match_plan_expectations_where_frozen() -> None:
    # Rows the plan pins as viewer-default traps (P-1, P-2, P-4…P-7): explicit set
    # equality, independent of the parity rule above (acceptance-plan §2 table).
    for kw in ({}, {"headers": {"X-Role": "viewer"}}, {"headers": {"X-Role": "ADMIN"}},
               {"headers": {"X-Role": "admin "}}, {"headers": {"X-Role": " admin"}},
               {"headers": {"X-Role": ""}}):
        assert csv_ids(get_csv(**kw).content) == VIEWER_IDS
    assert csv_ids(get_csv(headers={"X-Role": "admin"}).content) == ADMIN_IDS


# --- §2 restricted-attempt attack list (viewer caller) ------------------------------------


def assert_viewer_or_catalog_error(r, *, form: str) -> None:
    """Each form: the ordinary viewer CSV or a §4 catalog error — never restricted
    bytes, never existence info, and (G-1) never 401/403."""
    assert r.status_code not in (401, 403), form
    if r.status_code == 200:
        assert r.headers["content-type"] == "text/csv; charset=utf-8", form
        assert csv_ids(r.content) == VIEWER_IDS, f"attack leaked non-viewer set: {form}"
        for rec in parsed_records(r.content):
            assert not RESTRICTED_ROW_FIELD_VALUES & set(rec), form
        assert len(r.content) == len(VIEWER_BYTES), form
    else:
        assert r.status_code in (404, 405), f"off-catalog status {r.status_code}: {form}"


ATTACK_FORMS_GET = [
    ("/api/reports.csv?role=admin", {}, "query ?role=admin"),
    ("/api/reports.csv?include_restricted=1", {}, "query ?include_restricted=1"),
    ("/api/reports.csv?format=csv", {}, "query ?format=csv"),
    ("/api/reports.csv;admin", {}, "path append ;admin"),
    ("/admin/reports.csv", {}, "path reorder /admin/reports.csv"),
    ("/api/reports.csv", {"X-Role": "administrator"}, 'header "administrator"'),
    ("/api/reports.csv", {"Cookie": "role=admin"}, "cookie role=admin"),
    ("/api/reports.csv", {"X-HTTP-Method-Override": "POST"}, "method-override header"),
]


@pytest.mark.parametrize("path,extra,form", ATTACK_FORMS_GET, ids=[a[2] for a in ATTACK_FORMS_GET])
def test_attack_form_yields_viewer_csv_or_catalog_error(path: str, extra: dict, form: str) -> None:
    assert_viewer_or_catalog_error(get_csv(path, headers=extra), form=form)


def test_post_then_get_sequence_is_viewer_only() -> None:
    # POST→GET confusion (E-6/§2): POST is 405 framework JSON; a following plain
    # GET (no header) is still exactly the viewer file.
    r = client.post("/api/reports.csv")
    assert r.status_code == 405, "POST must be a §4 catalog error"
    assert_viewer_or_catalog_error(get_csv(), form="GET after POST")


@pytest.mark.parametrize("method", ["put", "delete", "patch", "options"])
def test_other_methods_are_framework_405_not_csv(method: str) -> None:
    r = getattr(client, method)("/api/reports.csv", headers={"X-Role": "admin"})
    assert r.status_code not in (401, 403)
    assert r.status_code == 405
    assert r.headers["content-type"] == "application/json"
    assert r.content == b'{"detail":"Method Not Allowed"}'


def test_head_is_framework_default_and_leaks_nothing() -> None:
    # E-6 "HEAD check (framework default)": on this stack FastAPI's APIRoute
    # declares no HEAD for a GET route ⇒ 405, in-catalog and body-light.
    r = client.head("/api/reports.csv", headers={"X-Role": "admin"})
    assert r.status_code not in (401, 403)
    assert r.status_code in (200, 405)
    assert r.content == b""


def test_viewer_navigating_directly_yields_exactly_the_viewer_file() -> None:
    # §5.3/D-13(i) proof: a header-less (navigation-shaped) request is byte-equal
    # to the viewer file — the button path added no new authority input.
    r = get_csv()
    assert_csv_headers_200(r)
    assert r.content == VIEWER_BYTES


# --- §2 caching vector + determinism -----------------------------------------------------


def test_no_store_and_vary_on_every_200_csv() -> None:
    for headers in ({}, {"X-Role": "viewer"}, {"X-Role": "admin"}):
        r = get_csv(headers=headers)
        assert r.headers["cache-control"] == "no-store"
        assert r.headers["vary"] == "X-Role"


def test_double_fetch_is_byte_identical_per_role() -> None:
    # contract §4: the CSV analogue of SC-10's byte pin.
    for headers in ({}, {"X-Role": "admin"}):
        bodies = {get_csv(headers=headers).content for _ in range(2)}
        assert len(bodies) == 1


# --- no-existence-leak residue under D-9(a) (contract §1.2, §5.2) -------------------------


def test_paths_by_id_csv_suffix_indistinguishable_restricted_vs_absent() -> None:
    # D-9(a): there is no per-id export surface; /api/reports/<id>.csv falls through
    # to the JSON {report_id} int-parsing shape (422, E-5b family) identically for a
    # RESTRICTED id and an ABSENT id — one undifferentiated error, no existence info,
    # no CSV bytes (§5.2). The acceptance-plan's D-9(b)-shaped 404 byte-identity
    # vector has no surface to act on under the decided D-9(a) (contract §1.2).
    r_restricted = get_csv("/api/reports/3.csv", headers={})
    r_absent = get_csv("/api/reports/999999.csv", headers={})
    r_typo = get_csv("/api/reports/xyzzy.csv", headers={})
    assert r_restricted.status_code == r_absent.status_code == 422
    bodies = [r.json()["detail"][0] for r in (r_restricted, r_absent, r_typo)]
    assert all(b["type"] == "int_parsing" for b in bodies), (
        "request-shape rejection happens before the data layer — one undifferentiated "
        "422 that cannot tell restricted id 3 from absent id 999999 or from a typo"
    )
    assert not RESTRICTED_ROW_FIELD_VALUES & {str(b) for b in bodies}
    csv = r_restricted.headers.get("content-type", "")
    assert "text/csv" not in csv
    for marker in (b"Payroll", b"finance"):
        assert marker not in r_restricted.content


def test_json_route_404_shaped_identically_for_viewer_restricted_and_absent() -> None:
    r_restricted = get_json("/api/reports/3", headers={})
    r_absent = get_json("/api/reports/999999", headers={})
    assert r_restricted.status_code == r_absent.status_code == 404
    assert r_restricted.content == r_absent.content  # no existence info (§5.2)


def test_json_route_noninteger_id_is_422_framework_shape() -> None:
    # E-5b parity: today's /api/reports/abc behavior must be untouched by export work.
    r = get_json("/api/reports/abc")
    assert r.status_code not in (401, 403)
    assert r.status_code == 422
    assert "detail" in r.json()


def test_unknown_path_is_catalog_404_and_the_baseline_fail_shape() -> None:
    # E-7 doubles as the seeded-defect baseline: at 2664b63 *every* test in this
    # file that requires 200 fails against exactly this response.
    r = get_csv("/api/reports.csv.typo")
    assert r.status_code == 404
    assert r.content == b'{"detail":"Not Found"}'
