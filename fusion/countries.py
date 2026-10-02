"""Exact-key country merge between power_plants (ISO3 + name) and logistics_risk (name only)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# logistics_risk spellings -> power_plants spellings. Only real synonyms, no guessing.
NAME_ALIASES: dict[str, str] = {
    "uk": "united kingdom",
    "usa": "united states of america",
    "uae": "united arab emirates",
    "north macedonia": "macedonia",
}


@dataclass(frozen=True)
class MergedCountry:
    country_code: str | None
    name: str
    sources: tuple[str, ...]
    logistics_name: str | None

    @property
    def key(self) -> str:
        return f"ISO3:{self.country_code}" if self.country_code else f"NAME:{self.name}"


@dataclass(frozen=True)
class CountryMerge:
    countries: tuple[MergedCountry, ...]
    lr_name_to_key: dict[str, str]  # logistics_risk Country.name -> MergedCountry.key
    unmatched_lr: tuple[str, ...]


def normalise_name(name: str) -> str:
    """Case/accent/punctuation-insensitive key, then apply the alias table."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    key = re.sub(r"[^a-z0-9]+", " ", ascii_name.lower()).strip()
    return NAME_ALIASES.get(key, key)


def pp_country_key(code: str) -> str:
    return f"ISO3:{code}"


def merge_countries(pp_countries: list[tuple[str, str]], lr_names: list[str]) -> CountryMerge:
    """pp_countries: (ISO3, name) pairs; lr_names: logistics_risk Country.name values."""
    by_norm = {normalise_name(name): code for code, name in pp_countries}
    lr_by_code: dict[str, str] = {}
    unmatched: list[str] = []
    for lr_name in lr_names:
        code = by_norm.get(normalise_name(lr_name))
        if code is None:
            unmatched.append(lr_name)
        else:
            lr_by_code[code] = lr_name

    merged = [
        MergedCountry(
            country_code=code,
            name=name,
            sources=("power_plants", "logistics_risk") if code in lr_by_code else ("power_plants",),
            logistics_name=lr_by_code.get(code),
        )
        for code, name in sorted(pp_countries)
    ]
    merged += [MergedCountry(None, n, ("logistics_risk",), n) for n in sorted(unmatched)]

    lr_map = {lr: pp_country_key(code) for code, lr in lr_by_code.items()}
    lr_map.update({n: f"NAME:{n}" for n in unmatched})
    return CountryMerge(tuple(merged), lr_map, tuple(sorted(unmatched)))
