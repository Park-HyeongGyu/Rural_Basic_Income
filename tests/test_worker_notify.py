from __future__ import annotations

from types import SimpleNamespace
from urllib.error import URLError
from urllib.parse import parse_qs

from rural_basic_income.worker import notify


class TelegramResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return b'{"ok": true}'


def make_settings(
    *,
    token: str | None = "TOKEN",
    chat_id: str | None = "CHAT",
    success: bool = True,
    failure: bool = True,
):
    return SimpleNamespace(
        telegram_bot_token=token,
        telegram_chat_id=chat_id,
        enable_success_telegram=success,
        enable_failure_telegram=failure,
    )


def test_send_telegram_message_posts_form_payload(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, *, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = parse_qs(request.data.decode("utf-8"))
        return TelegramResponse()

    monkeypatch.setattr(notify, "urlopen", fake_urlopen)

    result = notify.send_telegram_message(
        "hello",
        settings=make_settings(),
        timeout=3,
    )

    assert result.status == "sent"
    assert captured["url"].endswith("/botTOKEN/sendMessage")
    assert captured["timeout"] == 3
    assert captured["payload"]["chat_id"] == ["CHAT"]
    assert captured["payload"]["text"] == ["hello"]
    assert captured["payload"]["disable_web_page_preview"] == ["true"]


def test_send_telegram_message_returns_failed_without_raising(monkeypatch) -> None:
    def fake_urlopen(request, *, timeout):
        raise URLError("network down")

    monkeypatch.setattr(notify, "urlopen", fake_urlopen)

    result = notify.send_telegram_message(
        "hello",
        settings=make_settings(),
    )

    assert result.status == "failed"
    assert "network down" in result.detail


def test_notify_worker_command_respects_disabled_success() -> None:
    result = notify.notify_worker_command(
        outcome="success",
        command="update",
        argv=("update", "--latest"),
        settings=make_settings(success=False),
    )

    assert result.status == "disabled"


def test_notify_worker_command_respects_missing_config() -> None:
    result = notify.notify_worker_command(
        outcome="failure",
        command="update",
        argv=("update", "--latest"),
        error=RuntimeError("boom"),
        settings=make_settings(token=None),
    )

    assert result.status == "missing_config"


def test_notify_worker_command_allows_import_subcommand(monkeypatch) -> None:
    calls = []

    def fake_send_telegram_message(text, *, settings=None):
        calls.append(text)
        return notify.NotificationResult("sent")

    monkeypatch.setattr(notify, "send_telegram_message", fake_send_telegram_message)

    result = notify.notify_worker_command(
        outcome="success",
        command="import living-population",
        argv=("import", "living-population", "--file", "/imports/living.csv"),
        settings=make_settings(),
    )

    assert result.status == "sent"
    assert len(calls) == 1
    assert "command_type: import living-population" in calls[0]
