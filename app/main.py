"""FastAPI app: JSON API under /api plus a small browser UI at /."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import data, fixtures

BASE = Path(__file__).parent
app = FastAPI(title="pilot-target", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")


def _role(x_role: str | None) -> str:
    """Trial-grade auth: the role comes from a header. Good enough to test permission paths."""
    return data.ROLE_ADMIN if x_role == data.ROLE_ADMIN else data.ROLE_VIEWER


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "version": app.version}


@app.get("/api/reports")
def api_reports(x_role: str | None = Header(default=None)) -> list[dict]:
    return [r.to_dict() for r in data.list_reports(_role(x_role))]


@app.get("/api/reports.csv")
def api_reports_csv(x_role: str | None = Header(default=None)) -> Response:
    """Contract stub (contract v0.2 §1.1, §2, §8): per-role frozen fixture bytes.

    Role derivation reuses `_role()` verbatim, so a missing/other `X-Role`
    behaves exactly like today's list endpoint (absent ⇒ viewer). The real
    CSV generation engine is a separate backend issue; this route only serves
    the frozen fixture constants.
    """
    is_admin = _role(x_role) == data.ROLE_ADMIN
    body = fixtures.CSV_ADMIN_BYTES if is_admin else fixtures.CSV_VIEWER_BYTES
    filename = f"reports-{datetime.now(UTC).date().isoformat()}.csv"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "Vary": "X-Role",
        },
    )


@app.get("/api/reports/{report_id}")
def api_report(report_id: int, x_role: str | None = Header(default=None)) -> dict:
    r = data.get_report(report_id, _role(x_role))
    if r is None:
        raise HTTPException(status_code=404, detail="report not found")
    return r.to_dict()


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {"title": "Reports"})
