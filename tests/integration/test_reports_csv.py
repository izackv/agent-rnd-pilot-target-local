"""Byte pins for `GET /api/reports.csv` — real engine (api-contract v0.2 §§1–8).

The admin/viewer constants below are the §3.2/§8 expectation pins kept from the
stub; the route now generates those bytes through app/csv_export.py from the
real data layer.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app import data
from app.main import app

client = TestClient(app)

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

DISPOSITION_RE = re.compile(r'^attachment; filename="reports-(\d{4})-(\d{2})-(\d{2})\.csv"$')


def _expected_utc_dates() -> set[str]:
    today = datetime.now(UTC).date()
    return {today.isoformat(), (today - timedelta(days=1)).isoformat()}


def _assert_headers(r, body: bytes) -> None:
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["vary"] == "X-Role"
    m = DISPOSITION_RE.match(r.headers["content-disposition"])
    assert m, r.headers["content-disposition"]
    assert f"{m.group(1)}-{m.group(2)}-{m.group(3)}" in _expected_utc_dates()
    assert r.headers["content-length"] == str(len(body))


def test_admin_bytes_are_the_contract_3_2_worked_example():
    r = client.get("/api/reports.csv", headers={"X-Role": "admin"})
    _assert_headers(r, ADMIN_BYTES)
    assert r.content == ADMIN_BYTES


def test_viewer_bytes_are_the_contract_8_fixture_1_2_4():
    r = client.get("/api/reports.csv", headers={"X-Role": "viewer"})
    _assert_headers(r, VIEWER_BYTES)
    assert r.content == VIEWER_BYTES


def test_no_bom_and_crlf_terminated():
    for headers in ({"X-Role": "admin"}, {"X-Role": "viewer"}):
        body = client.get("/api/reports.csv", headers=headers).content
        assert not body.startswith(b"\xef\xbb\xbf")
        assert body.startswith(b"id,title,owner,rows\r\n")
        assert body.endswith(b"\r\n")
        assert b"\n" not in body.replace(b"\r\n", b"")  # every LF is part of a CRLF


def test_missing_x_role_serves_viewer_bytes_parity_with_list():
    r = client.get("/api/reports.csv")
    _assert_headers(r, VIEWER_BYTES)
    assert r.content == VIEWER_BYTES
    assert [x["id"] for x in client.get("/api/reports").json()] == [1, 2, 4]


def test_admin_role_value_is_case_sensitive_and_untrimmed():
    # contract v0.2 §1.1: anything other than exactly "admin" => viewer.
    for value in ("Admin", " Admin", "admin ", "ADMIN", "anything-else", ""):
        r = client.get("/api/reports.csv", headers={"X-Role": value})
        assert r.content == VIEWER_BYTES, value


def test_id_set_equals_json_list_for_every_header_variant():
    # contract v0.2 §5.1 QA formulation: CSV ids == /api/reports ids per header,
    # and the CSV id sequence is strictly ascending.
    for headers in (None, {"X-Role": "viewer"}, {"X-Role": "admin"}, {"X-Role": "whatever"}):
        req_headers = headers or {}
        csv_ids = [
            int(line.split(",", 1)[0])
            for line in client.get("/api/reports.csv", headers=req_headers)
            .content.decode()
            .removeprefix("id,title,owner,rows\r\n")
            .splitlines()
        ]
        json_ids = [x["id"] for x in client.get("/api/reports", headers=req_headers).json()]
        assert set(csv_ids) == set(json_ids)
        assert csv_ids == sorted(csv_ids) and len(set(csv_ids)) == len(csv_ids)


def test_unknown_query_params_are_ignored():
    r = client.get("/api/reports.csv?format=json&include_restricted=true")
    assert r.status_code == 200
    assert r.content == VIEWER_BYTES


# --- §5: export set ≡ list visibility, no existence leak ----------------------------


def test_viewer_export_contains_no_restricted_report_by_title_or_flag() -> None:
    for headers in ({}, {"X-Role": "viewer"}, {"X-Role": "nope"}):
        body = client.get("/api/reports.csv", headers=headers).content
        assert b"Payroll" not in body
        assert b"restricted" not in body.lower()


def test_admin_export_equals_admin_list_projection() -> None:
    listed = client.get("/api/reports", headers={"X-Role": "admin"}).json()
    exported = client.get("/api/reports.csv", headers={"X-Role": "admin"}).content.decode()
    for item in listed:
        assert f"{item['id']},{item['title']},{item['owner']},{item['rows']}\r\n" in exported


def test_export_uses_the_same_list_reports_function_as_the_json_route(monkeypatch) -> None:
    calls: list[str] = []
    real = data.list_reports

    def spy(role: str = data.ROLE_VIEWER) -> list[data.Report]:
        calls.append(role)
        return real(role)

    monkeypatch.setattr(data, "list_reports", spy)
    client.get("/api/reports.csv", headers={"X-Role": "admin"})
    client.get("/api/reports", headers={"X-Role": "admin"})
    assert calls == ["admin", "admin"]  # no re-implemented filter in the export path


# --- §6 error catalog (byte-exact framework shapes) ----------------------------------


def test_e4_empty_result_is_header_only_21_bytes_200(monkeypatch) -> None:
    monkeypatch.setattr(data, "list_reports", lambda role=data.ROLE_VIEWER: [])
    r = client.get("/api/reports.csv", headers={"X-Role": "admin"})
    assert r.status_code == 200
    assert r.content == b"id,title,owner,rows\r\n"
    assert len(r.content) == 21
    assert r.headers["content-length"] == "21"
    assert r.headers["content-type"] == "text/csv; charset=utf-8"


def test_e6_unsupported_method_is_framework_405_json() -> None:
    for method in ("post", "put", "delete", "patch"):
        r = getattr(client, method)("/api/reports.csv")
        assert r.status_code == 405, method
        assert r.headers["content-type"] == "application/json"
        assert r.content == b'{"detail":"Method Not Allowed"}'


def test_route_declares_only_the_contracted_get_method() -> None:
    # §1.1/§6 E-6: no extra verbs are special-cased; responses ride framework defaults.
    methods = {
        m
        for route in app.routes
        if getattr(route, "path", None) == "/api/reports.csv"
        for m in route.methods
    }
    assert methods == {"GET"}


def test_e7_unknown_path_is_framework_404_json() -> None:
    r = client.get("/api/reportsCSV")
    assert r.status_code == 404
    assert r.content == b'{"detail":"Not Found"}'


def test_e8_generation_failure_is_plain_500_with_zero_csv_bytes(monkeypatch) -> None:
    def boom(role: str = data.ROLE_VIEWER) -> list[data.Report]:
        raise RuntimeError("generator exploded")

    monkeypatch.setattr(data, "list_reports", boom)
    r = TestClient(app, raise_server_exceptions=False).get("/api/reports.csv")
    assert r.status_code == 500
    assert r.headers["content-type"] == "text/plain; charset=utf-8"
    assert r.content == b"Internal Server Error"


# --- §8 adversarial corpus through the real engine -----------------------------------


CORPUS = [
    data.Report(1, "Signup funnel, weekly", "growth", 5200),
    data.Report(2, 'Q3 "peak" load', "sre", 48),
    data.Report(3, "two\nlines", "ops-a\nops-b", 7),
    data.Report(4, "  spaced  ", "ops", 1),
    data.Report(5, "", "", 0),
    data.Report(6, "Ärende, Södertälje", "ärende", 2),
    data.Report(7, "表单 📊", "ops", 3),
    data.Report(10, "=1+1", "+root", 10),
]

CORPUS_BYTES = (
    b"id,title,owner,rows\r\n"
    b'1,"Signup funnel, weekly",growth,5200\r\n'
    b'2,"Q3 ""peak"" load",sre,48\r\n'
    b'3,"two\nlines","ops-a\nops-b",7\r\n'
    b"4,  spaced  ,ops,1\r\n"
    b"5,,,0\r\n"
    b'6,"\xc3\x84rende, S\xc3\xb6dert\xc3\xa4lje",\xc3\xa4rende,2\r\n'
    b"7,\xe8\xa1\xa8\xe5\x8d\x95 \xf0\x9f\x93\x8a,ops,3\r\n"
    b"10,'=1+1,'+root,10\r\n"
)


def _serve_corpus(monkeypatch) -> TestClient:
    monkeypatch.setattr(data, "_REPORTS", list(CORPUS))
    return client


def test_e8_corpus_exports_exactly_per_section_3(monkeypatch) -> None:
    _serve_corpus(monkeypatch)
    r = client.get("/api/reports.csv", headers={"X-Role": "admin"})
    assert r.status_code == 200
    assert r.content == CORPUS_BYTES
    assert r.headers["content-length"] == str(len(CORPUS_BYTES))


def test_formula_cell_exports_neutralized_while_table_still_shows_it(monkeypatch) -> None:
    _serve_corpus(monkeypatch)
    exported = client.get("/api/reports.csv", headers={"X-Role": "admin"}).content
    assert b"10,'=1+1," in exported
    assert b"'+root" in exported  # owner is a text column too (§3.1)
    assert b"10,=1+1," not in exported  # raw formula never leaves the API
    listed = client.get("/api/reports", headers={"X-Role": "admin"}).json()
    assert [x["title"] for x in listed if x["id"] == 10] == ["=1+1"]


def test_corpus_export_is_deterministic_across_requests(monkeypatch) -> None:
    _serve_corpus(monkeypatch)
    bodies = {client.get("/api/reports.csv", headers={"X-Role": "admin"}).content for _ in range(3)}
    assert bodies == {CORPUS_BYTES}  # §4


def test_corpus_viewer_ids_equal_viewer_list_ids(monkeypatch) -> None:
    _serve_corpus(monkeypatch)
    for role_headers in ({}, {"X-Role": "viewer"}, {"X-Role": "admin"}, {"X-Role": "zzz"}):
        text = client.get("/api/reports.csv", headers=role_headers).content.decode()
        rows = list(csv.reader(io.StringIO(text)))  # csv-aware so embedded LF parses
        ids = [int(row[0]) for row in rows[1:]]
        json_ids = [x["id"] for x in client.get("/api/reports", headers=role_headers).json()]
        assert ids == sorted(set(json_ids)) and set(ids) == set(json_ids)
