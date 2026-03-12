# drivers/rs_smbv100b.py - COMPLETE FILE
"""
Driver for Rohde & Schwarz SMBV100B signal generator.
"""

import os
from utils.visa_manager import get_visa_rm
from utils.logger import get_logger

# Waveform storage path on the instrument
WAVEFORM_DIR = "/var/user/waveform"


class RSSMBV100B:
    def __init__(self, visa_address: str, name: str = ""):
        self._logger       = get_logger(__name__)
        self._visa_address = visa_address
        self._name         = name or visa_address
        self._inst         = None

    def connect(self):
        rm = get_visa_rm()
        self._inst         = rm.open_resource(self._visa_address)
        self._inst.timeout = 10000   # 10s — waveform ops can be slow
        try:
            self._inst.write("*RST")
            idn = self._inst.query("*IDN?").strip()
        except Exception:
            idn = "IDN failed"
        self._logger.info(
            f"Connected SMBV100B '{self._name}' at {self._visa_address}: {idn}")

    def close(self):
        if self._inst is None:
            return
        try:
            self.rf_on(False)
            self._inst.close()
            self._logger.info(
                f"Disconnected SMBV100B '{self._name}' at {self._visa_address}")
        finally:
            self._inst = None

    def idn(self) -> str:
        if self._inst is None:
            return "Not connected"
        try:
            return self._inst.query("*IDN?").strip()
        except Exception:
            return "IDN query failed"

    # ── RF settings ────────────────────────────────────────────
    def set_freq(self, freq_hz: float):
        self._inst.write(f"SOUR:FREQ {freq_hz}")
        self._logger.info(f"{self._name} frequency set to {freq_hz} Hz")

    def set_power(self, level_dbm: float):
        self._inst.write(f"SOUR:POW:LEV:IMM:AMPL {level_dbm}")
        self._logger.info(f"{self._name} power set to {level_dbm} dBm")

    def rf_on(self, enable: bool):
        state = "ON" if enable else "OFF"
        self._inst.write(f"OUTP:STAT {state}")
        self._logger.info(f"{self._name} RF {state}")

    # ── Waveform management ────────────────────────────────────
    def list_waveforms(self) -> list:
        """
        Query the ARB waveform catalogue from the instrument.
        Returns a list of waveform name strings.
        """
        try:
            # Primary method — ARB catalogue query
            raw = self._inst.query("SOUR:BB:ARB:WAV:CAT?").strip()
            if raw:
                # Response is comma-separated quoted names:
                # "wave1","wave2","wave3"
                names = [n.strip().strip('"') for n in raw.split(",") if n.strip()]
                names = [n for n in names if n]   # drop empty strings
                self._logger.info(
                    f"{self._name} waveform list: {len(names)} waveform(s)")
                return names
        except Exception as e:
            self._logger.warning(
                f"{self._name} ARB CAT query failed, trying MMEM: {e}")

        try:
            # Fallback — file system catalogue of waveform directory
            raw   = self._inst.query(f"MMEM:CAT? '{WAVEFORM_DIR}'").strip()
            names = []
            # MMEM:CAT? response: <used>,<free>,"name,type,size","name,type,size",...
            parts = raw.split(",")
            i = 2   # skip used/free counts
            while i < len(parts):
                entry = parts[i].strip().strip('"')
                if entry.lower().endswith((".wv", ".iq", ".bin")):
                    names.append(entry)
                i += 3  # each entry is name, type, size
            self._logger.info(
                f"{self._name} MMEM waveform list: {len(names)} waveform(s)")
            return names
        except Exception as e:
            self._logger.error(f"{self._name} list_waveforms failed: {e}")
            return []

    def set_waveform(self, name: str):
        """Select a waveform by name and enable ARB mode."""
        # Build full path if not already a path
        if not name.startswith("/"):
            path = f"{WAVEFORM_DIR}/{name}"
        else:
            path = name
        self._inst.write(f'SOUR:BB:ARB:WAV:SEL "{path}"')
        self._inst.write("SOUR:BB:ARB:STAT ON")
        self._logger.info(f"{self._name} waveform selected: {path}")

    def upload_waveform(self, filepath: str):
        """
        Upload a waveform file to the instrument via MMEM:DATA binary transfer.
        Supports .wv, .iq, .bin files.
        """
        filename = os.path.basename(filepath)
        dest     = f"{WAVEFORM_DIR}/{filename}"

        with open(filepath, "rb") as f:
            data = f.read()

        # IEEE 488.2 definite length binary block header
        length_str  = str(len(data))
        header      = f"#{len(length_str)}{length_str}".encode()
        cmd_prefix  = f'MMEM:DATA "{dest}",'.encode()

        # Increase timeout for upload — large files can take several seconds
        old_timeout         = self._inst.timeout
        self._inst.timeout  = 30000
        try:
            self._inst.write_raw(cmd_prefix + header + data)
            # Wait for operation complete
            self._inst.query("*OPC?")
            self._logger.info(
                f"{self._name} uploaded '{filename}' → '{dest}' "
                f"({len(data)} bytes)")
        finally:
            self._inst.timeout = old_timeout

    def delete_waveform(self, name: str):
        """Delete a waveform from instrument storage by name."""
        if not name.startswith("/"):
            path = f"{WAVEFORM_DIR}/{name}"
        else:
            path = name
        self._inst.write(f'MMEM:DEL "{path}"')
        self._logger.info(f"{self._name} deleted waveform: {path}")

    def get_freq_axis(self) -> list:
        """
        Return the frequency axis for the current span/center settings.
        Used by the sequencer to pair with trace data.
        """
        try:
            center = float(self._inst.query("SOUR:FREQ?").strip())
            return [center]   # SigGen is single-frequency, return center
        except Exception:
            return []
