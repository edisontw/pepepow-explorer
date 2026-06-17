from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from typing import Any, Iterable

from monitor.collector.normalize import normalize_int


SEMVER_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?")
SEMVER_MARKER_RE = re.compile(r"(?i)\b(?:core|version|ver|wallet|daemon)\b")
STRICT_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+\.\d+$")


def format_hashrate(value: float | None) -> str:
    if value is None or value < 0:
        return "-"

    units = ["H/s", "KH/s", "MH/s", "GH/s", "TH/s", "PH/s"]
    amount = float(value)
    index = 0
    while amount >= 1000 and index < len(units) - 1:
        amount /= 1000.0
        index += 1
    return f"{amount:.4f} {units[index]}"


def parse_version_tuple(raw: str | None) -> tuple[int, int, int, int] | None:
    if raw is None:
        return None
    match = SEMVER_RE.search(str(raw))
    if not match:
        return None
    parts = [int(piece) if piece is not None else 0 for piece in match.groups()]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])


def mask_peer_address(address: str | None) -> str:
    if not address:
        return "-"
    if address.count(".") == 3 and ":" in address:
        host, port = address.rsplit(":", 1)
        octets = host.split(".")
        return ".".join(octets[:3] + ["x"]) + f":{port}"
    if ":" in address:
        host, _, port = address.rpartition(":")
        if host.count(":") >= 2:
            segments = [segment for segment in host.split(":") if segment]
            prefix = ":".join(segments[:2]) if segments else host
            return f"{prefix}:...:{port}"
    return address


def build_peer_version_summary(peers: list[dict[str, Any]], minimum_subver: str | None) -> dict[str, Any]:
    minimum_version = parse_version_tuple(minimum_subver)
    counts = Counter()
    upgraded = 0
    legacy = 0
    unknown = 0

    for peer in peers:
        label = str(peer.get("subver") or "unknown")
        counts[label] += 1
        version_tuple = parse_version_tuple(label)
        if version_tuple is None or minimum_version is None:
            unknown += 1
            continue
        if version_tuple >= minimum_version:
            upgraded += 1
        else:
            legacy += 1

    total = len(peers)
    upgrade_percent = round((upgraded / total) * 100, 2) if total else 0.0

    return {
        "total_peers": total,
        "upgraded_peers": upgraded,
        "legacy_peers": legacy,
        "unknown_peers": unknown,
        "upgrade_percent": upgrade_percent,
        "versions": [{"label": label, "count": count} for label, count in counts.most_common()],
    }


def sanitize_peers(peers: list[dict[str, Any]], limit: int = 50) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for peer in peers[:limit]:
        sanitized.append(
            {
                "addr": mask_peer_address(peer.get("addr")),
                "subver": peer.get("subver"),
                "version": peer.get("version"),
                "inbound": bool(peer.get("inbound", False)),
                "synced_blocks": peer.get("synced_blocks"),
                "synced_headers": peer.get("synced_headers"),
                "banscore": peer.get("banscore"),
            }
        )
    return sanitized


def build_hashrate_point(timestamp: str, height: int | None, hashrate_hps: float | None) -> dict[str, Any]:
    return {
        "timestamp": timestamp,
        "height": height,
        "value": round(float(hashrate_hps or 0.0), 4),
    }


def build_interval_points(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "height": block["height"],
            "timestamp": block["time"],
            "value": block["interval_from_prev"],
        }
        for block in blocks
        if block.get("interval_from_prev") is not None
    ]


def numeric_median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[midpoint])
    return float((ordered[midpoint - 1] + ordered[midpoint]) / 2)


def safe_ratio(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return math.inf
    return numerator / denominator


def average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def extract_host(address: str | None) -> str | None:
    if not address:
        return None
    raw = str(address).strip()
    if raw.startswith("[") and "]" in raw:
        return raw[1 : raw.index("]")]
    if raw.count(".") == 3 and ":" in raw:
        return raw.rsplit(":", 1)[0]
    if raw.count(":") >= 2:
        return raw
    if ":" in raw:
        return raw.rsplit(":", 1)[0]
    return raw


def is_enabled_masternode(masternode: dict[str, Any]) -> bool:
    status = str(masternode.get("status") or "").upper()
    return "ENABLE" in status


def _build_ip_semver_map(peers: list[dict[str, Any]]) -> dict[str, str]:
    ip_semvers: dict[str, str] = {}
    for peer in peers:
        host = extract_host(peer.get("addr"))
        semver = clean_semver(peer.get("subver"))
        if host and semver:
            ip_semvers[host] = semver
    return ip_semvers


def build_masternode_summary(
    masternodes: list[dict[str, Any]],
    masternode_count: dict[str, int] | None,
    minimum_subver: str | None,
    peers: list[dict[str, Any]],
) -> dict[str, Any]:
    enabled_nodes = [item for item in masternodes if is_enabled_masternode(item)]
    protocol_semver_map = _build_protocol_semver_map(peers)
    ip_semver_map = _build_ip_semver_map(peers)
    buckets: dict[tuple[int | None, str | None], dict[str, Any]] = {}
    upgraded_enabled = 0
    legacy_enabled = 0
    unknown_enabled = 0

    for masternode in enabled_nodes:
        protocol_version, semver = resolve_masternode_version(masternode, ip_semver_map)
        
        # If semver is still None, but there's a unique semver for this protocol_version in peerinfo:
        if semver is None and protocol_version in protocol_semver_map:
            candidates = list(set(protocol_semver_map[protocol_version]))
            if len(candidates) == 1:
                semver = candidates[0]

        key = (protocol_version, semver)
        bucket = buckets.setdefault(
            key,
            {
                "protocol_version": protocol_version,
                "semver": semver,
                "count": 0,
                "semver_candidates": [],
                "fallback_semvers": [],
            },
        )
        bucket["count"] += 1
        if semver:
            bucket["fallback_semvers"].append(semver)
        if protocol_version in protocol_semver_map:
            bucket["semver_candidates"].extend(protocol_semver_map[protocol_version])

    enabled_total = normalize_int((masternode_count or {}).get("enabled")) or len(enabled_nodes)
    total = normalize_int((masternode_count or {}).get("total")) or len(masternodes)
    versions = _build_structured_version_buckets(buckets, minimum_subver)

    for entry in versions:
        if entry["is_upgraded"] is True:
            upgraded_enabled += entry["count"]
        elif entry["is_upgraded"] is False:
            legacy_enabled += entry["count"]
        else:
            unknown_enabled += entry["count"]

    classified_total = upgraded_enabled + legacy_enabled + unknown_enabled
    if enabled_total > classified_total:
        remainder = enabled_total - classified_total
        versions.append(
            {
                "protocol_version": None,
                "display_version": "unknown",
                "semver": None,
                "count": remainder,
                "is_upgraded": None,
            }
        )
        unknown_enabled += remainder

    upgrade_ratio = round(upgraded_enabled / enabled_total, 4) if enabled_total else 0.0
    versions.sort(key=_version_sort_key)
    return {
        "enabled": enabled_total,
        "total": total,
        "upgraded_enabled": upgraded_enabled,
        "legacy_enabled": legacy_enabled,
        "unknown_enabled": unknown_enabled,
        "upgrade_ratio": upgrade_ratio,
        "versions": versions,
    }


def resolve_masternode_version(
    masternode: dict[str, Any],
    ip_semver_map: dict[str, str] | None = None,
) -> tuple[int | None, str | None]:
    protocol_version = normalize_int(masternode.get("version"))
    semver = clean_semver(masternode.get("subver"))
    if semver is None:
        semver = clean_semver_from_raw(masternode.get("raw"))
    if semver is None and ip_semver_map:
        host = extract_host(masternode.get("ip_address") or masternode.get("ip"))
        if host in ip_semver_map:
            semver = ip_semver_map[host]
    if protocol_version is None and semver is None:
        return None, None
    return protocol_version, semver


def clean_semver(raw: str | None) -> str | None:
    parsed = parse_version_tuple(raw)
    if parsed is None:
        return None
    return ".".join(str(part) for part in parsed)


def clean_semver_from_raw(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or not SEMVER_MARKER_RE.search(text):
        return None
    return clean_semver(text)


def is_probable_ip_semver_noise(raw: str | None) -> bool:
    if raw is None:
        return False
    text = str(raw).strip()
    if not STRICT_SEMVER_RE.fullmatch(text):
        return False
    parts = [int(part) for part in text.split(".")]
    return parts[2] > 99 and parts[3] > 99


def compress_semver_labels(labels: list[str]) -> str | None:
    cleaned = [clean_semver(label) for label in labels]
    versions = [value for value in cleaned if value]
    if not versions:
        return None
    tuples = [parse_version_tuple(item) for item in versions]
    tuples = [item for item in tuples if item is not None]
    if not tuples:
        return None
    unique = sorted(set(tuples))
    if len(unique) == 1:
        return ".".join(str(part) for part in unique[0])

    columns = list(zip(*unique))
    prefix: list[str] = []
    for index, column in enumerate(columns):
        if len(set(column)) == 1:
            prefix.append(str(column[0]))
            continue
        if index == 3 and prefix:
            prefix.append("x")
            return ".".join(prefix)
        break
    return ".".join(str(part) for part in unique[0])


def normalize_semver_evidence(labels: Iterable[str | None]) -> list[tuple[int, int, int, int]]:
    evidence: list[tuple[int, int, int, int]] = []
    for label in labels:
        parsed = parse_version_tuple(label)
        if parsed is not None:
            evidence.append(parsed)
    return evidence


def classify_semver_evidence(
    labels: Iterable[str | None],
    minimum_subver: str | None,
) -> bool | None:
    minimum_version = parse_version_tuple(minimum_subver)
    if minimum_version is None:
        return None

    evidence = normalize_semver_evidence(labels)
    if not evidence:
        return None

    if all(version >= minimum_version for version in evidence):
        return True
    if all(version < minimum_version for version in evidence):
        return False
    return None


def build_masternode_summary_fingerprint(
    masternodes: list[dict[str, Any]],
    masternode_count: dict[str, int] | None,
    peers: list[dict[str, Any]],
) -> str:
    count_part = (
        normalize_int((masternode_count or {}).get("enabled")) or 0,
        normalize_int((masternode_count or {}).get("total")) or 0,
    )

    masternode_part = sorted(
        (
            str(item.get("txhash") or ""),
            normalize_int(item.get("outidx")) or -1,
            str(item.get("addr") or ""),
            str(item.get("ip_address") or ""),
            str(item.get("status") or ""),
            normalize_int(item.get("version")) or -1,
            clean_semver(item.get("subver")) or clean_semver_from_raw(item.get("raw")) or "",
        )
        for item in masternodes
    )
    peer_part = sorted(
        (
            str(peer.get("addr") or ""),
            normalize_int(peer.get("version")) or -1,
            clean_semver(peer.get("subver")) or "",
        )
        for peer in peers
    )
    payload = repr((count_part, masternode_part, peer_part))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _build_protocol_semver_map(peers: list[dict[str, Any]]) -> dict[int, list[str]]:
    protocol_semvers: dict[int, list[str]] = defaultdict(list)
    for peer in peers:
        protocol = normalize_int(peer.get("version"))
        semver = clean_semver(peer.get("subver"))
        if protocol is not None and semver is not None:
            protocol_semvers[protocol].append(semver)
    return protocol_semvers


def _build_structured_version_buckets(
    buckets: dict[tuple[int | None, str | None], dict[str, Any]],
    minimum_subver: str | None,
) -> list[dict[str, Any]]:
    structured: list[dict[str, Any]] = []

    for (protocol_version, semver), bucket in buckets.items():
        evidence_labels = [semver] if semver else (list(bucket["semver_candidates"]) + list(bucket["fallback_semvers"]))
        is_upgraded = classify_semver_evidence(evidence_labels, minimum_subver)
        display_version = "unknown" if protocol_version is None else str(protocol_version)

        structured.append(
            {
                "protocol_version": protocol_version,
                "display_version": display_version,
                "semver": semver,
                "count": bucket["count"],
                "is_upgraded": is_upgraded,
            }
        )

    return structured


def _version_sort_key(entry: dict[str, Any]) -> tuple[int, int, tuple[int, ...]]:
    protocol_version = entry.get("protocol_version")
    semver = entry.get("semver") or ""
    semver_tuple = parse_version_tuple(semver) or (0, 0, 0, 0)
    negated_semver = tuple(-x for x in semver_tuple)
    if protocol_version is None:
        return (1, 0, negated_semver)
    return (0, -int(protocol_version), negated_semver)
