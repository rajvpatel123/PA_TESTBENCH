# utils/logger.py - COMPLETE FILE
import os
import json
import csv
import threading
import datetime
import logging
from pathlib import Path
from typing import Optional, Callable

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
_log_filename = LOG_DIR / f"axiro_testbench_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler(_log_filename),
        logging.StreamHandler()
    ]
)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


class Logger:
    """
    Thread-safe session logger for Axiro PA Testbench.

    CSV columns:
        Timestamp, Instrument, Channel,
        Gate_V(V), Drain_V(V), Gate_A(A), Drain_A(A),
        Voltage(V), Current(A),
        Frequency(Hz), Power(dBm),
        Pin_dBm, Pout_dBm, Gain_dB,
        PDC_W, PAE_%,
        Notes
    """

    CSV_HEADERS = [
        "Timestamp", "Instrument", "Channel",
        "Gate_V(V)", "Drain_V(V)", "Gate_A(A)", "Drain_A(A)",
        "Voltage(V)", "Current(A)",
        "Frequency(Hz)", "Power(dBm)",
        "Pin_dBm", "Pout_dBm", "Gain_dB",
        "PDC_W", "PAE_%",
        "Notes",
    ]

    def __init__(self, base_dir: str = "session_logs"):
        self.base_dir            = base_dir
        self.active              = False
        self.lock                = threading.Lock()
        self.log_dir: Optional[str]  = None
        self.data_file           = None
        self.csv_writer          = None
        self._on_stop: Optional[Callable[[str], None]] = None

    # ── Callback registration ──────────────────────────────────
    def set_on_stop_callback(self, callback: Callable[[str], None]):
        """
        Register a function to call when a session ends.
        Receives the session log directory path as its argument.
        Used by ResultsViewerTab to auto-refresh after a test.
        """
        self._on_stop = callback

    def get_latest_session_dir(self) -> Optional[str]:
        """Returns the most recently started session directory, or None."""
        return self.log_dir

    # ── Session lifecycle ──────────────────────────────────────
    def start(self, metadata: Optional[dict] = None):
        """
        Start a new session. If one is already active, stop it cleanly first
        so back-to-back runs don't share a log file.
        """
        if self.active:
            self.stop()

        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.log_dir = os.path.join(self.base_dir, ts)
        os.makedirs(self.log_dir, exist_ok=True)

        if metadata:
            with open(os.path.join(self.log_dir, "metadata.json"), "w") as f:
                json.dump(metadata, f, indent=2)

        self.data_file  = open(
            os.path.join(self.log_dir, "data.csv"), "w", newline="")
        self.csv_writer = csv.writer(self.data_file)
        self.csv_writer.writerow(self.CSV_HEADERS)
        self.data_file.flush()
        self.active = True
        print(f"[LOGGER] Session started -> {self.log_dir}")

    def stop(self):
        """
        Stop the active session. Idempotent — safe to call multiple times.
        Fires the on_stop callback with the session directory path.
        """
        if not self.active:
            return
        self.active = False
        with self.lock:
            if self.data_file:
                try:
                    self.data_file.close()
                except Exception:
                    pass
                self.data_file  = None
                self.csv_writer = None
        print(f"[LOGGER] Session stopped -> {self.log_dir}")

        # Notify Results tab (or anything else) that a session just finished
        if self._on_stop and self.log_dir:
            try:
                self._on_stop(self.log_dir)
            except Exception as e:
                print(f"[LOGGER] on_stop callback error: {e}")

    # ── Data logging ───────────────────────────────────────────
    def log(self,
            instrument,
            channel  = "-",
            gate_v   = "-",
            drain_v  = "-",
            gate_a   = "-",
            drain_a  = "-",
            voltage  = "-",
            current  = "-",
            freq     = "-",
            power    = "-",
            pin_dbm  = "-",
            pout_dbm = "-",
            gain_db  = "-",
            pdc_w    = "-",
            pae_pct  = "-",
            notes    = ""):
        if not self.active:
            return
        with self.lock:
            row = [
                datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3],
                instrument, channel,
                gate_v, drain_v, gate_a, drain_a,
                voltage, current,
                freq, power,
                pin_dbm, pout_dbm, gain_db,
                pdc_w, pae_pct,
                notes,
            ]
            self.csv_writer.writerow(row)
            self.data_file.flush()

    def log_trace(self, frequencies: list, amplitudes: list,
                  notes: str = ""):
        if not self.active:
            return
        with self.lock:
            ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            for freq, amp in zip(frequencies, amplitudes):
                row = [ts, "PXA_N9030A", "-",
                       "-", "-", "-", "-",
                       "-", "-",
                       freq, amp,
                       "-", "-", "-",
                       "-", "-",
                       notes]
                self.csv_writer.writerow(row)
            self.data_file.flush()


session_logger = Logger()
