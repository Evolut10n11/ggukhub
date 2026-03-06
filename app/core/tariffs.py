from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.utils import load_json


class TariffDirectory:
    def __init__(self, path: Path):
        data = load_json(path)
        if not isinstance(data, dict):
            raise ValueError("Tariffs file must be a JSON object")
        self._data: dict[str, Any] = data

    def list_complexes(self) -> list[str]:
        return list(self._data.keys())

    def get_tariff(self, complex_name: str) -> Any:
        return self._data.get(complex_name)

