"""Summarise numbers and export the result using the same backend functions."""
import json
from pathlib import Path
from statistics import mean


def summarise(values: list[float]) -> dict:
    """Return count, mean, minimum and maximum; reject empty or non-finite data."""
    import math
    numbers = [float(v) for v in values]
    if not numbers or any(not math.isfinite(v) for v in numbers):
        raise ValueError("provide at least one finite number")
    return {"count": len(numbers), "mean": mean(numbers), "minimum": min(numbers), "maximum": max(numbers)}


def export_summary(values: list[float], output_path: str) -> dict:
    """Write a new JSON summary; refuse to overwrite an existing file."""
    result = summarise(values)
    path = Path(output_path)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(result, stream)
    return {"output": str(path), "summary": result}
