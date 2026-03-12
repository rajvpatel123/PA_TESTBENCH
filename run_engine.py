import threading
import time
import csv
import os
import re
from datetime import datetime
from utils.logger import get_logger

_logger = get_logger(__name__)


class RunEngine:

    def __init__(self, driver_registry: dict, ramp_tab=None,
                 on_complete=None, on_step=None, on_error=None):
        self._registry    = driver_registry
        self._ramp_tab    = ramp_tab
        self._on_complete = on_complete
        self._on_step     = on_step
        self._on_error    = on_error
        self._stop_event  = threading.Event()
        self._thread      = None

    def start(self, plan_rows: list, output_path: str):
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(plan_rows, output_path),
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()

    # ══════════════════════════════════════════════════════════
    #  THREAD ENTRY
    # ══════════════════════════════════════════════════════════
    def _run(self, plan_rows: list, output_path: str):
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
        except Exception:
            pass

        results = []
        try:
            self._execute_steps(plan_rows, results, offset=0)
        except _AbortRun as e:
            _logger.warning(f"Run aborted: {e}")
            if self._on_error:
                self._on_error(str(e))
            self._write_csv(output_path, results)
            return
        except Exception as e:
            _logger.exception(f"Unhandled run error: {e}")
            if self._on_error:
                self._on_error(str(e))
            self._write_csv(output_path, results)
            return

        self._write_csv(output_path, results)
        if self._on_complete:
            self._on_complete()

    # ══════════════════════════════════════════════════════════
    #  STEP EXECUTOR  (recursive for LOOP)
    # ══════════════════════════════════════════════════════════
    def _execute_steps(self, plan_rows: list, results: list, offset: int = 0):
        i = 0
        while i < len(plan_rows):
            if self._stop_event.is_set():
                raise _AbortRun("User stopped the run.")

            row     = plan_rows[i]
            cmd     = row.get("command", "").upper()
            params  = row.get("params", {})
            abs_idx = offset + i

            # ── LOOP: gather inner block then recurse ──────────
            if cmd == "LOOP":
                count = int(params.get("count", 1))
                label = params.get("label", "")
                inner = []
                j = i + 1
                while j < len(plan_rows):
                    if plan_rows[j].get("command", "").upper() == "LOOP":
                        break
                    inner.append(plan_rows[j])
                    j += 1

                self._notify_step(abs_idx, "running")
                _logger.info(
                    f"LOOP ×{count}  '{label}'  "
                    f"({len(inner)} inner steps  idx={abs_idx})")

                for iteration in range(count):
                    if self._stop_event.is_set():
                        raise _AbortRun("User stopped during loop.")
                    _logger.info(f"  → iteration {iteration + 1}/{count}")
                    self._execute_steps(inner, results, offset=abs_idx + 1)

                self._notify_step(abs_idx, "done")
                i = j
                continue

            # ── All other commands ─────────────────────────────
            self._notify_step(abs_idx, "running")
            try:
                result = self._dispatch(cmd, params)
                if isinstance(result, list):
                    results.extend(result)
                elif result:
                    results.append(result)
                self._notify_step(abs_idx, "done")
            except _AbortRun:
                self._notify_step(abs_idx, "error")
                raise
            except Exception as e:
                self._notify_step(abs_idx, "error")
                _logger.error(f"Step {abs_idx} ({cmd}) raised: {e}")
                raise _AbortRun(f"Step {abs_idx + 1} ({cmd}) failed: {e}")

            i += 1

    # ══════════════════════════════════════════════════════════
    #  COMMAND DISPATCHER
    # ══════════════════════════════════════════════════════════
    def _dispatch(self, cmd: str, params: dict):
        handlers = {
            "SET_BIAS":     self._cmd_set_bias,
            "RAMP":         self._cmd_ramp,
            "OUTPUT_ON":    self._cmd_output_on,
            "OUTPUT_OFF":   self._cmd_output_off,
            "POWER_SWEEP":  self._cmd_power_sweep,
            "MEASURE":      self._cmd_measure,
            "SAVE_RESULTS": self._cmd_save_results,
            "WAIT":         self._cmd_wait,
            "MESSAGE":      self._cmd_message,
            "GROUP":        self._cmd_group,
            "COND_ABORT":   self._cmd_cond_abort,
            "SCPI_COMMAND": self._cmd_scpi_command,
            "SCPI_POLL":    self._cmd_scpi_poll,
        }
        handler = handlers.get(cmd)
        if handler:
            return handler(params)
        _logger.warning(f"Unknown command '{cmd}' — skipping.")
        return None

    # ══════════════════════════════════════════════════════════
    #  INSTRUMENT RESOLVERS
    # ══════════════════════════════════════════════════════════
    def _get_sa(self):
        SA_KEYS = ("MXA", "EXA", "PXA", "CXA", "N90", "E44",
                   "FieldFox", "SpectrumAnalyzer", "SA")
        for key in self._registry:
            if any(k.lower() in key.lower() for k in SA_KEYS):
                return self._registry[key]
        return None

    def _get_sg(self):
        SG_KEYS = ("PSG", "MXG", "EXG", "N51", "N52", "E82",
                   "SMW", "SMB", "SignalGenerator", "SG")
        for key in self._registry:
            if any(k.lower() in key.lower() for k in SG_KEYS):
                return self._registry[key]
        return None

    def _resolve_channel(self, channel_str: str):
        for key in self._registry:
            if key in channel_str:
                return self._registry[key]
        return None

    def _channel_number(self, channel_str: str) -> int:
        m = re.search(r"CH(\d+)", channel_str)
        return int(m.group(1)) if m else 1

    # ══════════════════════════════════════════════════════════
    #  BIASING HANDLERS
    # ══════════════════════════════════════════════════════════
    def _cmd_set_bias(self, p: dict):
        channel = p.get("channel", "")
        mode    = p.get("mode", "CV")
        drv     = self._resolve_channel(channel)
        if drv is None:
            raise _AbortRun(f"No driver found for channel: {channel!r}")
        ch_num = self._channel_number(channel)
        if mode == "CV":
            drv.set_voltage(ch_num, p["voltage"])
            drv.set_ocp(ch_num, p["ocp"])
        else:
            drv.set_current(ch_num, p["current"])
            drv.set_ovp(ch_num, p["ovp"])
        _logger.info(f"SET_BIAS  ch={channel}  mode={mode}")
        return None

    def _cmd_ramp(self, p: dict):
        use_editor = p.get("use_ramp_editor", True)
        direction  = p.get("direction", "up")
        if use_editor and self._ramp_tab is not None:
            steps = self._ramp_tab.get_ramp_steps()
            if direction == "down":
                steps = list(reversed(steps))
            for step in steps:
                if self._stop_event.is_set():
                    raise _AbortRun("Stopped during ramp.")
                channel = step.get("channel", "")
                drv     = self._resolve_channel(channel)
                if drv is None:
                    continue
                drv.set_voltage(self._channel_number(channel), step.get("voltage", 0.0))
                time.sleep(step.get("dwell_ms", 100) / 1000.0)
        else:
            channel = p.get("channel", "")
            drv     = self._resolve_channel(channel)
            if drv is None:
                raise _AbortRun(f"No driver for ramp channel: {channel!r}")
            drv.set_voltage(self._channel_number(channel), p.get("voltage", 0.0))
            drv.set_ocp(self._channel_number(channel), p.get("ocp", 1.0))
        _logger.info(f"RAMP  direction={direction}")
        return None

    def _cmd_output_on(self, p: dict):
        channel = p.get("channel", "")
        drv     = self._resolve_channel(channel)
        if drv is None:
            raise _AbortRun(f"No driver for OUTPUT_ON: {channel!r}")
        drv.output_on(self._channel_number(channel))
        _logger.info(f"OUTPUT_ON  ch={channel}")
        return None

    def _cmd_output_off(self, p: dict):
        channel = p.get("channel", "")
        drv     = self._resolve_channel(channel)
        if drv is None:
            raise _AbortRun(f"No driver for OUTPUT_OFF: {channel!r}")
        drv.output_off(self._channel_number(channel))
        _logger.info(f"OUTPUT_OFF  ch={channel}")
        return None

    # ══════════════════════════════════════════════════════════
    #  MEASUREMENT HANDLERS
    # ══════════════════════════════════════════════════════════
    def _cmd_power_sweep(self, p: dict):
        start_dbm = float(p.get("start_dbm", -20.0))
        stop_dbm  = float(p.get("stop_dbm",   10.0))
        step_db   = float(p.get("step_db",     1.0))
        dwell_ms  = float(p.get("dwell_ms",  200.0))

        sg = self._get_sg()
        sa = self._get_sa()

        if sg is None:
            raise _AbortRun("POWER_SWEEP: no Signal Generator found in registry.")
        if sa is None:
            raise _AbortRun("POWER_SWEEP: no Spectrum Analyzer found in registry.")

        n      = int(abs(stop_dbm - start_dbm) / step_db) + 1
        points = [start_dbm + i * step_db for i in range(n)]

        _logger.info(
            f"POWER_SWEEP  {start_dbm} → {stop_dbm} dBm  "
            f"step {step_db} dB  {n} points")

        sweep_results = []
        for pin_dbm in points:
            if self._stop_event.is_set():
                raise _AbortRun("Stopped during power sweep.")

            sg.write(f":POW {pin_dbm:.3f} DBM")
            time.sleep(dwell_ms / 1000.0)

            sa.write(":INIT:IMM")
            sa.query("*OPC?")
            sa.write(":CALC:MARK1:MAX")
            pout_dbm = float(sa.query(":CALC:MARK1:Y?"))

            gain_db = pout_dbm - pin_dbm

            _logger.debug(
                f"  Pin={pin_dbm:.1f} dBm  Pout={pout_dbm:.2f} dBm  "
                f"Gain={gain_db:.2f} dB")

            sweep_results.append({
                "command":   "POWER_SWEEP",
                "pin_dbm":   pin_dbm,
                "pout_dbm":  pout_dbm,
                "gain_db":   gain_db,
                "timestamp": datetime.now().isoformat(),
            })

        return sweep_results

    def _cmd_measure(self, p: dict):
        notes = p.get("notes", "")
        sa    = self._get_sa()

        if sa is None:
            _logger.warning("MEASURE: no SA in registry — logging note only.")
            return {
                "command":   "MEASURE",
                "notes":     notes,
                "pout_dbm":  None,
                "timestamp": datetime.now().isoformat(),
            }

        sa.write(":INIT:IMM")
        sa.query("*OPC?")
        sa.write(":CALC:MARK1:MAX")
        pout_dbm = float(sa.query(":CALC:MARK1:Y?"))

        _logger.info(f"MEASURE  Pout={pout_dbm:.2f} dBm  notes={notes!r}")

        return {
            "command":   "MEASURE",
            "notes":     notes,
            "pout_dbm":  pout_dbm,
            "timestamp": datetime.now().isoformat(),
        }

    def _cmd_save_results(self, p: dict):
        _logger.info(f"SAVE_RESULTS  filename={p.get('filename', '(auto)')}")
        return None

    # ══════════════════════════════════════════════════════════
    #  FLOW HANDLERS
    # ══════════════════════════════════════════════════════════
    def _cmd_wait(self, p: dict):
        seconds = float(p.get("seconds", 1.0))
        _logger.info(f"WAIT  {seconds} s")
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self._stop_event.is_set():
                raise _AbortRun("Stopped during wait.")
            time.sleep(min(0.1, deadline - time.monotonic()))
        return {
            "command":   "WAIT",
            "seconds":   seconds,
            "timestamp": datetime.now().isoformat(),
        }

    def _cmd_message(self, p: dict):
        text = p.get("text", "")
        _logger.info(f"MESSAGE: {text}")
        return {
            "command":   "MESSAGE",
            "text":      text,
            "timestamp": datetime.now().isoformat(),
        }

    def _cmd_group(self, p: dict):
        _logger.debug(f"GROUP  label={p.get('label', '')} (no-op)")
        return None

    def _cmd_cond_abort(self, p: dict):
        channel      = p.get("channel", "")
        threshold_ma = float(p.get("threshold_ma", 500.0))
        condition    = p.get("condition", ">")

        drv = self._resolve_channel(channel)
        if drv is None:
            _logger.warning(
                f"COND_ABORT: no driver for {channel!r} — skipping check")
            return None

        ch_num     = self._channel_number(channel)
        current_a  = drv.measure_current(ch_num)
        current_ma = current_a * 1000.0

        triggered = (
            (condition == ">"  and current_ma >  threshold_ma) or
            (condition == "<"  and current_ma <  threshold_ma) or
            (condition == ">=" and current_ma >= threshold_ma) or
            (condition == "<=" and current_ma <= threshold_ma)
        )

        if triggered:
            msg = (f"COND_ABORT triggered: {channel} "
                   f"I={current_ma:.1f} mA {condition} {threshold_ma} mA")
            _logger.error(msg)
            raise _AbortRun(msg)

        _logger.info(
            f"COND_ABORT OK: I={current_ma:.1f} mA "
            f"(limit {condition} {threshold_ma} mA)")
        return None

    # ══════════════════════════════════════════════════════════
    #  SCPI HANDLERS
    # ══════════════════════════════════════════════════════════
    def _cmd_scpi_command(self, p: dict):
        inst_name = p.get("instrument", "")
        command   = p.get("command",    "")
        drv       = self._registry.get(inst_name)
        if drv is None:
            raise _AbortRun(
                f"SCPI_COMMAND: instrument not in registry: {inst_name!r}")
        drv.write(command)
        _logger.info(f"SCPI_COMMAND  {inst_name} ← {command!r}")
        return None

    def _cmd_scpi_poll(self, p: dict):
        inst_name = p.get("instrument", "")
        query     = p.get("query",      "")
        expected  = p.get("expected",   "").strip()
        timeout_s = float(p.get("timeout_s", 10.0))

        drv = self._registry.get(inst_name)
        if drv is None:
            raise _AbortRun(
                f"SCPI_POLL: instrument not in registry: {inst_name!r}")

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self._stop_event.is_set():
                raise _AbortRun("Stopped during SCPI poll.")
            response = str(drv.query(query)).strip()
            if not expected or response == expected:
                _logger.info(
                    f"SCPI_POLL ✓  {inst_name}  "
                    f"{query!r} → {response!r}")
                return None
            _logger.debug(
                f"SCPI_POLL waiting  got={response!r}  want={expected!r}")
            time.sleep(0.25)

        raise _AbortRun(
            f"SCPI_POLL timeout ({timeout_s} s): "
            f"{inst_name} query={query!r} expected={expected!r}")

    # ══════════════════════════════════════════════════════════
    #  HELPERS
    # ══════════════════════════════════════════════════════════
    def _notify_step(self, idx: int, status: str):
        if self._on_step:
            try:
                self._on_step(idx, status)
            except Exception:
                pass

    def _write_csv(self, path: str, results: list):
        if not results:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            keys = sorted({k for row in results for k in row})
            with open(path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(results)
            _logger.info(f"Results written → {path}  ({len(results)} rows)")
        except Exception as e:
            _logger.error(f"Failed to write CSV {path}: {e}")


# ══════════════════════════════════════════════════════════════
#  INTERNAL EXCEPTION
# ══════════════════════════════════════════════════════════════
class _AbortRun(Exception):
    """Raised internally to cleanly abort a run with a reason message."""
    pass
