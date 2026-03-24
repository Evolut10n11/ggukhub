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
class ManagementCompanyInfo:
    name: str
    dispatcher_phone: str
    emergency_phone: str


@dataclass(slots=True)
class BuildingRegistry:
    complexes: list[ComplexInfo] = field(default_factory=list)
    standalone_houses: list[HouseInfo] = field(default_factory=list)
    _mc_by_address: dict[str, ManagementCompanyInfo] = field(default_factory=dict)

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

    def management_company_for(self, address: str) -> ManagementCompanyInfo | None:
        """Find management company by house address (fuzzy substring match)."""
        if not address:
            return None
        # Exact match first
        if address in self._mc_by_address:
            return self._mc_by_address[address]
        # Fuzzy: check if any registered address is contained in the query or vice versa
        addr_lower = address.lower()
        for registered, mc in self._mc_by_address.items():
            if registered.lower() in addr_lower or addr_lower in registered.lower():
                return mc
        return None

    @classmethod
    def from_file(cls, path: Path) -> BuildingRegistry:
        raw = json.loads(path.read_text(encoding="utf-8"))

        if isinstance(raw, list):
            return cls(
                complexes=[ComplexInfo(name=name) for name in raw],
                standalone_houses=[],
            )

        # Parse management companies
        mc_by_address: dict[str, ManagementCompanyInfo] = {}
        for mc_raw in raw.get("management_companies", []):
            phones = mc_raw.get("phones", {})
            mc = ManagementCompanyInfo(
                name=mc_raw["name"],
                dispatcher_phone=phones.get("dispatcher", ""),
                emergency_phone=phones.get("emergency", ""),
            )
            for addr in mc_raw.get("addresses", []):
                mc_by_address[addr] = mc

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

        return cls(complexes=complexes, standalone_houses=standalone, _mc_by_address=mc_by_address)
