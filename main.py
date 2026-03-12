# main.py - COMPLETE FILE
import tkinter as tk
from tkinter import ttk
import json
import os

# ── Set matplotlib backend ONCE before any tab imports ────────
import matplotlib
matplotlib.use("TkAgg")

from utils.logger import get_logger

_logger = get_logger(__name__)

PROFILES_FILE = "test_profiles.json"
ALIASES_FILE  = "instrument_aliases.json"


def load_profiles() -> dict:
    if os.path.exists(PROFILES_FILE):
        try:
            with open(PROFILES_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_profiles(profiles: dict):
    try:
        with open(PROFILES_FILE, "w") as f:
            json.dump(profiles, f, indent=2)
    except Exception as e:
        _logger.error(f"Failed to save profiles: {e}")


def load_aliases() -> dict:
    if os.path.exists(ALIASES_FILE):
        try:
            with open(ALIASES_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


from tabs.device_info_tab       import DeviceInfoTab
from tabs.power_supply_tab      import PowerSupplyTab
from tabs.signal_generator_tab  import SignalGeneratorTab
from tabs.spectrum_analyzer_tab import SpectrumAnalyzerTab
from tabs.sequencer_tab         import SequencerTab
from tabs.dmm_tab               import DMMTab
from tabs.ramp_editor_tab       import RampEditorTab
from tabs.results_viewer_tab    import ResultsViewerTab
from tabs.sweep_plan_tab        import SweepPlanTab


def main():
    root = tk.Tk()
    root.title("Axiro PA Testbench")
    root.geometry("1280x800")
    root.minsize(1100, 700)

    style = ttk.Style()
    style.theme_use("clam")

    profiles        = load_profiles()
    aliases         = load_aliases()
    driver_registry = {}

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=5, pady=5)

    device_tab  = DeviceInfoTab(notebook)
    power_tab   = PowerSupplyTab(notebook, driver_registry)
    siggen_tab  = SignalGeneratorTab(notebook, driver_registry)
    specan_tab  = SpectrumAnalyzerTab(notebook, driver_registry)
    seq_tab     = SequencerTab(notebook, driver_registry, profiles, save_profiles)
    dmm_tab     = DMMTab(notebook, driver_registry)
    ramp_tab    = RampEditorTab(notebook)
    sweep_tab   = SweepPlanTab(notebook, driver_registry)
    results_tab = ResultsViewerTab(notebook)

    notebook.add(device_tab,  text="  Device Manager  ")
    notebook.add(power_tab,   text="  Power Supplies  ")
    notebook.add(siggen_tab,  text="  Signal Generator  ")
    notebook.add(specan_tab,  text="  Spectrum Analyzer  ")
    notebook.add(seq_tab,     text="  Sequencer  ")
    notebook.add(dmm_tab,     text="  DMMs  ")
    notebook.add(ramp_tab,    text="  Ramp Editor  ")
    notebook.add(sweep_tab,   text="  Sweep Plan  ")
    notebook.add(results_tab, text="  Results  ")

    # Push aliases immediately so dropdown is populated on first load
    sweep_tab.set_aliases(aliases)

    # Wire ramp and results refs to sweep plan
    sweep_tab.set_ramp_tab_ref(ramp_tab)
    sweep_tab.set_results_tab_ref(results_tab)

    def on_drivers_updated(registry: dict):
        driver_registry.update(registry)
        power_tab.set_driver_registry(driver_registry)
        siggen_tab.set_driver_registry(driver_registry)
        specan_tab.set_driver_registry(driver_registry)
        seq_tab.set_driver_registry(driver_registry)
        dmm_tab.set_driver_registry(driver_registry)
        sweep_tab.set_driver_registry(driver_registry)
        sweep_tab.set_results_tab_ref(results_tab)

        # Re-push aliases with live connection status after connecting
        sweep_tab.set_aliases(device_tab._alias_map)

        # Push aliases to PSU tab after connect
        power_tab.set_aliases(device_tab._alias_map)

        _logger.info(f"Driver registry updated: {list(registry.keys())}")

    device_tab.register_driver_callback(on_drivers_updated)
    device_tab.set_driver_registry(driver_registry)

    seq_tab.set_tab_refs(power_tab, siggen_tab, specan_tab)
    seq_tab.set_ramp_editor(ramp_tab)
    seq_tab.set_dmm_tab_ref(dmm_tab)
    seq_tab.set_sweep_plan_tab_ref(sweep_tab)
    seq_tab.set_results_tab_ref(results_tab)

    root.protocol("WM_DELETE_WINDOW",
                  lambda: [dmm_tab.stop_polling(),
                           power_tab.stop_polling(),
                           specan_tab.stop_live(),
                           root.destroy()])

    root.mainloop()


if __name__ == "__main__":
    main()
