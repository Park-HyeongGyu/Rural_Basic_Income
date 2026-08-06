from __future__ import annotations

import logging
import shlex
import socket
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from rural_basic_income.config import Settings, get_settings

LOGGER = logging.getLogger(__name__)
NotificationStatus = Literal["sent", "disabled", "missing_config", "failed"]
NotificationOutcome = Literal["success", "failure"]
NOTIFIABLE_COMMANDS = {"update", "clean", "import", "export"}
MAX_ERROR_LENGTH = 1800


@dataclass(frozen=True)
class NotificationResult:
    status: NotificationStatus
    detail: str = ""

    @property
    def sent(self) -> bool:
        return self.status == "sent"


def telegram_configured(settings: Settings) -> bool:
    return bool(settings.telegram_bot_token and settings.telegram_chat_id)


def notification_enabled(
    outcome: NotificationOutcome,
    settings: Settings,
) -> bool:
    if outcome == "success":
        return settings.enable_success_telegram
    return settings.enable_failure_telegram


def command_is_notifiable(command: str) -> bool:
    return command.split()[0] in NOTIFIABLE_COMMANDS


def format_command(argv: tuple[str, ...]) -> str:
    if not argv:
        return "rbi"
    return "rbi " + shlex.join(argv)


def truncate_message(value: str, *, limit: int = MAX_ERROR_LENGTH) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def format_worker_message(
    *,
    outcome: NotificationOutcome,
    command: str,
    argv: tuple[str, ...],
    duration_seconds: float | None = None,
    error: BaseException | None = None,
) -> str:
    title = "RBI worker succeeded" if outcome == "success" else "RBI worker failed"
    lines = [
        f"[{title}]",
        f"time: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"host: {socket.gethostname()}",
        f"command: {format_command(argv)}",
        f"command_type: {command}",
    ]
    if duration_seconds is not None:
        lines.append(f"duration_seconds: {duration_seconds:.1f}")
    if error is not None:
        error_text = truncate_message(f"{type(error).__name__}: {error}")
        lines.append(f"error: {error_text}")
    return "\n".join(lines)


def send_telegram_message(
    text: str,
    *,
    settings: Settings | None = None,
    timeout: float = 10,
) -> NotificationResult:
    resolved_settings = settings or get_settings()
    if not telegram_configured(resolved_settings):
        return NotificationResult("missing_config")

    url = (
        "https://api.telegram.org/"
        f"bot{resolved_settings.telegram_bot_token}/sendMessage"
    )
    payload = urlencode(
        {
            "chat_id": resolved_settings.telegram_chat_id,
            "text": text,
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    request = Request(
        url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            response.read()
    except (HTTPError, URLError, OSError) as exc:
        LOGGER.warning("telegram notification failed: %s", exc)
        return NotificationResult("failed", str(exc))

    if status >= 400:
        LOGGER.warning("telegram notification failed with HTTP status %s", status)
        return NotificationResult("failed", f"HTTP {status}")

    return NotificationResult("sent")


def notify_worker_command(
    *,
    outcome: NotificationOutcome,
    command: str,
    argv: tuple[str, ...],
    duration_seconds: float | None = None,
    error: BaseException | None = None,
    settings: Settings | None = None,
) -> NotificationResult:
    resolved_settings = settings or get_settings()
    if not command_is_notifiable(command):
        return NotificationResult("disabled")
    if not notification_enabled(outcome, resolved_settings):
        return NotificationResult("disabled")
    if not telegram_configured(resolved_settings):
        LOGGER.warning(
            "telegram %s notification enabled but token/chat id is missing",
            outcome,
        )
        return NotificationResult("missing_config")

    message = format_worker_message(
        outcome=outcome,
        command=command,
        argv=argv,
        duration_seconds=duration_seconds,
        error=error,
    )
    result = send_telegram_message(message, settings=resolved_settings)
    LOGGER.info(
        "telegram %s notification status=%s command=%s",
        outcome,
        result.status,
        command,
    )
    return result


def notify_worker_command_success(
    *,
    command: str,
    argv: tuple[str, ...],
    duration_seconds: float | None = None,
) -> NotificationResult:
    return notify_worker_command(
        outcome="success",
        command=command,
        argv=argv,
        duration_seconds=duration_seconds,
    )


def notify_worker_command_failure(
    *,
    command: str,
    argv: tuple[str, ...],
    duration_seconds: float | None = None,
    error: BaseException,
) -> NotificationResult:
    return notify_worker_command(
        outcome="failure",
        command=command,
        argv=argv,
        duration_seconds=duration_seconds,
        error=error,
    )
