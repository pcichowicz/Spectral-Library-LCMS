"""
Copies a pipeline run's output into docs/data/ for the GitHub Pages QC
report page (docs/qc-report.md + assets/js/qc-report.js) to render.

Deliberately trims `raw_qc_metrics` before publishing: that field can
carry full per-feature blank-flag lists (thousands of entries on a real
cohort), which the report page never reads except for
`raw_qc_metrics.library_matching` (used for the per-compound match
table). Everything else the page needs is already in the top-level
`qc_metrics` summary and `processing_log`.

Usage:
    python scripts/publish_docs_data.py --study mtbls1861
    python scripts/publish_docs_data.py --study mtbls1861 --base-dir /path/to/v3 --docs-dir docs
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

# Only these raw_qc_metrics keys are ever read by qc-report.js -- keep in
# sync with that file's renderLibraryMatching(). Everything else in
# raw_qc_metrics is dropped from the published copy.
RAW_METRICS_KEYS_TO_KEEP = {"library_matching"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", required=True, help="study_id, e.g. mtbls1861")
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=None,
        help="Path to the v3/ directory (defaults to <script's parent>/../v3)",
    )
    parser.add_argument(
        "--docs-dir",
        type=Path,
        default=None,
        help="Path to the docs/ directory (defaults to <script's parent>/../docs)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    base_dir = args.base_dir or (repo_root / "v3")
    docs_dir = args.docs_dir or (repo_root / "docs")

    qc_report_path = base_dir / "results" / args.study / "qc_report" / "qc_report.json"
    library_csv_path = base_dir / "results" / args.study / "library" / "library.csv"

    if not qc_report_path.exists():
        print(f"ERROR: {qc_report_path} not found -- run the pipeline for "
              f"study {args.study!r} first.", file=sys.stderr)
        return 1
    if not library_csv_path.exists():
        print(f"ERROR: {library_csv_path} not found -- run the pipeline for "
              f"study {args.study!r} first.", file=sys.stderr)
        return 1

    data_dir = docs_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    report = json.loads(qc_report_path.read_text())
    trimmed = dict(report)
    raw = report.get("raw_qc_metrics", {})
    trimmed["raw_qc_metrics"] = {k: v for k, v in raw.items() if k in RAW_METRICS_KEYS_TO_KEEP}

    out_report_path = data_dir / "qc_report.json"
    out_report_path.write_text(json.dumps(trimmed, indent=2, default=str))

    out_library_path = data_dir / "library.csv"
    shutil.copyfile(library_csv_path, out_library_path)

    before = qc_report_path.stat().st_size
    after = out_report_path.stat().st_size
    print(f"Published {out_report_path} ({after:,} bytes, was {before:,} full)")
    print(f"Published {out_library_path} ({out_library_path.stat().st_size:,} bytes)")
    print("Commit docs/data/ to update the published QC report page.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
