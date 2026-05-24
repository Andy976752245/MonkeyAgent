from __future__ import annotations

from pathlib import Path
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
        self.offset_path = _offset_path(settings)
        self.offset: int | None = _read_offset(self.offset_path)

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
                        _write_offset(self.offset_path, self.offset)
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


def _offset_path(settings: Settings) -> Path:
    return settings.runtime_dir / "personal" / "integrations" / "telegram_offset.txt"


def _read_offset(path: Path) -> int | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _write_offset(path: Path, offset: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(str(offset), encoding="utf-8")
    tmp.replace(path)
