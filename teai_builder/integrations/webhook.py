"""Webhook integration for TeAI Builder."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Webhook:
    webhook_id: str
    url: str
    secret: str | None = None
    events: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WebhookDelivery:
    webhook_id: str
    event: str
    payload: dict[str, Any]
    delivered: bool = False
    status_code: int | None = None
    error: str | None = None


class WebhookManager:
    def __init__(self, http_client: Callable[..., Any] | None = None) -> None:
        self.webhooks: dict[str, Webhook] = {}
        self.deliveries: list[WebhookDelivery] = []
        self.http_client = http_client

    def register(self, webhook: Webhook) -> None:
        self.webhooks[webhook.webhook_id] = webhook

    def dispatch(self, event: str, payload: dict[str, Any]) -> list[WebhookDelivery]:
        deliveries: list[WebhookDelivery] = []
        for webhook in self.webhooks.values():
            if event not in webhook.events:
                continue
            delivery = WebhookDelivery(webhook_id=webhook.webhook_id, event=event, payload=payload)
            if self.http_client:
                try:
                    response = self.http_client(webhook.url, json=payload, headers=self._headers(webhook))
                    delivery.status_code = getattr(response, "status_code", None)
                    delivery.delivered = True
                except Exception as exc:
                    delivery.error = str(exc)
            self.deliveries.append(delivery)
            deliveries.append(delivery)
        return deliveries

    def _headers(self, webhook: Webhook) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if webhook.secret:
            signature = hmac.new(webhook.secret.encode(), json.dumps({}).encode(), hashlib.sha256).hexdigest()
            headers["X-TEAI-Signature"] = signature
        return headers
