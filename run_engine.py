# engine/run_engine.py - COMPLETE FILE
import threading
import csv
import time
import re
from datetime import datetime
from utils.logger import get_logger

_logger = get_logger(__name__)


def parse_channel(channel_str: str):
    """Extract device name and channel number from a channel dropdown string.
    Handles formats like:
      'Gate Driver  [AgilentE3648AGPIB15]  CH1'
      'AgilentE3648AGPIB15  CH1 (not connected)'
    Returns (device_name, channel_int) or (None, None).
    """
    m = re.search(r'\[(.+?)\].*?CH(\d+)', channel_str)
    if m:
        return m.group(1).strip(), int(m.group(2))
    m = re.search(r'^([^\s].+?)\s+CH(\d+)', channel_str)
    if m:
        return m.group(1).strip(), int(m.group(2))
    return None, None


class RunEngine:
    def __init__(self, driver_registry: dict, ramp_tab=None,
                 on_complete=None, on_step=None, on_error=None):
        self._drivers     = driver_registry
        self._ramp_tab    = ramp_tab
        self._on_complete = on_complete
        self._on_step     = on_step
        self._on_error    = on_error
        self._stop_event  = threading.Event()
        self._thread      = None

    # ── Public API ──────────────────────────────────────────────────

    def start(self, sweep_plan: list, output_csv: str):
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(sweep_plan, output_csv),
            daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()

    # ── Internal ────────────────────────────────────────────────────

    def _run(self, sweep_plan: list, output_csv: str):
        results = []
        try:
            for i, step in enumerate(sweep_plan):
                if self._stop_event.is_set():
                    break
                if self._on_step:
                    self._on_step(i, "running")
                try:
                    row = self._execute_step(step, i)
                    if row:
                        results.append(row)
                    if self._on_step:
                        self._on_step(i, "done")
                except Exception as e:
                    if self._on_step:
                        self._on_step(i, "error")
                    if self._on_error:
                        self._on_error(f"Step {i+1}: {str(e)}")
                    break
            self._write_csv(results, output_csv)
        except Exception as e:
            if self._on_error:
                self._on_error(str(e))
        finally:
            if self._on_complete:
                self._on_complete()

    def _execute_step(self, step: dict, index: int) -> dict:
        cmd    = step.get("command", "")
        params = step.get("params", {})
        ts     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row    = {"step": index + 1, "command": cmd, "timestamp": ts}

        if cmd == "SET_BIAS":
            self._set_bias(params, row)

        elif cmd == "OUTPUT_ON":
            self._set_output(params, True, row)

        elif cmd == "OUTPUT_OFF":
            self._set_output(params, False, row)

        elif cmd == "RAMP":
            self._execute_ramp(params, row)

        elif cmd == "MEASURE":
            self._measure(params, row)

        elif cmd == "POWER_SWEEP":
            self._power_sweep(params, row)

        elif cmd == "WAIT":
            time.sleep(params.get("seconds", 1.0))

        elif cmd == "SCPI_COMMAND":
            self._execute_scpi_command(params, row)

        elif cmd == "SCPI_POLL":
            self._execute_scpi_poll(params, row)

        elif cmd == "SAVE_RESULTS":
            pass  # handled at end of run

        return row

    # ── Bias / Output ───────────────────────────────────────────────

    def _set_bias(self, params: dict, row: dict):
        ch_str  = params.get("channel", "")
        mode    = params.get("mode", "CV")
        dev, ch = parse_channel(ch_str)
        drv     = self._drivers.get(dev) if dev else None

        if drv is None:
            row["error"] = f"Driver not found for: {ch_str}"
            return

        try:
            if mode == "CV":
                drv.set_voltage(ch, params["voltage"])
                drv.set_current(ch, params["ocp"])
            else:
                drv.set_current(ch, params["current"])
                drv.set_voltage(ch, params.get("ovp", 35.0))

            drv.output_on(ch, True)
            row["channel"] = ch_str
            row["mode"]    = mode

            target_ma = params.get("target_idq_ma")
            if target_ma:
                self._idq_target(drv, ch, params, row)

        except Exception as e:
            row["error"] = str(e)

    def _idq_target(self, drain_drv, drain_ch: int, params: dict, row: dict):
        target   = params["target_idq_ma"]
        tol      = params.get("tolerance_ma", 5.0)
        step_mv  = params.get("gate_step_mv", 50.0) / 1000.0
        abort_ma = params.get("hard_abort_ma") or target * 3

        gate_str  = params.get("gate_channel", "")
        gdev, gch = parse_channel(gate_str)
        gate_drv  = self._drivers.get(gdev) if gdev else None
        if gate_drv is None:
            row["idq_error"] = "Gate driver not found for Idq targeting"
            return

        current_vg = float(params.get("voltage", -3.0))
        for _ in range(100):
            if self._stop_event.is_set():
                break
            try:
                idq = drain_drv.measure_current(drain_ch) * 1000
            except Exception:
                break
            row["idq_ma"] = round(idq, 3)
            if idq > abort_ma:
                row["idq_error"] = f"Hard abort: Idq {idq:.1f} mA > {abort_ma} mA"
                break
            if abs(idq - target) <= tol:
                break
            direction  = 1 if idq < target else -1
            current_vg += direction * step_mv
            try:
                gate_drv.set_voltage(gch, current_vg)
            except Exception:
                break
            time.sleep(0.1)

    def _set_output(self, params: dict, state: bool, row: dict):
        ch_str  = params.get("channel", "")
        dev, ch = parse_channel(ch_str)
        drv     = self._drivers.get(dev) if dev else None
        if drv is None:
            row["error"] = f"Driver not found for: {ch_str}"
            return
        try:
            drv.output_on(ch, state)
            row["channel"] = ch_str
            row["output"]  = "ON" if state else "OFF"
        except Exception as e:
            row["error"] = str(e)

    # ── Ramp ────────────────────────────────────────────────────────

    def _execute_ramp(self, params: dict, row: dict):
        """
        Execute ramp steps. When using the ramp editor, steps come back with
        a 'supply' role ("Gate" / "Drain") which is resolved to a driver via
        _resolve_supply_role(). Manual override still uses a raw channel string.
        """
        use_editor = params.get("use_ramp_editor", True)
        steps      = []

        if use_editor and self._ramp_tab:
            steps = self._ramp_tab.get_ramp_steps()   # [{supply, voltage, current, dwell, label}]
        else:
            ch_str = params.get("channel", "")
            steps  = [{"channel": ch_str,
                       "voltage": params.get("voltage", 0.0),
                       "current": params.get("ocp", 1.0),
                       "dwell":   0.1}]

        for s in steps:
            if self._stop_event.is_set():
                break

            # Ramp editor steps use supply role; manual override uses channel string
            if "supply" in s:
                drv, ch = self._resolve_supply_role(s["supply"])
            else:
                dev, ch = parse_channel(s.get("channel", ""))
                drv     = self._drivers.get(dev) if dev else None

            if drv:
                try:
                    drv.set_voltage(ch, s["voltage"])
                    drv.set_current(ch, s.get("current", 1.0))
                    _logger.debug(
                        f"Ramp step '{s.get('label', '')}': "
                        f"{s['voltage']} V / {s.get('current', 1.0)} A"
                    )
                except Exception as e:
                    row["error"] = str(e)
                    _logger.error(f"Ramp step error: {e}")
            else:
                _logger.warning(
                    f"Ramp step '{s.get('label', '')}': "
                    f"no driver resolved for supply '{s.get('supply', s.get('channel', '?'))}'"
                )

            time.sleep(s.get("dwell", 0.1))

    def _resolve_supply_role(self, role: str):
        """
        Resolve a supply role label ("Gate" or "Drain") to (driver, channel).
        Checks driver registry keys for a case-insensitive match on the role word,
        then falls back to the first driver that has set_voltage.
        Returns (driver, 1) or (None, None).
        """
        role_lower = role.lower()
        for name, drv in self._drivers.items():
            if role_lower in name.lower() and hasattr(drv, "set_voltage"):
                return drv, 1
        # Fallback — first power supply found
        for name, drv in self._drivers.items():
            if hasattr(drv, "set_voltage"):
                return drv, 1
        return None, None

    # ── Measurement ─────────────────────────────────────────────────

    def _measure(self, params: dict, row: dict):
        drv = self._drivers.get("PXAN9030A")
        if drv:
            try:
                row["power_dbm"] = drv.get_marker_power()
                row["freq_hz"]   = drv.get_marker_freq()
            except Exception as e:
                row["error"] = str(e)

    def _power_sweep(self, params: dict, row: dict):
        sg = self._drivers.get("RSSMBV100B")
        sa = self._drivers.get("PXAN9030A")
        if not sg or not sa:
            row["error"] = "Sig gen or spec an not connected"
            return

        start = params.get("start_dbm", -20.0)
        stop  = params.get("stop_dbm",  10.0)
        step  = params.get("step_db",   1.0)
        dwell = params.get("dwell_ms",  200) / 1000.0
        pwr   = start

        while pwr <= stop:
            if self._stop_event.is_set():
                break
            try:
                sg.set_rf_level(pwr)
                time.sleep(dwell)
                pout = sa.get_marker_power()
                row[f"pout_{pwr:.1f}dBm"] = pout
            except Exception as e:
                row["error"] = str(e)
                break
            pwr += step

    # ── SCPI ────────────────────────────────────────────────────────

    def _execute_scpi_command(self, params: dict, row: dict):
        """Send a fire-and-forget SCPI write to a named instrument."""
        instrument = params.get("instrument", "").strip()
        command    = params.get("command", "").strip()

        if not instrument or not command:
            row["error"] = "SCPI Command: instrument and command must not be empty"
            _logger.warning(row["error"])
            return

        drv = self._drivers.get(instrument)
        if drv is None:
            row["error"] = f"SCPI Command: instrument '{instrument}' not found in registry"
            _logger.warning(row["error"])
            return

        try:
            drv.write(command)
            row["scpi_command"] = command
            _logger.info(f"SCPI CMD [{instrument}]: {command}")
        except Exception as e:
            row["error"] = f"SCPI Command failed: {e}"
            _logger.error(row["error"])

    def _execute_scpi_poll(self, params: dict, row: dict):
        """
        Repeatedly query an instrument until the response matches `expected`
        or the timeout expires. Polls every 250 ms.
        If `expected` is blank, the first successful response is treated as a pass.
        """
        instrument = params.get("instrument", "").strip()
        query      = params.get("query", "").strip()
        expected   = params.get("expected", "").strip()
        timeout_s  = float(params.get("timeout", 10.0))

        if not instrument or not query:
            row["error"] = "SCPI Poll: instrument and query must not be empty"
            _logger.warning(row["error"])
            return

        drv = self._drivers.get(instrument)
        if drv is None:
            row["error"] = f"SCPI Poll: instrument '{instrument}' not found in registry"
            _logger.warning(row["error"])
            return

        deadline      = time.time() + timeout_s
        last_response = ""

        while time.time() < deadline:
            if self._stop_event.is_set():
                row["error"] = "SCPI Poll: aborted by stop event"
                _logger.warning(row["error"])
                return
            try:
                last_response = drv.query(query).strip()
                _logger.debug(
                    f"SCPI POLL [{instrument}] {query!r} → {last_response!r}"
                )
                if not expected or last_response == expected:
                    row["scpi_poll_response"] = last_response
                    _logger.info(
                        f"SCPI Poll matched on [{instrument}]: {last_response!r}"
                    )
                    return
            except Exception as e:
                _logger.warning(f"SCPI Poll query error: {e}")
            time.sleep(0.25)

        # Timed out without a match
        row["error"] = (
            f"SCPI Poll timed out after {timeout_s}s — "
            f"last response: {last_response!r}, expected: {expected!r}"
        )
        _logger.error(row["error"])

    # ── CSV output ──────────────────────────────────────────────────

    def _write_csv(self, results: list, path: str):
        if not results:
            return
        import os
        os.makedirs(
            os.path.dirname(path) if os.path.dirname(path) else ".",
            exist_ok=True
        )
        keys = list(dict.fromkeys(k for r in results for k in r))
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(results)
