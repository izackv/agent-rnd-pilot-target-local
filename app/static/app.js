function setStatus(msg) {
  document.getElementById("status").textContent = msg;
}

async function load() {
  const role = document.getElementById("role").value;
  const status = document.getElementById("status");
  status.textContent = "Loading…";
  const res = await fetch("/api/reports", { headers: { "X-Role": role } });
  const tbody = document.querySelector("#reports tbody");
  tbody.innerHTML = "";
  if (!res.ok) { status.textContent = `Error ${res.status}`; return; }
  const rows = await res.json();
  for (const r of rows) {
    const tr = document.createElement("tr");
    tr.dataset.id = r.id;
    tr.innerHTML = `<td>${r.id}</td><td>${r.title}</td><td>${r.owner}</td><td>${r.rows}</td>`;
    tbody.appendChild(tr);
  }
  status.textContent = rows.length ? `${rows.length} reports` : "No reports";
}

// Contract v0.2 §8 (D-12a, D-13i, D-3 + C-10). One control: JS fetch + Blob,
// never an `<a href>` / navigation, so the `X-Role` header survives. BOM is
// added only in the Blob; the API bytes stay plain UTF-8 (D-3). `#status` is
// written by this function only AFTER a click, never before (D-13 precision).
async function exportCsv() {
  const role = document.getElementById("role").value;        // same source as the table (§5.3)
  let res;
  try {
    res = await fetch("/api/reports.csv", { headers: { "X-Role": role } });
  } catch {
    setStatus("Export failed (network error)"); return;      // D-13: failure copy only, only after click
  }
  if (res.status === 404) { setStatus("Export not available yet"); return; } // E-7 stub path
  if (!res.ok) { setStatus(`Export failed (${res.status})`); return; }       // E-6/E-8: never parse as CSV
  const text = await res.text();                             // API bytes: plain UTF-8, no BOM (D-3)
  const blob = new Blob(["\uFEFF", text],                    // BOM belongs ONLY here (D-3 / C-10)
                        { type: "text/csv;charset=utf-8" });
  const cd = res.headers.get("Content-Disposition") || "";
  const name = (cd.match(/filename="?([^";]+)"?/) || [])[1] || "reports.csv"; // D-6(b) dated name
  const a = Object.assign(document.createElement("a"),
    { href: URL.createObjectURL(blob), download: name });
  a.click(); URL.revokeObjectURL(a.href);
}

document.getElementById("role").addEventListener("change", load);
document.getElementById("export").addEventListener("click", exportCsv);
load();
