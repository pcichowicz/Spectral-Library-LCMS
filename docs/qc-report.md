---
layout: default
title: QC Report
nav_order: 5
---

# QC Report
{: .no_toc }

This page renders the pipeline's own output -- `qc_report.json` and
`library.csv` -- committed to `docs/data/` by
`scripts/publish_docs_data.py` after a run. It is not hand-written; if
it looks wrong, the fix belongs in the pipeline or the publish script,
not this page.
{: .fs-5 .fw-300 }

<div id="qc-loading">Loading latest report…</div>
<div id="qc-error" style="display:none; color:#c1121f;"></div>

<div id="qc-content" style="display:none;" markdown="1">

<div id="qc-meta"></div>

## Validation summary

<div id="qc-summary-cards"></div>

## Spectral library matching (Stage 9)

<p>The primary pass/fail signal: does the top library match's compound name equal the known identity, at or above the configured score threshold?</p>

<div id="qc-library-matching"></div>

## Library entries

<div id="qc-library-table"></div>

## Processing log

<div id="qc-processing-log"></div>

</div>

<script>window.SITE_BASEURL = "{{ site.baseurl }}";</script>
<script src="{{ '/assets/js/qc-report.js' | relative_url }}"></script>
