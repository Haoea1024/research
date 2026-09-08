"""Version-controlled Jinja prompt templates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape


PROMPT_ROOT = Path(__file__).with_name("prompts")


class PromptRenderer:
    def __init__(self, root: Path = PROMPT_ROOT) -> None:
        self.environment = Environment(
            loader=FileSystemLoader(root),
            autoescape=select_autoescape(default=False),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
        )

    def render(self, template_name: str, **context: Any) -> str:
        return self.environment.get_template(template_name).render(**context)
