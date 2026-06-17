from __future__ import annotations

import asyncio
import socket
import unittest

from monitor.collector.sources import MonitorSources
from monitor.tests.test_scheduler import build_settings


async def _start_pool_server(handler):
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    sockets = server.sockets or []
    port = sockets[0].getsockname()[1]
    return server, port


class MiningPoolSourceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.settings = build_settings()
        self.settings.request_connect_timeout_seconds = 0.1
        self.settings.request_read_timeout_seconds = 0.1
        self.sources = MonitorSources(self.settings)

    async def asyncTearDown(self) -> None:
        await self.sources.close()

    async def test_check_mining_pool_reports_stratum_success(self):
        async def handler(reader, writer):
            await reader.readline()
            writer.write(b'{"id":1,"result":[[], "sub", 4], "error":null}\n')
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server, port = await _start_pool_server(handler)
        self.addAsyncCleanup(server.wait_closed)
        try:
            result = await self.sources.check_mining_pool("127.0.0.1", port)
        finally:
            server.close()

        self.assertTrue(result["tcp_connect_ok"])
        self.assertTrue(result["stratum_ok"])
        self.assertIsNone(result["error"])

    async def test_check_mining_pool_reports_read_timeout_as_degraded(self):
        async def handler(reader, writer):
            await reader.readline()
            await asyncio.sleep(0.3)
            writer.close()
            await writer.wait_closed()

        server, port = await _start_pool_server(handler)
        self.addAsyncCleanup(server.wait_closed)
        try:
            result = await self.sources.check_mining_pool("127.0.0.1", port)
        finally:
            server.close()

        self.assertTrue(result["tcp_connect_ok"])
        self.assertFalse(result["stratum_ok"])
        self.assertEqual(result["error"], "read timeout waiting for stratum response")

    async def test_check_mining_pool_reports_invalid_json(self):
        async def handler(reader, writer):
            await reader.readline()
            writer.write(b'not-json\n')
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server, port = await _start_pool_server(handler)
        self.addAsyncCleanup(server.wait_closed)
        try:
            result = await self.sources.check_mining_pool("127.0.0.1", port)
        finally:
            server.close()

        self.assertTrue(result["tcp_connect_ok"])
        self.assertFalse(result["stratum_ok"])
        self.assertEqual(result["error"], "invalid json response")

    async def test_check_mining_pool_reports_connect_failure(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            unused_port = sock.getsockname()[1]

        result = await self.sources.check_mining_pool("127.0.0.1", unused_port)

        self.assertFalse(result["tcp_connect_ok"])
        self.assertFalse(result["stratum_ok"])
        self.assertIn(result["error"], {"connection refused", "connect timeout"})


if __name__ == "__main__":
    unittest.main()
