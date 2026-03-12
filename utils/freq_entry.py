# utils/freq_entry.py
"""
Reusable compound widget: numeric Entry + unit Combobox for frequency fields.
Always stores and returns values in Hz internally.
"""
import tkinter as tk
from tkinter import ttk
from typing import Optional

FREQ_UNITS = ["Hz", "kHz", "MHz", "GHz"]

MULTIPLIERS = {
    "Hz":  1e0,
    "kHz": 1e3,
    "MHz": 1e6,
    "GHz": 1e9,
}


class FreqEntry(ttk.Frame):
    """
    Drop-in replacement for a plain ttk.Entry on frequency fields.

    Usage:
        fe = FreqEntry(parent)
        fe.pack(...)

        hz = fe.get_hz()       # returns float in Hz, or None if empty/invalid
        fe.set_hz(2.4e9)       # sets display to "2.4 GHz" (auto-picks best unit)
        fe.get()               # returns raw display string e.g. "2.4"
        fe.get_unit()          # returns current unit string e.g. "GHz"
    """

    def __init__(self, parent, width=12, default_unit="MHz", **kwargs):
        super().__init__(parent, **kwargs)
        self._val_var  = tk.StringVar()
        self._unit_var = tk.StringVar(value=default_unit)

        self._entry = ttk.Entry(self, textvariable=self._val_var, width=width)
        self._entry.pack(side="left")

        self._combo = ttk.Combobox(self, textvariable=self._unit_var,
                                    values=FREQ_UNITS, state="readonly", width=5)
        self._combo.pack(side="left", padx=(3, 0))

    def get_hz(self) -> Optional[float]:
        """Return the entered value converted to Hz. Returns None if empty or invalid."""
        raw = self._val_var.get().strip()
        if not raw:
            return None
        try:
            return float(raw) * MULTIPLIERS[self._unit_var.get()]
        except (ValueError, KeyError):
            return None

    def set_hz(self, hz: float):
        """Set the widget value from a Hz float, auto-selecting the best display unit."""
        if hz is None:
            self._val_var.set("")
            return
        # Pick the largest unit where the display value is >= 1
        for unit in reversed(FREQ_UNITS):  # GHz → MHz → kHz → Hz
            converted = hz / MULTIPLIERS[unit]
            if converted >= 1.0:
                self._unit_var.set(unit)
                # Trim unnecessary trailing zeros
                display = f"{converted:.6g}"
                self._val_var.set(display)
                return
        # Fallback for very small values
        self._unit_var.set("Hz")
        self._val_var.set(f"{hz:.6g}")

    def get(self) -> str:
        """Return raw display string (without unit)."""
        return self._val_var.get()

    def get_unit(self) -> str:
        return self._unit_var.get()

    def set(self, value: str):
        """Set raw display string directly."""
        self._val_var.set(value)

    def configure(self, **kwargs):
        """Pass state/width through to both child widgets."""
        state = kwargs.get("state")
        if state:
            self._entry.configure(state=state)
            self._combo.configure(state="readonly" if state == "normal" else state)
