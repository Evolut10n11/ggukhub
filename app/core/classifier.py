from __future__ import annotations

from pathlib import Path

from app.core.utils import load_json, normalize_text


class CategoryClassifier:
    def __init__(self, rules: dict[str, dict[str, object]]):
        self._rules = rules
        # Pre-normalize keywords once at init for fast classify()
        self._normalized: dict[str, list[tuple[str, int]]] = {}
        self._labels: dict[str, str] = {}
        for category, config in rules.items():
            self._labels[category] = str(config.get("label", category))
            keywords = config.get("keywords", [])
            if not isinstance(keywords, list):
                continue
            tokens: list[tuple[str, int]] = []
            for kw in keywords:
                token = normalize_text(str(kw))
                if token:
                    tokens.append((token, len(token)))
            self._normalized[category] = tokens

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

        for category, tokens in self._normalized.items():
            score = 0
            for token, length in tokens:
                if token in source:
                    score += length
            if score > best_score:
                best_score = score
                best_category = category

        return best_category

    def categories(self) -> list[str]:
        return list(self._rules.keys())

    def label(self, category: str) -> str:
        return self._labels.get(category, category)
