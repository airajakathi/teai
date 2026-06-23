"""Third-party service connectors for TeAI Builder."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ServiceConnector:
    service: str
    name: str
    connected: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    last_checked_at: float = field(default_factory=time.time)
    last_error: str | None = None


class ConnectorRegistry:
    def __init__(self) -> None:
        self.connectors: dict[str, ServiceConnector] = {}
        self.clients: dict[str, Callable[..., Any]] = {}

    def register(self, connector: ServiceConnector, client: Callable[..., Any]) -> None:
        self.connectors[connector.service] = connector
        self.clients[connector.service] = client

    async def connect(self, service: str) -> bool:
        connector = self.connectors.get(service)
        if not connector:
            raise KeyError(f"Unknown service connector: {service}")
        try:
            client = self.clients[service]
            if asyncio.iscoroutinefunction(getattr(client, "connect", None)):
                await client.connect()
            connector.connected = True
            connector.last_error = None
            return True
        except Exception as exc:
            connector.connected = False
            connector.last_error = str(exc)
            return False

    async def disconnect(self, service: str) -> None:
        connector = self.connectors.get(service)
        if connector:
            connector.connected = False
