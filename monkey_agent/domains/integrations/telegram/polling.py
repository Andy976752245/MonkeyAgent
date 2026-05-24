from __future__ import annotations

import time
from typing import Any

from monkey_agent.core.config import Settings
from monkey_agent.domains.integrations.telegram.client import TelegramClient
from monkey_agent.domains.integrations.telegram.handler import TelegramMessageHandler


class TelegramPollingRunner:
    def __init__(
        self,
        settings: Settings,
        client: TelegramClient,
        handler: TelegramMessageHandler,
    ) -> None:
        self.settings = settings
        self.client = client
        self.handler = handler
        self.offset: int | None = None

    def run(self, once: bool = False) -> dict[str, Any]:
        processed = 0
        errors: list[str] = []
        while True:
            try:
                updates = self.client.get_updates(
                    offset=self.offset,
                    timeout=self.settings.telegram_poll_timeout,
                )
                for update in updates:
                    update_id = int(update.get("update_id") or 0)
                    if update_id:
                        self.offset = update_id + 1
                    self.handler.handle_update(update)
                    processed += 1
                if once:
                    return {"status": "completed", "processed": processed, "errors": errors}
                time.sleep(self.settings.telegram_poll_interval)
            except KeyboardInterrupt:
                return {"status": "stopped", "processed": processed, "errors": errors}
            except Exception as exc:  # noqa: BLE001 - polling should keep running
                errors.append(str(exc))
                if once:
                    return {"status": "failed", "processed": processed, "errors": errors}
                time.sleep(max(self.settings.telegram_poll_interval, 3))
