# utils/visa_helper.py - COMPLETE FILE
"""
VISA helper for Axiro PA Testbench.
- Provides a shared pyvisa ResourceManager.
- Maps company-specific VISA addresses to driver classes.
- Provides fuzzy registry lookup so tabs don't need hardcoded name strings.
"""

import pyvisa
from utils.logger import get_logger

from drivers import (
    KeysightE36xxSupply,
    AgilentE3648ASupply,
    HP6633BSupply,
    Keysight3446xDMM,
    PXAN9030A,
    RSSMBV100B,
)

_logger = get_logger(__name__)
_rm = None  # singleton ResourceManager

# ── Instrument type tags ───────────────────────────────────────
# Each entry maps a set of name fragments to a canonical role string.
# Used by find_driver() to locate instruments without hardcoded keys.
_ROLE_HINTS = {
    "siggen":  ["SMBV", "SMB", "SMF", "SMA", "E8257", "E8267",
                "MG369", "Signal", "SigGen"],
    "specan":  ["N9030", "PXA", "N9020", "MXA", "FSV", "FSW",
                "RSA", "Spectrum", "SpecAn"],
    "psu":     ["E3623", "E3624", "E3648", "E3631", "6633",
                "6634", "6643", "Supply", "PSU"],
    "dmm":     ["34465", "34461", "34411", "34401", "DMM",
                "Multimeter"],
}


def get_visa_rm():
    """Return a singleton pyvisa ResourceManager."""
    global _rm
    if _rm is None:
        _rm = pyvisa.ResourceManager()
        _logger.info("Initialized VISA ResourceManager")
    return _rm


def find_driver(registry: dict, role: str, name_hint: str = ""):
    """
    Fuzzy-search the driver registry for an instrument by role or name.

    Priority:
      1. Exact key match on name_hint (fast path, e.g. "RS_SMBV100B")
      2. Partial name match on name_hint against registry keys
      3. Role-based match using _ROLE_HINTS tags against registry keys

    Returns the driver object or None — never raises.

    Examples:
        drv = find_driver(registry, "siggen")
        drv = find_driver(registry, "specan", "PXA_N9030A")
        drv = find_driver(registry, "psu",    "Keysight_E36234A")
    """
    if not registry:
        return None

    # 1. Exact key
    if name_hint and name_hint in registry:
        return registry[name_hint]

    # 2. Partial name match
    if name_hint:
        hint_lower = name_hint.lower()
        for key, drv in registry.items():
            if hint_lower in key.lower():
                _logger.debug(
                    f"find_driver: partial match '{name_hint}' -> '{key}'")
                return drv

    # 3. Role-based tag search
    role_lower = role.lower()
    tags = _ROLE_HINTS.get(role_lower, [])
    for key, drv in registry.items():
        key_upper = key.upper()
        for tag in tags:
            if tag.upper() in key_upper:
                _logger.debug(
                    f"find_driver: role '{role}' matched tag '{tag}' -> '{key}'")
                return drv

    _logger.warning(
        f"find_driver: no match for role='{role}' hint='{name_hint}'")
    return None


def find_all_drivers(registry: dict, role: str) -> list:
    """
    Return ALL drivers matching a role (e.g. all PSUs).
    Useful for the Sweep Plan to populate channel dropdowns.
    """
    tags      = _ROLE_HINTS.get(role.lower(), [])
    results   = []
    for key, drv in registry.items():
        key_upper = key.upper()
        for tag in tags:
            if tag.upper() in key_upper:
                results.append((key, drv))
                break
    return results


def load_driver(address: str):
    """
    Given a VISA address string, create and connect the appropriate driver.
    Hard-coded mapping for Axiro lab instruments.
    """
    addr = address.strip()

    # ── Power supplies ─────────────────────────────────────────
    if "0x2A8D::0x3402" in addr or "0x2A8D::0x3302" in addr:
        drv = KeysightE36xxSupply(addr)
        drv.connect()
        return drv

    if addr.startswith("GPIB0::15") or addr.startswith("GPIB0::11"):
        drv = AgilentE3648ASupply(addr)
        drv.connect()
        return drv

    if addr.startswith("GPIB0::10"):
        drv = HP6633BSupply(addr)
        drv.connect()
        return drv

    # ── DMMs ───────────────────────────────────────────────────
    if "0x2A8D::0x0101" in addr or "0x2A8D::0x1301" in addr:
        drv = Keysight3446xDMM(addr)
        drv.connect()
        return drv

    # ── Spectrum analyzer ──────────────────────────────────────
    if addr.startswith("GPIB0::18"):
        drv = PXAN9030A(addr)
        drv.connect()
        return drv

    # ── Signal generator ───────────────────────────────────────
    if addr.startswith("GPIB0::28"):
        drv = RSSMBV100B(addr)
        drv.connect()
        return drv

    raise RuntimeError(
        f"No driver mapping defined for VISA address: {address}")
