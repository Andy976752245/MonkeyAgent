from __future__ import annotations

from pathlib import Path
from contextlib import suppress
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
        self.lock_path = _lock_path(settings)
        self.offset: int | None = _read_offset(self.offset_path)

    def run(self, once: bool = False) -> dict[str, Any]:
        lock_handle = _acquire_process_lock(self.lock_path)
        if lock_handle is None:
            return {
                "status": "already_running",
                "processed": 0,
                "errors": ["another Telegram polling process is already running"],
            }
        processed = 0
        errors: list[str] = []
        try:
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
        finally:
            _release_process_lock(lock_handle)


def _offset_path(settings: Settings) -> Path:
    return settings.runtime_dir / "personal" / "integrations" / "telegram_offset.txt"


def _lock_path(settings: Settings) -> Path:
    return settings.runtime_dir / "personal" / "integrations" / "telegram_polling.lock"


def _acquire_process_lock(path: Path) -> Any | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (ImportError, BlockingIOError, OSError):
        handle.close()
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(str(time.time()))
    handle.flush()
    return handle


def _release_process_lock(handle: Any) -> None:
    with suppress(Exception):
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    with suppress(Exception):
        handle.close()


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
