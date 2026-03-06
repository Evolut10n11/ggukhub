from __future__ import annotations

from pathlib import Path

from app.core.utils import load_json, normalize_text


class CategoryClassifier:
    def __init__(self, rules: dict[str, dict[str, object]]):
        self._rules = rules

    @classmethod
    def from_file(cls, path: Path) -> "CategoryClassifier":
        data = load_json(path)
        if not isinstance(data, dict):
            raise ValueError("Categories file must be an object")
        return cls(data)

    def classify(self, text: str) -> str:
        source = normalize_text(text)
        best_category = "other"
        best_score = 0

        for category, config in self._rules.items():
            keywords = config.get("keywords", [])
            if not isinstance(keywords, list):
                continue
            score = 0
            for keyword in keywords:
                token = normalize_text(str(keyword))
                if token and token in source:
                    score += len(token)
            if score > best_score:
                best_score = score
                best_category = category

        return best_category

    def categories(self) -> list[str]:
        return list(self._rules.keys())

    def label(self, category: str) -> str:
        raw = self._rules.get(category, {})
        label = raw.get("label", category)
        return str(label)

