/**
 * Renders docs/qc-report.md from docs/data/qc_report.json + library.csv,
 * both written by scripts/publish_docs_data.py. No build step, no deps --
 * plain fetch + DOM, since this only ever needs to run inside GitHub
 * Pages' static Jekyll build.
 */
(function () {
  "use strict";

  const BASE = window.SITE_BASEURL || "";

  injectStyles();

  Promise.all([
    fetchJSON(`${BASE}/data/qc_report.json`),
    fetchText(`${BASE}/data/library.csv`).catch(() => null),
  ])
    .then(([report, libraryCsvText]) => {
      renderMeta(report);
      renderSummaryCards(report);
      renderLibraryMatching(report);
      renderLibraryTable(libraryCsvText);
      renderProcessingLog(report);

      show("qc-content");
      hide("qc-loading");
    })
    .catch((err) => {
      hide("qc-loading");
      const el = document.getElementById("qc-error");
      el.style.display = "block";
      el.innerHTML =
        `Couldn't load a published QC report yet. Run ` +
        `<code>python scripts/publish_docs_data.py --study &lt;your_study&gt;</code> ` +
        `and commit <code>docs/data/</code> to populate this page.<br>` +
        `<small>${escapeHtml(String(err))}</small>`;
    });

  // ---------- fetch helpers ----------

  function fetchJSON(url) {
    return fetch(url).then((r) => {
      if (!r.ok) throw new Error(`${url}: ${r.status}`);
      return r.json();
    });
  }

  function fetchText(url) {
    return fetch(url).then((r) => {
      if (!r.ok) throw new Error(`${url}: ${r.status}`);
      return r.text();
    });
  }

  // ---------- rendering ----------

  function renderMeta(report) {
    const timestamps = (report.processing_log || [])
      .map((e) => e.timestamp)
      .filter(Boolean)
      .sort();
    const lastRun = timestamps.length ? timestamps[timestamps.length - 1] : "unknown";

    setHTML(
      "qc-meta",
      card([
        row("Study", report.study_id ?? "—"),
        row("Config version", report.config_version ?? "—"),
        row("Dataset profile", report.dataset_profile ?? "—"),
        row("Last stage timestamp (UTC)", lastRun),
      ])
    );
  }

  function renderSummaryCards(report) {
    const qm = report.qc_metrics || {};
    const idRate = qm.identification_rate || {};
    const purity = qm.spectral_purity || {};
    const blank = qm.blank_background || {};
    const libMatch = (report.raw_qc_metrics || {}).library_matching;

    const blankRates = Object.values(blank.per_sample || {})
      .map((s) => s.flag_rate)
      .filter((v) => typeof v === "number");
    const avgBlankFlagRate = blankRates.length
      ? blankRates.reduce((a, b) => a + b, 0) / blankRates.length
      : null;

    const cards = [
      statCard(
        "System suitability",
        formatPct(idRate.rate),
        `${idRate.n_confirmed ?? "?"} / ${idRate.n_checked ?? "?"} expected ions confirmed`
      ),
      statCard(
        "Spectral purity (median)",
        formatPct(purity.median_purity),
        `${purity.n_computed ?? 0} computed, ${purity.n_below_threshold ?? 0} below threshold`
      ),
      statCard(
        "Blank background",
        formatPct(avgBlankFlagRate),
        "average feature flag rate across samples"
      ),
    ];

    if (libMatch) {
      cards.push(
        statCard(
          "Stage 9: identity recovered",
          formatPct(libMatch.validation_rate),
          `${libMatch.n_correct ?? 0} / ${libMatch.n_attempted ?? 0} confirmed compounds correctly identified`,
          libMatch.validation_rate != null && libMatch.validation_rate >= 0.8 ? "good" : "warn"
        )
      );
    } else {
      cards.push(
        statCard(
          "Stage 9: identity recovered",
          "not run",
          "library_matching hasn't been published for this report yet",
          "warn"
        )
      );
    }

    setHTML("qc-summary-cards", `<div class="qc-card-row">${cards.join("")}</div>`);
  }

  function renderLibraryMatching(report) {
    const lm = (report.raw_qc_metrics || {}).library_matching;
    const el = document.getElementById("qc-library-matching");
    if (!lm) {
      el.innerHTML = `<p><em>No library_matching results in this report yet -- see
        <a href="./running-the-pipeline#reference-library">setting up the reference library</a>.</em></p>`;
      return;
    }

    const rows = [];
    for (const [sampleId, result] of Object.entries(lm.results || {})) {
      for (const m of result.matches || []) {
        rows.push(m);
      }
    }

    if (!rows.length) {
      el.innerHTML = "<p><em>No confirmed compounds had a library match attempted.</em></p>";
      return;
    }

    const headers = ["Sample compound", "Top library match", "Score", "Correct identity?"];
    const bodyRows = rows.map((m) => {
      const scoreStr = typeof m.match_score === "number" ? m.match_score.toFixed(3) : "—";
      const correct = m.is_correct_match;
      const correctCell =
        correct === true
          ? `<span class="qc-pill qc-pill-good">correct</span>`
          : correct === false
          ? `<span class="qc-pill qc-pill-bad">incorrect / no match</span>`
          : `<span class="qc-pill">—</span>`;
      return [
        escapeHtml(m.known_identity ?? m.compound ?? "—"),
        escapeHtml(m.match_compound_name ?? "—"),
        scoreStr,
        correctCell,
      ];
    });

    el.innerHTML = table(headers, bodyRows);
  }

  function renderLibraryTable(csvText) {
    const el = document.getElementById("qc-library-table");
    if (!csvText) {
      el.innerHTML = "<p><em>No library.csv published yet.</em></p>";
      return;
    }
    const rows = parseCSV(csvText);
    if (!rows.length) {
      el.innerHTML = "<p><em>library.csv is empty.</em></p>";
      return;
    }

    const headers = rows[0];
    const displayCols = [
      "compound_name",
      "precursor_mz",
      "rt_sec",
      "adduct",
      "spectral_purity",
      "match_score",
      "is_correct_match",
      "blank_flagged",
    ];
    const colIdx = displayCols
      .map((c) => headers.indexOf(c))
      .filter((i) => i !== -1);
    const colNames = colIdx.map((i) => headers[i]);

    const bodyRows = rows.slice(1).map((r) => colIdx.map((i) => escapeHtml(r[i] ?? "")));
    el.innerHTML = table(colNames, bodyRows);
  }

  function renderProcessingLog(report) {
    const log = report.processing_log || [];
    const headers = ["Stage", "Timestamp (UTC)", "Warnings"];
    const bodyRows = log.map((entry) => [
      escapeHtml(entry.stage || entry.step || "—"),
      escapeHtml(entry.timestamp || "—"),
      String((entry.warnings || []).length),
    ]);
    setHTML("qc-processing-log", table(headers, bodyRows));
  }

  // ---------- small DOM/format helpers ----------

  function statCard(label, value, sub, tone) {
    const toneClass = tone === "good" ? "qc-card-good" : tone === "warn" ? "qc-card-warn" : "";
    return `<div class="qc-card ${toneClass}">
      <div class="qc-card-value">${escapeHtml(value)}</div>
      <div class="qc-card-label">${escapeHtml(label)}</div>
      <div class="qc-card-sub">${escapeHtml(sub)}</div>
    </div>`;
  }

  function card(rowsHtml) {
    return `<div class="qc-meta-card">${rowsHtml.join("")}</div>`;
  }

  function row(label, value) {
    return `<div class="qc-meta-row"><span class="qc-meta-label">${escapeHtml(
      label
    )}</span><span class="qc-meta-value">${escapeHtml(String(value))}</span></div>`;
  }

  function table(headers, bodyRows) {
    const thead = `<tr>${headers.map((h) => `<th>${escapeHtml(h)}</th>`).join("")}</tr>`;
    const tbody = bodyRows
      .map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`)
      .join("");
    return `<div class="qc-table-wrap"><table class="qc-table"><thead>${thead}</thead><tbody>${tbody}</tbody></table></div>`;
  }

  function formatPct(v) {
    if (typeof v !== "number") return "—";
    return `${(v * 100).toFixed(1)}%`;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function setHTML(id, html) {
    document.getElementById(id).innerHTML = html;
  }
  function show(id) {
    document.getElementById(id).style.display = "";
  }
  function hide(id) {
    document.getElementById(id).style.display = "none";
  }

  // Minimal CSV parser: handles quoted fields with embedded commas/quotes
  // (RFC 4180-ish). Good enough for export.py's csv.DictWriter output.
  function parseCSV(text) {
    const rows = [];
    let row = [];
    let field = "";
    let inQuotes = false;

    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (inQuotes) {
        if (c === '"') {
          if (text[i + 1] === '"') {
            field += '"';
            i++;
          } else {
            inQuotes = false;
          }
        } else {
          field += c;
        }
      } else if (c === '"') {
        inQuotes = true;
      } else if (c === ",") {
        row.push(field);
        field = "";
      } else if (c === "\n" || c === "\r") {
        if (c === "\r" && text[i + 1] === "\n") i++;
        row.push(field);
        field = "";
        if (row.length > 1 || row[0] !== "") rows.push(row);
        row = [];
      } else {
        field += c;
      }
    }
    if (field !== "" || row.length) {
      row.push(field);
      rows.push(row);
    }
    return rows;
  }

  function injectStyles() {
    const style = document.createElement("style");
    style.textContent = `
      .qc-card-row { display: flex; flex-wrap: wrap; gap: 1rem; margin: 1rem 0; }
      .qc-card {
        flex: 1 1 200px; border: 1px solid #e0e0e0; border-radius: 8px;
        padding: 1rem; background: #fafafa;
      }
      .qc-card-good { border-color: #2f9e44; background: #f1fbf3; }
      .qc-card-warn { border-color: #e8590c; background: #fff6ed; }
      .qc-card-value { font-size: 1.8rem; font-weight: 700; }
      .qc-card-label { font-weight: 600; margin-top: .25rem; }
      .qc-card-sub { color: #666; font-size: .85rem; margin-top: .25rem; }
      .qc-meta-card { border: 1px solid #e0e0e0; border-radius: 8px; padding: .75rem 1rem; margin: 1rem 0; }
      .qc-meta-row { display: flex; justify-content: space-between; padding: .15rem 0; font-size: .95rem; }
      .qc-meta-label { color: #666; }
      .qc-table-wrap { overflow-x: auto; margin: 1rem 0; }
      .qc-table { border-collapse: collapse; width: 100%; font-size: .9rem; }
      .qc-table th, .qc-table td { border: 1px solid #e0e0e0; padding: .4rem .6rem; text-align: left; white-space: nowrap; }
      .qc-table th { background: #f5f5f5; }
      .qc-pill { display: inline-block; padding: .1rem .5rem; border-radius: 999px; background: #eee; font-size: .8rem; }
      .qc-pill-good { background: #d3f9d8; color: #2b8a3e; }
      .qc-pill-bad { background: #ffe3e3; color: #c92a2a; }
    `;
    document.head.appendChild(style);
  }
})();
