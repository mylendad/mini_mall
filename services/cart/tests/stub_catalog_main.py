"""Стаб Catalog для ручных проверок (k6, walk-through): все продукты активны.

Запуск: uv run python tests/stub_catalog_main.py   (порт 8000)
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.stubs import StubCatalogServer, StubResponse


class FixedPortStubServer(StubCatalogServer):
    """Стаб на фиксированном порту (для BASE_URL сервисов)."""

    async def start(self) -> None:
        host = os.environ.get("STUB_HOST", "127.0.0.1")
        self._server = await asyncio.start_server(
            self._handle, host, int(os.environ.get("STUB_PORT", "8000"))
        )


async def main() -> None:
    server = FixedPortStubServer(
        lambda path: StubResponse(status=200, body=b'{"is_active": true}')
    )
    await server.start()
    print("stub catalog listening on", server.port, flush=True)
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
