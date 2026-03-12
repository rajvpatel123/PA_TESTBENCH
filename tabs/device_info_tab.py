# tabs/device_info_tab.py - COMPLETE FILE
import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
from utils.logger import get_logger
from utils.visa_helper import load_driver

_logger = get_logger(__name__)

ALIASES_FILE = "instrument_aliases.json"

COMPANY_INSTRUMENTS = [
    {"name": "Keysight_E36234A",       "address": "USB0::0x2A8D::0x3402::MY61002290::INSTR", "role": "Power Supply"},
    {"name": "Keysight_E36233A",       "address": "USB0::0x2A8D::0x3302::MY61003932::INSTR", "role": "Power Supply"},
    {"name": "Agilent_E3648A_GPIB15",  "address": "GPIB0::15::INSTR",                        "role": "Power Supply"},
    {"name": "Agilent_E3648A_GPIB11",  "address": "GPIB0::11::INSTR",                        "role": "Power Supply"},
    {"name": "Agilent_3648A",          "address": "GPIB0::10::INSTR",                        "role": "Power Supply"},
    {"name": "Keysight_34465A_1",      "address": "USB0::0x2A8D::0x0101::MY60050792::INSTR", "role": "DMM"},
    {"name": "Keysight_34465A_2",      "address": "USB0::0x2A8D::0x0101::MY59001442::INSTR", "role": "DMM"},
    {"name": "Keysight_34461A",        "address": "USB0::0x2A8D::0x1301::MY57206934::0::INSTR", "role": "DMM"},
    {"name": "PXA_N9030A",             "address": "GPIB0::18::INSTR",                        "role": "Spectrum Analyzer"},
    {"name": "RS_SMBV100B",            "address": "GPIB0::28::INSTR",                        "role": "Signal Generator"},
]


class DeviceInfoTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._driver_update_callback = None
        self._driver_registry = {}
        self._alias_map = self._load_aliases()
        self._build_ui()

    # ── Alias persistence ──────────────────────────────────────
    def _load_aliases(self) -> dict:
        if os.path.exists(ALIASES_FILE):
            try:
                with open(ALIASES_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_aliases(self):
        try:
            with open(ALIASES_FILE, "w") as f:
                json.dump(self._alias_map, f, indent=2)
        except Exception as e:
            _logger.error(f"Failed to save aliases: {e}")

    # ── UI ─────────────────────────────────────────────────────
    def _build_ui(self):
        ttk.Label(self, text="Axiro PA Testbench - Device Manager",
                  font=("Segoe UI", 14, "bold")).pack(pady=10)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(pady=5)

        ttk.Button(btn_frame, text="Connect All",
                   command=self._connect_all).grid(row=0, column=0, padx=5)
        ttk.Button(btn_frame, text="Reconnect Selected",
                   command=self._reconnect_selected).grid(row=0, column=1, padx=5)
        ttk.Button(btn_frame, text="Self-Test Selected",
                   command=self._self_test_selected).grid(row=0, column=2, padx=5)
        ttk.Button(btn_frame, text="Reset Selected",
                   command=self._reset_selected).grid(row=0, column=3, padx=5)
        ttk.Button(btn_frame, text="Edit Alias",
                   command=self._edit_alias).grid(row=0, column=4, padx=5)
        ttk.Button(btn_frame, text="Clear List",
                   command=self._clear_list).grid(row=0, column=5, padx=5)

        cols = ("Name", "Alias", "Role", "Address", "IDN", "Driver", "Status")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=15)
        col_widths = {
            "Name":    200, "Alias":  160, "Role":   140,
            "Address": 280, "IDN":    260, "Driver": 150, "Status": 120,
        }
        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=col_widths[col], anchor="w")
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)
        self.tree.bind("<Double-1>", lambda e: self._edit_alias())

        ttk.Label(self, text="Double-click a row to edit its alias",
                  foreground="gray").pack()

        self.status_lbl = ttk.Label(self, text="Status: Idle", foreground="gray")
        self.status_lbl.pack(pady=5)

    def register_driver_callback(self, callback):
        self._driver_update_callback = callback

    def set_driver_registry(self, registry):
        self._driver_registry = registry

    # ── Alias editing ──────────────────────────────────────────
    def _edit_alias(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("No Selection", "Select an instrument to edit its alias.")
            return
        item_id = sel[0]
        vals    = self.tree.item(item_id, "values")
        name    = vals[0]
        current_alias = self._alias_map.get(name, "")

        dialog = tk.Toplevel(self)
        dialog.title(f"Edit Alias: {name}")
        dialog.grab_set()
        dialog.resizable(False, False)

        ttk.Label(dialog, text=f"Instrument: {name}",
                  font=("Segoe UI", 10, "bold")).grid(
                  row=0, column=0, columnspan=2, padx=15, pady=10)
        ttk.Label(dialog, text="Alias:").grid(row=1, column=0, padx=10, sticky="e")

        alias_var = tk.StringVar(value=current_alias)
        ttk.Entry(dialog, textvariable=alias_var, width=28).grid(
                  row=1, column=1, padx=10, pady=8)

        ttk.Label(dialog,
                  text="Alias is a friendly label only.\nThe instrument name in the registry stays unchanged.",
                  foreground="gray", justify="left").grid(
                  row=2, column=0, columnspan=2, padx=12, pady=4)

        def apply():
            alias = alias_var.get().strip()
            self._alias_map[name] = alias
            self._save_aliases()
            # Update tree row
            new_vals = list(vals)
            new_vals[1] = alias
            self.tree.item(item_id, values=new_vals)
            _logger.info(f"Alias set: {name} -> '{alias}'")
            dialog.destroy()

        def clear_alias():
            self._alias_map.pop(name, None)
            self._save_aliases()
            new_vals = list(vals)
            new_vals[1] = ""
            self.tree.item(item_id, values=new_vals)
            _logger.info(f"Alias cleared for {name}")
            dialog.destroy()

        ttk.Button(dialog, text="Apply",       command=apply).grid(row=3, column=0, pady=10, padx=10)
        ttk.Button(dialog, text="Clear Alias", command=clear_alias).grid(row=3, column=1, pady=10, padx=10)

    # ── Self-test ──────────────────────────────────────────────
    def _self_test_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("No Selection", "Select an instrument to self-test.")
            return
        item_id = sel[0]
        vals    = self.tree.item(item_id, "values")
        name    = vals[0]
        drv     = self._driver_registry.get(name)

        if drv is None:
            messagebox.showerror("Not Connected", f"{name} is not connected.")
            return

        try:
            result = drv._inst.query("*TST?").strip()
            if result == "0":
                msg = f"{name} self-test PASSED (result: {result})"
                self._set_row_status(item_id, vals, "Self-Test OK")
                messagebox.showinfo("Self-Test Passed", msg)
            else:
                msg = f"{name} self-test FAILED (result: {result})"
                self._set_row_status(item_id, vals, f"Self-Test FAIL ({result})")
                messagebox.showwarning("Self-Test Failed", msg)
            _logger.info(msg)
        except Exception as e:
            messagebox.showerror("Self-Test Error", f"{name}:\n{e}")
            _logger.error(f"Self-test error for {name}: {e}")

    # ── Reset ──────────────────────────────────────────────────
    def _reset_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("No Selection", "Select an instrument to reset.")
            return
        item_id = sel[0]
        vals    = self.tree.item(item_id, "values")
        name    = vals[0]
        drv     = self._driver_registry.get(name)

        if drv is None:
            messagebox.showerror("Not Connected", f"{name} is not connected.")
            return

        if not messagebox.askyesno("Confirm Reset",
                                    f"Send *RST to {name}?\n"
                                    "This resets the instrument to factory defaults."):
            return
        try:
            drv._inst.write("*RST")
            drv._inst.write("*CLS")
            self._set_row_status(item_id, vals, "Reset OK")
            self.status_lbl.config(text=f"Status: {name} reset", foreground="green")
            _logger.info(f"Reset sent to {name}")
        except Exception as e:
            messagebox.showerror("Reset Error", f"{name}:\n{e}")
            _logger.error(f"Reset error for {name}: {e}")

    # ── Helpers ────────────────────────────────────────────────
    def _set_row_status(self, item_id, vals, status: str):
        new_vals = list(vals)
        new_vals[6] = status
        self.tree.item(item_id, values=new_vals)

    def _clear_list(self):
        self.tree.delete(*self.tree.get_children())
        self._driver_registry.clear()
        self.status_lbl.config(text="Status: Cleared", foreground="gray")
        _logger.info("Device list cleared")

    # ── Connect ────────────────────────────────────────────────
    def _connect_all(self):
        _logger.info("Connect All triggered")
        self.tree.delete(*self.tree.get_children())
        self._driver_registry.clear()

        success = 0
        failed  = 0

        for dev in COMPANY_INSTRUMENTS:
            name    = dev["name"]
            address = dev["address"]
            role    = dev["role"]
            alias   = self._alias_map.get(name, "")

            try:
                drv = load_driver(address)
                try:
                    idn = drv.idn()
                except Exception:
                    idn = "IDN unavailable"

                drv_name = drv.__class__.__name__
                self._driver_registry[name] = drv

                self.tree.insert("", "end", iid=name,
                                 values=(name, alias, role, address, idn, drv_name, "Connected"))
                _logger.info(f"Connected: {name} ({alias}) at {address}")
                success += 1

            except Exception as e:
                self.tree.insert("", "end", iid=name,
                                 values=(name, alias, role, address, "", "Error", "Failed"))
                _logger.error(f"Failed to connect {name} at {address}: {e}")
                failed += 1

        if self._driver_update_callback:
            self._driver_update_callback(self._driver_registry)

        color = "green" if failed == 0 else "orange"
        msg   = f"{success} connected, {failed} failed"
        self.status_lbl.config(text=f"Status: {msg}", foreground=color)
        messagebox.showinfo("Connection Summary", msg)

    def _reconnect_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("No Selection", "Select a device to reconnect.")
            return

        item_id = sel[0]
        vals    = self.tree.item(item_id, "values")
        name, alias, role, address = vals[0], vals[1], vals[2], vals[3]

        try:
            drv = load_driver(address)
            try:
                idn = drv.idn()
            except Exception:
                idn = "IDN unavailable"

            drv_name = drv.__class__.__name__
            self._driver_registry[name] = drv

            self.tree.item(item_id,
                           values=(name, alias, role, address, idn, drv_name, "Connected"))
            _logger.info(f"Reconnected: {name} at {address}")
            self.status_lbl.config(text=f"Status: {name} reconnected", foreground="green")

            if self._driver_update_callback:
                self._driver_update_callback(self._driver_registry)

        except Exception as e:
            self.tree.item(item_id,
                           values=(name, alias, role, address, "", "Error", "Failed"))
            _logger.error(f"Reconnect failed for {name}: {e}")
            self.status_lbl.config(text=f"Status: {name} failed", foreground="red")
            messagebox.showerror("Reconnect Failed", f"{name} failed to reconnect:\n{e}")
