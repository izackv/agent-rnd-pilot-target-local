"""Byte pins for the `GET /api/reports.csv` contract stub (api-contract v0.2 §1.1, §2, §3.2, §8)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

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
