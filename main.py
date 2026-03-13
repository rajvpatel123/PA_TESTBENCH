# main.py - POLISHED SHELL VERSION

import tkinter as tk
from tkinter import ttk
import json
import os

# ── Set matplotlib backend ONCE before any tab imports ────────
import matplotlib
matplotlib.use("TkAgg")

from utils.logger import get_logger
from utils.ui_theme import apply_app_theme, APP_COLORS

from tabs.device_info_tab import DeviceInfoTab
from tabs.power_supply_tab import PowerSupplyTab
from tabs.signal_generator_tab import SignalGeneratorTab
from tabs.spectrum_analyzer_tab import SpectrumAnalyzerTab
from tabs.sequencer_tab import SequencerTab
from tabs.dmm_tab import DMMTab
from tabs.ramp_editor_tab import RampEditorTab
from tabs.results_viewer_tab import ResultsViewerTab
from tabs.sweep_plan_tab import SweepPlanTab

_logger = get_logger(__name__)

PROFILES_FILE = "test_profiles.json"
ALIASES_FILE = "instrument_aliases.json"


def load_profiles() -> dict:
    if os.path.exists(PROFILES_FILE):
        try:
            with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_profiles(profiles: dict):
    try:
        with open(PROFILES_FILE, "w", encoding="utf-8") as f:
            json.dump(profiles, f, indent=2)
    except Exception as e:
        _logger.error(f"Failed to save profiles: {e}")


def load_aliases() -> dict:
    if os.path.exists(ALIASES_FILE):
        try:
            with open(ALIASES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


class AxiroTestBenchApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Axiro PA Testbench")
        self.root.geometry("1380x860")
        self.root.minsize(1180, 760)

        apply_app_theme(self.root)

        self.profiles = load_profiles()
        self.aliases = load_aliases()
        self.driver_registry = {}

        self._build_shell()
        self._build_tabs()
        self._wire_tabs()
        self._set_shell_status("Ready", tone="muted")

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Shell ──────────────────────────────────────────────────
    def _build_shell(self):
        self.shell = ttk.Frame(self.root)
        self.shell.pack(fill="both", expand=True)

        # Header bar
        self.header = tk.Frame(
            self.shell,
            bg=APP_COLORS["header"],
            height=64,
            highlightthickness=0,
            bd=0,
        )
        self.header.pack(fill="x")
        self.header.pack_propagate(False)

        left = tk.Frame(self.header, bg=APP_COLORS["header"])
        left.pack(side="left", fill="y", padx=16)

        tk.Label(
            left,
            text="Axiro PA Testbench",
            bg=APP_COLORS["header"],
            fg="white",
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w", pady=(10, 0))

        tk.Label(
            left,
            text="",
            bg=APP_COLORS["header"],
            fg="#CBD5E1",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(2, 10))

        right = tk.Frame(self.header, bg=APP_COLORS["header"])
        right.pack(side="right", fill="y", padx=16)

        self.header_conn_var = tk.StringVar(value="Connected: 0")
        self.header_status_var = tk.StringVar(value="Idle")

        tk.Label(
            right,
            textvariable=self.header_conn_var,
            bg=APP_COLORS["header"],
            fg="white",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="e", pady=(12, 0))

        tk.Label(
            right,
            textvariable=self.header_status_var,
            bg=APP_COLORS["header"],
            fg="#CBD5E1",
            font=("Segoe UI", 9),
        ).pack(anchor="e", pady=(2, 10))

        # Content area
        self.content = ttk.Frame(self.shell)
        self.content.pack(fill="both", expand=True, padx=10, pady=10)

        self.notebook = ttk.Notebook(self.content)
        self.notebook.pack(fill="both", expand=True)

        # Footer
        self.footer = tk.Frame(
            self.shell,
            bg="#E5E7EB",
            height=28,
            highlightthickness=0,
            bd=0,
        )
        self.footer.pack(fill="x", side="bottom")
        self.footer.pack_propagate(False)

        self.footer_status_var = tk.StringVar(value="Ready")
        self.footer_status_lbl = tk.Label(
            self.footer,
            textvariable=self.footer_status_var,
            bg="#E5E7EB",
            fg="#475569",
            font=("Segoe UI", 9),
            anchor="w",
        )
        self.footer_status_lbl.pack(fill="x", padx=12, pady=4)

    # ── Tabs ───────────────────────────────────────────────────
    def _build_tabs(self):
        self.device_tab = DeviceInfoTab(self.notebook)
        self.power_tab = PowerSupplyTab(self.notebook, self.driver_registry)
        self.siggen_tab = SignalGeneratorTab(self.notebook, self.driver_registry)
        self.specan_tab = SpectrumAnalyzerTab(self.notebook, self.driver_registry)
        self.seq_tab = SequencerTab(self.notebook, self.driver_registry, self.profiles, save_profiles)
        self.dmm_tab = DMMTab(self.notebook, self.driver_registry)
        self.ramp_tab = RampEditorTab(self.notebook)
        self.sweep_tab = SweepPlanTab(self.notebook, self.driver_registry)
        self.results_tab = ResultsViewerTab(self.notebook)

        self.notebook.add(self.device_tab, text=" Device Manager ")
        self.notebook.add(self.power_tab, text=" Power Supplies ")
        self.notebook.add(self.siggen_tab, text=" Signal Generator ")
        self.notebook.add(self.specan_tab, text=" Spectrum Analyzer ")
        self.notebook.add(self.seq_tab, text=" Sequencer ")
        self.notebook.add(self.dmm_tab, text=" DMMs ")
        self.notebook.add(self.ramp_tab, text=" Ramp Editor ")
        self.notebook.add(self.sweep_tab, text=" Sweep Plan ")
        self.notebook.add(self.results_tab, text=" Results ")

    def _wire_tabs(self):
        # Push aliases immediately so dropdowns populate on first load
        self.sweep_tab.set_aliases(self.aliases)

        # Wire ramp/results refs to sweep plan
        self.sweep_tab.set_ramp_tab_ref(self.ramp_tab)
        self.sweep_tab.set_results_tab_ref(self.results_tab)

        def on_drivers_updated(registry: dict):
            self.driver_registry.clear()
            self.driver_registry.update(registry)

            self.power_tab.set_driver_registry(self.driver_registry)
            self.siggen_tab.set_driver_registry(self.driver_registry)
            self.specan_tab.set_driver_registry(self.driver_registry)
            self.seq_tab.set_driver_registry(self.driver_registry)
            self.dmm_tab.set_driver_registry(self.driver_registry)
            self.sweep_tab.set_driver_registry(self.driver_registry)

            self.sweep_tab.set_results_tab_ref(self.results_tab)

            # Re-push aliases with live connection status after connecting
            alias_map = getattr(self.device_tab, "_alias_map", self.aliases)
            self.sweep_tab.set_aliases(alias_map)
            self.power_tab.set_aliases(alias_map)

            self._refresh_header_counts()
            self._set_shell_status(
                f"Driver registry updated: {len(self.driver_registry)} connected",
                tone="info",
            )
            _logger.info(f"Driver registry updated: {list(registry.keys())}")

        # Compatibility with either callback name
        if hasattr(self.device_tab, "register_driver_callback"):
            self.device_tab.register_driver_callback(on_drivers_updated)
        else:
            self.device_tab.set_driver_update_callback(on_drivers_updated)

        # Keep old main wiring behavior
        if hasattr(self.device_tab, "set_driver_registry"):
            self.device_tab.set_driver_registry(self.driver_registry)

        self.seq_tab.set_tab_refs(self.power_tab, self.siggen_tab, self.specan_tab)
        self.seq_tab.set_ramp_editor(self.ramp_tab)
        self.seq_tab.set_dmm_tab_ref(self.dmm_tab)
        self.seq_tab.set_sweep_plan_tab_ref(self.sweep_tab)
        self.seq_tab.set_results_tab_ref(self.results_tab)

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self._refresh_header_counts()

    # ── Header / footer helpers ────────────────────────────────
    def _refresh_header_counts(self):
        connected = len(self.driver_registry)
        self.header_conn_var.set(f"Connected: {connected}")

    def _set_shell_status(self, text: str, tone: str = "muted"):
        self.footer_status_var.set(text)
        self.header_status_var.set(text)

        color_map = {
            "muted": "#475569",
            "success": "#166534",
            "warning": "#92400E",
            "danger": "#991B1B",
            "info": "#0F766E",
        }
        self.footer_status_lbl.config(fg=color_map.get(tone, "#475569"))

    def _on_tab_changed(self, _event=None):
        try:
            current = self.notebook.tab(self.notebook.select(), "text").strip()
            self._set_shell_status(f"Viewing: {current}", tone="muted")
        except Exception:
            pass

    # ── Shutdown ───────────────────────────────────────────────
    def _on_close(self):
        try:
            self.dmm_tab.stop_polling()
        except Exception:
            pass

        try:
            self.power_tab.stop_polling()
        except Exception:
            pass

        try:
            self.specan_tab.stop_live()
        except Exception:
            pass

        self.root.destroy()


def main():
    root = tk.Tk()
    app = AxiroTestBenchApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()