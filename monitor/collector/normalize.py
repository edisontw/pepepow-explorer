from __future__ import annotations

from typing import Any


def normalize_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        return int(float(value.strip()))
    raise ValueError(f"cannot normalize int from {value!r}")


def normalize_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return float(value.strip())
    raise ValueError(f"cannot normalize float from {value!r}")


def block_to_sample(
    block: dict[str, Any],
    previous_time: int | None,
    source: str,
    hoohash_bit: int | None,
    xelis_bit: int | None,
) -> dict[str, Any]:
    version = int(block.get("version", 0) or 0)
    block_time = int(block.get("time", 0) or 0)

    return {
        "height": int(block.get("height", 0) or 0),
        "hash": block.get("hash"),
        "previous_hash": block.get("previousblockhash"),
        "version": version,
        "version_hex": f"0x{version & 0xFFFFFFFF:08x}",
        "time": block_time,
        "mediantime": int(block.get("mediantime", block_time) or block_time),
        "difficulty": float(block.get("difficulty", 0) or 0),
        "interval_from_prev": (block_time - previous_time) if previous_time else None,
        "has_hoohash_bit": bool(hoohash_bit and version & hoohash_bit),
        "has_xelis_bit": bool(xelis_bit and version & xelis_bit),
        "source": source,
    }


def merge_recent_blocks(existing: list[dict[str, Any]], new_blocks: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    combined: dict[int, dict[str, Any]] = {int(item["height"]): item for item in existing}
    for block in new_blocks:
        combined[int(block["height"])] = block
    ordered = [combined[height] for height in sorted(combined)]
    return ordered[-limit:]
