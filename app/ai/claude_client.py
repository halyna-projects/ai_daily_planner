from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from app.ai.prompts import EXTRACT_DUE_DATE_TOOL, build_system_prompt
from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class ParsedTask:
    title: str
    due_at: datetime | None


class TaskParser:
    """Resolves a deadline out of a free-text task message. Falls back to a
    lightweight regex parser when no API key is configured, so the bot stays
    runnable end-to-end without a live key (same pattern as the real estate
    bot's DialogueEngine)."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None
        if self.settings.anthropic_api_key:
            from anthropic import Anthropic

            self._client = Anthropic(api_key=self.settings.anthropic_api_key)

    @property
    def is_live(self) -> bool:
        return self._client is not None

    def parse(self, text: str, now: datetime) -> ParsedTask:
        title = text.strip()

        if not self.is_live:
            from app.ai.fallback import extract_due_at

            return ParsedTask(title=title, due_at=extract_due_at(text, now))

        try:
            response = self._client.messages.create(
                model=self.settings.anthropic_model,
                max_tokens=256,
                system=build_system_prompt(now.isoformat()),
                tools=[EXTRACT_DUE_DATE_TOOL],
                tool_choice={"type": "tool", "name": "extract_task"},
                messages=[{"role": "user", "content": text}],
            )
            for block in response.content:
                if block.type == "tool_use" and block.name == "extract_task":
                    due_at_raw = block.input.get("due_at")
                    due_at = datetime.fromisoformat(due_at_raw) if due_at_raw else None
                    return ParsedTask(title=title, due_at=due_at)
        except Exception:
            logger.exception("TaskParser: live extraction failed, falling back")

        from app.ai.fallback import extract_due_at

        return ParsedTask(title=title, due_at=extract_due_at(text, now))
