#!/usr/bin/env python3
"""
Generate the `supply_chain_deep` graph: a multi-tier defense supply chain that is
deliberately *deep* (5-12 hop paths) and anchored on real-world reference data.

Layers
  1. Bill of materials (BOM), 8 levels, single edge type CONTAINS:
       Platform -> System -> Subsystem -> Assembly -> Subassembly -> Component
                -> Material (1-4 processing steps) -> Mineral
  2. Production: every item is PRODUCED_AT facilities, OPERATED_BY companies,
     LOCATED_IN countries. Facilities form a physical SUPPLIES network
     (mine -> refiner -> ... -> prime final assembly).
  3. Ownership: Company -[:SUBSIDIARY_OF]-> Company chains (up to 5 levels,
     through holding companies in offshore jurisdictions).
  4. Logistics: real ports + sea areas + chokepoints joined by SEA_LANE edges
     (haversine distances), Shipment nodes routed over that network.
  5. Disruptions: real events (Red Sea attacks, Panama drought, Chinese export
     controls) that affect chokepoints / minerals / materials and shape the
     shipment delays.

Real (approximate) data: mineral & refining country shares (USGS Mineral Commodity
Summaries 2024 orders of magnitude, rounded), port / chokepoint coordinates, NATO / EU
membership, the disruption events and their dates.
Synthetic: platforms, parts, companies, facilities, ownership, supplier links, shipments.

Usage (from the repo root; `uv` installs the pinned turingdb==3.0 on first run)
  uv run scripts/generate_supply_chain_deep.py --out /tmp/scd [--scale 1.0] [--seed 7]
  uv run turing-parquet -nodes /tmp/scd/nodes.parquet -edges /tmp/scd/edges.parquet \
                        -out /tmp/scd/turing -graph supply_chain_deep < /dev/null
  cp -r /tmp/scd/turing/graphs/supply_chain_deep graphs/
"""

import argparse
import heapq
import json
import math
import os
import random
from collections import defaultdict
from datetime import date, timedelta

import pandas as pd

# --------------------------------------------------------------------------------------
# Reference data (real)
# --------------------------------------------------------------------------------------

NATO = {"USA", "CAN", "GBR", "FRA", "DEU", "ITA", "ESP", "NLD", "BEL", "LUX", "POL", "CZE",
        "SWE", "FIN", "NOR", "DNK", "ROU", "TUR", "GRC"}
EU = {"FRA", "DEU", "ITA", "ESP", "NLD", "BEL", "LUX", "POL", "CZE", "SWE", "FIN", "DNK",
      "ROU", "GRC", "IRL", "CYP"}
EU_SANCTIONED = {"RUS", "BLR", "IRN"}

# iso3: (name, region, [cities])
COUNTRIES = {
    "USA": ("United States", "North America", ["Huntsville", "Tucson", "Dallas", "San Diego", "Pittsburgh", "Phoenix", "Wichita", "Boston"]),
    "CAN": ("Canada", "North America", ["Montreal", "Toronto", "Calgary", "Sudbury"]),
    "MEX": ("Mexico", "North America", ["Monterrey", "Queretaro", "Guadalajara", "Tijuana"]),
    "BRA": ("Brazil", "South America", ["Sao Paulo", "Belo Horizonte", "Araxa", "Sao Jose dos Campos"]),
    "ARG": ("Argentina", "South America", ["Buenos Aires", "Salta", "Cordoba"]),
    "CHL": ("Chile", "South America", ["Antofagasta", "Santiago", "Calama"]),
    "PER": ("Peru", "South America", ["Lima", "Arequipa", "Cerro de Pasco"]),
    "BOL": ("Bolivia", "South America", ["Potosi", "Oruro", "La Paz"]),
    "GBR": ("United Kingdom", "Europe", ["Bristol", "Derby", "Glasgow", "Birmingham", "Barrow"]),
    "FRA": ("France", "Europe", ["Toulouse", "Bourges", "Bordeaux", "Lyon", "Grenoble"]),
    "DEU": ("Germany", "Europe", ["Munich", "Unterluss", "Dusseldorf", "Friedrichshafen", "Ulm", "Hanau"]),
    "ITA": ("Italy", "Europe", ["Rome", "Turin", "Genoa", "La Spezia"]),
    "ESP": ("Spain", "Europe", ["Madrid", "Seville", "Bilbao"]),
    "NLD": ("Netherlands", "Europe", ["Eindhoven", "Hengelo", "Rotterdam"]),
    "BEL": ("Belgium", "Europe", ["Liege", "Herstal", "Olen"]),
    "LUX": ("Luxembourg", "Europe", ["Luxembourg"]),
    "POL": ("Poland", "Europe", ["Stalowa Wola", "Bydgoszcz", "Krakow", "Wroclaw"]),
    "CZE": ("Czechia", "Europe", ["Prague", "Brno", "Vlasim"]),
    "SWE": ("Sweden", "Europe", ["Karlskoga", "Linkoping", "Gothenburg"]),
    "FIN": ("Finland", "Europe", ["Tampere", "Kokkola", "Vihtavuori"]),
    "NOR": ("Norway", "Europe", ["Raufoss", "Kongsberg", "Oslo"]),
    "DNK": ("Denmark", "Europe", ["Aarhus", "Copenhagen"]),
    "ROU": ("Romania", "Europe", ["Brasov", "Bucharest"]),
    "GRC": ("Greece", "Europe", ["Athens", "Thessaloniki"]),
    "UKR": ("Ukraine", "Europe", ["Kyiv", "Kharkiv", "Zaporizhzhia", "Dnipro"]),
    "BLR": ("Belarus", "Europe", ["Minsk", "Gomel"]),
    "RUS": ("Russia", "Europe/Asia", ["Yekaterinburg", "Norilsk", "Perm", "Novosibirsk", "Berezniki"]),
    "TUR": ("Turkiye", "Europe/Asia", ["Ankara", "Istanbul", "Izmir", "Eskisehir"]),
    "ISR": ("Israel", "Middle East", ["Haifa", "Rehovot", "Beersheba"]),
    "EGY": ("Egypt", "Middle East", ["Cairo", "Port Said"]),
    "SAU": ("Saudi Arabia", "Middle East", ["Jubail", "Riyadh", "Yanbu"]),
    "ARE": ("United Arab Emirates", "Middle East", ["Abu Dhabi", "Dubai"]),
    "QAT": ("Qatar", "Middle East", ["Ras Laffan", "Doha"]),
    "IRN": ("Iran", "Middle East", ["Isfahan", "Bandar Abbas", "Tabriz"]),
    "IND": ("India", "Asia", ["Bengaluru", "Hyderabad", "Pune", "Chennai", "Visakhapatnam"]),
    "CHN": ("China", "Asia", ["Shenzhen", "Baotou", "Ganzhou", "Shanghai", "Xi'an", "Chengdu", "Suzhou", "Zhuzhou", "Jinchang"]),
    "HKG": ("Hong Kong", "Asia", ["Hong Kong"]),
    "TWN": ("Taiwan", "Asia", ["Hsinchu", "Taichung", "Tainan", "Kaohsiung"]),
    "JPN": ("Japan", "Asia", ["Nagoya", "Kyoto", "Osaka", "Toyama", "Kitakyushu"]),
    "KOR": ("South Korea", "Asia", ["Changwon", "Gumi", "Ulsan", "Daejeon"]),
    "SGP": ("Singapore", "Asia", ["Singapore"]),
    "MYS": ("Malaysia", "Asia", ["Penang", "Kuantan", "Kulim"]),
    "IDN": ("Indonesia", "Asia", ["Morowali", "Batam", "Bangka"]),
    "VNM": ("Vietnam", "Asia", ["Hanoi", "Ho Chi Minh City", "Thai Nguyen"]),
    "THA": ("Thailand", "Asia", ["Bangkok", "Rayong"]),
    "PHL": ("Philippines", "Asia", ["Manila", "Cebu"]),
    "MMR": ("Myanmar", "Asia", ["Myitkyina", "Yangon"]),
    "MNG": ("Mongolia", "Asia", ["Ulaanbaatar"]),
    "KAZ": ("Kazakhstan", "Asia", ["Ust-Kamenogorsk", "Aktobe", "Pavlodar"]),
    "TJK": ("Tajikistan", "Asia", ["Dushanbe", "Khujand"]),
    "AUS": ("Australia", "Oceania", ["Perth", "Kalgoorlie", "Port Hedland", "Adelaide", "Melbourne"]),
    "ZAF": ("South Africa", "Africa", ["Johannesburg", "Rustenburg", "Pretoria"]),
    "ZWE": ("Zimbabwe", "Africa", ["Harare", "Bikita"]),
    "ZMB": ("Zambia", "Africa", ["Kitwe", "Ndola"]),
    "MOZ": ("Mozambique", "Africa", ["Balama", "Moma"]),
    "MDG": ("Madagascar", "Africa", ["Toamasina", "Tolagnaro"]),
    "COD": ("DR Congo", "Africa", ["Kolwezi", "Lubumbashi", "Bukavu"]),
    "RWA": ("Rwanda", "Africa", ["Kigali"]),
    "TZA": ("Tanzania", "Africa", ["Dar es Salaam"]),
    "GAB": ("Gabon", "Africa", ["Moanda"]),
    "NGA": ("Nigeria", "Africa", ["Jos", "Lagos"]),
    "GIN": ("Guinea", "Africa", ["Boke", "Kamsar"]),
    "MAR": ("Morocco", "Africa", ["Casablanca", "Tangier"]),
    # holding-company jurisdictions (no production)
    "IRL": ("Ireland", "Europe", ["Dublin"]),
    "CYP": ("Cyprus", "Europe", ["Limassol"]),
    "CHE": ("Switzerland", "Europe", ["Zug", "Geneva"]),
    "VGB": ("British Virgin Islands", "Caribbean", ["Road Town"]),
}

# Raw minerals: name -> {iso3: approx % of world mine production}. Rounded, order-of-magnitude
# figures in the spirit of USGS Mineral Commodity Summaries 2024; renormalised on use.
MINERALS = {
    "Bauxite":                 {"AUS": 26, "GIN": 25, "CHN": 17, "BRA": 8, "IND": 6, "IDN": 5, "RUS": 2},
    "Zinc ore":                {"CHN": 33, "PER": 11, "AUS": 10, "IND": 7, "USA": 6, "MEX": 5, "BOL": 4, "RUS": 3},
    "Rare earth ore":          {"CHN": 69, "USA": 12, "MMR": 11, "AUS": 5, "THA": 2, "IND": 1},
    "Tungsten ore":            {"CHN": 81, "VNM": 4, "RUS": 3, "BOL": 2, "RWA": 2, "ESP": 1},
    "Antimony ore":            {"CHN": 48, "TJK": 25, "TUR": 7, "RUS": 6, "MMR": 4, "BOL": 4, "AUS": 2},
    "Cobalt ore":              {"COD": 74, "IDN": 5, "RUS": 4, "AUS": 2, "PHL": 2, "CAN": 2},
    "Lithium ore":             {"AUS": 47, "CHL": 24, "CHN": 18, "ARG": 5, "BRA": 3, "ZWE": 3},
    "Natural graphite":        {"CHN": 77, "MDG": 6, "MOZ": 6, "BRA": 5, "KOR": 1, "IND": 1},
    "Titanium mineral sands":  {"CHN": 31, "MOZ": 13, "ZAF": 10, "AUS": 8, "CAN": 5, "NOR": 4, "UKR": 3, "IND": 3, "MDG": 3},
    "Nickel ore":              {"IDN": 50, "PHL": 11, "RUS": 6, "CAN": 5, "AUS": 4, "CHN": 3, "BRA": 2},
    "Coltan (tantalum ore)":   {"COD": 41, "RWA": 22, "BRA": 16, "NGA": 7, "CHN": 5},
    "Pyrochlore (niobium ore)": {"BRA": 91, "CAN": 8},
    "Beryl / bertrandite":     {"USA": 60, "CHN": 30, "MOZ": 7, "BRA": 2},
    "Chromite":                {"ZAF": 44, "TUR": 16, "KAZ": 15, "IND": 9, "FIN": 4},
    "Manganese ore":           {"ZAF": 36, "GAB": 23, "AUS": 17, "CHN": 5},
    "Vanadiferous magnetite":  {"CHN": 70, "RUS": 18, "ZAF": 8, "BRA": 6},
    "PGM ore":                 {"ZAF": 55, "RUS": 25, "ZWE": 8, "CAN": 5, "USA": 5},
    "Copper ore":              {"CHL": 24, "PER": 11, "COD": 11, "CHN": 8, "USA": 5, "RUS": 4, "IDN": 4, "AUS": 4, "ZMB": 3},
    "Tin ore":                 {"CHN": 30, "IDN": 22, "MMR": 9, "PER": 9, "COD": 6, "BRA": 6, "BOL": 6},
    "Silver ore":              {"MEX": 25, "CHN": 13, "PER": 13, "CHL": 5, "POL": 5, "AUS": 5, "RUS": 5, "BOL": 5},
    "Quartz (silica)":         {"CHN": 40, "USA": 10, "BRA": 10, "NOR": 5, "RUS": 5, "IND": 5, "AUS": 5},
    "Iron ore":                {"AUS": 37, "BRA": 17, "CHN": 13, "IND": 10, "RUS": 4, "ZAF": 3, "UKR": 2, "CAN": 2},
    "Cotton":                  {"CHN": 24, "IND": 22, "USA": 12, "BRA": 12, "AUS": 4, "TUR": 3},
    "Fluorspar":               {"CHN": 63, "MEX": 12, "MNG": 9, "ZAF": 4, "VNM": 2},
    "Molybdenite":             {"CHN": 40, "PER": 16, "CHL": 16, "USA": 14, "MNG": 2},
    "Lead ore":                {"CHN": 43, "AUS": 10, "USA": 6, "PER": 6, "MEX": 6, "RUS": 5, "IND": 5},
    "Borate ore":              {"TUR": 60, "USA": 15, "CHL": 8, "ARG": 7},
    "Crude oil":               {"USA": 15, "SAU": 12, "RUS": 12, "CAN": 6, "CHN": 5, "IRN": 4, "ARE": 4, "BRA": 4, "NOR": 2, "KAZ": 2},
    "Natural gas":             {"USA": 25, "RUS": 15, "IRN": 6, "CHN": 6, "CAN": 5, "QAT": 4, "AUS": 4, "NOR": 3},
    "Rock salt / brine":       {"CHN": 20, "USA": 15, "IND": 10, "DEU": 5, "AUS": 4, "CAN": 4},
}

GENERIC_PROCESSING = {"CHN": 30, "USA": 12, "DEU": 8, "JPN": 8, "KOR": 6, "IND": 5, "FRA": 4, "TWN": 4,
                      "GBR": 3, "ITA": 3, "RUS": 3, "BRA": 2, "TUR": 2, "POL": 2, "ESP": 2, "SWE": 1, "CAN": 2}

# Processed materials: name -> (category, [inputs], {country: share} or None for generic)
# Inputs refer to other materials or to MINERALS; this creates 1-4 processing levels.
MATERIALS = {
    "Alumina":                       ("metal", ["Bauxite"], {"CHN": 55, "AUS": 13, "BRA": 8, "IND": 5, "RUS": 3, "SAU": 2}),
    "Primary aluminium":             ("metal", ["Alumina"], {"CHN": 59, "IND": 6, "RUS": 5, "CAN": 4, "ARE": 4, "NOR": 2, "SAU": 1, "USA": 1}),
    "Aluminium alloy 7075 plate":    ("alloy", ["Primary aluminium", "Zinc (refined)", "Copper cathode"], {"USA": 30, "DEU": 15, "FRA": 15, "CHN": 20, "JPN": 10, "RUS": 5, "GBR": 5}),
    "Aluminium powder (atomized)":   ("energetic-precursor", ["Primary aluminium"], {"USA": 25, "DEU": 20, "CHN": 30, "FRA": 10, "RUS": 5, "GBR": 10}),
    "Primary gallium":               ("critical-metal", ["Alumina"], {"CHN": 98, "RUS": 1, "JPN": 1}),
    "High-purity gallium (6N)":      ("critical-metal", ["Primary gallium"], {"CHN": 60, "JPN": 20, "USA": 8, "CAN": 6, "DEU": 6}),
    "GaAs substrate wafer":          ("semiconductor", ["High-purity gallium (6N)"], {"JPN": 35, "CHN": 25, "DEU": 20, "USA": 15, "TWN": 5}),
    "Silicon carbide substrate":     ("semiconductor", ["Silicon metal"], {"USA": 50, "CHN": 20, "JPN": 15, "DEU": 5, "KOR": 5, "SWE": 5}),
    "GaN-on-SiC epitaxial wafer":    ("semiconductor", ["High-purity gallium (6N)", "Silicon carbide substrate"], {"USA": 40, "JPN": 25, "CHN": 15, "DEU": 10, "TWN": 5, "KOR": 5}),
    "Zinc (refined)":                ("metal", ["Zinc ore"], {"CHN": 48, "KOR": 7, "IND": 6, "CAN": 5, "JPN": 4, "ESP": 4, "AUS": 3, "MEX": 3, "PER": 3}),
    "Germanium (refined)":           ("critical-metal", ["Zinc ore"], {"CHN": 68, "BEL": 10, "CAN": 10, "USA": 7, "RUS": 5}),
    "Germanium optical blank":       ("optical", ["Germanium (refined)"], {"CHN": 40, "BEL": 20, "USA": 20, "DEU": 10, "RUS": 5, "FRA": 5}),
    "Indium (refined)":              ("critical-metal", ["Zinc ore"], {"CHN": 60, "KOR": 15, "JPN": 7, "CAN": 6, "FRA": 4}),
    "Antimony metal / trioxide":     ("critical-metal", ["Antimony ore"], {"CHN": 60, "TJK": 10, "RUS": 10, "VNM": 5, "BEL": 5, "TUR": 7, "USA": 3}),
    "Antimony trisulfide":           ("energetic-precursor", ["Antimony metal / trioxide"], {"CHN": 55, "USA": 15, "DEU": 10, "IND": 10, "CZE": 10}),
    "Indium antimonide wafer":       ("semiconductor", ["Indium (refined)", "Antimony metal / trioxide"], {"USA": 40, "GBR": 30, "FRA": 20, "ISR": 10}),
    "Rare earth oxides (separated)": ("critical-metal", ["Rare earth ore"], {"CHN": 90, "MYS": 6, "FRA": 2, "USA": 2}),
    "NdFeB magnet alloy":            ("magnetic", ["Rare earth oxides (separated)", "Iron (pig iron)", "Boron (refined)"], {"CHN": 90, "JPN": 7, "DEU": 2, "USA": 1}),
    "Sintered NdFeB magnet":         ("magnetic", ["NdFeB magnet alloy"], {"CHN": 90, "JPN": 7, "DEU": 2, "VNM": 1}),
    "Samarium-cobalt magnet":        ("magnetic", ["Rare earth oxides (separated)", "Cobalt (refined)"], {"CHN": 70, "USA": 10, "DEU": 10, "JPN": 10}),
    "Cobalt (refined)":              ("critical-metal", ["Cobalt ore"], {"CHN": 76, "FIN": 9, "CAN": 3, "BEL": 3, "NOR": 2, "JPN": 2, "AUS": 2}),
    "Lithium chemicals":             ("battery", ["Lithium ore"], {"CHN": 65, "CHL": 25, "ARG": 5, "AUS": 3, "USA": 2}),
    "Battery-grade graphite anode":  ("battery", ["Natural graphite"], {"CHN": 95, "JPN": 2, "KOR": 2, "USA": 1}),
    "Nickel (class 1)":              ("metal", ["Nickel ore"], {"CHN": 30, "IDN": 30, "RUS": 7, "JPN": 5, "CAN": 5, "AUS": 5, "NOR": 4, "FIN": 3}),
    "Manganese (high-purity)":       ("battery", ["Manganese ore"], {"CHN": 90, "ZAF": 5, "JPN": 5}),
    "NMC cathode material":          ("battery", ["Lithium chemicals", "Cobalt (refined)", "Nickel (class 1)", "Manganese (high-purity)"], {"CHN": 70, "KOR": 15, "JPN": 10, "POL": 3, "FIN": 2}),
    "Tungsten carbide powder":       ("critical-metal", ["Tungsten ore"], {"CHN": 80, "VNM": 5, "DEU": 4, "USA": 3, "JPN": 3, "RUS": 3, "SWE": 2}),
    "Tungsten heavy alloy":          ("alloy", ["Tungsten carbide powder", "Nickel (class 1)", "Iron (pig iron)"], {"CHN": 30, "USA": 25, "DEU": 20, "FRA": 10, "GBR": 10, "ISR": 5}),
    "Titanium sponge":               ("metal", ["Titanium mineral sands"], {"CHN": 57, "JPN": 17, "RUS": 13, "KAZ": 9, "SAU": 3, "UKR": 1}),
    "Ferrovanadium":                 ("alloy", ["Vanadiferous magnetite"], {"CHN": 65, "RUS": 20, "ZAF": 8, "BRA": 7}),
    "Ti-6Al-4V mill product":        ("alloy", ["Titanium sponge", "Primary aluminium", "Ferrovanadium"], {"USA": 25, "CHN": 25, "RUS": 15, "JPN": 10, "FRA": 8, "DEU": 7, "GBR": 5, "KAZ": 5}),
    "Ferrochrome":                   ("alloy", ["Chromite"], {"CHN": 45, "ZAF": 30, "KAZ": 10, "IND": 10, "FIN": 3, "TUR": 2}),
    "Ferroniobium":                  ("alloy", ["Pyrochlore (niobium ore)"], {"BRA": 90, "CAN": 10}),
    "Molybdenum oxide":              ("metal", ["Molybdenite"], {"CHN": 45, "CHL": 15, "USA": 15, "PER": 10, "MEX": 5, "NLD": 5, "BEL": 5}),
    "Inconel 718 (Ni superalloy)":   ("alloy", ["Nickel (class 1)", "Ferrochrome", "Ferroniobium", "Molybdenum oxide"], {"USA": 40, "DEU": 15, "GBR": 10, "FRA": 10, "JPN": 10, "CHN": 10, "SWE": 5}),
    "Tantalum powder (capacitor grade)": ("critical-metal", ["Coltan (tantalum ore)"], {"CHN": 40, "USA": 20, "DEU": 15, "JPN": 10, "KAZ": 10, "THA": 5}),
    "Copper cathode":                ("metal", ["Copper ore"], {"CHN": 44, "CHL": 8, "COD": 7, "JPN": 6, "RUS": 4, "USA": 4, "DEU": 3, "POL": 2, "IND": 2, "ZMB": 2}),
    "Beryllium-copper alloy":        ("alloy", ["Beryl / bertrandite", "Copper cathode"], {"USA": 60, "JPN": 20, "CHN": 15, "DEU": 5}),
    "Copper magnet wire":            ("metal", ["Copper cathode"], None),
    "Copper foil":                   ("metal", ["Copper cathode"], {"CHN": 60, "JPN": 15, "KOR": 10, "TWN": 10, "LUX": 5}),
    "Tin (refined)":                 ("metal", ["Tin ore"], {"CHN": 48, "IDN": 15, "MYS": 8, "PER": 6, "THA": 5, "BOL": 5, "BRA": 5}),
    "Silver (refined)":              ("metal", ["Silver ore"], {"MEX": 20, "CHN": 25, "PER": 10, "POL": 7, "JPN": 6, "KOR": 6, "USA": 5, "RUS": 5}),
    "SAC305 solder alloy":           ("alloy", ["Tin (refined)", "Silver (refined)", "Copper cathode"], {"CHN": 35, "JPN": 25, "USA": 10, "DEU": 10, "MYS": 10, "KOR": 10}),
    "Silicon metal":                 ("metal", ["Quartz (silica)"], {"CHN": 79, "RUS": 5, "BRA": 4, "NOR": 4, "USA": 3, "FRA": 2}),
    "Polysilicon (electronic grade)": ("semiconductor", ["Silicon metal"], {"CHN": 40, "DEU": 25, "USA": 15, "JPN": 15, "KOR": 5}),
    "Silicon wafer (300 mm)":        ("semiconductor", ["Polysilicon (electronic grade)"], {"JPN": 50, "TWN": 15, "KOR": 13, "DEU": 12, "CHN": 5, "USA": 5}),
    "Advanced-node logic die":       ("semiconductor", ["Silicon wafer (300 mm)", "Copper cathode"], {"TWN": 70, "KOR": 15, "USA": 10, "JPN": 5}),
    "Mature-node die (>=28 nm)":     ("semiconductor", ["Silicon wafer (300 mm)"], {"CHN": 35, "TWN": 30, "USA": 10, "KOR": 8, "JPN": 7, "DEU": 5, "SGP": 5}),
    "E-glass fiber":                 ("composite", ["Quartz (silica)", "Borate ore"], {"CHN": 65, "USA": 10, "JPN": 5, "IND": 5, "DEU": 5, "FRA": 5, "TUR": 5}),
    "Epoxy resin":                   ("polymer", ["Crude oil"], {"CHN": 45, "KOR": 10, "TWN": 10, "USA": 10, "DEU": 10, "JPN": 5, "NLD": 5, "THA": 5}),
    "FR-4 copper-clad laminate":     ("polymer", ["E-glass fiber", "Epoxy resin", "Copper foil"], {"CHN": 70, "TWN": 15, "JPN": 8, "KOR": 5, "USA": 2}),
    "Barium titanate dielectric":    ("ceramic", ["Titanium mineral sands"], {"JPN": 60, "KOR": 20, "CHN": 15, "USA": 5}),
    "Acrylonitrile (PAN precursor)": ("polymer", ["Crude oil", "Natural gas"], {"CHN": 35, "USA": 20, "JPN": 10, "KOR": 10, "DEU": 10, "TWN": 10, "RUS": 5}),
    "Carbon fiber (PAN-based)":      ("composite", ["Acrylonitrile (PAN precursor)"], {"JPN": 40, "USA": 20, "CHN": 20, "DEU": 8, "KOR": 5, "FRA": 4, "TUR": 3}),
    "Aramid fiber":                  ("composite", ["Crude oil"], {"USA": 40, "JPN": 25, "KOR": 15, "CHN": 15, "NLD": 5}),
    "UHMWPE fiber":                  ("composite", ["Crude oil"], {"NLD": 30, "USA": 25, "CHN": 35, "JPN": 10}),
    "Boron (refined)":               ("critical-metal", ["Borate ore"], {"TUR": 40, "USA": 30, "CHN": 20, "DEU": 10}),
    "Boron carbide ceramic":         ("ceramic", ["Boron (refined)", "Crude oil"], {"CHN": 40, "USA": 30, "DEU": 15, "JPN": 10, "IND": 5}),
    "Iron (pig iron)":               ("metal", ["Iron ore"], {"CHN": 60, "IND": 7, "JPN": 6, "RUS": 4, "KOR": 4, "BRA": 3, "USA": 2, "DEU": 2}),
    "Armor steel plate":             ("alloy", ["Iron (pig iron)", "Ferrochrome", "Nickel (class 1)", "Molybdenum oxide"], {"SWE": 25, "DEU": 20, "FIN": 15, "USA": 15, "FRA": 10, "POL": 5, "CZE": 5, "KOR": 5}),
    "Forging-grade steel":           ("alloy", ["Iron (pig iron)", "Manganese (high-purity)", "Ferrovanadium"], {"USA": 20, "DEU": 15, "POL": 10, "CZE": 10, "KOR": 10, "TUR": 10, "IND": 10, "FRA": 5, "ITA": 5, "ESP": 5}),
    "Ammonia":                       ("chemical", ["Natural gas"], {"CHN": 30, "RUS": 10, "USA": 10, "IND": 8, "QAT": 5, "SAU": 5, "DEU": 4, "POL": 3, "NLD": 3}),
    "Nitric acid":                   ("chemical", ["Ammonia"], None),
    "Cotton linters (purified)":     ("chemical", ["Cotton"], {"CHN": 45, "IND": 20, "USA": 10, "BRA": 10, "TUR": 10, "DEU": 5}),
    "Nitrocellulose":                ("energetic", ["Cotton linters (purified)", "Nitric acid"], {"CHN": 40, "USA": 15, "DEU": 15, "FRA": 10, "POL": 8, "CZE": 6, "KOR": 3, "TUR": 3}),
    "Hexamine":                      ("chemical", ["Ammonia", "Natural gas"], None),
    "RDX / HMX":                     ("energetic", ["Nitric acid", "Hexamine"], {"USA": 30, "DEU": 15, "POL": 10, "SWE": 10, "FRA": 10, "IND": 10, "KOR": 5, "ESP": 5, "CHN": 5}),
    "Toluene":                       ("chemical", ["Crude oil"], None),
    "TNT":                           ("energetic", ["Toluene", "Nitric acid"], {"POL": 40, "USA": 20, "IND": 15, "CHN": 15, "CZE": 5, "TUR": 5}),
    "Sodium chlorate":               ("chemical", ["Rock salt / brine"], None),
    "Ammonium perchlorate":          ("energetic", ["Sodium chlorate", "Ammonia"], {"USA": 50, "CHN": 20, "FRA": 15, "JPN": 5, "IND": 5, "KOR": 5}),
    "HTPB binder":                   ("polymer", ["Crude oil"], {"USA": 40, "FRA": 20, "CHN": 20, "JPN": 10, "IND": 10}),
    "Lead (refined)":                ("metal", ["Lead ore"], None),
    "Lead azide / lead styphnate":   ("energetic", ["Lead (refined)", "Nitric acid"], {"DEU": 25, "USA": 25, "CZE": 15, "FRA": 10, "SWE": 10, "IND": 10, "KOR": 5}),
    "Sapphire window blank":         ("optical", ["Alumina"], {"USA": 30, "CHN": 30, "RUS": 20, "KOR": 10, "JPN": 10}),
    "PTFE fluoropolymer":            ("polymer", ["Fluorspar", "Crude oil"], {"CHN": 50, "USA": 15, "JPN": 15, "DEU": 10, "BEL": 5, "ITA": 5}),
    "Optical fiber preform":         ("optical", ["Quartz (silica)", "Germanium (refined)"], {"CHN": 40, "JPN": 30, "USA": 20, "KOR": 5, "DEU": 5}),
    "Thermal battery salts":         ("battery", ["Lithium chemicals", "Rock salt / brine"], {"USA": 60, "GBR": 20, "FRA": 20}),
    "Vanadium oxide thin film":      ("semiconductor", ["Ferrovanadium"], {"USA": 30, "FRA": 25, "ISR": 15, "CHN": 20, "KOR": 10}),
    "Platinum group metals (refined)": ("critical-metal", ["PGM ore"], {"ZAF": 50, "RUS": 25, "GBR": 8, "USA": 5, "JPN": 5, "BEL": 4, "CHE": 3}),
}

# Component families: family -> (kind, [(material, qty_per_unit, unit)], part_numbers, cost_eur, lead_days, country override)
COMPONENTS = {
    # electronic
    "FPGA (rad-tolerant)":            ("electronic", [("Advanced-node logic die", 1, "die"), ("FR-4 copper-clad laminate", 0.01, "m2")], 24, 9000, (180, 420), {"USA": 70, "TWN": 15, "FRA": 10, "JPN": 5}),
    "Microcontroller":                ("electronic", [("Mature-node die (>=28 nm)", 1, "die")], 40, 12, (60, 200), {"USA": 25, "DEU": 15, "JPN": 15, "TWN": 15, "CHN": 15, "NLD": 10, "MYS": 5}),
    "MLCC capacitor":                 ("electronic", [("Barium titanate dielectric", 0.001, "kg"), ("Nickel (class 1)", 0.0005, "kg")], 60, 0.1, (30, 180), {"JPN": 45, "KOR": 20, "CHN": 20, "TWN": 10, "USA": 5}),
    "Tantalum capacitor":             ("electronic", [("Tantalum powder (capacitor grade)", 0.002, "kg")], 30, 2, (60, 240), {"USA": 25, "CZE": 20, "MEX": 15, "CHN": 15, "JPN": 15, "THA": 10}),
    "Thick-film resistor":            ("electronic", [("Silver (refined)", 0.0001, "kg"), ("Alumina", 0.001, "kg")], 50, 0.05, (20, 90), {"TWN": 35, "CHN": 30, "JPN": 15, "USA": 10, "DEU": 10}),
    "SiC power MOSFET":               ("electronic", [("Silicon carbide substrate", 1, "die")], 20, 25, (90, 300), {"USA": 40, "DEU": 20, "JPN": 15, "CHN": 15, "ITA": 10}),
    "DC-DC converter module":         ("electronic", [("Mature-node die (>=28 nm)", 2, "die"), ("Copper magnet wire", 0.02, "kg")], 30, 150, (60, 180), {"USA": 40, "CHN": 20, "FRA": 10, "TWN": 10, "ISR": 10, "DEU": 10}),
    "Multilayer PCB (bare board)":    ("electronic", [("FR-4 copper-clad laminate", 0.05, "m2"), ("Copper foil", 0.02, "kg")], 60, 80, (20, 70), {"CHN": 45, "TWN": 20, "USA": 10, "KOR": 8, "DEU": 7, "JPN": 5, "THA": 5}),
    "MIL-spec circular connector":    ("electronic", [("Beryllium-copper alloy", 0.01, "kg"), ("Aluminium alloy 7075 plate", 0.02, "kg"), ("PTFE fluoropolymer", 0.005, "kg")], 50, 120, (60, 220), {"USA": 40, "FRA": 20, "MEX": 15, "DEU": 10, "CHN": 10, "GBR": 5}),
    "Coaxial RF cable assembly":      ("electronic", [("Copper magnet wire", 0.05, "kg"), ("PTFE fluoropolymer", 0.02, "kg"), ("Silver (refined)", 0.001, "kg")], 30, 60, (30, 120), None),
    "Memory IC":                      ("electronic", [("Advanced-node logic die", 1, "die")], 20, 15, (60, 200), {"KOR": 60, "USA": 20, "TWN": 10, "JPN": 10}),
    "Solder paste":                   ("electronic", [("SAC305 solder alloy", 0.05, "kg")], 8, 40, (14, 60), None),
    # rf
    "GaN power amplifier MMIC":       ("rf", [("GaN-on-SiC epitaxial wafer", 0.02, "wafer")], 30, 1800, (150, 330), {"USA": 45, "FRA": 15, "DEU": 10, "GBR": 10, "ISR": 10, "JPN": 10}),
    "GaAs low-noise amplifier MMIC":  ("rf", [("GaAs substrate wafer", 0.01, "wafer")], 30, 300, (90, 260), {"USA": 40, "TWN": 20, "FRA": 10, "DEU": 10, "JPN": 10, "CHN": 10}),
    "RF filter (SAW/BAW)":            ("rf", [("Tantalum powder (capacitor grade)", 0.0005, "kg"), ("Lithium chemicals", 0.0005, "kg")], 30, 8, (60, 180), {"JPN": 40, "USA": 25, "CHN": 15, "DEU": 10, "KOR": 10}),
    "T/R module (phased array)":      ("rf", [("GaN-on-SiC epitaxial wafer", 0.05, "wafer"), ("GaAs substrate wafer", 0.02, "wafer"), ("Aluminium alloy 7075 plate", 0.1, "kg")], 20, 4500, (180, 360), {"USA": 40, "FRA": 15, "DEU": 15, "ISR": 10, "GBR": 10, "ITA": 10}),
    "Patch antenna element":          ("rf", [("Copper foil", 0.01, "kg"), ("PTFE fluoropolymer", 0.02, "kg")], 30, 40, (30, 100), None),
    # inertial / navigation
    "MEMS gyroscope":                 ("inertial", [("Silicon wafer (300 mm)", 0.002, "wafer"), ("Mature-node die (>=28 nm)", 1, "die")], 20, 250, (90, 240), {"USA": 35, "NOR": 15, "FRA": 15, "DEU": 10, "JPN": 10, "CHN": 10, "GBR": 5}),
    "Fiber-optic gyro coil":          ("inertial", [("Optical fiber preform", 0.05, "kg")], 15, 3500, (120, 300), {"USA": 40, "FRA": 25, "DEU": 10, "ISR": 10, "RUS": 5, "CHN": 10}),
    "GNSS receiver chip":             ("inertial", [("Mature-node die (>=28 nm)", 1, "die")], 20, 60, (60, 200), {"USA": 30, "TWN": 20, "CHN": 20, "CHE": 0, "GBR": 10, "FRA": 10, "JPN": 10}),
    "Quartz crystal oscillator":      ("inertial", [("Quartz (silica)", 0.001, "kg")], 30, 15, (30, 120), {"JPN": 35, "TWN": 25, "CHN": 20, "USA": 15, "DEU": 5}),
    # electro-optic
    "Germanium IR lens":              ("electro_optic", [("Germanium optical blank", 0.3, "kg")], 30, 2500, (90, 270), {"USA": 30, "BEL": 15, "FRA": 15, "DEU": 10, "ISR": 10, "CHN": 15, "GBR": 5}),
    "InSb IR focal-plane array":      ("electro_optic", [("Indium antimonide wafer", 0.05, "wafer"), ("Advanced-node logic die", 1, "die")], 15, 15000, (180, 420), {"USA": 45, "FRA": 20, "GBR": 15, "ISR": 15, "DEU": 5}),
    "Uncooled microbolometer":        ("electro_optic", [("Vanadium oxide thin film", 0.01, "wafer"), ("Silicon wafer (300 mm)", 0.01, "wafer")], 20, 1200, (90, 240), {"USA": 30, "FRA": 25, "CHN": 25, "ISR": 10, "KOR": 10}),
    "Sapphire dome / window":         ("electro_optic", [("Sapphire window blank", 0.4, "kg")], 20, 900, (90, 240), None),
    "Laser diode (GaAs)":             ("electro_optic", [("GaAs substrate wafer", 0.005, "wafer")], 25, 400, (60, 200), {"USA": 30, "DEU": 25, "CHN": 20, "JPN": 15, "FRA": 10}),
    "Image intensifier tube":         ("electro_optic", [("GaAs substrate wafer", 0.01, "wafer"), ("Alumina", 0.05, "kg")], 10, 3000, (180, 360), {"USA": 50, "NLD": 25, "FRA": 25}),
    # motors / actuation
    "Brushless DC motor":             ("motor", [("Sintered NdFeB magnet", 0.15, "kg"), ("Copper magnet wire", 0.2, "kg"), ("Aluminium alloy 7075 plate", 0.3, "kg")], 40, 180, (45, 150), {"CHN": 50, "DEU": 10, "JPN": 10, "USA": 10, "TWN": 10, "POL": 5, "UKR": 5}),
    "Servo actuator":                 ("motor", [("Samarium-cobalt magnet", 0.08, "kg"), ("Copper magnet wire", 0.1, "kg"), ("Ti-6Al-4V mill product", 0.2, "kg")], 30, 1400, (90, 240), {"USA": 40, "FRA": 15, "DEU": 15, "GBR": 10, "ITA": 10, "JPN": 10}),
    "Precision bearing":              ("motor", [("Forging-grade steel", 0.2, "kg")], 30, 90, (60, 200), {"DEU": 25, "JPN": 25, "SWE": 15, "USA": 15, "CHN": 15, "ITA": 5}),
    "Composite propeller":            ("motor", [("Carbon fiber (PAN-based)", 0.3, "kg"), ("Epoxy resin", 0.2, "kg")], 20, 120, (30, 90), None),
    # battery
    "Li-ion cell (21700)":            ("battery", [("NMC cathode material", 0.03, "kg"), ("Battery-grade graphite anode", 0.02, "kg"), ("Lithium chemicals", 0.005, "kg"), ("Copper foil", 0.008, "kg")], 20, 4, (60, 180), {"CHN": 60, "KOR": 15, "JPN": 10, "POL": 7, "USA": 5, "HUN": 0, "DEU": 3}),
    "Battery management IC":          ("battery", [("Mature-node die (>=28 nm)", 1, "die")], 15, 6, (60, 200), {"USA": 40, "CHN": 25, "TWN": 15, "DEU": 10, "JPN": 10}),
    "Thermal battery":                ("battery", [("Thermal battery salts", 0.2, "kg")], 15, 2500, (180, 365), {"USA": 60, "GBR": 20, "FRA": 20}),
    # mechanical
    "Machined titanium bracket":      ("mechanical", [("Ti-6Al-4V mill product", 0.5, "kg")], 40, 350, (60, 210), None),
    "Aluminium structural frame":     ("mechanical", [("Aluminium alloy 7075 plate", 3, "kg")], 40, 600, (45, 150), None),
    "Titanium fastener kit":          ("mechanical", [("Ti-6Al-4V mill product", 0.1, "kg")], 30, 80, (60, 240), {"USA": 40, "FRA": 15, "DEU": 10, "GBR": 10, "CHN": 10, "JPN": 10, "TUR": 5}),
    "Superalloy turbine blade":       ("mechanical", [("Inconel 718 (Ni superalloy)", 0.4, "kg")], 20, 2200, (180, 420), {"USA": 45, "GBR": 20, "FRA": 15, "DEU": 10, "JPN": 10}),
    "Steel forging":                  ("mechanical", [("Forging-grade steel", 8, "kg")], 30, 300, (45, 160), None),
    "Fluoroelastomer seal kit":       ("mechanical", [("PTFE fluoropolymer", 0.05, "kg")], 30, 25, (20, 90), None),
    "Catalytic / PGM sensor":         ("mechanical", [("Platinum group metals (refined)", 0.002, "kg")], 15, 400, (60, 180), {"DEU": 30, "USA": 25, "JPN": 20, "GBR": 15, "ZAF": 10}),
    # composite
    "Carbon-fiber airframe panel":    ("composite", [("Carbon fiber (PAN-based)", 2, "kg"), ("Epoxy resin", 1, "kg")], 40, 1500, (60, 180), None),
    "Glass-composite radome":         ("composite", [("E-glass fiber", 3, "kg"), ("Epoxy resin", 1.5, "kg")], 20, 2500, (90, 240), None),
    # rocket motor
    "Composite propellant grain":     ("rocket_motor", [("Ammonium perchlorate", 12, "kg"), ("HTPB binder", 2, "kg"), ("Aluminium powder (atomized)", 3, "kg")], 20, 6000, (180, 420), {"USA": 40, "FRA": 15, "DEU": 10, "GBR": 10, "NOR": 10, "ITA": 5, "KOR": 5, "TUR": 5}),
    "Filament-wound motor case":      ("rocket_motor", [("Carbon fiber (PAN-based)", 6, "kg"), ("Epoxy resin", 3, "kg")], 15, 4000, (120, 300), {"USA": 40, "FRA": 20, "DEU": 10, "ITA": 10, "NOR": 10, "TUR": 10}),
    "Nozzle throat insert":           ("rocket_motor", [("Tungsten heavy alloy", 0.8, "kg"), ("Carbon fiber (PAN-based)", 0.5, "kg")], 15, 2000, (120, 300), None),
    "Igniter (BKNO3)":                ("rocket_motor", [("Boron (refined)", 0.01, "kg"), ("Lead azide / lead styphnate", 0.002, "kg")], 15, 350, (90, 240), None),
    # energetics
    "Main charge (RDX/TNT fill)":     ("energetics", [("RDX / HMX", 4, "kg"), ("TNT", 3, "kg")], 20, 900, (90, 365), {"USA": 25, "POL": 15, "DEU": 15, "FRA": 10, "SWE": 10, "CZE": 5, "NOR": 5, "ESP": 5, "KOR": 5, "TUR": 5}),
    "Single-base propellant charge":  ("energetics", [("Nitrocellulose", 10, "kg")], 20, 400, (120, 400), {"USA": 25, "DEU": 15, "FRA": 10, "POL": 10, "CZE": 10, "FIN": 10, "KOR": 10, "TUR": 10}),
    "Detonator":                      ("energetics", [("Lead azide / lead styphnate", 0.001, "kg"), ("Copper cathode", 0.01, "kg")], 20, 45, (60, 200), None),
    "Fuze electronics module":        ("energetics", [("Mature-node die (>=28 nm)", 2, "die"), ("Tantalum powder (capacitor grade)", 0.001, "kg")], 20, 250, (90, 300), None),
    "Forged shell body":              ("energetics", [("Forging-grade steel", 30, "kg")], 15, 350, (60, 240), {"USA": 25, "POL": 15, "CZE": 10, "DEU": 10, "KOR": 10, "TUR": 10, "IND": 10, "ESP": 5, "UKR": 5}),
    "Tungsten preformed fragments":   ("energetics", [("Tungsten heavy alloy", 2, "kg")], 15, 600, (90, 300), None),
    "Percussion primer / tracer":     ("energetics", [("Antimony trisulfide", 0.002, "kg"), ("Lead azide / lead styphnate", 0.001, "kg")], 20, 3, (60, 240), None),
    # armor
    "Armor steel plate (cut)":        ("armor", [("Armor steel plate", 120, "kg")], 20, 3000, (60, 200), None),
    "Boron carbide armor tile":       ("armor", [("Boron carbide ceramic", 2, "kg")], 20, 700, (90, 240), None),
    "Aramid ballistic fabric":        ("armor", [("Aramid fiber", 2, "kg")], 20, 250, (45, 150), None),
    "UHMWPE ballistic panel":         ("armor", [("UHMWPE fiber", 3, "kg")], 20, 500, (45, 150), None),
    # engine
    "Diesel engine block":            ("engine", [("Forging-grade steel", 300, "kg"), ("Aluminium alloy 7075 plate", 80, "kg")], 10, 45000, (180, 400), {"DEU": 35, "USA": 25, "GBR": 10, "FRA": 10, "KOR": 10, "TUR": 5, "ITA": 5}),
    "Turbocharger":                   ("engine", [("Inconel 718 (Ni superalloy)", 3, "kg")], 15, 4000, (90, 240), None),
    "Fuel injector":                  ("engine", [("Forging-grade steel", 0.5, "kg"), ("Molybdenum oxide", 0.01, "kg")], 20, 300, (60, 180), None),
    "Small turbojet core":            ("engine", [("Inconel 718 (Ni superalloy)", 6, "kg"), ("Ti-6Al-4V mill product", 4, "kg")], 10, 25000, (240, 420), {"USA": 40, "FRA": 20, "GBR": 15, "CZE": 10, "TUR": 10, "UKR": 5}),
}

# Subassembly kinds -> component families they draw from
SUBASSEMBLY_KINDS = {
    "pcba":          ("PCB assembly", ["FPGA (rad-tolerant)", "Microcontroller", "MLCC capacitor", "Tantalum capacitor", "Thick-film resistor", "Multilayer PCB (bare board)", "Memory IC", "Solder paste", "MIL-spec circular connector", "DC-DC converter module"]),
    "power":         ("Power conditioning unit", ["SiC power MOSFET", "DC-DC converter module", "MLCC capacitor", "Tantalum capacitor", "Multilayer PCB (bare board)", "Coaxial RF cable assembly"]),
    "rf_frontend":   ("RF front-end", ["GaN power amplifier MMIC", "GaAs low-noise amplifier MMIC", "RF filter (SAW/BAW)", "Patch antenna element", "Coaxial RF cable assembly", "Multilayer PCB (bare board)", "MLCC capacitor"]),
    "array_tile":    ("Antenna array tile", ["T/R module (phased array)", "Patch antenna element", "FPGA (rad-tolerant)", "Aluminium structural frame", "Coaxial RF cable assembly"]),
    "imu":           ("Inertial measurement unit", ["MEMS gyroscope", "Fiber-optic gyro coil", "Quartz crystal oscillator", "Microcontroller", "Multilayer PCB (bare board)"]),
    "gnss":          ("GNSS module", ["GNSS receiver chip", "Patch antenna element", "Quartz crystal oscillator", "RF filter (SAW/BAW)", "Multilayer PCB (bare board)"]),
    "ir_optics":     ("IR optical train", ["Germanium IR lens", "Sapphire dome / window", "InSb IR focal-plane array", "Uncooled microbolometer", "Aluminium structural frame"]),
    "laser":         ("Laser rangefinder / designator", ["Laser diode (GaAs)", "Germanium IR lens", "Microcontroller", "DC-DC converter module"]),
    "night_vision":  ("Night-vision channel", ["Image intensifier tube", "Germanium IR lens", "Battery management IC"]),
    "motor_drive":   ("Motor & drive", ["Brushless DC motor", "Precision bearing", "SiC power MOSFET", "Microcontroller", "Composite propeller"]),
    "actuation":     ("Control actuation unit", ["Servo actuator", "Precision bearing", "Machined titanium bracket", "Microcontroller"]),
    "battery_pack":  ("Battery pack", ["Li-ion cell (21700)", "Battery management IC", "Multilayer PCB (bare board)", "MIL-spec circular connector"]),
    "thermal_power": ("Thermal battery assembly", ["Thermal battery", "MIL-spec circular connector"]),
    "structure":     ("Structural section", ["Aluminium structural frame", "Machined titanium bracket", "Titanium fastener kit", "Carbon-fiber airframe panel", "Fluoroelastomer seal kit"]),
    "radome":        ("Radome assembly", ["Glass-composite radome", "Titanium fastener kit"]),
    "rocket_motor":  ("Rocket motor", ["Composite propellant grain", "Filament-wound motor case", "Nozzle throat insert", "Igniter (BKNO3)"]),
    "warhead":       ("Warhead section", ["Main charge (RDX/TNT fill)", "Detonator", "Fuze electronics module", "Tungsten preformed fragments"]),
    "cartridge":     ("Projectile & charge", ["Forged shell body", "Main charge (RDX/TNT fill)", "Single-base propellant charge", "Percussion primer / tracer", "Fuze electronics module"]),
    "armor":         ("Armor package", ["Armor steel plate (cut)", "Boron carbide armor tile", "Aramid ballistic fabric", "UHMWPE ballistic panel", "Titanium fastener kit"]),
    "powerpack":     ("Engine powerpack", ["Diesel engine block", "Turbocharger", "Fuel injector", "Precision bearing", "Catalytic / PGM sensor"]),
    "turbojet":      ("Turbojet unit", ["Small turbojet core", "Superalloy turbine blade", "Precision bearing", "Microcontroller"]),
    "running_gear":  ("Running gear", ["Steel forging", "Precision bearing", "Fluoroelastomer seal kit", "Armor steel plate (cut)"]),
}

# System domains -> subassembly kinds used inside
DOMAINS = {
    "Airframe":            ["structure", "radome", "actuation"],
    "Electric propulsion": ["motor_drive", "battery_pack", "power"],
    "Rocket propulsion":   ["rocket_motor", "structure", "actuation"],
    "Jet propulsion":      ["turbojet", "pcba", "structure"],
    "Diesel powertrain":   ["powerpack", "running_gear", "pcba"],
    "Guidance & navigation": ["imu", "gnss", "pcba"],
    "EO/IR seeker":        ["ir_optics", "laser", "pcba"],
    "RF seeker":           ["rf_frontend", "pcba", "radome"],
    "Warhead & fuzing":    ["warhead", "pcba", "thermal_power"],
    "Datalink & comms":    ["rf_frontend", "pcba", "gnss"],
    "Power":               ["battery_pack", "power", "thermal_power"],
    "Protection":          ["armor", "structure"],
    "Fire control":        ["ir_optics", "laser", "pcba", "night_vision"],
    "Mobility":            ["running_gear", "powerpack", "actuation"],
    "Radar":               ["array_tile", "rf_frontend", "pcba", "power"],
    "Electronic warfare":  ["rf_frontend", "array_tile", "pcba"],
    "Ammunition":          ["cartridge", "warhead"],
    "Weapon station":      ["actuation", "ir_optics", "cartridge", "pcba"],
}

# Platform archetypes (synthetic designations) -> domains
PLATFORMS = {
    "Loitering munition":          ["Airframe", "Electric propulsion", "Guidance & navigation", "EO/IR seeker", "Warhead & fuzing", "Datalink & comms", "Power"],
    "FPV strike drone":            ["Airframe", "Electric propulsion", "Guidance & navigation", "Datalink & comms", "Warhead & fuzing", "Power"],
    "Fixed-wing ISR UAV":          ["Airframe", "Electric propulsion", "Guidance & navigation", "EO/IR seeker", "Datalink & comms", "Power", "Electronic warfare"],
    "Jet-powered target drone":    ["Airframe", "Jet propulsion", "Guidance & navigation", "Datalink & comms", "Power"],
    "Air-defense interceptor":     ["Airframe", "Rocket propulsion", "Guidance & navigation", "RF seeker", "Warhead & fuzing", "Datalink & comms", "Power"],
    "Anti-tank guided missile":    ["Airframe", "Rocket propulsion", "Guidance & navigation", "EO/IR seeker", "Warhead & fuzing", "Power"],
    "Cruise missile":              ["Airframe", "Jet propulsion", "Guidance & navigation", "EO/IR seeker", "RF seeker", "Warhead & fuzing", "Datalink & comms", "Power"],
    "Guided MLRS rocket":          ["Airframe", "Rocket propulsion", "Guidance & navigation", "Warhead & fuzing", "Power"],
    "155mm artillery round":       ["Ammunition", "Guidance & navigation"],
    "Self-propelled howitzer":     ["Protection", "Mobility", "Fire control", "Weapon station", "Datalink & comms", "Power"],
    "Main battle tank":            ["Protection", "Mobility", "Fire control", "Weapon station", "Datalink & comms", "Power", "Electronic warfare"],
    "Infantry fighting vehicle":   ["Protection", "Mobility", "Fire control", "Weapon station", "Datalink & comms", "Power"],
    "SHORAD system":               ["Radar", "Fire control", "Weapon station", "Mobility", "Datalink & comms", "Power"],
    "Ground surveillance radar":   ["Radar", "Power", "Datalink & comms", "Protection"],
    "Counter-UAS jammer":          ["Electronic warfare", "Radar", "Power", "Datalink & comms"],
    "Tactical radio":              ["Datalink & comms", "Power"],
    "Thermal weapon sight":        ["Fire control", "Power"],
    "Unmanned surface vessel":     ["Airframe", "Diesel powertrain", "Guidance & navigation", "EO/IR seeker", "Datalink & comms", "Warhead & fuzing", "Power"],
    "Unmanned ground vehicle":     ["Mobility", "Electric propulsion", "Guidance & navigation", "Fire control", "Datalink & comms", "Power"],
    "Body armor system":           ["Protection"],
}

PRIME_COUNTRIES = {"USA": 25, "FRA": 10, "DEU": 10, "GBR": 10, "ITA": 6, "SWE": 5, "POL": 5, "ISR": 5, "KOR": 5,
                   "TUR": 4, "ESP": 3, "NOR": 3, "UKR": 4, "FIN": 2, "CZE": 2, "JPN": 2}
INTEGRATOR_COUNTRIES = {**PRIME_COUNTRIES, "NLD": 3, "BEL": 2, "CAN": 3, "JPN": 4, "CZE": 3, "DNK": 1}
SUBTIER_COUNTRIES = {**INTEGRATOR_COUNTRIES, "TWN": 3, "IND": 3, "MEX": 3, "CHN": 3, "ROU": 2, "GRC": 1}
COMPONENT_COUNTRIES = {"USA": 14, "CHN": 14, "TWN": 10, "JPN": 10, "KOR": 7, "DEU": 7, "MYS": 5, "VNM": 3,
                       "THA": 3, "MEX": 4, "IND": 4, "FRA": 3, "GBR": 3, "ITA": 2, "ISR": 2, "PHL": 2, "SGP": 2,
                       "CZE": 1, "POL": 2, "TUR": 2, "CAN": 1, "SWE": 1}
HOLDING_JURISDICTIONS = {"LUX": 20, "NLD": 20, "IRL": 10, "CYP": 10, "CHE": 10, "VGB": 8, "HKG": 10, "SGP": 8, "ARE": 4}

# Ports: name -> (locode-ish id, iso3, lat, lon, [adjacent sea areas])
PORTS = {
    "Rotterdam": ("NLRTM", "NLD", 51.95, 4.05, ["Dover Strait", "North Sea"]),
    "Antwerp": ("BEANR", "BEL", 51.27, 4.33, ["Dover Strait"]),
    "Hamburg": ("DEHAM", "DEU", 53.54, 9.97, ["North Sea"]),
    "Bremerhaven": ("DEBRV", "DEU", 53.55, 8.58, ["North Sea"]),
    "Felixstowe": ("GBFXT", "GBR", 51.95, 1.32, ["Dover Strait", "North Sea"]),
    "Le Havre": ("FRLEH", "FRA", 49.48, 0.11, ["Dover Strait"]),
    "Gothenburg": ("SEGOT", "SWE", 57.69, 11.90, ["North Sea", "Danish Straits"]),
    "Oslo": ("NOOSL", "NOR", 59.90, 10.75, ["North Sea"]),
    "Aarhus": ("DKAAR", "DNK", 56.15, 10.22, ["Danish Straits"]),
    "Gdansk": ("PLGDN", "POL", 54.40, 18.67, ["Baltic Sea"]),
    "Helsinki": ("FIHEL", "FIN", 60.15, 24.95, ["Baltic Sea"]),
    "St Petersburg": ("RULED", "RUS", 59.88, 30.20, ["Baltic Sea"]),
    "Valencia": ("ESVLC", "ESP", 39.44, -0.32, ["Western Mediterranean"]),
    "Marseille": ("FRMRS", "FRA", 43.30, 5.36, ["Western Mediterranean"]),
    "Genoa": ("ITGOA", "ITA", 44.40, 8.92, ["Western Mediterranean"]),
    "Piraeus": ("GRPIR", "GRC", 37.94, 23.63, ["Eastern Mediterranean", "Sicily Channel"]),
    "Haifa": ("ILHFA", "ISR", 32.82, 35.00, ["Eastern Mediterranean"]),
    "Port Said": ("EGPSD", "EGY", 31.26, 32.30, ["Eastern Mediterranean", "Suez Canal"]),
    "Ambarli": ("TRAMR", "TUR", 40.97, 28.68, ["Turkish Straits"]),
    "Constanta": ("ROCND", "ROU", 44.17, 28.65, ["Black Sea"]),
    "Odesa": ("UAODS", "UKR", 46.49, 30.74, ["Black Sea"]),
    "Novorossiysk": ("RUNVS", "RUS", 44.72, 37.78, ["Black Sea"]),
    "Jeddah": ("SAJED", "SAU", 21.48, 39.17, ["Red Sea"]),
    "Jebel Ali": ("AEJEA", "ARE", 25.01, 55.06, ["Persian Gulf"]),
    "Dammam": ("SADMM", "SAU", 26.50, 50.20, ["Persian Gulf"]),
    "Ras Laffan": ("QARLF", "QAT", 25.92, 51.55, ["Persian Gulf"]),
    "Bandar Abbas": ("IRBND", "IRN", 27.15, 56.20, ["Strait of Hormuz"]),
    "Nhava Sheva": ("INNSA", "IND", 18.95, 72.95, ["Arabian Sea"]),
    "Chennai": ("INMAA", "IND", 13.10, 80.30, ["Indian Ocean (Sri Lanka)"]),
    "Yangon": ("MMRGN", "MMR", 16.77, 96.17, ["Andaman Sea"]),
    "Port Klang": ("MYPKG", "MYS", 3.00, 101.39, ["Strait of Malacca"]),
    "Singapore": ("SGSIN", "SGP", 1.26, 103.82, ["Strait of Malacca", "South China Sea"]),
    "Tanjung Priok": ("IDTPP", "IDN", -6.10, 106.88, ["Sunda Strait", "South China Sea"]),
    "Cai Mep": ("VNCMP", "VNM", 10.55, 107.03, ["South China Sea"]),
    "Laem Chabang": ("THLCH", "THA", 13.08, 100.88, ["South China Sea"]),
    "Manila": ("PHMNL", "PHL", 14.60, 120.96, ["South China Sea", "Luzon Strait"]),
    "Hong Kong": ("HKHKG", "HKG", 22.30, 114.17, ["South China Sea", "Taiwan Strait"]),
    "Shenzhen": ("CNSZX", "CHN", 22.50, 113.88, ["South China Sea", "Taiwan Strait"]),
    "Kaohsiung": ("TWKHH", "TWN", 22.61, 120.28, ["Taiwan Strait", "Luzon Strait"]),
    "Shanghai": ("CNSHA", "CHN", 30.62, 122.07, ["East China Sea"]),
    "Ningbo": ("CNNGB", "CHN", 29.93, 121.85, ["East China Sea"]),
    "Qingdao": ("CNTAO", "CHN", 36.07, 120.32, ["Yellow Sea"]),
    "Tianjin": ("CNTSN", "CHN", 38.98, 117.75, ["Yellow Sea"]),
    "Busan": ("KRPUS", "KOR", 35.10, 129.04, ["Korea Strait"]),
    "Yokohama": ("JPYOK", "JPN", 35.45, 139.65, ["Philippine Sea", "North Pacific"]),
    "Nagoya": ("JPNGO", "JPN", 35.05, 136.85, ["Philippine Sea", "Korea Strait"]),
    "Vladivostok": ("RUVVO", "RUS", 43.11, 131.88, ["Sea of Japan"]),
    "Port Hedland": ("AUPHE", "AUS", -20.31, 118.58, ["Lombok Strait", "Central Indian Ocean"]),
    "Melbourne": ("AUMEL", "AUS", -37.84, 144.92, ["Great Australian Bight", "Coral Sea"]),
    "Durban": ("ZADUR", "ZAF", -29.87, 31.03, ["Mozambique Channel", "Cape of Good Hope"]),
    "Richards Bay": ("ZARCB", "ZAF", -28.80, 32.08, ["Mozambique Channel", "Cape of Good Hope"]),
    "Beira": ("MZBEW", "MOZ", -19.83, 34.84, ["Mozambique Channel"]),
    "Toamasina": ("MGTOA", "MDG", -18.15, 49.41, ["Central Indian Ocean", "Mozambique Channel"]),
    "Dar es Salaam": ("TZDAR", "TZA", -6.82, 39.29, ["Mozambique Channel", "Gulf of Aden"]),
    "Owendo": ("GAOWE", "GAB", 0.29, 9.50, ["Gulf of Guinea"]),
    "Lagos": ("NGLOS", "NGA", 6.44, 3.39, ["Gulf of Guinea"]),
    "Kamsar": ("GNKMR", "GIN", 10.65, -14.61, ["Canary Basin", "Gulf of Guinea"]),
    "Casablanca": ("MACAS", "MAR", 33.61, -7.61, ["Strait of Gibraltar", "Canary Basin"]),
    "Santos": ("BRSSZ", "BRA", -23.98, -46.30, ["South Atlantic", "Mid Atlantic"]),
    "Buenos Aires": ("ARBUE", "ARG", -34.60, -58.37, ["South Atlantic", "Cape Horn"]),
    "Valparaiso": ("CLVAP", "CHL", -33.03, -71.63, ["South-East Pacific"]),
    "Antofagasta": ("CLANF", "CHL", -23.65, -70.40, ["South-East Pacific"]),
    "Callao": ("PECLL", "PER", -12.05, -77.15, ["South-East Pacific"]),
    "Manzanillo": ("MXZLO", "MEX", 19.05, -104.31, ["Eastern Pacific"]),
    "Veracruz": ("MXVER", "MEX", 19.20, -96.13, ["Gulf of Mexico"]),
    "Los Angeles": ("USLAX", "USA", 33.73, -118.26, ["Eastern Pacific", "North Pacific"]),
    "Houston": ("USHOU", "USA", 29.73, -95.27, ["Gulf of Mexico"]),
    "New York": ("USNYC", "USA", 40.67, -74.04, ["North Atlantic"]),
    "Norfolk": ("USORF", "USA", 36.90, -76.33, ["North Atlantic", "Florida Strait"]),
    "Vancouver": ("CAVAN", "CAN", 49.29, -123.11, ["North Pacific", "Eastern Pacific"]),
    "Montreal": ("CAMTR", "CAN", 45.55, -73.52, ["North Atlantic"]),
}

# Landlocked / portless producer countries -> gateway ports (inland leg by rail/road)
GATEWAY_PORTS = {
    "BOL": ["Antofagasta", "Callao"], "KAZ": ["Novorossiysk", "Tianjin"], "TJK": ["Tianjin"],
    "MNG": ["Tianjin"], "RWA": ["Dar es Salaam"], "COD": ["Dar es Salaam", "Durban"],
    "ZMB": ["Dar es Salaam", "Durban"], "ZWE": ["Beira", "Durban"], "BLR": ["St Petersburg"],
    "CZE": ["Hamburg"], "LUX": ["Antwerp"], "CHE": ["Rotterdam", "Genoa"],
}

# Sea areas / chokepoints: name -> (lat, lon, is_chokepoint)
WAYPOINTS = {
    "Dover Strait": (51.0, 1.45, True), "North Sea": (55.5, 3.5, False), "Danish Straits": (55.6, 12.8, True),
    "Baltic Sea": (57.5, 19.5, False), "Cape Finisterre": (43.5, -10.0, False), "North Atlantic": (42.0, -40.0, False),
    "Strait of Gibraltar": (35.95, -5.6, True), "Western Mediterranean": (38.5, 5.0, False),
    "Sicily Channel": (37.3, 11.5, False), "Eastern Mediterranean": (34.0, 28.0, False),
    "Turkish Straits": (41.1, 29.05, True), "Black Sea": (43.3, 34.0, False), "Suez Canal": (30.5, 32.35, True),
    "Red Sea": (20.0, 38.5, False), "Bab-el-Mandeb": (12.6, 43.3, True), "Gulf of Aden": (12.5, 48.5, False),
    "Arabian Sea": (15.0, 62.0, False), "Strait of Hormuz": (26.5, 56.4, True), "Persian Gulf": (27.0, 51.5, False),
    "Indian Ocean (Sri Lanka)": (5.5, 80.5, False), "Andaman Sea": (9.0, 96.0, False),
    "Strait of Malacca": (2.5, 101.3, True), "South China Sea": (12.0, 113.0, False),
    "Taiwan Strait": (24.0, 119.5, True), "Luzon Strait": (20.5, 121.0, True), "East China Sea": (30.0, 125.0, False),
    "Yellow Sea": (36.0, 123.0, False), "Korea Strait": (34.5, 129.0, True), "Sea of Japan": (40.0, 134.0, False),
    "Philippine Sea": (20.0, 130.0, False), "North Pacific": (38.0, -170.0, False),
    "Lombok Strait": (-8.7, 115.7, True), "Sunda Strait": (-6.0, 105.8, True),
    "Central Indian Ocean": (-10.0, 75.0, False), "Mozambique Channel": (-18.0, 41.0, False),
    "Cape of Good Hope": (-35.0, 19.0, False), "Gulf of Guinea": (2.0, 3.0, False), "Canary Basin": (27.0, -18.0, False),
    "Mid Atlantic": (5.0, -30.0, False), "South Atlantic": (-25.0, -30.0, False), "Caribbean Sea": (15.0, -75.0, False),
    "Florida Strait": (24.3, -81.5, True), "Gulf of Mexico": (25.5, -91.0, False), "Panama Canal": (9.1, -79.7, True),
    "Eastern Pacific": (15.0, -100.0, False), "South-East Pacific": (-15.0, -80.0, False), "Cape Horn": (-56.5, -67.0, False),
    "Great Australian Bight": (-37.0, 125.0, False), "Coral Sea": (-15.0, 155.0, False),
}

SEA_LINKS = [
    ("Dover Strait", "North Sea"), ("Dover Strait", "Cape Finisterre"), ("North Sea", "Danish Straits"),
    ("Danish Straits", "Baltic Sea"), ("Cape Finisterre", "Strait of Gibraltar"), ("Cape Finisterre", "North Atlantic"),
    ("Cape Finisterre", "Canary Basin"), ("Strait of Gibraltar", "Canary Basin"), ("Strait of Gibraltar", "Western Mediterranean"),
    ("Western Mediterranean", "Sicily Channel"), ("Sicily Channel", "Eastern Mediterranean"),
    ("Eastern Mediterranean", "Suez Canal"), ("Eastern Mediterranean", "Turkish Straits"), ("Turkish Straits", "Black Sea"),
    ("Suez Canal", "Red Sea"), ("Red Sea", "Bab-el-Mandeb"), ("Bab-el-Mandeb", "Gulf of Aden"),
    ("Gulf of Aden", "Arabian Sea"), ("Arabian Sea", "Strait of Hormuz"), ("Strait of Hormuz", "Persian Gulf"),
    ("Arabian Sea", "Indian Ocean (Sri Lanka)"), ("Indian Ocean (Sri Lanka)", "Andaman Sea"),
    ("Indian Ocean (Sri Lanka)", "Strait of Malacca"), ("Andaman Sea", "Strait of Malacca"),
    ("Indian Ocean (Sri Lanka)", "Central Indian Ocean"), ("Gulf of Aden", "Mozambique Channel"),
    ("Mozambique Channel", "Cape of Good Hope"), ("Central Indian Ocean", "Cape of Good Hope"),
    ("Central Indian Ocean", "Mozambique Channel"), ("Cape of Good Hope", "South Atlantic"),
    ("Cape of Good Hope", "Gulf of Guinea"), ("Gulf of Guinea", "Mid Atlantic"), ("Gulf of Guinea", "Canary Basin"),
    ("Mid Atlantic", "Canary Basin"), ("Mid Atlantic", "Caribbean Sea"), ("Mid Atlantic", "South Atlantic"),
    ("North Atlantic", "Florida Strait"), ("Florida Strait", "Gulf of Mexico"), ("Caribbean Sea", "Gulf of Mexico"),
    ("Caribbean Sea", "Panama Canal"), ("Caribbean Sea", "North Atlantic"), ("Panama Canal", "Eastern Pacific"),
    ("Panama Canal", "South-East Pacific"), ("South-East Pacific", "Cape Horn"), ("Cape Horn", "South Atlantic"),
    ("Eastern Pacific", "North Pacific"), ("Strait of Malacca", "South China Sea"), ("Sunda Strait", "South China Sea"),
    ("Sunda Strait", "Lombok Strait"), ("Sunda Strait", "Central Indian Ocean"), ("South China Sea", "Taiwan Strait"),
    ("South China Sea", "Luzon Strait"), ("Luzon Strait", "Philippine Sea"), ("Taiwan Strait", "East China Sea"),
    ("East China Sea", "Yellow Sea"), ("East China Sea", "Korea Strait"), ("Korea Strait", "Sea of Japan"),
    ("East China Sea", "Philippine Sea"), ("Philippine Sea", "North Pacific"), ("Philippine Sea", "Lombok Strait"),
    ("Philippine Sea", "Coral Sea"), ("Lombok Strait", "Central Indian Ocean"),
    ("Central Indian Ocean", "Great Australian Bight"), ("Korea Strait", "Philippine Sea"),
]

# Overland connectivity (rail/road) between countries
LAND_GROUPS = [
    {"GBR", "FRA", "DEU", "ITA", "ESP", "NLD", "BEL", "LUX", "POL", "CZE", "SWE", "FIN", "NOR", "DNK", "ROU",
     "GRC", "UKR", "BLR", "RUS", "TUR", "CHE", "IRL"},
    {"USA", "CAN", "MEX"},
    {"BRA", "ARG", "CHL", "PER", "BOL"},
    {"CHN", "HKG", "VNM", "THA", "MYS", "SGP", "MMR", "MNG", "KAZ", "TJK", "RUS", "IND"},
    {"ZAF", "ZWE", "ZMB", "MOZ", "COD", "RWA", "TZA"},
    {"TUR", "IRN", "ISR", "EGY", "SAU", "ARE", "QAT"},
]

# Real disruption events (dates are the public announcement / start dates)
DISRUPTIONS = [
    ("D01", "Red Sea / Bab-el-Mandeb attacks on merchant shipping", "maritime", "2023-11-19", None,
     ["Bab-el-Mandeb", "Red Sea", "Suez Canal"], "Houthi attacks force most container lines to divert around the Cape of Good Hope."),
    ("D02", "Panama Canal drought transit restrictions", "maritime", "2023-06-01", "2024-08-31",
     ["Panama Canal"], "Low Gatun Lake levels cut daily transits and draft limits."),
    ("D03", "China export licensing for gallium and germanium", "export-control", "2023-08-01", None,
     ["Primary gallium", "High-purity gallium (6N)", "Germanium (refined)", "Germanium optical blank"], "MOFCOM export licence requirement."),
    ("D04", "China export controls on graphite", "export-control", "2023-12-01", None,
     ["Natural graphite", "Battery-grade graphite anode"], "Licence requirement for high-purity / spherical graphite."),
    ("D05", "China export controls on antimony", "export-control", "2024-09-15", None,
     ["Antimony ore", "Antimony metal / trioxide", "Antimony trisulfide"], "Licence requirement for antimony products."),
    ("D06", "China ban on Ga/Ge/Sb exports to the United States", "export-control", "2024-12-03", None,
     ["Primary gallium", "High-purity gallium (6N)", "Germanium (refined)", "Germanium optical blank",
      "Antimony metal / trioxide", "Antimony trisulfide"], "Export ban of dual-use gallium, germanium, antimony items to the US."),
    ("D07", "China export controls on tungsten, indium, molybdenum (and Te, Bi)", "export-control", "2025-02-04", None,
     ["Tungsten carbide powder", "Indium (refined)", "Molybdenum oxide"], "Licence requirement on several minor metals."),
    ("D08", "China export controls on medium/heavy rare earths and magnets", "export-control", "2025-04-04", None,
     ["Rare earth oxides (separated)", "NdFeB magnet alloy", "Sintered NdFeB magnet", "Samarium-cobalt magnet"],
     "Licence requirement on Sm, Gd, Tb, Dy, Lu, Sc, Y and related magnets."),
    ("D09", "EU sanctions on Russia (post Feb 2022 packages)", "sanctions", "2022-02-23", None,
     ["RUS"], "Broad EU import / export restrictions; Russian-origin supply to EU buyers prohibited or restricted."),
]
EXPORT_CONTROL_START = {}   # material/mineral -> [(date, to_country or None, event_id)]
for eid, _, kind, start, _, targets, _ in DISRUPTIONS:
    if kind == "export-control":
        for t in targets:
            EXPORT_CONTROL_START.setdefault(t, []).append((start, "USA" if eid == "D06" else None, eid))

WESTERN_ROOTS = ["Arkon", "Veltra", "Norvex", "Calder", "Brenna", "Ostrand", "Halvar", "Meridian", "Kestrel", "Corvan",
                 "Daltek", "Ferrum", "Granit", "Helion", "Isard", "Jarvik", "Lumen", "Marrow", "Nexa", "Orrin", "Pelion",
                 "Quarrel", "Ravel", "Sorrel", "Tamber", "Ulvane", "Varro", "Wexley", "Ystad", "Zephra", "Altair",
                 "Brightwater", "Castellan", "Dunmore", "Elstree", "Falkner", "Glenridge", "Hartwell", "Ironvale",
                 "Kingsbridge", "Lockwood", "Montclair", "Northgate", "Oakridge", "Penrose", "Redstone", "Silverline",
                 "Thornbury", "Upland", "Westmark", "Avior", "Borealis", "Cygnet", "Draco", "Eridan", "Fornax", "Grus",
                 "Hydra", "Lyra", "Mensa", "Norma", "Orion", "Pavo", "Sagitta", "Triton", "Vela", "Volans"]
ASIAN_ROOTS = {
    "CHN": ["Jinrui", "Huaxin", "Zhongke", "Ruitai", "Hengxin", "Tianhong", "Longxi", "Xinyuan", "Baoli", "Kaida",
            "Shengtai", "Yuntu", "Minghai", "Fuxing", "Jiahe", "Haitong", "Weida", "Lianfa", "Dongsheng", "Huarui"],
    "HKG": ["Pacific Crest", "Harbour Gate", "Victoria Peak", "Kowloon Bay", "Jade Harbour"],
    "TWN": ["Hsinwei", "Chuanyu", "Taihong", "Yungshin", "Kaiyang", "Lixiang", "Hongtai"],
    "JPN": ["Kanshin", "Mitsuhara", "Takumi", "Seiren", "Hokuryo", "Nishikawa", "Shinwa", "Toyokawa", "Daisen"],
    "KOR": ["Hanbit", "Daesung", "Seojin", "Woori", "Kumyang", "Sejong", "Yuhan"],
    "VNM": ["Viet Tien", "Hoang Long", "Minh Phat"], "THA": ["Siam Union", "Chao Phraya"], "MYS": ["Kinta", "Perak Jaya"],
    "IDN": ["Nusantara", "Sumber Jaya"], "IND": ["Shakti", "Bharat Precision", "Vajra", "Agni", "Suryodaya"],
    "RUS": ["Uralmet", "Sibtekh", "Volgaprom", "Krasnoye", "Severnaya"],
}
SUFFIX = {"USA": "Inc.", "CAN": "Ltd.", "GBR": "Ltd", "DEU": "GmbH", "FRA": "SAS", "ITA": "S.p.A.", "ESP": "S.A.",
          "NLD": "B.V.", "BEL": "NV", "LUX": "S.a r.l.", "POL": "Sp. z o.o.", "CZE": "s.r.o.", "SWE": "AB", "FIN": "Oy",
          "NOR": "AS", "DNK": "A/S", "CHE": "AG", "CHN": "Co., Ltd.", "HKG": "Holdings Ltd", "TWN": "Corp.",
          "JPN": "K.K.", "KOR": "Co., Ltd.", "RUS": "JSC", "BRA": "Ltda.", "IND": "Pvt. Ltd.", "TUR": "A.S.",
          "ISR": "Ltd.", "AUS": "Pty Ltd", "ZAF": "(Pty) Ltd", "IRL": "Holdings DAC", "CYP": "Holdings Ltd",
          "VGB": "Holdings Ltd", "SGP": "Pte. Ltd.", "ARE": "FZE", "MEX": "S.A. de C.V."}
INDUSTRY_WORD = {0: "Defence Systems", 1: "Systems", 2: "Electronics", 3: "Technologies", 4: "Industries",
                 5: "Components", 6: "Materials", 7: "Mining", "holding": "Group", "trader": "Trading"}

# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def haversine_nm(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 3440.065 * math.asin(math.sqrt(h))


class Builder:
    def __init__(self, seed, scale):
        self.rng = random.Random(seed)
        self.scale = scale
        self.nodes = []      # (id, label, props)
        self.edges = []      # (from, to, type, props)
        self.counters = defaultdict(int)

    def node(self, label, prefix, props):
        self.counters[prefix] += 1
        nid = f"{prefix}{self.counters[prefix]:05d}"
        props = {k: v for k, v in props.items() if v is not None}
        self.nodes.append((nid, label, props))
        return nid

    def edge(self, a, b, etype, **props):
        self.edges.append((a, b, etype, {k: v for k, v in props.items() if v is not None}))

    def pick_weighted(self, weights):
        keys = [k for k, w in weights.items() if w > 0]
        return self.rng.choices(keys, weights=[weights[k] for k in keys])[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--scale", type=float, default=1.0, help="multiplies part-number pools and shipments")
    ap.add_argument("--shipments", type=int, default=120000)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    B = Builder(args.seed, args.scale)
    rng = B.rng

    # ---------------- countries, ports, sea network ----------------
    country_id = {}
    for iso, (name, region, _) in COUNTRIES.items():
        country_id[iso] = B.node("Country", "CTY", {
            "country_code": iso, "name": name, "region": region,
            "nato_member": iso in NATO, "eu_member": iso in EU, "eu_sanctions_target": iso in EU_SANCTIONED})

    wp_id, wp_pos = {}, {}
    for name, (lat, lon, is_cp) in WAYPOINTS.items():
        label = "Chokepoint" if is_cp else "SeaArea"
        wp_id[name] = B.node(label, "WPT", {"waypoint_id": name.upper().replace(" ", "_"), "name": name,
                                           "lat": lat, "lon": lon, "is_chokepoint": is_cp})
        wp_pos[name] = (lat, lon)
    port_id, port_pos, ports_by_country = {}, {}, defaultdict(list)
    for name, (code, iso, lat, lon, _) in PORTS.items():
        port_id[name] = B.node("Port", "PRT", {"port_id": code, "name": f"Port of {name}", "lat": lat, "lon": lon,
                                              "country_code": iso})
        port_pos[name] = (lat, lon)
        ports_by_country[iso].append(name)
        B.edge(port_id[name], country_id[iso], "LOCATED_IN")
    for iso, gws in GATEWAY_PORTS.items():
        ports_by_country.setdefault(iso, [])

    # adjacency for routing (node name -> [(neighbor, nm)])
    adj = defaultdict(list)

    def link(a, pa, b, pb, ida, idb):
        nm = round(haversine_nm(pa, pb) * 1.15, 0)
        days = round(nm / (14 * 24), 2)
        B.edge(ida, idb, "SEA_LANE", distance_nm=nm, transit_days=days)
        B.edge(idb, ida, "SEA_LANE", distance_nm=nm, transit_days=days)
        adj[a].append((b, nm))
        adj[b].append((a, nm))

    for a, b in SEA_LINKS:
        link(a, wp_pos[a], b, wp_pos[b], wp_id[a], wp_id[b])
    for name, (_, _, _, _, wps) in PORTS.items():
        for w in wps:
            link("P:" + name, port_pos[name], w, wp_pos[w], port_id[name], wp_id[w])

    route_cache = {}
    RED_SEA = {"Bab-el-Mandeb", "Red Sea", "Suez Canal"}

    def sea_route(src, dst, avoid=frozenset()):
        key = (src, dst, avoid)
        if key in route_cache:
            return route_cache[key]
        start, goal = "P:" + src, "P:" + dst
        dist, prev, pq = {start: 0}, {}, [(0, start)]
        while pq:
            d, u = heapq.heappop(pq)
            if u == goal:
                break
            if d > dist.get(u, 1e18):
                continue
            if u.startswith("P:") and u != start:
                continue  # ports are not transit nodes
            for v, w in adj[u]:
                if v in avoid:
                    continue
                nd = d + w
                if nd < dist.get(v, 1e18):
                    dist[v], prev[v] = nd, u
                    heapq.heappush(pq, (nd, v))
        if goal not in dist:
            route_cache[key] = None
            return None
        path, u = [goal], goal
        while u != start:
            u = prev[u]
            path.append(u)
        path.reverse()
        route_cache[key] = (dist[goal], [p for p in path if not p.startswith("P:")])
        return route_cache[key]

    # ---------------- disruptions ----------------
    disruption_id = {}
    for eid, name, kind, start, end, targets, desc in DISRUPTIONS:
        disruption_id[eid] = B.node("Disruption", "DIS", {"disruption_id": eid, "name": name, "kind": kind,
                                                          "start_date": start, "end_date": end, "description": desc})

    # ---------------- companies & facilities ----------------
    companies = []           # dict(id, country, tier, kind)
    company_by_key = defaultdict(list)   # (tier, kind) -> [company idx]
    facilities = {}          # fid -> dict(country, company, tier, kind, port, inland)
    fac_pool = defaultdict(list)          # (tier, kind) -> [fid]
    fac_load = defaultdict(int)

    def company_name(iso, tier):
        roots = ASIAN_ROOTS.get(iso, WESTERN_ROOTS)
        root = rng.choice(roots)
        if roots is WESTERN_ROOTS and rng.random() < 0.35:
            root = root + rng.choice(["-", " "]) + rng.choice(WESTERN_ROOTS)
        return f"{root} {INDUSTRY_WORD[tier]} {SUFFIX.get(iso, 'Ltd.')}".replace("  ", " ")

    def new_company(iso, tier, kind, ctype="operating"):
        cname = company_name(iso, tier if ctype == "operating" else ctype)
        cid = B.node("Company", "CMP", {"company_id": None, "name": cname,
                                        "company_type": ctype, "tier": tier if isinstance(tier, int) else None,
                                        "sector": kind, "hq_country": iso})
        B.nodes[-1][2]["company_id"] = cid
        B.edge(cid, country_id[iso], "HEADQUARTERED_IN")
        companies.append({"id": cid, "name": cname, "country": iso, "tier": tier, "kind": kind, "type": ctype})
        company_by_key[(tier, kind)].append(len(companies) - 1)
        return len(companies) - 1

    FAC_TYPE = {0: "final assembly plant", 1: "systems integration plant", 2: "subsystem plant", 3: "assembly plant",
                4: "subassembly line", 5: "component fab", 6: "processing plant", 7: "mine"}

    def new_facility(iso, tier, kind, company_idx=None):
        if company_idx is None:
            # multinational: sometimes attach a new plant to an existing foreign company of the same trade
            same = company_by_key[(tier, kind)]
            if same and rng.random() < 0.22:
                company_idx = rng.choice(same)
            else:
                company_idx = new_company(iso, tier, kind)
        comp = companies[company_idx]
        city = rng.choice(COUNTRIES[iso][2])
        port_choices = ports_by_country.get(iso) or GATEWAY_PORTS.get(iso, [])
        port = rng.choice(port_choices) if port_choices else None
        inland_km = rng.randint(15, 250) if ports_by_country.get(iso) else rng.randint(600, 2500)
        fid = B.node("Facility", "FAC", {"facility_id": None, "name": f"{comp['name']} - {city}",
                                         "facility_type": FAC_TYPE[tier], "tier": tier, "sector": kind,
                                         "city": city, "country_code": iso,
                                         "capacity_utilization": round(rng.uniform(0.45, 0.98), 2)})
        B.nodes[-1][2]["facility_id"] = fid
        B.edge(fid, comp["id"], "OPERATED_BY")
        B.edge(fid, country_id[iso], "LOCATED_IN")
        if port:
            B.edge(fid, port_id[port], "SHIPS_VIA", mode="road" if inland_km < 400 else "rail", inland_km=inland_km)
        facilities[fid] = {"country": iso, "company": company_idx, "tier": tier, "kind": kind, "port": port,
                           "inland_km": inland_km}
        fac_pool[(tier, kind)].append(fid)
        return fid

    def assign_facilities(item_id, tier, kind, country_weights, n_min, n_max, reuse=0.55):
        """Attach an item to 1..n producing facilities (preferential attachment within (tier, kind))."""
        n = rng.randint(n_min, n_max)
        chosen = []
        for _ in range(n):
            iso = B.pick_weighted(country_weights)
            pool = [f for f in fac_pool[(tier, kind)] if facilities[f]["country"] == iso and f not in chosen]
            if pool and rng.random() < reuse:
                fid = rng.choices(pool, weights=[1 + fac_load[f] for f in pool])[0]
            else:
                fid = new_facility(iso, tier, kind)
            chosen.append(fid)
        shares = [rng.random() + 0.2 for _ in chosen]
        tot = sum(shares)
        for fid, s in zip(chosen, shares):
            fac_load[fid] += 1
            B.edge(item_id, fid, "PRODUCED_AT", share_pct=round(100 * s / tot, 1))
        return chosen

    producers = {}          # item id -> [fid]
    item_level = {}         # item id -> level
    item_name = {}

    # ---------------- minerals ----------------
    mineral_id = {}
    for m, shares in MINERALS.items():
        top = max(shares, key=shares.get)
        tot = sum(shares.values())
        mid = B.node("Mineral", "MIN", {"item_id": None, "name": m, "level": 7, "category": "raw material",
                                        "top_producer": top, "top_producer_share_pct": round(100 * shares[top] / tot, 1),
                                        "lead_time_days": rng.randint(30, 90)})
        B.nodes[-1][2]["item_id"] = mid
        mineral_id[m] = mid
        item_level[mid], item_name[mid] = 7, m
        for iso, s in shares.items():
            B.edge(mid, country_id[iso], "PRODUCTION_SHARE", share_pct=round(100 * s / tot, 1),
                   basis="approx. USGS MCS 2024 (mine production)")
        # mines: number proportional to country share
        fids = []
        for iso, s in shares.items():
            for _ in range(max(1, round(s / 8))):
                fids.append(new_facility(iso, 7, "mining"))
        for fid in fids:
            B.edge(mid, fid, "PRODUCED_AT", share_pct=None)
        producers[mid] = fids

    # ---------------- materials (topological order) ----------------
    material_id = {}
    pending = dict(MATERIALS)
    while pending:
        progressed = False
        for m, (cat, inputs, dist) in list(pending.items()):
            if not all(i in MINERALS or i in material_id for i in inputs):
                continue
            mat_id = B.node("Material", "MAT", {"item_id": None, "name": m, "level": 6, "category": cat,
                                                "lead_time_days": rng.randint(30, 180),
                                                "unit_cost_eur": round(math.exp(rng.uniform(0, 7)), 2)})
            B.nodes[-1][2]["item_id"] = mat_id
            material_id[m] = mat_id
            item_level[mat_id], item_name[mat_id] = 6, m
            for i in inputs:
                child = mineral_id.get(i) or material_id[i]
                B.edge(mat_id, child, "CONTAINS", qty=round(rng.uniform(0.05, 2.0), 3), unit="kg/kg")
            weights = dist or GENERIC_PROCESSING
            if dist:
                tot = sum(dist.values())
                for iso, s in dist.items():
                    if s > 0:
                        B.edge(mat_id, country_id[iso], "PRODUCTION_SHARE", share_pct=round(100 * s / tot, 1),
                               basis="approx. refining/processing share" if cat != "semiconductor" else "approx. capacity share")
            n = max(3, min(16, len([k for k, v in weights.items() if v > 0]) + 2))
            fids = assign_facilities(mat_id, 6, cat, weights, n - 2, n, reuse=0.35)
            producers[mat_id] = fids
            del pending[m]
            progressed = True
        assert progressed, f"material cycle: {list(pending)}"

    # ---------------- components (part numbers) ----------------
    family_parts = {}
    for fam, (kind, recipe, n_parts, cost, (lt0, lt1), cw) in COMPONENTS.items():
        parts = []
        for k in range(max(3, int(n_parts * B.scale))):
            pid = B.node("Component", "CMPT", {"item_id": None, "name": f"{fam} #{k + 1:03d}", "family": fam,
                                               "level": 5, "category": kind,
                                               "unit_cost_eur": round(cost * rng.uniform(0.5, 1.8), 2),
                                               "lead_time_days": rng.randint(lt0, lt1),
                                               "export_controlled": rng.random() < (0.6 if cost > 1000 else 0.15),
                                               "criticality": rng.choices("ABC", [0.3, 0.5, 0.2])[0]})
            B.nodes[-1][2]["item_id"] = pid
            item_level[pid], item_name[pid] = 5, f"{fam} #{k + 1:03d}"
            for mat, qty, unit in recipe:
                child = material_id.get(mat) or mineral_id[mat]
                B.edge(pid, child, "CONTAINS", qty=qty, unit=unit)
            producers[pid] = assign_facilities(pid, 5, kind, cw or COMPONENT_COUNTRIES, 1, 3)
            parts.append(pid)
        family_parts[fam] = parts

    # ---------------- subassemblies (shared pools per kind) ----------------
    sub_pool = {}
    for kind, (label, fams) in SUBASSEMBLY_KINDS.items():
        pool = []
        for k in range(int(40 * B.scale)):
            sid = B.node("Subassembly", "SUB", {"item_id": None, "name": f"{label} SA-{kind[:3].upper()}{k + 1:03d}",
                                                "level": 4, "category": kind,
                                                "unit_cost_eur": round(math.exp(rng.uniform(5, 10)), 2),
                                                "lead_time_days": rng.randint(20, 90),
                                                "criticality": rng.choices("ABC", [0.4, 0.45, 0.15])[0]})
            B.nodes[-1][2]["item_id"] = sid
            item_level[sid] = 4
            picks = rng.sample(fams, k=min(len(fams), rng.randint(3, 5)))
            for fam in picks:
                B.edge(sid, rng.choice(family_parts[fam]), "CONTAINS", qty=rng.choice([1, 1, 2, 4, 8, 16]), unit="ea")
            producers[sid] = assign_facilities(sid, 4, kind, SUBTIER_COUNTRIES, 1, 2)
            pool.append(sid)
        sub_pool[kind] = pool

    # ---------------- subsystems (shared pools per domain) & assemblies ----------------
    subsystem_pool = {}
    for dom, kinds in DOMAINS.items():
        pool = []
        for k in range(int(14 * B.scale)):
            ssid = B.node("Subsystem", "SSY", {"item_id": None, "name": f"{dom} subsystem SS-{k + 1:03d}",
                                               "level": 2, "category": dom,
                                               "unit_cost_eur": round(math.exp(rng.uniform(8, 12)), 2),
                                               "lead_time_days": rng.randint(30, 150),
                                               "criticality": rng.choices("AB", [0.6, 0.4])[0]})
            B.nodes[-1][2]["item_id"] = ssid
            item_level[ssid] = 2
            producers[ssid] = assign_facilities(ssid, 2, dom, INTEGRATOR_COUNTRIES, 1, 2)
            for a in range(rng.randint(2, 4)):
                kind = rng.choice(kinds)
                aid = B.node("Assembly", "ASM", {"item_id": None, "name": f"{SUBASSEMBLY_KINDS[kind][0]} assembly A-{dom[:3].upper()}{k + 1:03d}.{a + 1}",
                                                 "level": 3, "category": kind,
                                                 "unit_cost_eur": round(math.exp(rng.uniform(6, 11)), 2),
                                                 "lead_time_days": rng.randint(30, 120),
                                                 "criticality": rng.choices("ABC", [0.5, 0.4, 0.1])[0]})
                B.nodes[-1][2]["item_id"] = aid
                item_level[aid] = 3
                B.edge(ssid, aid, "CONTAINS", qty=rng.choice([1, 1, 2]), unit="ea")
                producers[aid] = assign_facilities(aid, 3, kind, SUBTIER_COUNTRIES, 1, 2)
                for s in rng.sample(sub_pool[kind], k=rng.randint(2, 4)):
                    B.edge(aid, s, "CONTAINS", qty=rng.choice([1, 1, 2, 4]), unit="ea")
                if rng.random() < 0.5:   # cross-kind subassembly (e.g. a PCBA inside a structure)
                    other = rng.choice(kinds)
                    B.edge(aid, rng.choice(sub_pool[other]), "CONTAINS", qty=1, unit="ea")
            pool.append(ssid)
        subsystem_pool[dom] = pool

    # ---------------- platforms & systems ----------------
    platform_ids = []
    for arch, doms in PLATFORMS.items():
        for v in range(max(1, int(2 * B.scale))):
            code = "".join(w[0] for w in arch.replace("-", " ").split() if w[0].isalpha()).upper()
            pname = f"{arch} {code}-{rng.randint(1, 9)}{rng.randint(0, 9)}{chr(65 + v)}"
            plid = B.node("Platform", "PLT", {"item_id": None, "name": pname, "archetype": arch, "level": 0,
                                              "category": arch, "unit_cost_eur": round(math.exp(rng.uniform(8, 16)), 2),
                                              "lead_time_days": rng.randint(90, 365),
                                              "annual_demand": rng.choice([50, 200, 1000, 5000, 20000, 100000])})
            B.nodes[-1][2]["item_id"] = plid
            item_level[plid] = 0
            producers[plid] = assign_facilities(plid, 0, "prime", PRIME_COUNTRIES, 1, 1, reuse=0.3)
            platform_ids.append(plid)
            for dom in doms:
                syid = B.node("System", "SYS", {"item_id": None, "name": f"{pname} / {dom}", "level": 1,
                                                "category": dom,
                                                "unit_cost_eur": round(math.exp(rng.uniform(7, 14)), 2),
                                                "lead_time_days": rng.randint(60, 200), "criticality": "A"})
                B.nodes[-1][2]["item_id"] = syid
                item_level[syid] = 1
                B.edge(plid, syid, "CONTAINS", qty=1, unit="ea")
                # systems are often built in-house by the prime
                if rng.random() < 0.4:
                    f = producers[plid][0]
                    B.edge(syid, f, "PRODUCED_AT", share_pct=100.0)
                    producers[syid] = [f]
                else:
                    producers[syid] = assign_facilities(syid, 1, dom, INTEGRATOR_COUNTRIES, 1, 2)
                for ss in rng.sample(subsystem_pool[dom], k=rng.randint(2, 4)):
                    B.edge(syid, ss, "CONTAINS", qty=rng.choice([1, 1, 2]), unit="ea")

    # ---------------- planted findings ----------------
    planted = []
    # (1) hidden single point of failure: every GaN PA MMIC part number made by one facility
    gan_parts = family_parts["GaN power amplifier MMIC"]
    spof = producers[gan_parts[0]][0]
    for p in gan_parts:
        B.edges = [e for e in B.edges if not (e[0] == p and e[2] == "PRODUCED_AT")]
        B.edge(p, spof, "PRODUCED_AT", share_pct=100.0)
        producers[p] = [spof]
    planted.append(f"SPOF: facility {spof} ({facilities[spof]['country']}) is the sole source of all "
                   f"{len(gan_parts)} 'GaN power amplifier MMIC' part numbers")

    # (2) foreign ownership: an EU magnet / motor maker owned via NLD -> HKG holdings by a CHN parent
    motor_facs = [f for f in fac_pool[(5, "motor")] if facilities[f]["country"] in {"DEU", "POL", "FRA", "ITA"}]
    if not motor_facs:
        motor_facs = [new_facility("DEU", 5, "motor")]
    target_fac = max(motor_facs, key=lambda f: fac_load[f])
    target_co = companies[facilities[target_fac]["company"]]
    h1 = new_company("NLD", "holding", "holding", ctype="holding")
    h2 = new_company("HKG", "holding", "holding", ctype="holding")
    parent = new_company("CHN", 6, "magnetic")
    owned_override = {target_co["id"]: (companies[h1]["id"], 100.0),
                      companies[h1]["id"]: (companies[h2]["id"], 100.0),
                      companies[h2]["id"]: (companies[parent]["id"], 72.5)}
    planted.append(f"Foreign ownership: {target_co['id']} ({target_co['country']}, operates {target_fac}) -> "
                   f"{companies[h1]['id']} (NLD) -> {companies[h2]['id']} (HKG) -> {companies[parent]['id']} (CHN)")

    # (3) sanctioned ownership: a TUR component maker owned via CYP holding by a RUS parent
    tur_facs = [f for f in facilities if facilities[f]["country"] == "TUR" and facilities[f]["tier"] in (4, 5)]
    tur_fac = max(tur_facs, key=lambda f: fac_load[f]) if tur_facs else new_facility("TUR", 5, "mechanical")
    tur_co = companies[facilities[tur_fac]["company"]]
    h3 = new_company("CYP", "holding", "holding", ctype="holding")
    rus_parent = new_company("RUS", 6, "alloy")
    owned_override[tur_co["id"]] = (companies[h3]["id"], 51.0)
    owned_override[companies[h3]["id"]] = (companies[rus_parent]["id"], 100.0)
    planted.append(f"Sanctions exposure: {tur_co['id']} (TUR, operates {tur_fac}) -> {companies[h3]['id']} (CYP) -> "
                   f"{companies[rus_parent]['id']} (RUS)")

    # ---------------- ownership chains ----------------
    holdings = []
    n_operating = len(companies)
    operating_by_country = defaultdict(list)
    for j in range(n_operating):
        if companies[j]["type"] == "operating" and isinstance(companies[j]["tier"], int):
            operating_by_country[companies[j]["country"]].append(j)
    all_operating = [j for js in operating_by_country.values() for j in js]
    for idx in range(n_operating):
        c = companies[idx]
        if c["type"] != "operating" or c["id"] in owned_override:
            continue
        if rng.random() > 0.32:
            continue
        child = c["id"]
        depth = 0
        while depth < 4:
            depth += 1
            r = rng.random()
            if r < 0.45:   # parent is an existing larger operating company, usually same country
                if not isinstance(c["tier"], int):
                    break
                base = operating_by_country[c["country"]] if rng.random() < 0.8 else all_operating
                # parents always have a lower index -> ownership graph stays acyclic
                cands = [j for j in base if j < idx and companies[j]["tier"] <= c["tier"]]
                if not cands:
                    break
                j = rng.choice(cands)
                if companies[j]["id"] in owned_override or j == idx:
                    break
                B.edge(child, companies[j]["id"], "SUBSIDIARY_OF", ownership_pct=round(rng.choice([100, 100, 75, 60, 51]), 1))
                break  # operating parents keep their own (separately drawn) ownership
            else:          # parent is a holding company in a holding jurisdiction
                juris = B.pick_weighted(HOLDING_JURISDICTIONS) if rng.random() < 0.6 else c["country"]
                h = new_company(juris, "holding", "holding", ctype="holding")
                holdings.append(h)
                hid = companies[h]["id"]
                B.edge(child, hid, "SUBSIDIARY_OF", ownership_pct=round(rng.choice([100, 100, 90, 75, 51]), 1))
                child = hid
                if rng.random() < 0.4:
                    break
    for child, (par, pct) in owned_override.items():
        B.edge(child, par, "SUBSIDIARY_OF", ownership_pct=pct)

    # ---------------- physical supply network (facility -> facility) ----------------
    contains = defaultdict(list)
    for a, b, t, p in B.edges:
        if t == "CONTAINS":
            contains[a].append(b)
    supplies = {}   # (src_fac, dst_fac, item) -> annual volume
    rus_trader_cache = {}

    def blocked_by_sanctions(src, dst):
        return facilities[src]["country"] in EU_SANCTIONED and (facilities[dst]["country"] in EU or facilities[dst]["country"] in NATO)

    for parent_item, children in contains.items():
        for dst in producers.get(parent_item, []):
            for child in children:
                srcs = producers.get(child, [])
                if not srcs:
                    continue
                k = 1 if rng.random() < 0.6 else 2
                picks = rng.sample(srcs, k=min(k, len(srcs)))
                for src in picks:
                    if src == dst:
                        continue
                    if blocked_by_sanctions(src, dst):
                        if rng.random() < 0.85:
                            alt = [s for s in srcs if not blocked_by_sanctions(s, dst) and s != dst]
                            if alt:
                                src = rng.choice(alt)
                            else:
                                continue
                        else:
                            # sanctions circumvention: route via a third-country trading company
                            hub = rng.choice(["TUR", "ARE", "KAZ"])
                            key = (src, hub)
                            if key not in rus_trader_cache:
                                rus_trader_cache[key] = new_facility(hub, 6, "trader", company_idx=new_company(hub, "trader", "trader"))
                                facilities[rus_trader_cache[key]]["kind"] = "trader"
                            trader = rus_trader_cache[key]
                            supplies[(src, trader, child)] = supplies.get((src, trader, child), 0) + rng.randint(10, 500)
                            src = trader
                    supplies[(src, dst, child)] = supplies.get((src, dst, child), 0) + rng.randint(10, 5000)
    for (src, dst, item), vol in supplies.items():
        B.edge(src, dst, "SUPPLIES", item_id=item, annual_volume=vol)
    # fix facility_type of traders
    for nid, label, props in B.nodes:
        if label == "Facility" and props.get("sector") == "trader":
            props["facility_type"] = "trading / distribution hub"
            props.pop("tier", None)

    # ---------------- shipments ----------------
    start_day, end_day = date(2023, 1, 1), date(2025, 12, 31)
    span = (end_day - start_day).days
    sup_list = list(supplies.keys())
    target = int(args.shipments * B.scale)
    weights = [1.0 / (1 + item_level.get(it, 6)) + (0.5 if item_level.get(it, 6) >= 5 else 0) for _, _, it in sup_list]
    chosen = rng.choices(range(len(sup_list)), weights=weights, k=target)

    def same_landmass(a, b):
        return a == b or any(a in g and b in g for g in LAND_GROUPS)

    item_lookup = {**{v: k for k, v in material_id.items()}, **{v: k for k, v in mineral_id.items()}}
    disrupt_counts = defaultdict(int)
    for idx in chosen:
        src, dst, it = sup_list[idx]
        fs, fd = facilities[src], facilities[dst]
        ship = start_day + timedelta(days=rng.randint(0, span))
        ship_s = ship.isoformat()
        level = item_level.get(it, 6)
        props = {"shipment_id": None, "ship_date": ship_s, "qty": rng.randint(1, 200) * (10 if level >= 5 else 1)}
        route_wps, events = [], []
        rerouted = False
        lp = lt = None
        if same_landmass(fs["country"], fd["country"]) or not fs["port"] or not fd["port"] or fs["port"] == fd["port"]:
            mode = "road" if fs["country"] == fd["country"] else "rail/road"
            planned = 1 + (0 if fs["country"] == fd["country"] else rng.randint(2, 6))
            actual = planned + max(0, rng.gauss(0.5, 1.5))
        elif level <= 5 and rng.random() < 0.3:
            mode = "air"
            planned = 3
            actual = planned + max(0, rng.gauss(0.5, 1.0))
        else:
            mode = "sea"
            lp, lt = fs["port"], fd["port"]
            base = sea_route(lp, lt)
            if base is None:
                mode, planned, actual = "air", 3, 3.5
            else:
                nm, route_wps = base
                handling = 4 + (fs["inland_km"] + fd["inland_km"]) / 400
                planned = nm / (14 * 24) + handling
                actual_nm = nm
                if ship_s >= "2023-11-19" and RED_SEA & set(route_wps) and rng.random() < 0.9:
                    alt = sea_route(lp, lt, avoid=frozenset(RED_SEA))
                    if alt:
                        actual_nm, route_wps = alt
                        rerouted = True
                        events.append("D01")
                if "Panama Canal" in route_wps and "2023-06-01" <= ship_s <= "2024-08-31":
                    handling += rng.uniform(3, 12)
                    events.append("D02")
                actual = actual_nm / (14 * 24) + handling + max(0, rng.gauss(1, 2.5))
        status = "delivered"
        mat_name = item_lookup.get(it)
        if mat_name in EXPORT_CONTROL_START and fs["country"] == "CHN" and fd["country"] != "CHN":
            for start, to_c, eid in EXPORT_CONTROL_START[mat_name]:
                if ship_s >= start and (to_c is None or fd["country"] == to_c):
                    events.append(eid)
                    if to_c is not None:
                        status = "blocked"
                    else:
                        actual += rng.uniform(15, 75)   # licence processing
        if ship_s >= "2025-10-01" and status == "delivered" and rng.random() < 0.5:
            status = "in_transit"
        arrival = ship + timedelta(days=round(actual))
        props.update({
            "mode": mode, "status": status, "planned_transit_days": round(planned, 1),
            "actual_transit_days": round(actual, 1) if status != "blocked" else None,
            "delay_days": round(actual - planned, 1) if status != "blocked" else None,
            "arrival_date": arrival.isoformat() if status == "delivered" else None,
            "rerouted": rerouted, "route": " > ".join(route_wps) if route_wps else None,
            "value_eur": None})
        sid = B.node("Shipment", "SHP", props)
        B.nodes[-1][2]["shipment_id"] = sid
        B.nodes[-1][2]["name"] = f"Shipment {sid}"
        B.edge(sid, src, "SHIPPED_FROM")
        B.edge(sid, dst, "SHIPPED_TO")
        B.edge(sid, it, "CARRIES")
        if lp:
            B.edge(sid, port_id[lp], "LOADED_AT")
            B.edge(sid, port_id[lt], "UNLOADED_AT")
            for seq, w in enumerate(route_wps):
                if WAYPOINTS[w][2]:
                    B.edge(sid, wp_id[w], "TRANSITED", seq=seq)
        for e in set(events):
            B.edge(sid, disruption_id[e], "IMPACTED_BY")
            disrupt_counts[e] += 1

    # disruption targets
    for eid, _, kind, _, _, targets, _ in DISRUPTIONS:
        for t in targets:
            tgt = wp_id.get(t) or material_id.get(t) or mineral_id.get(t) or country_id.get(t)
            B.edge(disruption_id[eid], tgt, "AFFECTS")

    # ---------------- unit costs on shipments ----------------
    cost = {nid: p.get("unit_cost_eur") for nid, _, p in B.nodes if "unit_cost_eur" in p}
    ship_item = {a: b for a, b, t, _ in B.edges if t == "CARRIES"}
    for nid, label, p in B.nodes:
        if label == "Shipment":
            c = cost.get(ship_item[nid])
            if c:
                p["value_eur"] = round(c * p["qty"], 2)

    # ---------------- names for nodes lacking one ----------------
    for nid, label, p in B.nodes:
        p.setdefault("name", f"{label}: {nid}")

    # ---------------- consistent property types ----------------
    # TuringDB stores a property key with mixed int/float values as String, so promote ints to
    # floats wherever a key ever holds a float (across nodes and edges, which share the key space).
    float_keys = {k for _, _, p in B.nodes for k, v in p.items() if isinstance(v, float)}
    float_keys |= {k for _, _, _, p in B.edges for k, v in p.items() if isinstance(v, float)}
    for props in [n[2] for n in B.nodes] + [e[3] for e in B.edges]:
        for k in float_keys & props.keys():
            if isinstance(props[k], int) and not isinstance(props[k], bool):
                props[k] = float(props[k])

    # ---------------- write parquet ----------------
    nodes_df = pd.DataFrame({"id": [n[0] for n in B.nodes], "label": [n[1] for n in B.nodes],
                             "properties": [json.dumps(n[2]) for n in B.nodes]})
    edges_df = pd.DataFrame({"from": [e[0] for e in B.edges], "to": [e[1] for e in B.edges],
                             "relation": [e[2] for e in B.edges], "properties": [json.dumps(e[3]) for e in B.edges]})
    nodes_df.to_parquet(os.path.join(args.out, "nodes.parquet"), index=False)
    edges_df.to_parquet(os.path.join(args.out, "edges.parquet"), index=False)

    print(f"nodes: {len(nodes_df):,}   edges: {len(edges_df):,}")
    print(nodes_df["label"].value_counts().to_string())
    print(edges_df["relation"].value_counts().to_string())
    print("shipments impacted per disruption:", dict(disrupt_counts))
    print("planted findings:")
    for p in planted:
        print("  -", p)
    with open(os.path.join(args.out, "planted_findings.txt"), "w") as f:
        f.write("\n".join(planted) + "\n")


if __name__ == "__main__":
    main()
