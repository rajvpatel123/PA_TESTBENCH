# drivers/hp_6633b.py - COMPLETE FILE
"""
Driver for HP 6633B power supply (GPIB) — single channel.
Channel argument accepted but ignored to stay compatible
with the multi-channel calling convention in the sequencer.
"""

import time
from utils.visa_manager import get_visa_rm
from utils.logger import get_logger


class HP6633BSupply:
    def __init__(self, visa_address: str, name: str = ""):
        self._logger       = get_logger(__name__)
        self._visa_address = visa_address
        self._name         = name or visa_address
        self._inst         = None

        # Safety limits — adjust to your DUT's max ratings
        self.ovp_headroom  = 1.20   # OVP set to 120% of programmed voltage
        self.max_voltage   = 50.0   # hard cap — 6633B max is 50V
        self.max_current   = 2.0    # hard cap — 6633B max is 2A

    def connect(self):
        rm = get_visa_rm()
        self._inst         = rm.open_resource(self._visa_address)
        self._inst.timeout = 5000
        try:
            self._inst.write("*RST")
            time.sleep(0.2)                    # let RST complete before querying
            self._inst.write("OUTP:PROT:CLE")  # clear any latched fault from previous session
            self._inst.write("OUTP OFF")
            idn = self._inst.query("*IDN?").strip()
        except Exception:
            idn = "IDN failed"
        self._logger.info(
            f"Connected HP 6633B '{self._name}' at {self._visa_address}: {idn}")

    def close(self):
        if self._inst is None:
            return
        try:
            self.output_on(False)
            self._inst.close()
            self._logger.info(
                f"Disconnected HP 6633B '{self._name}' at {self._visa_address}")
        finally:
            self._inst = None

    def idn(self) -> str:
        if self._inst is None:
            return "Not connected"
        try:
            return self._inst.query("*IDN?").strip()
        except Exception:
            return "IDN query failed"

    def set_voltage(self, channel_or_volts, volts: float = None):
        """
        Accepts both single-arg (volts) and two-arg (channel, volts) calls.
        Channel is ignored — HP 6633B is single channel.
        Sets OVP to 120% of programmed voltage before applying.
        """
        value = volts if volts is not None else channel_or_volts
        if value > self.max_voltage:
            raise ValueError(
                f"{self._name}: Requested {value}V exceeds max {self.max_voltage}V")
        ovp = min(round(value * self.ovp_headroom, 2), self.max_voltage)
        self._inst.write(f"VOLT:PROT {ovp}")  # set OVP headroom first
        self._inst.write(f"VOLT {value}")
        self._logger.info(f"{self._name} voltage set to {value} V (OVP={ovp} V)")

    def set_current(self, channel_or_amps, amps: float = None):
        """
        Accepts both single-arg (amps) and two-arg (channel, amps) calls.
        Channel is ignored — HP 6633B is single channel.
        """
        value = amps if amps is not None else channel_or_amps
        if value > self.max_current:
            raise ValueError(
                f"{self._name}: Requested {value}A exceeds max {self.max_current}A")
        self._inst.write(f"CURR {value}")
        self._logger.info(f"{self._name} current limit set to {value} A")

    def output_on(self, channel_or_enable, enable: bool = None):
        """
        Accepts both single-arg (enable) and two-arg (channel, enable) calls.
        Channel is ignored — HP 6633B is single channel.
        Clears any latched protection fault before turning ON.
        """
        value = enable if enable is not None else channel_or_enable
        if value:
            self._inst.write("OUTP:PROT:CLE")  # clear latched OVP/OCP before ON
        state = "ON" if value else "OFF"
        self._inst.write(f"OUTP {state}")
        self._logger.info(f"{self._name} output {state}")

    def measure_voltage(self, channel=None) -> float:
        """Read back actual output voltage. Channel arg ignored."""
        self._inst.write("MEAS:VOLT?")
        time.sleep(0.05)                       # 6633B needs ~50 ms to complete
        return float(self._inst.read().strip())

    def measure_current(self, channel=None) -> float:
        """Read back actual output current. Channel arg ignored."""
        self._inst.write("MEAS:CURR?")
        time.sleep(0.05)
        return float(self._inst.read().strip())

    def clear_faults(self):
        """Manually clear any latched OVP / OCP protection faults."""
        self._inst.write("OUTP:PROT:CLE")
        self._logger.info(f"{self._name} protection faults cleared")

    def get_status(self) -> dict:
        """Return a snapshot of key supply status registers."""
        try:
            v   = self.measure_voltage()
            a   = self.measure_current()
            raw = self._inst.query("STAT:QUES:COND?").strip()
            return {"voltage": v, "current": a, "status_reg": raw}
        except Exception as e:
            return {"error": str(e)}
