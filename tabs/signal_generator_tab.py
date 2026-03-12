# tabs/signal_generator_tab.py - COMPLETE FILE
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from utils.logger import get_logger
from utils.freq_entry import FreqEntry

_logger = get_logger(__name__)


class SignalGeneratorTab(ttk.Frame):

    DRIVER_NAME = "RS_SMBV100B"

    def __init__(self, parent, driver_registry: dict):
        super().__init__(parent)
        self._registry = driver_registry
        self._build_ui()

    def set_driver_registry(self, registry: dict):
        self._registry = registry

    def _get_driver(self):
        drv = self._registry.get(self.DRIVER_NAME)
        if drv is None:
            messagebox.showerror("Not Connected",
                                 f"{self.DRIVER_NAME} not connected.\n"
                                 "Go to Device Manager and click Connect All.")
        return drv

    def _build_ui(self):
        ttk.Label(self, text="Signal Generator - R&S SMBV100B",
                  font=("Segoe UI", 14, "bold")).pack(pady=10)

        main = ttk.Frame(self)
        main.pack(fill="both", expand=True, padx=15, pady=5)

        # ── LEFT: Settings ─────────────────────────────────────
        left = ttk.LabelFrame(main, text="RF Settings")
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))

        # Frequency row with FreqEntry
        freq_frame = ttk.Frame(left)
        freq_frame.pack(fill="x", padx=10, pady=8)
        ttk.Label(freq_frame, text="Frequency:",
                  width=18, anchor="e").pack(side="left")
        self.freq_fe = FreqEntry(freq_frame, width=14, default_unit="MHz")
        self.freq_fe.pack(side="left", padx=5)

        # Power row
        power_frame = ttk.Frame(left)
        power_frame.pack(fill="x", padx=10, pady=8)
        ttk.Label(power_frame, text="Power Level:",
                  width=18, anchor="e").pack(side="left")
        self.power_var = tk.StringVar(value="")
        ttk.Entry(power_frame, textvariable=self.power_var,
                  width=16).pack(side="left", padx=5)
        ttk.Label(power_frame, text="dBm").pack(side="left")

        # Modulation row
        mod_frame = ttk.Frame(left)
        mod_frame.pack(fill="x", padx=10, pady=8)
        ttk.Label(mod_frame, text="Modulation:",
                  width=18, anchor="e").pack(side="left")
        self.mod_var = tk.StringVar(value="")
        ttk.Combobox(mod_frame, textvariable=self.mod_var, width=14,
                     values=["None", "AM", "FM", "PM", "IQ", "ARB"],
                     state="readonly").pack(side="left", padx=5)

        ttk.Button(left, text="Apply Settings",
                   command=self._apply_settings).pack(pady=10, padx=10, fill="x")

        ttk.Separator(left, orient="horizontal").pack(fill="x", padx=10, pady=5)

        # RF toggle
        rf_frame = ttk.Frame(left)
        rf_frame.pack(fill="x", padx=10, pady=8)
        ttk.Label(rf_frame, text="RF Output:",
                  width=18, anchor="e").pack(side="left")
        self.rf_state_var = tk.StringVar(value="OFF")
        self.rf_btn = ttk.Button(rf_frame, text="RF OFF",
                                  command=self._toggle_rf)
        self.rf_btn.pack(side="left", padx=5)
        self.rf_status_lbl = ttk.Label(rf_frame, text="RF is OFF",
                                        foreground="red")
        self.rf_status_lbl.pack(side="left", padx=10)

        ttk.Separator(left, orient="horizontal").pack(fill="x", padx=10, pady=5)

        # Presets
        preset_frame = ttk.LabelFrame(left, text="Quick Presets")
        preset_frame.pack(fill="x", padx=10, pady=5)
        ttk.Button(preset_frame, text="1 GHz / 0 dBm",
                   command=lambda: self._apply_preset(1e9, 0)).pack(
                   side="left", padx=5, pady=5)
        ttk.Button(preset_frame, text="2.4 GHz / -10 dBm",
                   command=lambda: self._apply_preset(2.4e9, -10)).pack(
                   side="left", padx=5, pady=5)
        ttk.Button(preset_frame, text="5.8 GHz / -20 dBm",
                   command=lambda: self._apply_preset(5.8e9, -20)).pack(
                   side="left", padx=5, pady=5)

        # ── RIGHT: Waveforms ───────────────────────────────────
        right = ttk.LabelFrame(main, text="Waveform Management")
        right.pack(side="right", fill="both", expand=True)

        ttk.Button(right, text="Upload Waveform from File...",
                   command=self._upload_waveform).pack(fill="x", padx=10, pady=8)
        ttk.Button(right, text="Refresh Waveform List",
                   command=self._refresh_waveforms).pack(fill="x", padx=10, pady=4)

        ttk.Label(right, text="Waveforms on Device:").pack(
            anchor="w", padx=10, pady=(8, 2))
        self.waveform_list = tk.Listbox(right, height=12, width=40)
        self.waveform_list.pack(fill="both", expand=True, padx=10, pady=4)

        wf_btn_frame = ttk.Frame(right)
        wf_btn_frame.pack(fill="x", padx=10, pady=4)
        ttk.Button(wf_btn_frame, text="Select Waveform",
                   command=self._select_waveform).pack(side="left", padx=5)
        ttk.Button(wf_btn_frame, text="Delete Waveform",
                   command=self._delete_waveform).pack(side="left", padx=5)

        self.selected_wf_lbl = ttk.Label(right, text="Selected: None",
                                          foreground="gray")
        self.selected_wf_lbl.pack(padx=10, pady=4)

        self.status_lbl = ttk.Label(self, text="Status: Idle", foreground="gray")
        self.status_lbl.pack(pady=5)

    # ── Settings ───────────────────────────────────────────────
    def _apply_settings(self):
        drv = self._get_driver()
        if drv is None:
            return

        freq_hz = self.freq_fe.get_hz()
        if freq_hz is None:
            messagebox.showwarning("Missing Values", "Enter a frequency.")
            return

        power_str = self.power_var.get().strip()
        if not power_str:
            messagebox.showwarning("Missing Values", "Enter a power level.")
            return
        try:
            power = float(power_str)
        except ValueError:
            messagebox.showerror("Invalid Input", "Power must be a number.")
            return

        try:
            drv.set_freq(freq_hz)
            drv.set_power(power)
            self.status_lbl.config(
                text=f"Status: Set {freq_hz/1e6:.3f} MHz / {power} dBm",
                foreground="green")
            _logger.info(f"SigGen: freq={freq_hz} Hz, power={power} dBm")
        except Exception as e:
            messagebox.showerror("Hardware Error", str(e))
            _logger.error(f"SigGen apply settings failed: {e}")

    def _apply_preset(self, freq: float, power: float):
        self.freq_fe.set_hz(freq)
        self.power_var.set(str(power))
        self._apply_settings()

    # ── RF toggle ──────────────────────────────────────────────
    def _toggle_rf(self):
        drv = self._get_driver()
        if drv is None:
            return
        new_state = "OFF" if self.rf_state_var.get() == "ON" else "ON"
        try:
            drv.rf_on(new_state == "ON")
            self.rf_state_var.set(new_state)
            self.rf_btn.config(text=f"RF {new_state}")
            color = "green" if new_state == "ON" else "red"
            self.rf_status_lbl.config(text=f"RF is {new_state}", foreground=color)
            self.status_lbl.config(text=f"Status: RF {new_state}", foreground=color)
            _logger.info(f"SigGen RF {new_state}")
        except Exception as e:
            messagebox.showerror("Hardware Error", str(e))
            _logger.error(f"SigGen RF toggle failed: {e}")

    # ── Waveform management ────────────────────────────────────
    def _upload_waveform(self):
        drv = self._get_driver()
        if drv is None:
            return
        filepath = filedialog.askopenfilename(
            title="Select Waveform File",
            filetypes=[("Waveform files", "*.wv *.iq *.bin"),
                       ("All files", "*.*")])
        if not filepath:
            return
        try:
            drv.upload_waveform(filepath)
            self.status_lbl.config(
                text=f"Status: Uploaded {filepath.split('/')[-1]}",
                foreground="green")
            _logger.info(f"SigGen uploaded waveform: {filepath}")
            self._refresh_waveforms()
        except Exception as e:
            messagebox.showerror("Upload Error", str(e))
            _logger.error(f"SigGen waveform upload failed: {e}")

    def _refresh_waveforms(self):
        drv = self._get_driver()
        if drv is None:
            return
        try:
            waveforms = drv.list_waveforms() if hasattr(drv, "list_waveforms") else []
            self.waveform_list.delete(0, tk.END)
            for wf in waveforms:
                self.waveform_list.insert(tk.END, wf)
            self.status_lbl.config(
                text=f"Status: {len(waveforms)} waveform(s) on device",
                foreground="green")
            _logger.info(f"SigGen waveform list refreshed: {len(waveforms)} items")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            _logger.error(f"SigGen waveform list failed: {e}")

    def _select_waveform(self):
        drv = self._get_driver()
        if drv is None:
            return
        sel = self.waveform_list.curselection()
        if not sel:
            messagebox.showwarning("No Selection", "Select a waveform from the list.")
            return
        wf_name = self.waveform_list.get(sel[0])
        try:
            drv.set_waveform(wf_name)
            self.selected_wf_lbl.config(
                text=f"Selected: {wf_name}", foreground="green")
            self.status_lbl.config(
                text=f"Status: Waveform set to {wf_name}", foreground="green")
            _logger.info(f"SigGen waveform selected: {wf_name}")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            _logger.error(f"SigGen set waveform failed: {e}")

    def _delete_waveform(self):
        drv = self._get_driver()
        if drv is None:
            return
        sel = self.waveform_list.curselection()
        if not sel:
            messagebox.showwarning("No Selection", "Select a waveform to delete.")
            return
        wf_name = self.waveform_list.get(sel[0])
        if not messagebox.askyesno("Confirm Delete",
                                   f"Delete waveform '{wf_name}' from device?"):
            return
        try:
            if hasattr(drv, "delete_waveform"):
                drv.delete_waveform(wf_name)
            self.waveform_list.delete(sel[0])
            self.status_lbl.config(
                text=f"Status: Deleted {wf_name}", foreground="gray")
            _logger.info(f"SigGen waveform deleted: {wf_name}")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            _logger.error(f"SigGen delete waveform failed: {e}")

    # ── get_settings / load_settings (sequencer + profiles) ───
    def get_settings(self) -> dict:
        return {
            "freq_hz":    self.freq_fe.get_hz(),
            "power_dbm":  self.power_var.get(),
            "modulation": self.mod_var.get(),
            "rf_on":      self.rf_state_var.get() == "ON",
            "waveform":   self.selected_wf_lbl.cget("text").replace("Selected: ", ""),
        }

    def load_settings(self, settings: dict):
        if settings.get("freq_hz"):
            self.freq_fe.set_hz(float(settings["freq_hz"]))
        self.power_var.set(settings.get("power_dbm", ""))
        self.mod_var.set(settings.get("modulation", ""))
        rf = settings.get("rf_on", False)
        self.rf_state_var.set("ON" if rf else "OFF")
        self.selected_wf_lbl.config(
            text=f"Selected: {settings.get('waveform', 'None')}")
