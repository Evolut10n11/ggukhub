from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def normalize_text(value: str) -> str:
    return " ".join(value.strip().lower().split())


def normalize_phone(value: str) -> str | None:
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("8"):
        digits = f"7{digits[1:]}"
    if len(digits) != 11 or not digits.startswith("7"):
        return None
    return f"+{digits}"


def compose_scope_key(jk: str | None, category: str) -> str:
    category_part = normalize_text(category)
    if jk and jk.strip():
        return f"{normalize_text(jk)}::{category_part}"
    return category_part


def build_address(house: str, entrance: str | None, apartment: str) -> str:
    chunks = [f"дом {house.strip()}"]
    if entrance and entrance.strip():
        chunks.append(f"подъезд {entrance.strip()}")
    chunks.append(f"кв {apartment.strip()}")
    return ", ".join(chunks)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
