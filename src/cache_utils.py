"""Cache management utilities for vocabulary data."""

import os
from pathlib import Path
from datetime import datetime, timedelta


def get_cache_age_hours(file_path: str) -> float:
    """Calculate the age of a cached file in hours."""
    if not os.path.exists(file_path):
        return float('inf')

    file_mtime = os.path.getmtime(file_path)
    age_seconds = (datetime.now() - datetime.fromtimestamp(file_mtime)).total_seconds()
    return age_seconds / 3600


def is_cache_valid(file_path: str, max_age_hours: float = 24) -> bool:
    """Check if a cached file is still valid based on age."""
    return get_cache_age_hours(file_path) <= max_age_hours


def clear_old_cache(directory: str, max_age_hours: float = 72):
    """Remove cached files older than max_age_hours."""
    if not os.path.exists(directory):
        return

    removed_files = []
    for file_path in Path(directory).glob("*_full_vocab_export.xlsx"):
        if get_cache_age_hours(str(file_path)) > max_age_hours:
            os.remove(file_path)
            removed_files.append(file_path.name)

    return removed_files
