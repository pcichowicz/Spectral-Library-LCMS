"""
Stage-level checking cache

Each stages defines a cache key.The pipeline compares the key agaisnt a saved checkpoint before running a stage;
when matched, it skips the execute and returns the qc_metrics[stage.name]
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

def _filehash_cache_path(results_dir: Path) -> Path:
    return results_dir / "filehash_cache.json"

def load_filehash_cache(results_dir: Path) -> dict[str, Any]:
    path = _filehash_cache_path(results_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.decoder.JSONDecodeError, OSError):
        return {}

def save_filehash_cache(results_dir: Path, cache: dict[str, Any]) -> None:
    _filehash_cache_path(results_dir).write_text(json.dumps(cache, indent=2))

def hash_file(path: Path, cache: dict[str, Any]) -> str:
    """sha256 of file contents. Skips re-reading the file if its mtime and
    size match what's already in `cache` for this path.
    """
    key = str(path.resolve())
    stat = path.stat()
    signature = {"mtime": stat.st_mtime, "size": stat.st_size}

    cached = cache.get(key)
    if cached and cached.get("mtime") == signature["mtime"] and cached.get("size") == signature["size"]:
        return cached["sha256"]

    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    sha256 = digest.hexdigest()

    cache[key] = {**signature, "sha256": sha256}
    return sha256

def hash_files(paths: list[Path], cache: dict[str, Any]) -> dict[str, str]:
    return {p.name: hash_file(p, cache) for p in sorted(paths)}

def compute_cache_key(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload,sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

def checkpoint_path(results_dir:Path, stage_name:str) -> Path:
    return results_dir / "checkpoints" / f"{stage_name}.json"

def load_checkpoint(results_dir: Path, stage_name:str) -> dict[str,Any] | None:
    path = checkpoint_path(results_dir, stage_name)
    if not path.exists():
        return None

    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None

def save_checkpoint(
        results_dir:Path,
        stage_name: str,
        key: str,
        qc_metrics_slice: Any,
        log_entry: dict[str, Any] | None
) -> None:
    path = checkpoint_path(results_dir, stage_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "stage": stage_name,
        "key": key,
        "qc_metrics": qc_metrics_slice,
        "log_entry": log_entry,
    }
    path.write_text(json.dumps(payload, indent=2, default=str))





