"""Utilities for parsing sample_metadata.csv's list-valued columns.

expected_compounds and expected_mz are stored as JSON array literals
(e.g. '["Glycine"]', '[74.0247]') so a plain csv/pandas read gives back
strings that still need one json.loads() to become real lists.
"""
from __future__ import annotations

import json
from typing import Any


def parse_list_field(value: Any) -> list:
    """Parse a JSON-array-as-string CSV cell into a Python list.

    Handles the already-a-list case too, so callers don't need to know
    whether the value came straight from pandas or was already parsed.
    """
    if isinstance(value, list):
        return value
    if value is None or (isinstance(value, float) and value != value):  # NaN
        return []
    value = value.strip()
    if not value:
        return []
    return json.loads(value)