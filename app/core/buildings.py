from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class HouseInfo:
    address: str
    entrances: int
    apartments: int


@dataclass(slots=True)
class ComplexInfo:
    name: str
    houses: list[HouseInfo] = field(default_factory=list)


@dataclass(slots=True)
class BuildingRegistry:
    complexes: list[ComplexInfo] = field(default_factory=list)
    standalone_houses: list[HouseInfo] = field(default_factory=list)

    @property
    def complex_names(self) -> list[str]:
        return [c.name for c in self.complexes]

    def houses_for_complex(self, name: str) -> list[HouseInfo]:
        for c in self.complexes:
            if c.name == name:
                return c.houses
        return []

    def find_house(self, address: str) -> HouseInfo | None:
        for c in self.complexes:
            for h in c.houses:
                if h.address == address:
                    return h
        for h in self.standalone_houses:
            if h.address == address:
                return h
        return None

    def complex_for_house(self, address: str) -> str | None:
        for c in self.complexes:
            for h in c.houses:
                if h.address == address:
                    return c.name
        return None

    @classmethod
    def from_file(cls, path: Path) -> BuildingRegistry:
        raw = json.loads(path.read_text(encoding="utf-8"))

        if isinstance(raw, list):
            return cls(
                complexes=[ComplexInfo(name=name) for name in raw],
                standalone_houses=[],
            )

        complexes: list[ComplexInfo] = []
        for item in raw.get("complexes", []):
            houses = [
                HouseInfo(
                    address=h["address"],
                    entrances=h.get("entrances", 1),
                    apartments=h.get("apartments", 0),
                )
                for h in item.get("houses", [])
            ]
            complexes.append(ComplexInfo(name=item["name"], houses=houses))

        standalone = [
            HouseInfo(
                address=h["address"],
                entrances=h.get("entrances", 1),
                apartments=h.get("apartments", 0),
            )
            for h in raw.get("standalone_houses", [])
        ]

        return cls(complexes=complexes, standalone_houses=standalone)
