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
  E36233A  - 2 ch
  E36234A  - 4 ch

Method map vs. reference bench script (psc.Keysight_E36234A):
  setVI(ch, volt, curr)                -> set_vi(ch, volt, curr)
  outOnOff(ch, 0/1)                    -> output_on(ch, bool)
  measCurr(ch)                         -> measure_current(ch)
  measVolt(ch)                         -> measure_voltage(ch)
  setCurrProtectionDelayStartCC(ch)    -> set_ocp_delay_start_cc(ch)
  setCurrProtectionDelay(ch, secs)     -> set_ocp_delay(ch, secs)
  currProtectionOnOff(ch, 1/0)         -> ocp_enable(ch, bool)
  askCurrProtectionTripped()           -> ocp_tripped(ch)
  clrOverCurrProtectionEvent(ch)       -> ocp_clear(ch)
"""
import time
from typing import List, Optional
from utils.visa_manager import get_visa_rm
from utils.logger import get_logger

INTER_CMD_DELAY = 0.02
DEFAULT_TIMEOUT = 10000


class KeysightE36xxSupply:
    def __init__(self, visa_address, name="", channels=2, debug=False):
        self._logger       = get_logger(__name__)
        self._visa_address = visa_address
        self._name         = name or visa_address
        self._inst         = None
        self._channels     = channels
        self._debug        = debug

    # -- Connection -----------------------------------------------
    def connect(self):
        rm = get_visa_rm()
        inst = rm.open_resource(self._visa_address)
        inst.timeout           = DEFAULT_TIMEOUT
        inst.read_termination  = "\n"
        inst.write_termination = "\n"
        inst.send_end          = True
        self._inst = inst
        self._write_raw("*CLS")
        self._write_raw("*RST")
        time.sleep(0.3)
        idn = self._query_raw("*IDN?") or "IDN failed"
        self._logger.info(
            "Connected Keysight E36xx '{}' @ {} ({}ch): {}".format(
                self._name, self._visa_address, self._channels, idn))

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
            self._logger.info("Disconnected Keysight E36xx '{}'".format(self._name))
        finally:
            self._inst = None

    # -- Pass-through helpers (used by device_info_tab) -----------
    def query(self, cmd: str) -> str:
        """Direct SCPI query pass-through (used for *IDN?, *TST? etc)."""
        return self._query_raw(cmd) or ""

    def write(self, cmd: str):
        """Direct SCPI write pass-through (used for *RST, *CLS etc)."""
        self._write_raw(cmd)

    # -- Identification -------------------------------------------
    def idn(self):
        if self._inst is None:
            return "Not connected"
        return self._query_raw("*IDN?") or "IDN query failed"

    # -- Channel selection ----------------------------------------
    def _select_channel(self, channel):
        self._check(channel)
        self._write_raw("INST:NSEL {}".format(channel))

    # -- Combined set ---------------------------------------------
    def set_vi(self, channel, volts, amps):
        """Set voltage and current limit in one call (matches setVI in reference)."""
        self.set_voltage(channel, volts)
        self.set_current(channel, amps)

    def setVI(self, channel, volts, amps):
        self.set_vi(channel, volts, amps)

    # -- Voltage / Current set ------------------------------------
    def set_voltage(self, channel, volts):
        self._select_channel(channel)
        self._write_raw("VOLT {:.6f}".format(volts))
        if self._debug:
            self._check_error("set_voltage CH{}".format(channel))
        self._logger.info("{} CH{} VOLT -> {} V".format(self._name, channel, volts))

    def set_current(self, channel, amps):
        self._select_channel(channel)
        self._write_raw("CURR {:.6f}".format(amps))
        if self._debug:
            self._check_error("set_current CH{}".format(channel))
        self._logger.info("{} CH{} CURR -> {} A".format(self._name, channel, amps))

    def set_ovp(self, channel, volts):
        """Over-Voltage Protection limit."""
        self._select_channel(channel)
        self._write_raw("VOLT:PROT {:.6f}".format(volts))
        if self._debug:
            self._check_error("set_ovp CH{}".format(channel))
        self._logger.info("{} CH{} OVP -> {} V".format(self._name, channel, volts))

    def set_ocp(self, channel, amps):
        """Over-Current Protection limit."""
        self._select_channel(channel)
        self._write_raw("CURR:PROT {:.6f}".format(amps))
        if self._debug:
            self._check_error("set_ocp CH{}".format(channel))
        self._logger.info("{} CH{} OCP -> {} A".format(self._name, channel, amps))

    def output_on(self, channel, enable):
        self._select_channel(channel)
        state = "ON" if enable else "OFF"
        self._write_raw("OUTP {}".format(state))
        if self._debug:
            self._check_error("output_on CH{} {}".format(channel, state))
        self._logger.info("{} CH{} OUTPUT {}".format(self._name, channel, state))

    def outOnOff(self, channel, state):
        self.output_on(channel, bool(state))

    # -- OCP trip delay / enable / query / clear ------------------
    def set_ocp_delay_start_cc(self, channel):
        """SCPI: CURR:PROT:DEL:STAR CC"""
        self._select_channel(channel)
        self._write_raw("CURR:PROT:DEL:STAR CC")
        if self._debug:
            self._check_error("set_ocp_delay_start_cc CH{}".format(channel))
        self._logger.info("{} CH{} OCP delay start -> CC".format(self._name, channel))

    def setCurrProtectionDelayStartCC(self, channel):
        self.set_ocp_delay_start_cc(channel)

    def set_ocp_delay(self, channel, seconds):
        """SCPI: CURR:PROT:DEL {secs}"""
        self._select_channel(channel)
        self._write_raw("CURR:PROT:DEL {:.3f}".format(seconds))
        if self._debug:
            self._check_error("set_ocp_delay CH{}".format(channel))
        self._logger.info("{} CH{} OCP delay -> {} s".format(self._name, channel, seconds))

    def setCurrProtectionDelay(self, channel, seconds):
        self.set_ocp_delay(channel, seconds)

    def ocp_enable(self, channel, enable):
        """SCPI: CURR:PROT:STAT ON|OFF"""
        self._select_channel(channel)
        state = "ON" if enable else "OFF"
        self._write_raw("CURR:PROT:STAT {}".format(state))
        if self._debug:
            self._check_error("ocp_enable CH{} {}".format(channel, state))
        self._logger.info("{} CH{} OCP -> {}".format(self._name, channel, state))

    def currProtectionOnOff(self, channel, state):
        self.ocp_enable(channel, bool(state))

    def ocp_tripped(self, channel):
        """SCPI: CURR:PROT:TRIP?"""
        self._select_channel(channel)
        raw = self._query_raw("CURR:PROT:TRIP?")
        try:
            return bool(int(raw))
        except (TypeError, ValueError):
            self._logger.warning(
                "{} CH{} ocp_tripped: unexpected response '{}'".format(
                    self._name, channel, raw))
            return False

    def askCurrProtectionTripped(self, channel=1):
        return self.ocp_tripped(channel)

    def ocp_clear(self, channel):
        """SCPI: CURR:PROT:CLE"""
        self._select_channel(channel)
        self._write_raw("CURR:PROT:CLE")
        if self._debug:
            self._check_error("ocp_clear CH{}".format(channel))
        self._logger.info("{} CH{} OCP latch cleared".format(self._name, channel))

    def clrOverCurrProtectionEvent(self, channel):
        self.ocp_clear(channel)

    # -- Measure methods ------------------------------------------
    def measure_voltage(self, channel):
        self._select_channel(channel)
        raw = self._query_raw("MEAS:VOLT?")
        return self._parse_float(raw, "measure_voltage CH{}".format(channel))

    def measure_current(self, channel):
        self._select_channel(channel)
        raw = self._query_raw("MEAS:CURR?")
        return self._parse_float(raw, "measure_current CH{}".format(channel))

    def measVolt(self, channel):
        return self.measure_voltage(channel)

    def measCurr(self, channel):
        return self.measure_current(channel)

    def measure_all(self, channel):
        """Return {'volt': float, 'curr': float} in one method call."""
        return {
            "volt": self.measure_voltage(channel),
            "curr": self.measure_current(channel),
        }

    # -- Error / status helpers -----------------------------------
    def check_errors(self):
        # type: () -> List[str]
        """Drain the SCPI error queue; return list of non-zero error strings."""
        errors = []
        if self._inst is None:
            return errors
        for _ in range(20):
            resp = self._query_raw("SYST:ERR?")
            if resp is None or resp.startswith("+0") or resp.startswith("0,"):
                break
            errors.append(resp)
            self._logger.warning("{} SCPI error: {}".format(self._name, resp))
        return errors

    def _check_error(self, context):
        errs = self.check_errors()
        if errs:
            self._logger.error(
                "{} [{}] SCPI errors: {}".format(self._name, context, errs))

    # -- Low-level VISA helpers -----------------------------------
    def _write_raw(self, cmd):
        """Write with inter-command delay."""
        self._ensure_connected()
        self._inst.write(cmd)
        time.sleep(INTER_CMD_DELAY)

    def _query_raw(self, cmd):
        # type: (str) -> Optional[str]
        """Query with inter-command delay; returns stripped string or None."""
        self._ensure_connected()
        try:
            resp = self._inst.query(cmd)
            time.sleep(INTER_CMD_DELAY)
            return resp.strip()
        except Exception as e:
            self._logger.error(
                "{} query '{}' failed: {}".format(self._name, cmd, e))
            return None

    def _parse_float(self, raw, context):
        # type: (Optional[str], str) -> float
        if raw is None:
            raise RuntimeError(
                "{} [{}]: no response from instrument".format(self._name, context))
        try:
            return float(raw)
        except ValueError:
            raise RuntimeError(
                "{} [{}]: cannot parse '{}' as float".format(self._name, context, raw))

    def _ensure_connected(self):
        if self._inst is None:
            raise RuntimeError(
                "{} is not connected. Call connect() first.".format(self._name))

    def _check(self, channel):
        self._ensure_connected()
        if not 1 <= channel <= self._channels:
            raise ValueError(
                "{}: channel must be 1-{}, got {}".format(
                    self._name, self._channels, channel))
