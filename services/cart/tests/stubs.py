"""Управляемый HTTP-стаб Catalog для интеграционных тестов (задачи 3.2/5.3).

Минимальный asyncio TCP-сервер, отвечающий на GET своим поведением
(status/body/задержка), чтобы проверять таймауты и circuit breaker на
реальных сокетах, а не на моках.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass
class StubResponse:
    """Ответ стаба: статус, тело и необязательная задержка."""

    status: int = 200
    body: bytes = b"{}"
    delay: float = 0.0
    content_type: str = "application/json"


Handler = Callable[[str], "StubResponse | Awaitable[StubResponse]"]


class StubCatalogServer:
    """Запускается на 127.0.0.1 со случайным портом; handler задаёт поведение."""

    def __init__(self, handler: Handler) -> None:
        self._handler = handler
        self._server: asyncio.Server | None = None
        self.requests: list[str] = []

    @property
    def port(self) -> int:
        assert self._server is not None
        return self._server.sockets[0].getsockname()[1]

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await reader.readline()
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
            path = request_line.decode().split()[1] if request_line else "/"
            self.requests.append(path)
            response = self._handler(path)
            if not isinstance(response, StubResponse):
                response = await response
            if response.delay:
                await asyncio.sleep(response.delay)
            reason = {200: "OK", 404: "Not Found"}.get(response.status, "Status")
            head = (
                f"HTTP/1.1 {response.status} {reason}\r\n"
                f"Content-Type: {response.content_type}\r\n"
                f"Content-Length: {len(response.body)}\r\n"
                "Connection: close\r\n\r\n"
            ).encode()
            writer.write(head + response.body)
            await writer.drain()
        except Exception:  # noqa: BLE001, S110 - стаб не должен ронять процесс
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001, S110
                pass
