from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import httpx

from monitor.collector.normalize import normalize_float, normalize_int
from monitor.config import ComparisonSource, Settings


MASTERNODE_COUNT_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")


class MonitorSources:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        default_timeout = httpx.Timeout(
            settings.request_read_timeout_seconds,
            connect=settings.request_connect_timeout_seconds,
        )
        client_limits = httpx.Limits(
            max_connections=settings.rpc_max_connections,
            max_keepalive_connections=settings.rpc_max_keepalive_connections,
        )
        self.rpc_client = httpx.AsyncClient(
            timeout=default_timeout,
            limits=client_limits,
            headers={"User-Agent": "PEPEPOWMonitor/1.0"},
        )
        self.http_client = httpx.AsyncClient(
            timeout=default_timeout,
            limits=client_limits,
            headers={"User-Agent": "PEPEPOWMonitor/1.0"},
        )

    async def close(self) -> None:
        await self.rpc_client.aclose()
        await self.http_client.aclose()

    async def rpc_call(
        self,
        method: str,
        params: list[Any] | None = None,
        *,
        url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout_seconds: float | None = None,
    ) -> Any:
        auth = None
        rpc_username = username if username is not None else self.settings.rpc_username
        rpc_password = password if password is not None else self.settings.rpc_password
        if rpc_username:
            auth = httpx.BasicAuth(rpc_username, rpc_password or "")

        response = await self.rpc_client.post(
            url or self.settings.rpc_url,
            json={
                "jsonrpc": "1.0",
                "id": "monitor",
                "method": method,
                "params": params or [],
            },
            auth=auth,
            timeout=self._build_timeout(timeout_seconds),
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError(str(payload["error"]))
        return payload.get("result")

    async def rpc_get_blockcount(self) -> int:
        return normalize_int(await self.rpc_call("getblockcount", timeout_seconds=1.5)) or 0

    async def rpc_get_blockhash(self, height: int) -> str:
        return str(await self.rpc_call("getblockhash", [height], timeout_seconds=2.0))

    async def rpc_get_block(self, blockhash: str) -> dict[str, Any]:
        payload = await self.rpc_call("getblock", [blockhash], timeout_seconds=2.0)
        if not isinstance(payload, dict):
            raise RuntimeError("invalid getblock payload")
        return payload

    async def rpc_get_peerinfo(self) -> list[dict[str, Any]]:
        payload = await self.rpc_call("getpeerinfo", timeout_seconds=2.0)
        if not isinstance(payload, list):
            raise RuntimeError("invalid getpeerinfo payload")
        return payload

    async def rpc_get_chaintips(self) -> list[dict[str, Any]]:
        payload = await self.rpc_call("getchaintips", timeout_seconds=2.0)
        if not isinstance(payload, list):
            raise RuntimeError("invalid getchaintips payload")
        return payload

    async def rpc_get_networkhashps(self) -> float:
        return normalize_float(await self.rpc_call("getnetworkhashps", timeout_seconds=2.0)) or 0.0

    async def rpc_get_masternodecount(self) -> dict[str, int]:
        payload = await self.rpc_call(
            self.settings.masternode_count_rpc_method,
            list(self.settings.masternode_count_rpc_params),
            timeout_seconds=3.0,
        )
        return self._normalize_masternode_count(payload)

    async def rpc_get_masternodelist(self) -> list[dict[str, Any]]:
        payload = await self.rpc_call(
            self.settings.masternode_list_rpc_method,
            list(self.settings.masternode_list_rpc_params),
            timeout_seconds=3.0,
        )
        return self._normalize_masternode_list(payload)

    async def explorer_get_blockcount(self) -> int:
        response = await self.http_client.get(f"{self.settings.explorer_base_url}/api/getblockcount")
        response.raise_for_status()
        return normalize_int(response.text) or 0

    async def explorer_get_difficulty(self) -> float:
        response = await self.http_client.get(f"{self.settings.explorer_base_url}/api/getdifficulty")
        response.raise_for_status()
        return normalize_float(response.text) or 0.0

    async def explorer_get_summary(self) -> dict[str, Any]:
        response = await self.http_client.get(f"{self.settings.explorer_base_url}/ext/getsummary")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("invalid explorer summary payload")
        return payload

    async def explorer_get_masternodecount(self) -> dict[str, int]:
        response = await self.http_client.get(f"{self.settings.explorer_base_url}/api/getmasternodecount")
        response.raise_for_status()
        payload: Any
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            payload = response.json()
        else:
            payload = response.text
        return self._normalize_masternode_count(payload)

    async def explorer_get_masternodelist(self) -> list[dict[str, Any]]:
        response = await self.http_client.get(f"{self.settings.explorer_base_url}/ext/getmasternodelist")
        response.raise_for_status()
        payload = response.json()
        return self._normalize_masternode_list(payload)

    async def public_get_height(self) -> int:
        response = await self.http_client.get(f"{self.settings.public_api_base_url}/v1/chain/height")
        response.raise_for_status()
        payload = response.json()
        return normalize_int(payload.get("height")) or 0

    async def public_get_mempool(self) -> dict[str, Any]:
        response = await self.http_client.get(f"{self.settings.public_api_base_url}/v1/mempool/info")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("invalid public mempool payload")
        return payload

    async def check_site(self, url: str) -> dict[str, Any]:
        started = time.perf_counter()
        response = await self.http_client.get(
            url,
            follow_redirects=True,
            timeout=self._build_timeout(5.0),
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return {
            "url": url,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
        }

    async def check_mining_pool(self, host: str, port: int) -> dict[str, Any]:
        started = time.perf_counter()
        connect_timeout = min(self.settings.request_connect_timeout_seconds, 2.0)
        read_timeout = min(self.settings.request_read_timeout_seconds, 2.0)
        probe_line = b'{"id":1,"method":"mining.subscribe","params":[]}\n'
        reader: asyncio.StreamReader | None = None
        writer: asyncio.StreamWriter | None = None
        tcp_connect_ok = False
        stratum_ok = False
        error: str | None = None
        invalid_json_seen = False
        lines_seen = 0
        bytes_read = 0

        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=connect_timeout)
            tcp_connect_ok = True
            writer.write(probe_line)
            await writer.drain()

            while lines_seen < 3 and bytes_read < 4096:
                try:
                    chunk = await asyncio.wait_for(reader.readline(), timeout=read_timeout)
                except TimeoutError as exc:
                    raise TimeoutError("read timeout waiting for stratum response") from exc

                if not chunk:
                    if not stratum_ok and not invalid_json_seen:
                        error = "eof before response"
                    break

                bytes_read += len(chunk)
                lines_seen += 1
                line = chunk.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    invalid_json_seen = True
                    error = "invalid json response"
                    continue
                if isinstance(payload, dict):
                    stratum_ok = True
                    error = None
                    break

            if tcp_connect_ok and not stratum_ok and error is None:
                error = "invalid json response" if invalid_json_seen else "no valid stratum response"
        except TimeoutError as exc:
            message = str(exc) or exc.__class__.__name__
            error = "connect timeout" if not tcp_connect_ok and "stratum" not in message else message
        except ConnectionRefusedError:
            error = "connection refused"
        except OSError as exc:
            message = str(exc).strip().lower()
            if not tcp_connect_ok:
                if "name or service not known" in message or "temporary failure in name resolution" in message:
                    error = "dns resolution failed"
                elif "timed out" in message:
                    error = "connect timeout"
                else:
                    error = str(exc) or exc.__class__.__name__
            else:
                error = str(exc) or exc.__class__.__name__
        finally:
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass

        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return {
            "tcp_connect_ok": tcp_connect_ok,
            "stratum_ok": stratum_ok,
            "latency_ms": latency_ms,
            "error": None if stratum_ok else error,
        }

    async def comparison_get_state(self, source: ComparisonSource, local_height: int) -> dict[str, Any]:
        if source.type == "explorer_http":
            base_url = (source.base_url or "").rstrip("/")
            height_response = await self.http_client.get(f"{base_url}/api/getblockcount")
            height_response.raise_for_status()
            remote_height = normalize_int(height_response.text) or 0
            remote_hash = None
            if remote_height == local_height:
                hash_response = await self.http_client.get(f"{base_url}/api/getblockhash", params={"height": local_height})
                hash_response.raise_for_status()
                remote_hash = hash_response.text.strip()
            return {"height": remote_height, "hash": remote_hash}

        if source.type == "rpc_http":
            rpc_url = source.rpc_url or source.base_url
            if not rpc_url:
                raise RuntimeError(f"comparison source {source.name} missing rpc_url")
            remote_height = normalize_int(
                await self.rpc_call(
                    "getblockcount",
                    [],
                    url=rpc_url,
                    username=source.username,
                    password=source.password,
                    timeout_seconds=1.5,
                )
            ) or 0
            remote_hash = None
            if remote_height == local_height:
                remote_hash = str(
                    await self.rpc_call(
                        "getblockhash",
                        [local_height],
                        url=rpc_url,
                        username=source.username,
                        password=source.password,
                        timeout_seconds=2.0,
                    )
                )
            return {"height": remote_height, "hash": remote_hash}

        raise RuntimeError(f"unsupported comparison source type: {source.type}")

    def _build_timeout(self, timeout_seconds: float | None) -> httpx.Timeout | None:
        if timeout_seconds is None:
            return None
        connect_timeout = min(self.settings.request_connect_timeout_seconds, timeout_seconds)
        return httpx.Timeout(timeout_seconds, connect=connect_timeout)

    def _normalize_masternode_count(self, payload: Any) -> dict[str, int]:
        if isinstance(payload, dict):
            total = normalize_int(payload.get("total"))
            enabled = normalize_int(payload.get("enabled"))
            if total is not None and enabled is not None:
                return {"total": total, "enabled": enabled}
        if isinstance(payload, str):
            match = MASTERNODE_COUNT_RE.match(payload)
            if match:
                enabled, total = match.groups()
                return {"total": int(total), "enabled": int(enabled)}
            total_match = re.search(r"Total:\s*(\d+)", payload)
            enabled_match = re.search(r"Enabled:\s*(\d+)", payload)
            if total_match and enabled_match:
                return {"total": int(total_match.group(1)), "enabled": int(enabled_match.group(1))}
        raise RuntimeError("invalid masternode count payload")

    def _normalize_masternode_list(self, payload: Any) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        if isinstance(payload, list):
            items = list(payload)
        elif isinstance(payload, dict):
            items = []
            for key, value in payload.items():
                if isinstance(value, dict):
                    item = dict(value)
                    item.setdefault("txhash", key)
                else:
                    item = {"raw": value, "txhash": key}
                items.append(item)
        else:
            raise RuntimeError("invalid masternode list payload")

        for item in items:
            if isinstance(item, dict):
                normalized.append(dict(item))
            else:
                normalized.append({"raw": item})
        return normalized
