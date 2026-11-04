"""Machine-readable tags carried inside chat messages.

Parsing is deliberately strict: a tag must match exactly, name a known clause and hold a valid
value. Anything else is treated as ordinary conversation and never reaches Counsel. This is what
keeps free text from the deal room, including prompt injection, away from the limits.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .clauses import CLAUSES, parse_value, show

TAG = re.compile(r"`\[([A-Z]+)(?: ([a-z_]+))?(?:=([A-Za-z0-9. ]{1,24}?))?(?: ([A-Z_]+))?\]`")


@dataclass(frozen=True)
class Tag:
    verb: str
    clause: str | None = None
    value: float | str | None = None
    extra: str | None = None


def render(verb: str, clause: str | None = None, value: float | str | None = None, extra: str | None = None) -> str:
    text = verb
    if clause:
        text += f" {clause}"
    if value is not None and clause:
        text += f"={show(clause, value)}"
    if extra:
        text += f" {extra}"
    return f"`[{text}]`"


def parse(body: str) -> list[Tag]:
    """Return the valid tags in a message. Malformed tags are ignored, not repaired."""
    tags: list[Tag] = []
    for verb, clause, raw, extra in TAG.findall(body):
        if clause and clause not in CLAUSES:
            continue
        value: float | str | None = None
        if raw:
            if not clause:
                continue
            try:
                value = parse_value(clause, raw)
            except ValueError:
                continue
        tags.append(Tag(verb, clause or None, value, extra or None))
    return tags
