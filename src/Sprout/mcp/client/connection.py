"""One stdio connection to an external MCP server."""

from __future__ import annotations

import logging

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger("sprout.mcp.client")


class MCPConnection:
    """Owns the lifecycle of one external MCP server subprocess.

    Use as an async context manager, or call :meth:`start` / :meth:`stop`.
    """

    def __init__(
        self,
        name: str,
        command: str,
        args: tuple[str, ...] | list[str] = (),
        env: dict[str, str] | None = None,
    ) -> None:
        self.name = name
        self._command = command
        self._args = list(args)
        self._env = env
        self._session: ClientSession | None = None
        self._stdio_cm = None
        self._session_cm = None
        self._started = False

    @property
    def session(self) -> ClientSession:
        if self._session is None:
            raise RuntimeError(f"MCP connection {self.name!r} is not started")
        return self._session

    async def start(self) -> None:
        if self._started:
            return
        params = StdioServerParameters(
            command=self._command, args=self._args, env=self._env
        )
        self._stdio_cm = stdio_client(params)
        read_stream, write_stream = await self._stdio_cm.__aenter__()
        self._session_cm = ClientSession(read_stream, write_stream)
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()
        self._started = True
        logger.info("MCP connection %r started (%s)", self.name, self._command)

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        for cm in (self._session_cm, self._stdio_cm):
            if cm is None:
                continue
            try:
                await cm.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001 - shutdown must not raise
                logger.warning("Error while closing MCP connection %r", self.name, exc_info=True)
        self._session = None
        self._session_cm = None
        self._stdio_cm = None

    async def __aenter__(self) -> MCPConnection:
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.stop()

    # -- operations -------------------------------------------------------
    async def list_tools(self) -> list:
        result = await self.session.list_tools()
        return list(result.tools)

    async def call_tool(self, name: str, arguments: dict) -> object:
        return await self.session.call_tool(name, arguments or {})

    async def list_resources(self) -> list:
        result = await self.session.list_resources()
        return list(result.resources)

    async def list_prompts(self) -> list:
        result = await self.session.list_prompts()
        return list(result.prompts)
