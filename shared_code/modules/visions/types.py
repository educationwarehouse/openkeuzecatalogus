"""Typed payloads for public vision resolution."""

import typing as t
from collections import defaultdict

from shared_code.data_model import AnyDict

type VisionIds = defaultdict[str, list[int | None]]  # {theme: [vision_ed.id per compared record]}


class ResolvedVision(t.TypedDict):
    """One public vision resolved from a method or its supplier."""

    theme: str
    source: str
    content: str
    properties: AnyDict
