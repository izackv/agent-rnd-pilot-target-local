"""Contract v0.2 §8 (D-12a, D-13i): the single "Export CSV" button saves
BOM + the API's current-role bytes via fetch + Blob (not a navigation)."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Browser, expect

BOM = b"\xef\xbb\xbf"


def _api_bytes(page, base_url: str, role: str) -> bytes:
    r = page.request.get(base_url + "/api/reports.csv", headers={"X-Role": role})
    assert r.ok
    return r.body()


def _click_download(page):
    with page.expect_download() as dl_info:
        page.locator("button#export").click()
    dl = dl_info.value
    p = dl.path()
    assert p is not None, "download path missing"
    return dl.suggested_filename, Path(str(p)).read_bytes()


def _assert_status_has_no_export_copy(page):
    status = page.locator("#status").inner_text()
    assert "Export" not in status, status
    assert "not available yet" not in status, status


def _open_page(base_url: str, browser: Browser):
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()
    page.goto(base_url + "/", wait_until="domcontentloaded")
    page.wait_for_selector("#reports tbody tr")
    return context, page


def test_button_visible_once_and_no_export_copy_before_click(base_url: str, browser: Browser):
    context, page = _open_page(base_url, browser)
    try:
        expect(page.locator("button#export")).to_have_count(1)
        _assert_status_has_no_export_copy(page)
    finally:
        context.close()


def test_download_matches_bom_plus_current_role_api_bytes(base_url: str, browser: Browser):
    context, page = _open_page(base_url, browser)
    try:
        expected_viewer = BOM + _api_bytes(page, base_url, "viewer")
        filename, downloaded = _click_download(page)
        assert downloaded == expected_viewer
        assert filename.startswith("reports-") and filename.endswith(".csv")

        page.locator("select#role").select_option("admin")
        page.wait_for_function("document.querySelectorAll('#reports tbody tr').length === 4")
        _assert_status_has_no_export_copy(page)

        expected_admin = BOM + _api_bytes(page, base_url, "admin")
        _, downloaded = _click_download(page)
        assert downloaded == expected_admin
        assert b"Payroll summary" in downloaded
        assert b"Payroll summary" not in expected_viewer
    finally:
        context.close()
