# pilot-target

A deliberately small reports web app. It exists so that an agent team can be evaluated on a
realistic delivery loop: plan → small tickets → PRs → protected merge → release to a real host.

- Browser UI at `/` lists reports visible to the selected role, with an **Export CSV** button.
- JSON API under `/api`, plus the CSV export route `/api/reports.csv` (see `api.md`).
- Health endpoint `/healthz`.

## Export CSV (browser)

One control ships: the **Export CSV** button on the reports page, next to the role selector
(contract v0.2 §8, journey J-02). Clicking it fetches `/api/reports.csv` **with the same
`X-Role` header the table uses** and saves the result as a file — it is not a plain link, so
the role always travels with the request.

- **You export exactly what you can see.** The export reuses the list route's permission
  filter (§5.1): as `viewer` the file never contains the restricted report; as `admin` it
  contains every row in the table. Rows are ordered by `id` ascending (§5.1).
- **File name:** `reports-YYYY-MM-DD.csv`, the UTC date of the request (§2, D-6b).
- **Opening the file:** the downloaded file starts with a UTF-8 BOM so spreadsheet apps
  detect the encoding even with non-ASCII titles (§3 rule 1, D-3). The API path itself is
  plain UTF-8 without BOM — `curl -H 'X-Role: admin' .../api/reports.csv > reports.csv` (§8).
- **Formula-like cells:** a title/owner starting with `=`, `+`, `-` or `@` is exported with a
  leading apostrophe (so `=1+1` lands as `'=1+1`) to stop spreadsheet apps evaluating it; the
  UI table keeps showing the original text (§3 rule 5, D-2).
- The status line under the table only ever receives export **failure** messages, and only
  after a click (§8, D-13). Nothing export-related writes it on page load.

## Run locally

```
uv sync
uv run uvicorn app.main:app --reload
```

## Tests

```
uv run ruff check .
uv run pytest tests/unit tests/integration
uv run playwright install chromium && uv run pytest tests/e2e
```

## Documentation policy

Any change under `app/` must touch `docs/` in the same PR, or the PR description must contain
the line `docs-impact: none` with a one-line reason. The `docs` CI check enforces this.
