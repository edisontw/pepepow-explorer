from __future__ import annotations

from typing import Any

from monitor.collector.normalize import normalize_int


def normalize_masternode_records(masternodes: list[dict[str, Any]], *, source: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in masternodes:
        record = normalize_masternode_record(item, source=source)
        if record is not None:
            normalized.append(record)
    return normalized


def normalize_masternode_record(item: dict[str, Any], *, source: str) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None

    parsed_raw = _parse_raw_record(item)
    merged = dict(item)
    if parsed_raw:
        merged = {
            **parsed_raw,
            **merged,
        }

    txhash, outidx = _split_txhash(_first_string(merged, "txhash", "txid", "collateral_txid"))
    if outidx is None:
        outidx = normalize_int(merged.get("outidx"))
    addr = _first_string(merged, "addr", "collateral_address", "collateraladdress", "payee")
    ip_address = _first_string(merged, "ip_address", "ip", "service", "address")
    status = _normalized_status(merged.get("status"))
    lastseen = _first_int(merged, "lastseen", "last_seen")
    activetime = _first_int(merged, "activetime", "active_time", "activeseconds")
    version = normalize_int(merged.get("version"))
    subver = _first_string(merged, "subver")
    raw = _first_string(merged, "raw")

    if not _has_visible_fields(addr, txhash, ip_address, status, version, lastseen):
        return None

    return {
        "addr": addr,
        "txhash": txhash,
        "outidx": outidx,
        "ip_address": ip_address,
        "status": status,
        "lastseen": lastseen,
        "activetime": activetime,
        "version": version,
        "subver": subver,
        "raw": raw,
        "seen_in_explorer": source == "explorer",
        "seen_in_rpc": source == "rpc",
    }


def normalize_masternode_items(masternodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    records = masternodes
    if records and "seen_in_explorer" not in records[0] and "seen_in_rpc" not in records[0]:
        records = normalize_masternode_records(masternodes, source="unknown")

    for record in records:
        normalized.append(
            {
                "addr": record.get("addr"),
                "txid": record.get("txhash"),
                "ip": record.get("ip_address"),
                "status": record.get("status"),
                "lastseen": record.get("lastseen"),
                "activetime": record.get("activetime"),
                "version": record.get("version"),
                "subver": record.get("subver"),
                "fallback_only": bool(record.get("seen_in_rpc")) and not bool(record.get("seen_in_explorer")),
            }
        )
    return normalized


def merge_masternode_records(
    explorer_items: list[dict[str, Any]],
    rpc_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    index_by_key: dict[str, int] = {}

    for source, group in (("explorer", explorer_items), ("rpc", rpc_items)):
        for item in normalize_masternode_records(group, source=source):
            key = _record_key(item)
            if key is None:
                merged.append(item)
                continue

            existing_index = index_by_key.get(key)
            if existing_index is None:
                index_by_key[key] = len(merged)
                merged.append(item)
                continue

            merged[existing_index] = _merge_record_values(merged[existing_index], item)

    return merged


def _parse_raw_record(item: dict[str, Any]) -> dict[str, Any] | None:
    raw = _first_string(item, "raw")
    if raw is None:
        return None

    parts = raw.split()
    if len(parts) < 5:
        return None

    result: dict[str, Any] = {
        "status": parts[0],
        "version": normalize_int(parts[1]),
        "addr": parts[2],
        "lastseen": normalize_int(parts[3]),
        "activetime": normalize_int(parts[4]),
        "raw": raw,
    }

    for value in reversed(parts[5:]):
        if ":" in value or value.count(".") == 3:
            result["ip_address"] = value
            break

    txhash, outidx = _split_txhash(_first_string(item, "txhash", "txid"))
    if txhash is not None:
        result["txhash"] = txhash
    if outidx is not None:
        result["outidx"] = outidx
    return result


def _record_key(item: dict[str, Any]) -> str | None:
    txhash = _first_string(item, "txhash")
    if txhash:
        outidx = normalize_int(item.get("outidx"))
        return f"txhash:{txhash}:{outidx if outidx is not None else -1}"

    addr = _first_string(item, "addr")
    if addr:
        return f"addr:{addr}"

    ip_address = _first_string(item, "ip_address")
    if ip_address:
        return f"ip:{ip_address}"

    return None


def _merge_record_values(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in incoming.items():
        if merged.get(key) in {None, ""} and value not in {None, ""}:
            merged[key] = value
    return merged


def _split_txhash(value: str | None) -> tuple[str | None, int | None]:
    if value is None:
        return None, None
    if "-" not in value:
        return value, None

    txhash, outidx = value.rsplit("-", 1)
    return txhash, normalize_int(outidx)


def _first_string(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _first_int(item: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = normalize_int(item.get(key))
        if value is not None:
            return value
    return None


def _normalized_status(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text.upper()


def _has_visible_fields(
    addr: str | None,
    txhash: str | None,
    ip_address: str | None,
    status: str | None,
    version: int | None,
    lastseen: int | None,
) -> bool:
    if addr or txhash or ip_address:
        return True
    return status is not None or version is not None or lastseen is not None
