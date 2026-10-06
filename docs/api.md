# API

Role is supplied by the `X-Role` header (`viewer` default, `admin`). This is trial-grade
authentication, chosen so permission paths can be tested without an identity provider.

| Method | Path | Behavior |
|---|---|---|
| GET | `/healthz` | `{"status": "ok", "version": ...}` |
| GET | `/api/reports` | Reports visible to the role. Restricted reports are admin-only. |
| GET | `/api/reports/{id}` | One report, or 404 if missing or not visible to the role. |
| GET | `/api/reports.csv` | CSV export of the role-filtered list — see below (contract v0.2 §1.1). |

## CSV export — `GET /api/reports.csv`

Normed by `api-contract` **v0.2**, sections cited inline. The rows come from the same
`data.list_reports()` call that backs `GET /api/reports`, so the export is exactly what the
caller's role can list — no separate filtering exists in the export path (§5.1, C-2).

### Request (§1.1)

- `GET` only; `HEAD` is the framework default of a GET route; any other method is 405 (E-6).
- Role comes only from the `X-Role` header, evaluated by the same `_role()` helper as the
  JSON routes: header absent, or any value other than exactly `admin` (case-sensitive, no
  trimming — `X-Role: " Admin"` ⇒ viewer) ⇒ **viewer** (§1.1).
- No parameters at all. Unknown query parameters are **ignored** with a 200 (§1.1, E-5).
  A role/filter/format/paging parameter would be a contract revision, not an extension.
- There is **no per-report CSV route** in v0.2 (§1.2); per-id errors E-3 and the id part of
  E-5 are N/A for this reason.

### Response headers — every 200 CSV (§2)

| Header | Value |
|---|---|
| `Content-Type` | `text/csv; charset=utf-8` |
| `Content-Disposition` | `attachment; filename="reports-2026-10-06.csv"` — the UTC date at request time (D-6b); server-generated, never embeds report/role/user data |
| `Cache-Control` | `no-store` — the URL is role-independent but the body is not, so any cache is a permission-leak vector |
| `Vary` | `X-Role` |
| `Content-Length` | exact byte count — the body is batched in memory, never chunked (§7) |

No `Set-Cookie` and no CORS headers; the route creates or changes no auth state (§1.1, C-8).

### Byte profile (§3)

1. Plain UTF-8, **no BOM** (§3 rule 1, D-3). The browser download adds the BOM client-side
   when saving the file — same bytes, see `index.md` (§8, C-10).
2. One header record `id,title,owner,rows` — raw lowercase, identical for both roles — then
   one record per visible report (§3.1). The `restricted` field is never exported (§3.1).
3. Every record ends with `CRLF`, **including the last**, and nothing follows (§3 rule 3).
4. Fields are separated by `,`, no padding; a field is quoted (RFC 4180, inner `"` doubled)
   iff it contains `,` `"` CR or LF — minimal, deterministic quoting (§3 rules 4, 6).
5. **Formula neutralization** (§3 rule 5, DEC-D-2): in the text fields `title` and `owner`, a
   value whose *first character* is `=` `+` `-` or `@` is exported with one leading apostrophe
   — a title `=1+1` exports as `'=1+1`. Integer columns are never modified. Deviation note
   (SC-7): for such cells the exported text differs from the UI text by that apostrophe;
   visible UI text is unchanged.
6. Records are sorted by `id` ascending as a stated rule, not by data order (§5.1, D-11b).
7. Two requests that see the same dataset and role get **byte-identical** responses (§4).

### Example (as on `main`)

CRLF-terminated records are shown as lines; headers omitted for brevity.

```
$ curl -s -H 'X-Role: admin' http://127.0.0.1:8000/api/reports.csv
id,title,owner,rows
1,Monthly usage,ops,1200
2,Error budget,sre,48
3,Payroll summary,finance,310
4,Signup funnel,growth,5200
```

The same request with no header (or any non-`admin` value) returns exactly these bytes
**minus** the `3,Payroll summary,…` record — ids 1, 2, 4 (§3.2). The downloaded file from the
UI button is `EF BB BF` + the API bytes above (§3 rule 1 / §8).

If the caller's filtered set were empty — not reachable with the current data, mocked in
tests — the response is still 200 with exactly `id,title,owner,rows` + CRLF: header-only,
21 bytes (§1.1 200-E, E-4).

### Errors (§6)

| ID | Case | Status | Body |
|---|---|---|---|
| E-1 | unauthenticated | — | Does not exist: no sessions; an anonymous caller is `viewer` and gets a 200 viewer CSV. A 401 here would be a contract violation. |
| E-2 | restricted content requested | — | No 403 anywhere; the list route only filters (§6). |
| E-3 | not found / restricted by id | — | N/A in v0.2 — no per-id route (§1.2). |
| E-4 | empty result | 200 | `id,title,owner,rows\r\n` — header only, exactly 21 bytes; the browser-saved file adds the BOM (3 + 21 bytes) (§3.1, §6). |
| E-5 | malformed params | 200 | Unknown query params are ignored (§1.1); the non-integer-id case is N/A (§1.2). |
| E-6 | unsupported method | 405 | `{"detail":"Method Not Allowed"}` (`application/json`) |
| E-7 | unknown path | 404 | `{"detail":"Not Found"}` (`application/json`) |
| E-8 | failure mid-generation | 500 | `Internal Server Error` (`text/plain; charset=utf-8`) — generation is batched, so this is all-or-nothing and never arrives with partial CSV bytes (§7). |

E-9 was retired in v0.2 (D-14); its slot must not be reused.

## Accepted user journeys

| ID | Journey | Test |
|---|---|---|
| J-01 | Viewer opens the reports page and sees permitted reports; admin sees the restricted one too | `tests/e2e/test_journey.py` |
| J-02 | User clicks **Export CSV** on the reports page and the saved file is the BOM + their current view's API bytes | `tests/e2e/test_export_button.py` |
| J-03 | API caller downloads the CSV for a role: headers, byte profile and sort match contract v0.2 | `tests/integration/test_reports_csv.py` |
