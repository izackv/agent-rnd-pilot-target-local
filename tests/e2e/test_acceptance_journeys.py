"""Acceptance-plan §1 journeys J-02…J-05 (AGEA-16 / W6) through the real button.

J-01 lives in `test_journey.py` untouched (no-regression half; QA never edits
existing tests). These tests drive the actual `Export CSV` control with Playwright
(`accept_downloads`), assert on the **saved bytes** parsed with the real `csv`
module (never navigation), and pin both D-3 byte paths:
API bytes carry NO BOM and the saved file is exactly `BOM + the API bytes`.

Contract: v0.2 §1.1/§2 (bytes/headers), §5.1/§5.3 (visibility), §8 (button,
`#status` click-only precision, UTC-dated filename). D-15 (target spreadsheet
matrix) is still open with the board — no matrix-dependent assertion is invented
here; machine-parse parity covers everything automated regardless (AGEA-16 scope).
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from playwright.sync_api import Browser, Download, Error, Page, Route, expect

BOM = b"\xef\xbb\xbf"
ADMIN_IDS = ["1", "2", "3", "4"]
VIEWER_IDS = ["1", "2", "4"]
VIEWER_FILE_BYTES = (  # §4 byte pin (frozen in two places on purpose, §3.2 worked example)
    b"id,title,owner,rows\r\n"
    b"1,Monthly usage,ops,1200\r\n"
    b"2,Error budget,sre,48\r\n"
    b"4,Signup funnel,growth,5200\r\n"
)
RESTRICTED_ROW_FIELD_VALUES = {"3", "Payroll summary", "finance", "310"}
NAME_RE = re.compile(r"^reports-(\d{4})-(\d{2})-(\d{2})\.csv$")
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def fixture_records() -> list[dict]:
    return json.loads((FIXTURES / "adversarial_reports.json").read_text("utf-8"))["records"]


def fixture_expected_bytes() -> bytes:
    return (FIXTURES / "adversarial_expected_api.csv").read_bytes()


def parse_records(data: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(data.decode("utf-8"), newline=""), strict=True))


def parse_saved(data: bytes) -> list[list[str]]:
    assert data.startswith(BOM), "button download must carry the D-3 client-side BOM"
    return parse_records(data[len(BOM) :])


def open_page(base_url: str, browser: Browser) -> tuple[object, Page]:
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()
    page.goto(base_url + "/", wait_until="domcontentloaded")
    page.wait_for_selector("#reports tbody tr")
    return context, page


def click_export(page: Page) -> tuple[str, bytes]:
    with page.expect_download() as info:
        page.locator("button#export").click()
    dl: Download = info.value
    return dl.suggested_filename, Path(str(dl.path())).read_bytes()


def api_bytes(context, base_url: str, role: str | None = None) -> bytes:
    headers = {"X-Role": role} if role is not None else {}
    r = context.request.get(base_url + "/api/reports.csv", headers=headers)
    assert r.ok
    return r.body()


def assert_no_restricted_in_saved(data: bytes) -> None:
    records = parse_saved(data)
    assert [rec[0] for rec in records[1:]] == VIEWER_IDS  # no row with id 3
    for rec in records:
        # structural (review N1): no whole cell equals any field value of report 3
        assert not RESTRICTED_ROW_FIELD_VALUES & set(rec)


# --- J-02: browser download ≡ the page, click-time role (SC-1/2/6) ------------------------


def test_j02_saved_file_parses_to_the_visible_id_sets(base_url: str, browser: Browser) -> None:
    context, page = open_page(base_url, browser)
    try:
        # viewer selected at load time
        name, saved = click_export(page)
        assert NAME_RE.match(name), name  # UTC-dated filename also pinned in J-03
        assert parse_saved(saved)[0] == ["id", "title", "owner", "rows"]
        assert_no_restricted_in_saved(saved)
        assert saved == BOM + api_bytes(context, base_url, "viewer")  # both D-3 pins

        page.locator("select#role").select_option("admin")
        page.wait_for_function("document.querySelectorAll('#reports tbody tr').length === 4")
        _, saved = click_export(page)
        records = parse_saved(saved)
        assert [rec[0] for rec in records[1:]] == ADMIN_IDS
        assert saved == BOM + api_bytes(context, base_url, "admin")
    finally:
        context.close()


def test_j02_file_columns_match_the_displayed_table(base_url: str, browser: Browser) -> None:
    context, page = open_page(base_url, browser)
    try:
        _, saved = click_export(page)
        header = parse_saved(saved)[0]
        dom_cols = page.locator("#reports thead th")
        assert header == ["id", "title", "owner", "rows"]  # exact raw labels (DEC-D-5)
        assert dom_cols.count() == len(header)
        dom_labels = [dom_cols.nth(i).inner_text() for i in range(len(header))]
        assert [d.lower() for d in dom_labels] == header  # same columns, same order
    finally:
        context.close()


def test_j02_sc6_click_time_role_no_cached_bytes(base_url: str, browser: Browser) -> None:
    # export at click time takes the CURRENT dropdown: admin file, then a viewer
    # re-select must NOT replay the cached admin bytes — and must not drop rows.
    context, page = open_page(base_url, browser)
    try:
        page.locator("select#role").select_option("admin")
        page.wait_for_function("document.querySelectorAll('#reports tbody tr').length === 4")
        _, admin_saved = click_export(page)
        assert [rec[0] for rec in parse_saved(admin_saved)[1:]] == ADMIN_IDS

        page.locator("select#role").select_option("viewer")
        page.wait_for_function("document.querySelectorAll('#reports tbody tr').length === 3")
        _, viewer_saved = click_export(page)
        assert viewer_saved != admin_saved
        assert_no_restricted_in_saved(viewer_saved)
        assert viewer_saved == BOM + api_bytes(context, base_url, "viewer")

        page.locator("select#role").select_option("admin")
        page.wait_for_function("document.querySelectorAll('#reports tbody tr').length === 4")
        _, again = click_export(page)
        assert again == admin_saved  # determinism across the click-time switch (§4)
    finally:
        context.close()


# --- J-03: API download profile, from the browser's own request stack --------------------


def test_j03_api_role_set_headers_and_no_bom(base_url: str, browser: Browser) -> None:
    context = browser.new_context()
    try:
        r = context.request.get(base_url + "/api/reports.csv", headers={"X-Role": "admin"})
        body = r.body()
        assert r.status == 200
        assert r.headers["content-type"] == "text/csv; charset=utf-8"
        assert r.headers["cache-control"] == "no-store"
        assert r.headers["vary"] == "X-Role"
        assert int(r.headers["content-length"]) == len(body)  # exact, always present (§2)
        disposition = r.headers["content-disposition"]
        m = NAME_RE.match(re.search(r'filename="([^"]+)"', disposition).group(1))
        assert m, disposition
        served = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=UTC)
        today = datetime.now(UTC)
        assert timedelta(0) <= today - served < timedelta(days=2), "UTC date at request time (D-6b)"
        assert not body.startswith(BOM)  # D-3: the API path has NO BOM
        text = body.decode("utf-8")
        assert [rec[0] for rec in list(csv.reader(io.StringIO(text, newline="")))[1:]] == ADMIN_IDS

        # parity rule (no header ⇒ viewer set) through the same stack
        r_v = context.request.get(base_url + "/api/reports.csv")
        ids_v = [
            rec[0]
            for rec in list(
                csv.reader(io.StringIO(r_v.body().decode("utf-8"), newline=""), strict=True)
            )[1:]
        ]
        ids_json = [str(x["id"]) for x in context.request.get(base_url + "/api/reports").json()]
        assert ids_v == ids_json == VIEWER_IDS
    finally:
        context.close()


# --- J-04: restricted attempt / direct navigation yields exactly the viewer file ---------


def test_j04_direct_navigation_downloads_the_viewer_file(base_url: str, browser: Browser) -> None:
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()
    try:
        with page.expect_download() as info:
            try:  # an `attachment` navigation ends as a download, not a "load"
                page.goto(base_url + "/api/reports.csv")  # no X-Role on navigation
            except Error:
                pass
        name, saved = info.value.suggested_filename, Path(str(info.value.path())).read_bytes()
        assert NAME_RE.match(name), name
        # D-3/C-10, third pin: a NAVIGATION download is the raw server body —
        # byte-equal to the API response, no BOM (the BOM lives only in the Blob).
        assert not saved.startswith(BOM)
        assert saved == api_bytes(context, base_url) == VIEWER_FILE_BYTES
        for rec in parse_records(saved)[1:]:
            assert not RESTRICTED_ROW_FIELD_VALUES & set(rec)
        assert [rec[0] for rec in parse_records(saved)[1:]] == VIEWER_IDS
    finally:
        context.close()


# --- `#status` failure semantics (D-13 precision): only on click, never before -----------


def _status_page(base_url: str, browser: Browser, handler) -> tuple[object, Page]:
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()
    page.route("**/api/reports.csv", handler)
    page.goto(base_url + "/", wait_until="domcontentloaded")
    page.wait_for_selector("#reports tbody tr")
    return context, page


def test_status_failure_copy_only_on_click(base_url: str, browser: Browser) -> None:
    context, page = _status_page(base_url, browser, lambda route: route.abort())
    try:
        expect(page.locator("#status")).to_have_text("3 reports")  # nothing before click
        page.locator("button#export").click()
        expect(page.locator("#status")).to_have_text("Export failed (network error)")
    finally:
        context.close()


def test_status_404_uses_the_unavailable_copy(base_url: str, browser: Browser) -> None:
    def not_yet(route: Route) -> None:
        route.fulfill(status=404, content_type="application/json", body='{"detail":"Not Found"}')

    context, page = _status_page(base_url, browser, not_yet)
    try:
        expect(page.locator("#status")).to_have_text("3 reports")
        page.locator("button#export").click()
        expect(page.locator("#status")).to_have_text("Export not available yet")
    finally:
        context.close()


def test_status_error_shape_is_never_parsed_as_csv(base_url: str, browser: Browser) -> None:
    def boom(route: Route) -> None:
        route.fulfill(
            status=500, content_type="text/plain; charset=utf-8", body="Internal Server Error"
        )

    context, page = _status_page(base_url, browser, boom)
    downloaded: list[Download] = []
    page.on("download", lambda d: downloaded.append(d))
    try:
        page.locator("button#export").click()
        expect(page.locator("#status")).to_have_text("Export failed (500)")
        page.wait_for_timeout(300)
        assert downloaded == [], "a failed export must never land a file"
    finally:
        context.close()


# --- adversarial fixture through the page (review N6: one source, both surfaces) ---------


def test_adversarial_fixture_reaches_table_and_export(base_url: str, browser: Browser) -> None:
    records = fixture_records()
    csv_bytes = fixture_expected_bytes()

    def serve_json(route: Route) -> None:
        admin = route.request.headers.get("x-role") == "admin"
        visible = [r for r in records if admin or not r["restricted"]]
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps([{k: v for k, v in r.items() if k != "export"} for r in visible]),
        )

    def serve_csv(route: Route) -> None:
        route.fulfill(
            status=200,
            content_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="reports.csv"'},
            body=csv_bytes,
        )

    context = browser.new_context(accept_downloads=True)
    page = context.new_page()
    page.route("**/api/reports", serve_json)
    page.route("**/api/reports.csv", serve_csv)
    page.goto(base_url + "/", wait_until="domcontentloaded")
    try:
        page.locator("select#role").select_option("admin")
        page.wait_for_function(
            f"document.querySelectorAll('#reports tbody tr').length === {len(records)}"
        )
        # the app text stays raw for the formula cell (§3.1 deviation note)
        expect(page.locator("#reports tbody tr[data-id='20'] td").nth(1)).to_have_text("=1+1")

        name, saved = click_export(page)
        assert name == "reports.csv"
        assert saved == BOM + csv_bytes  # the mocked API bytes, BOM-prefixed — nothing else
        parsed = parse_saved(saved)

        # review N6 pin, once: the same fixture ids the page listed are the ones exported,
        # in the rule's id-ascending order (D-11b).
        assert [rec[0] for rec in parsed[1:]] == [
            str(r["id"]) for r in sorted(records, key=lambda x: x["id"])
        ]
        # every exported cell is csv-module-parsed back to its fixture export value
        table = {rec[0]: rec for rec in parsed[1:]}
        for r in records:
            assert table[str(r["id"])][1] == r["export"]["title"]
        assert table["20"][1] == "'=1+1"  # neutralized in the file, raw in the table
        assert table["26"][1] == "\t=1+1"  # V-13: tab-prefixed bypass, NOT neutralized
    finally:
        context.close()
