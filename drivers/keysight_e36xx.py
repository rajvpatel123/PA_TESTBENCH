# drivers/keysight_e36xx.py
"""
Driver for Keysight E362xx / E3623x series power supplies.

Channel selection uses INST:NSEL {n} (numeric, 1-based).
Firmware quirks handled:
  - Write *CLS after connect to flush any pending error queue
  - Add explicit read terminator and 10 ms inter-query delay
  - Query SYST:ERR? after each write in debug mode to catch silent failures
  - OUTP is set per channel via INST:NSEL first
  - VOLT:PROT and CURR:PROT use colon form (not VOLT:PROT:LEV)
  - All queries strip trailing whitespace and \r\n

Models:
  E36233A  — 2 ch
  E36234A  — 4 ch

Method map vs. reference bench script (psc.Keysight_E36234A):
  setVI(ch, volt, curr)                → set_vi(ch, volt, curr)
  outOnOff(ch, 0/1)                    → output_on(ch, bool)
  measCurr(ch)                         → measure_current(ch)
  measVolt(ch)                         → measure_voltage(ch)
  setCurrProtectionDelayStartCC(ch)    → set_ocp_delay_start_cc(ch)
  setCurrProtectionDelay(ch, secs)     → set_ocp_delay(ch, secs)
  currProtectionOnOff(ch, 1/0)         → ocp_enable(ch, bool)
  askCurrProtectionTripped()           → ocp_tripped(ch)
  clrOverCurrProtectionEvent(ch)       → ocp_clear(ch)
"""
import time
from utils.visa_manager import get_visa_rm
from utils.logger import get_logger

INTER_CMD_DELAY = 0.02   # seconds between writes and queries
DEFAULT_TIMEOUT = 10000  # ms


class KeysightE36xxSupply:
    def __init__(self, visa_address: str, name: str = "",
                 channels: int = 2, debug: bool = False):
        self._logger       = get_logger(__name__)
        self._visa_address = visa_address
        self._name         = name or visa_address
        self._inst         = None
        self._channels     = channels
        self._debug        = debug

    # ── Connection ──────────────────────────────────────────────
    def connect(self):
        rm = get_visa_rm()
        inst = rm.open_resource(self._visa_address)
        inst.timeout              = DEFAULT_TIMEOUT
        inst.read_termination     = "\n"
        inst.write_termination    = "\n"
        inst.send_end             = True
        self._inst = inst

        # Flush error queue and reset comms state
        self._write_raw("*CLS")
        self._write_raw("*RST")
        time.sleep(0.3)   # let RST settle

        idn = self._query_raw("*IDN?") or "IDN failed"
        self._logger.info(
            f"Connected Keysight E36xx '{self._name}' "
            f"@ {self._visa_address} ({self._channels}ch): {idn}")

    def close(self):
        if self._inst is None:
            return
        try:
            for ch in range(1, self._channels + 1):
                try:
                    self.output_on(ch, False)
                except Exception:
                    pass
            self._inst.close()
            self._logger.info(f"Disconnected Keysight E36xx '{self._name}'")
        finally:
            self._inst = None

    # ── Identification ──────────────────────────────────────────
    def idn(self) -> str:
        if self._inst is None:
            return "Not connected"
        return self._query_raw("*IDN?") or "IDN query failed"

    # ── Channel selection ───────────────────────────────────────
    def _select_channel(self, channel: int):
        """
        Select output channel by numeric index.
        INST:NSEL is the correct form for E362xx (not INST:SEL OUT{n}).
        """
        self._check(channel)
        self._write_raw(f"INST:NSEL {channel}")

    # ── Combined set (matches reference setVI) ────────────────────
    def set_vi(self, channel: int, volts: float, amps: float):
        """Set voltage and current limit in one call (matches setVI in reference)."""
        self.set_voltage(channel, volts)
        self.set_current(channel, amps)

    # Alias for backwards compat with any code still using setVI
    def setVI(self, channel: int, volts: float, amps: float):
        self.set_vi(channel, volts, amps)

    # ── Voltage / Current set ──────────────────────────────────
    def set_voltage(self, channel: int, volts: float):
        self._select_channel(channel)
        self._write_raw(f"VOLT {volts:.6f}")
        if self._debug:
            self._check_error(f"set_voltage CH{channel}")
        self._logger.info(f"{self._name} CH{channel} VOLT → {volts} V")

    def set_current(self, channel: int, amps: float):
        self._select_channel(channel)
        self._write_raw(f"CURR {amps:.6f}")
        if self._debug:
            self._check_error(f"set_current CH{channel}")
        self._logger.info(f"{self._name} CH{channel} CURR → {amps} A")

    def set_ovp(self, channel: int, volts: float):
        """Over-Voltage Protection limit."""
        self._select_channel(channel)
        self._write_raw(f"VOLT:PROT {volts:.6f}")
        if self._debug:
            self._check_error(f"set_ovp CH{channel}")
        self._logger.info(f"{self._name} CH{channel} OVP → {volts} V")

    def set_ocp(self, channel: int, amps: float):
        """Over-Current Protection limit."""
        self._select_channel(channel)
        self._write_raw(f"CURR:PROT {amps:.6f}")
        if self._debug:
            self._check_error(f"set_ocp CH{channel}")
        self._logger.info(f"{self._name} CH{channel} OCP → {amps} A")

    def output_on(self, channel: int, enable: bool):
        self._select_channel(channel)
        state = "ON" if enable else "OFF"
        self._write_raw(f"OUTP {state}")
        if self._debug:
            self._check_error(f"output_on CH{channel} {state}")
        self._logger.info(f"{self._name} CH{channel} OUTPUT {state}")

    # Alias to match reference outOnOff(ch, 0/1)
    def outOnOff(self, channel: int, state):
        self.output_on(channel, bool(state))

    # ── OCP trip delay / enable / query / clear ───────────────────
    def set_ocp_delay_start_cc(self, channel: int):
        """
        Configure OCP delay to start when the supply enters CC mode.
        Matches setCurrProtectionDelayStartCC() in reference.
        SCPI: CURR:PROT:DEL:STAR CC
        """
        self._select_channel(channel)
        self._write_raw("CURR:PROT:DEL:STAR CC")
        if self._debug:
            self._check_error(f"set_ocp_delay_start_cc CH{channel}")
        self._logger.info(f"{self._name} CH{channel} OCP delay start → CC")

    # Alias to match reference
    def setCurrProtectionDelayStartCC(self, channel: int):
        self.set_ocp_delay_start_cc(channel)

    def set_ocp_delay(self, channel: int, seconds: float):
        """
        Set OCP trip delay in seconds.
        Matches setCurrProtectionDelay(ch, secs) in reference.
        SCPI: CURR:PROT:DEL {secs}
        """
        self._select_channel(channel)
        self._write_raw(f"CURR:PROT:DEL {seconds:.3f}")
        if self._debug:
            self._check_error(f"set_ocp_delay CH{channel}")
        self._logger.info(f"{self._name} CH{channel} OCP delay → {seconds} s")

    # Alias to match reference
    def setCurrProtectionDelay(self, channel: int, seconds: float):
        self.set_ocp_delay(channel, seconds)

    def ocp_enable(self, channel: int, enable: bool):
        """
        Enable or disable Over-Current Protection.
        Matches currProtectionOnOff(ch, 1/0) in reference.
        SCPI: CURR:PROT:STAT ON|OFF
        """
        self._select_channel(channel)
        state = "ON" if enable else "OFF"
        self._write_raw(f"CURR:PROT:STAT {state}")
        if self._debug:
            self._check_error(f"ocp_enable CH{channel} {state}")
        self._logger.info(f"{self._name} CH{channel} OCP → {state}")

    # Alias to match reference
    def currProtectionOnOff(self, channel: int, state):
        self.ocp_enable(channel, bool(state))

    def ocp_tripped(self, channel: int) -> bool:
        """
        Returns True if OCP has tripped on the given channel.
        Matches askCurrProtectionTripped() in reference.
        SCPI: CURR:PROT:TRIP?
        """
        self._select_channel(channel)
        raw = self._query_raw("CURR:PROT:TRIP?")
        try:
            return bool(int(raw))
        except (TypeError, ValueError):
            self._logger.warning(
                f"{self._name} CH{channel} ocp_tripped: unexpected response '{raw}'")
            return False

    def askCurrProtectionTripped(self, channel: int = 1) -> bool:
        """Alias to match reference (reference calls without channel arg on ps1)."""
        return self.ocp_tripped(channel)

    def ocp_clear(self, channel: int):
        """
        Clear OCP trip latch on the given channel.
        Matches clrOverCurrProtectionEvent(ch) in reference.
        SCPI: CURR:PROT:CLE
        """
        self._select_channel(channel)
        self._write_raw("CURR:PROT:CLE")
        if self._debug:
            self._check_error(f"ocp_clear CH{channel}")
        self._logger.info(f"{self._name} CH{channel} OCP latch cleared")

    # Alias to match reference
    def clrOverCurrProtectionEvent(self, channel: int):
        self.ocp_clear(channel)

    # ── Measure methods ────────────────────────────────────────
    def measure_voltage(self, channel: int) -> float:
        self._select_channel(channel)
        raw = self._query_raw("MEAS:VOLT?")
        return self._parse_float(raw, f"measure_voltage CH{channel}")

    def measure_current(self, channel: int) -> float:
        self._select_channel(channel)
        raw = self._query_raw("MEAS:CURR?")
        return self._parse_float(raw, f"measure_current CH{channel}")

    # Aliases to match reference measVolt / measCurr
    def measVolt(self, channel: int) -> float:
        return self.measure_voltage(channel)

    def measCurr(self, channel: int) -> float:
        return self.measure_current(channel)

    def measure_all(self, channel: int) -> dict:
        """Return {'volt': float, 'curr': float} in one method call."""
        return {
            "volt": self.measure_voltage(channel),
            "curr": self.measure_current(channel),
        }

    # ── Error / status helpers ──────────────────────────────────
    def check_errors(self) -> list[str]:
        """Drain the SCPI error queue; return list of non-zero error strings."""
        errors = []
        if self._inst is None:
            return errors
        for _ in range(20):   # max 20 errors in queue
            resp = self._query_raw("SYST:ERR?")
            if resp is None or resp.startswith("+0") or resp.startswith("0,"):
                break
            errors.append(resp)
            self._logger.warning(f"{self._name} SCPI error: {resp}")
        return errors

    def _check_error(self, context: str):
        errs = self.check_errors()
        if errs:
            self._logger.error(
                f"{self._name} [{context}] SCPI errors: {errs}")

    # ── Low-level VISA helpers ─────────────────────────────────
    def _write_raw(self, cmd: str):
        """Write with inter-command delay."""
        self._ensure_connected()
        self._inst.write(cmd)
        time.sleep(INTER_CMD_DELAY)

    def _query_raw(self, cmd: str) -> str | None:
        """Query with inter-command delay; returns stripped string or None."""
        self._ensure_connected()
        try:
            resp = self._inst.query(cmd)
            time.sleep(INTER_CMD_DELAY)
            return resp.strip()
        except Exception as e:
            self._logger.error(
                f"{self._name} query '{cmd}' failed: {e}")
            return None

    def _parse_float(self, raw: str | None, context: str) -> float:
        if raw is None:
            raise RuntimeError(
                f"{self._name} [{context}]: no response from instrument")
        try:
            return float(raw)
        except ValueError:
            raise RuntimeError(
                f"{self._name} [{context}]: cannot parse '{raw}' as float")

    def _ensure_connected(self):
        if self._inst is None:
            raise RuntimeError(
                f"{self._name} is not connected. Call connect() first.")

    def _check(self, channel: int):
        self._ensure_connected()
        if not 1 <= channel <= self._channels:
            raise ValueError(
                f"{self._name}: channel must be 1–{self._channels}, got {channel}")
