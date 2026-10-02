"""AssetType taxonomy: keyword rules that map cyber attacks to the kinds of system they hit,
and which physical assets run which kind of system."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class AssetType:
    asset_type_id: str
    name: str
    description: str
    pattern: re.Pattern[str]


def _rx(*words: str) -> re.Pattern[str]:
    return re.compile(r"\b(" + "|".join(words) + r")\b", re.IGNORECASE)


ASSET_TYPES: tuple[AssetType, ...] = (
    AssetType("ICS_SCADA", "ICS/SCADA", "Industrial control: PLCs, HMIs, RTUs, field protocols",
              _rx("ics", "scada", "plcs?", "hmis?", "modbus", "dnp3", "rtus?", r"iec[- ]?61850", r"iec[- ]?104",
                  "profinet", r"opc[- ]?ua", "bacnet", "historian", "industrial control", "stuxnet")),
    AssetType("OT_NETWORK", "OT network", "Operational-technology networks, substations, grid edge devices",
              _rx("ot", "ot network", "operational technology", "industrial network", "fieldbus", "substations?",
                  "smart grid", "power grid", "grid", "energy", "utility", "utilities", "smart meters?", "turbines?",
                  "inverters?", "iot devices?", "iot")),
    AssetType("ERP", "ERP", "Enterprise resource planning, procurement and finance systems",
              _rx("erp", "sap", "oracle", "mrp", "procurement", "invoices?", "invoicing", "payroll", "finance",
                  "financial", "accounting", "crm", "business email")),
    AssetType("LOGISTICS_IT", "Logistics IT", "Shipping, warehouse, fleet and tracking systems",
              _rx("logistics", "shipping", "warehouses?", "wms", "fleet", "tracking", "barcode", "maritime", "ais",
                  "freight", "courier", "delivery", "e-commerce")),
    AssetType("CORPORATE_IT", "Corporate IT", "Windows endpoints, AD, mail and enterprise networks",
              _rx("windows", "workstations?", "endpoints?", "active directory", "domain controllers?", "mail server",
                  "email", "exchange", "office users", "enterprise network", "internal network", "corporate",
                  "ldap", "kerberos", "vpn")),
    AssetType("SW_SUPPLY_CHAIN", "Software supply chain", "CI/CD pipelines, package registries, build systems",
              _rx("ci/cd", "ci-cd", "jenkins", "github actions", "gitlab", "github repo", "pipelines?",
                  "dependency", "dependencies", "npm", "pypi", "packages?", "build server", "container registry")),
    AssetType("SATCOM_GNSS", "SATCOM/GNSS", "Satellite links and satellite navigation receivers",
              _rx("satellite", "satellite communication", "satcom", "gps", "gps receivers?", "gnss", "vsat",
                  "ground station")),
    AssetType("UAS_AVIONICS", "UAS avionics", "Drone flight controllers, telemetry and control links",
              _rx("drones?", "uavs?", "uas", "quadcopters?", "flight controllers?", "mavlink", "px4", "ardupilot")),
    AssetType("PHYSICAL_ACCESS", "Physical access control", "Badges, RFID, door controllers, CCTV",
              _rx("rfid", "badges?", "access control", "physical access", "doors?", "cctv", "cameras?",
                  "keycards?", "tailgating", "nfc", "smart locks?")),
)

ASSET_TYPE_IDS = tuple(a.asset_type_id for a in ASSET_TYPES)

# Which physical asset kinds run which systems (drives synthetic RUNS edges).
RUNS_BY_KIND: dict[str, tuple[str, ...]] = {
    "PowerPlant": ("ICS_SCADA", "OT_NETWORK"),
    "Site": ("ICS_SCADA", "OT_NETWORK", "ERP", "CORPORATE_IT", "PHYSICAL_ACCESS"),
    "PartSupplier": ("ERP", "CORPORATE_IT", "SW_SUPPLY_CHAIN"),
    "LogisticsSupplier": ("LOGISTICS_IT", "ERP"),
    "Drone": ("UAS_AVIONICS", "SATCOM_GNSS"),
}


def match_asset_types(target_type: str | None, tags: str | None) -> list[tuple[str, str]]:
    """(asset_type_id, matched keyword) for every asset type whose rule hits target_type or tags."""
    text = " | ".join(t for t in (target_type, tags) if t)
    hits = []
    for asset in ASSET_TYPES:
        m = asset.pattern.search(text)
        if m:
            hits.append((asset.asset_type_id, m.group(0).lower()))
    return hits
