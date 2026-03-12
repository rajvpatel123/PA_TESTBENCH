# tabs/sequencer_tab.py - COMPLETE FILE
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import json
import math
import datetime
from typing import Optional, Tuple
from utils.logger import get_logger, session_logger
from run_engine import RunEngine

_logger = get_logger(__name__)

RAMP_UP_STEPS = [
    (-6.0,  0.0,  0.5),
    (-6.0, 10.0,  0.5),
    (-6.0, 48.0,  0.5),
    (-3.0, 48.0,  0.5),
]
RAMP_DOWN_STEPS = list(reversed(RAMP_UP_STEPS))

DEFAULT_BIAS_SETTLE_S = 0.5
DEFAULT_RF_SETTLE_S   = 0.05

# Idq safety constants
IDQ_STEP_SETTLE_S = 0.15    # settle time per gate step
IDQ_MAX_STEPS     = 200     # hard iteration limit
MAX_GATE_V_GAN    = 0.0     # never walk gate above 0V


class SequencerTab(ttk.Frame):

    def __init__(self, parent, driver_registry: dict,
                 test_profiles: dict, profile_save_callback):
        super().__init__(parent)
        self._registry       = driver_registry
        self._profiles       = test_profiles or {}
        self._save_callback  = profile_save_callback
        self._power_tab_ref  = None
        self._siggen_tab_ref = None
        self._specan_tab_ref = None
        self._dmm_tab_ref    = None
        self._ramp_editor    = None
        self._running        = False
        self._build_ui()
        self._engine          = None
    def set_driver_registry(self, registry: dict):
        self._registry = registry

    def set_tab_refs(self, power_tab, siggen_tab, specan_tab):
        self._power_tab_ref  = power_tab
        self._siggen_tab_ref = siggen_tab
        self._specan_tab_ref = specan_tab

    def set_dmm_tab_ref(self, dmm_tab):
        self._dmm_tab_ref = dmm_tab

    def set_ramp_editor(self, ramp_editor):
        self._ramp_editor = ramp_editor
    
    def set_results_tab_ref(self, results_tab):
        self._results_tab = results_tab
        
    def set_sweep_plan_tab_ref(self, sweep_plan_tab):
        self._sweep_plan_tab = sweep_plan_tab

    # ── Ramp steps ─────────────────────────────────────────────
    def _get_ramp_steps(self) -> tuple:
        if self._ramp_editor is not None:
            raw = self._ramp_editor.get_steps()
            up  = []
            for s in raw:
                up.append({
                    "supply":  s.get("supply", "Drain").lower(),
                    "voltage": float(s.get("voltage", 0)),
                    "delay_s": float(s.get("delay_ms", 500)) / 1000.0,
                    "label":   s.get("label", ""),
                    "current": float(s.get("current", 1.0)),
                })
            return up, list(reversed(up))
        else:
            up = [{"supply": "mixed", "gate_v": g, "drain_v": d,
                   "delay_s": w, "label": "", "current": 1.0}
                  for g, d, w in RAMP_UP_STEPS]
            return up, list(reversed(up))

    # ── Settling helpers ───────────────────────────────────────
    def _get_bias_settle(self) -> float:
        try:    return float(self.bias_settle_var.get())
        except: return DEFAULT_BIAS_SETTLE_S

    def _get_rf_settle(self) -> float:
        try:    return float(self.rf_settle_var.get())
        except: return DEFAULT_RF_SETTLE_S

    # ── Sweep helpers ──────────────────────────────────────────
    def _sweep_enabled(self) -> bool:
        return self.sweep_mode_var.get() == "sweep"

    def _get_sweep_params(self) -> Optional[Tuple[float, float, float, float]]:
        try:
            start = float(self.sweep_start_var.get())
            stop  = float(self.sweep_stop_var.get())
            step  = float(self.sweep_step_var.get())
            dwell = float(self.sweep_dwell_var.get())
            if step <= 0:
                raise ValueError("Step must be > 0")
            return start, stop, step, dwell
        except ValueError as e:
            messagebox.showerror("Invalid Sweep Params",
                                 f"Check sweep settings:\n{e}")
            return None

    def _build_ui(self):
        ttk.Label(self, text="Sequencer - Run Test",
                  font=("Segoe UI", 14, "bold")).pack(pady=10)

        main = ttk.Frame(self)
        main.pack(fill="both", expand=True, padx=15, pady=5)

        # ── LEFT: Profiles ─────────────────────────────────────
        left = ttk.LabelFrame(main, text="Test Profiles")
        left.pack(side="left", fill="y", padx=(0, 10))

        ttk.Label(left, text="Profile:").pack(anchor="w", padx=8, pady=(10, 2))
        self.profile_var = tk.StringVar(value="")
        self.profile_cb  = ttk.Combobox(left, textvariable=self.profile_var,
                                         state="readonly", width=28)
        self.profile_cb.pack(padx=8, pady=2)
        self.profile_cb.bind("<<ComboboxSelected>>", self._on_profile_selected)

        ttk.Button(left, text="New Profile",
                   command=self._new_profile).pack(fill="x", padx=8, pady=3)
        ttk.Button(left, text="Save Current Settings as Profile",
                   command=self._save_profile).pack(fill="x", padx=8, pady=3)
        ttk.Button(left, text="Delete Profile",
                   command=self._delete_profile).pack(fill="x", padx=8, pady=3)

        ttk.Separator(left, orient="horizontal").pack(fill="x", padx=8, pady=10)

        ttk.Label(left, text="Profile Contents:",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=8)
        self.profile_info = tk.Text(left, height=16, width=32,
                                     state="disabled", wrap="word",
                                     font=("Consolas", 8))
        self.profile_info.pack(padx=8, pady=4, fill="both", expand=True)
        self._refresh_profile_list()

        # ── RIGHT: Run panel ───────────────────────────────────
        right = ttk.Frame(main)
        right.pack(side="right", fill="both", expand=True)

        # Pre-flight
        checks_frame = ttk.LabelFrame(right, text="Pre-flight Checks")
        checks_frame.pack(fill="x", pady=(0, 6))
        self.check_vars = {}
        for key, label in [
            ("devices", "Instruments connected"),
            ("pairs",   "Gate/Drain pairs defined"),
            ("siggen",  "Signal generator configured"),
            ("specan",  "Spectrum analyzer configured"),
        ]:
            var = tk.StringVar(value="⬜  " + label)
            self.check_vars[key] = var
            ttk.Label(checks_frame, textvariable=var,
                      font=("Segoe UI", 10)).pack(anchor="w", padx=10, pady=3)

        ttk.Button(right, text="Run Pre-flight Check",
                   command=self._run_preflight).pack(fill="x", pady=5)

        ttk.Separator(right, orient="horizontal").pack(fill="x", pady=6)

        # Settling delays
        settle_frame = ttk.LabelFrame(right, text="Settling Delays")
        settle_frame.pack(fill="x", pady=(0, 6))

        row1 = ttk.Frame(settle_frame)
        row1.pack(fill="x", padx=10, pady=5)
        ttk.Label(row1, text="Bias Settle (s):",
                  width=18, anchor="e").pack(side="left")
        self.bias_settle_var = tk.StringVar(value=str(DEFAULT_BIAS_SETTLE_S))
        ttk.Entry(row1, textvariable=self.bias_settle_var,
                  width=8).pack(side="left", padx=6)
        ttk.Label(row1, text="Wait after Idq target reached before RF ON",
                  foreground="gray").pack(side="left", padx=4)

        row2 = ttk.Frame(settle_frame)
        row2.pack(fill="x", padx=10, pady=5)
        ttk.Label(row2, text="RF Settle (s):",
                  width=18, anchor="e").pack(side="left")
        self.rf_settle_var = tk.StringVar(value=str(DEFAULT_RF_SETTLE_S))
        ttk.Entry(row2, textvariable=self.rf_settle_var,
                  width=8).pack(side="left", padx=6)
        ttk.Label(row2, text="Wait after RF ON before spectrum acquire",
                  foreground="gray").pack(side="left", padx=4)

        ttk.Label(settle_frame,
                  text="GaN devices typically need 0.5–2.0 s bias settle. "
                       "RF settle 0.05 s is usually sufficient.",
                  foreground="gray", wraplength=520).pack(padx=10, pady=(0, 6))

        ttk.Separator(right, orient="horizontal").pack(fill="x", pady=6)

        # Power sweep
        sweep_frame = ttk.LabelFrame(right, text="Input Power Sweep")
        sweep_frame.pack(fill="x", pady=(0, 6))

        mode_row = ttk.Frame(sweep_frame)
        mode_row.pack(fill="x", padx=10, pady=6)
        self.sweep_mode_var = tk.StringVar(value="single")
        ttk.Radiobutton(mode_row, text="Single point  (use SigGen tab power)",
                        variable=self.sweep_mode_var, value="single",
                        command=self._on_sweep_mode_change).pack(
                        side="left", padx=(0, 20))
        ttk.Radiobutton(mode_row, text="Power sweep",
                        variable=self.sweep_mode_var, value="sweep",
                        command=self._on_sweep_mode_change).pack(side="left")

        self.sweep_params_frame = ttk.Frame(sweep_frame)
        self.sweep_params_frame.pack(fill="x", padx=10, pady=4)

        def sp_row(label, var, unit, row):
            ttk.Label(self.sweep_params_frame, text=label,
                      width=16, anchor="e").grid(
                      row=row, column=0, padx=4, pady=4, sticky="e")
            ttk.Entry(self.sweep_params_frame, textvariable=var,
                      width=10).grid(row=row, column=1, padx=4, pady=4)
            ttk.Label(self.sweep_params_frame, text=unit,
                      foreground="gray").grid(row=row, column=2, sticky="w")

        self.sweep_start_var = tk.StringVar(value="-30")
        self.sweep_stop_var  = tk.StringVar(value="10")
        self.sweep_step_var  = tk.StringVar(value="2")
        self.sweep_dwell_var = tk.StringVar(value="0.2")

        sp_row("Start Power:",  self.sweep_start_var, "dBm",     row=0)
        sp_row("Stop Power:",   self.sweep_stop_var,  "dBm",     row=1)
        sp_row("Step Size:",    self.sweep_step_var,  "dB",      row=2)
        sp_row("Dwell / step:", self.sweep_dwell_var, "seconds", row=3)

        self.sweep_pts_lbl = ttk.Label(sweep_frame, text="", foreground="gray")
        self.sweep_pts_lbl.pack(padx=10, pady=(0, 6))

        for v in (self.sweep_start_var, self.sweep_stop_var, self.sweep_step_var):
            v.trace_add("write", self._update_sweep_pts_label)

        self._on_sweep_mode_change()
        self._update_sweep_pts_label()

        ttk.Separator(right, orient="horizontal").pack(fill="x", pady=6)

        # Run / Abort
        self.run_btn = tk.Button(
            right, text="▶  RUN TEST",
            font=("Segoe UI", 16, "bold"),
            bg="#1a7a1a", fg="white",
            activebackground="#145a14", activeforeground="white",
            height=2, command=self._run_test
        )
        self.run_btn.pack(fill="x", pady=6)

        self.abort_btn = tk.Button(
            right, text="■  ABORT",
            font=("Segoe UI", 12, "bold"),
            bg="#8b0000", fg="white",
            activebackground="#5a0000", activeforeground="white",
            command=self._abort_test, state="disabled"
        )
        self.abort_btn.pack(fill="x", pady=4)

        ttk.Separator(right, orient="horizontal").pack(fill="x", pady=6)

        ttk.Label(right, text="Test Log:",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w")
        log_frame = ttk.Frame(right)
        log_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_frame, height=10, state="disabled",
                                 font=("Consolas", 9), wrap="word")
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.status_lbl = ttk.Label(self, text="Status: Idle", foreground="gray")
        self.status_lbl.pack(pady=5)

    # ── Sweep UI helpers ───────────────────────────────────────
    def _on_sweep_mode_change(self):
        is_sweep = self._sweep_enabled()
        state = "normal" if is_sweep else "disabled"
        for child in self.sweep_params_frame.winfo_children():
            try:
                child.configure(state=state)
            except tk.TclError:
                pass
        self.sweep_pts_lbl.config(
            text="" if not is_sweep else self.sweep_pts_lbl.cget("text"))

    def _update_sweep_pts_label(self, *_):
        if not self._sweep_enabled():
            self.sweep_pts_lbl.config(text="")
            return
        try:
            start = float(self.sweep_start_var.get())
            stop  = float(self.sweep_stop_var.get())
            step  = float(self.sweep_step_var.get())
            dwell = float(self.sweep_dwell_var.get())
            if step <= 0:
                raise ValueError
            n_pts    = int(math.floor((stop - start) / step)) + 1
            est_time = n_pts * dwell
            self.sweep_pts_lbl.config(
                text=f"{n_pts} points  ·  est. sweep time ≈ {est_time:.1f} s",
                foreground="gray")
        except (ValueError, ZeroDivisionError):
            self.sweep_pts_lbl.config(
                text="— check sweep values —", foreground="red")

    # ── Profile management ─────────────────────────────────────
    def _refresh_profile_list(self):
        names = list(self._profiles.keys())
        self.profile_cb["values"] = names
        if not names:
            self.profile_var.set("")

    def _on_profile_selected(self, event=None):
        name = self.profile_var.get()
        if name in self._profiles:
            self._show_profile_info(self._profiles[name])

    def _show_profile_info(self, profile: dict):
        self.profile_info.config(state="normal")
        self.profile_info.delete("1.0", tk.END)
        self.profile_info.insert(tk.END, json.dumps(profile, indent=2))
        self.profile_info.config(state="disabled")

    def _new_profile(self):
        dialog = tk.Toplevel(self)
        dialog.title("New Profile")
        dialog.grab_set()
        dialog.resizable(False, False)
        ttk.Label(dialog, text="Profile Name:").grid(
            row=0, column=0, padx=10, pady=10)
        name_var = tk.StringVar()
        ttk.Entry(dialog, textvariable=name_var, width=24).grid(
            row=0, column=1, padx=10)

        def create():
            name = name_var.get().strip()
            if not name:
                messagebox.showwarning("Empty Name", "Enter a profile name.")
                return
            if name in self._profiles:
                messagebox.showwarning("Exists",
                                       f"Profile '{name}' already exists.")
                return
            self._profiles[name] = {}
            self._save_callback(self._profiles)
            self._refresh_profile_list()
            self.profile_var.set(name)
            dialog.destroy()
            self._log(f"Profile created: {name}")

        ttk.Button(dialog, text="Create", command=create).grid(
            row=1, column=0, columnspan=2, pady=10)

    def _save_profile(self):
        name = self.profile_var.get().strip()
        if not name:
            messagebox.showwarning("No Profile",
                                   "Select or create a profile first.")
            return
        profile = {}
        if self._siggen_tab_ref: profile["siggen"]     = self._siggen_tab_ref.get_settings()
        if self._specan_tab_ref: profile["specan"]     = self._specan_tab_ref.get_settings()
        if self._power_tab_ref:  profile["pairs"]      = self._power_tab_ref.get_pairs()
        if self._ramp_editor:    profile["ramp_steps"] = self._ramp_editor.get_steps()
        profile["bias_settle_s"] = self._get_bias_settle()
        profile["rf_settle_s"]   = self._get_rf_settle()
        profile["sweep_mode"]    = self.sweep_mode_var.get()
        profile["sweep_start"]   = self.sweep_start_var.get()
        profile["sweep_stop"]    = self.sweep_stop_var.get()
        profile["sweep_step"]    = self.sweep_step_var.get()
        profile["sweep_dwell"]   = self.sweep_dwell_var.get()
        self._profiles[name] = profile
        self._save_callback(self._profiles)
        self._show_profile_info(profile)
        self._log(f"Profile saved: {name}")
        messagebox.showinfo("Saved", f"Profile '{name}' saved.")

    def _delete_profile(self):
        name = self.profile_var.get()
        if not name or name not in self._profiles:
            messagebox.showwarning("No Profile", "Select a profile to delete.")
            return
        if not messagebox.askyesno("Confirm", f"Delete profile '{name}'?"):
            return
        del self._profiles[name]
        self._save_callback(self._profiles)
        self._refresh_profile_list()
        self.profile_var.set("")
        self.profile_info.config(state="normal")
        self.profile_info.delete("1.0", tk.END)
        self.profile_info.config(state="disabled")
        self._log(f"Profile deleted: {name}")

    # ── Pre-flight ─────────────────────────────────────────────
    def _run_preflight(self) -> bool:
        all_ok = True

        if self._registry:
            self.check_vars["devices"].set("✅  Instruments connected")
        else:
            self.check_vars["devices"].set("❌  No instruments connected")
            all_ok = False

        pairs = self._power_tab_ref.get_pairs() if self._power_tab_ref else []
        if pairs:
            self.check_vars["pairs"].set(
                f"✅  {len(pairs)} Gate/Drain pair(s) defined")
        else:
            self.check_vars["pairs"].set("❌  No Gate/Drain pairs defined")
            all_ok = False

        if self._siggen_tab_ref:
            s = self._siggen_tab_ref.get_settings()
            if s.get("freq_hz") and s.get("power_dbm"):
                self.check_vars["siggen"].set("✅  Signal generator configured")
            else:
                self.check_vars["siggen"].set(
                    "❌  Signal generator: missing freq or power")
                all_ok = False
        else:
            self.check_vars["siggen"].set("⬜  Signal generator tab not linked")

        if self._specan_tab_ref:
            s = self._specan_tab_ref.get_settings()
            if s.get("center_hz") and s.get("span_hz"):
                self.check_vars["specan"].set("✅  Spectrum analyzer configured")
            else:
                self.check_vars["specan"].set(
                    "❌  Spectrum analyzer: missing center or span")
                all_ok = False
        else:
            self.check_vars["specan"].set("⬜  Spectrum analyzer tab not linked")

        return all_ok
    # ── Run Engine ──────────────────────────────────────  ← paste here
    def _on_run(self):
        plan = self._sweep_plan_tab.get_sweep_plan_rows()
        plan = self._get_sweep_plan_rows()
        output = "results/latest_run.csv"
        self._engine = RunEngine(
            driver_registry=self._driver_registry,
            on_complete=self._on_run_complete,
            on_step=self._on_step_update,
            on_error=self._on_run_error,
        )
        self._engine.start(plan, output)

    def _on_run_complete(self):
        if hasattr(self, "_results_tab"):
            self._results_tab.refresh()

    def _on_step_update(self, index, status):
        pass

    def _on_run_error(self, msg):
        print(f"[RunEngine Error] {msg}")
    # ── Run / Abort ────────────────────────────────────────────
    def _run_test(self):
        if self._running:
            return
        if not self._run_preflight():
            messagebox.showerror("Pre-flight Failed",
                                 "Fix the issues shown before running.")
            return
        if self._sweep_enabled():
            if self._get_sweep_params() is None:
                return
        self._running = True
        self.run_btn.config(state="disabled")
        self.abort_btn.config(state="normal")
        self.status_lbl.config(text="Status: Running...", foreground="orange")
        threading.Thread(target=self._execute_test_sequence, daemon=True).start()

    def _abort_test(self):
        self._running = False
        self._log("ABORT requested by user")
        self.status_lbl.config(text="Status: Aborted", foreground="red")

    # ── Main sequence ──────────────────────────────────────────
    def _execute_test_sequence(self):
        pairs         = self._power_tab_ref.get_pairs() if self._power_tab_ref else []
        bias_settle_s = self._get_bias_settle()
        rf_settle_s   = self._get_rf_settle()

        try:
            session_logger.start(metadata={
                "profile":       self.profile_var.get(),
                "bias_settle_s": bias_settle_s,
                "rf_settle_s":   rf_settle_s,
                "sweep_mode":    self.sweep_mode_var.get(),
            })

            # 1. Ramp up
            self._log("=== RAMP UP START ===")
            ramp_up, _ = self._get_ramp_steps()
            self._log(f"  Using "
                      f"{'RampEditor' if self._ramp_editor else 'hardcoded'} "
                      f"steps ({len(ramp_up)} steps)")

            last_gate_vs = {}
            for pair in pairs:
                if not self._running:
                    break
                last_gate_v = self._ramp_up(pair, ramp_up)
                if last_gate_v is None:
                    # Overcurrent abort during ramp
                    self._safe_shutdown(pairs)
                    return
                last_gate_vs[pair["gate_id"]] = last_gate_v

            if not self._running:
                self._safe_shutdown(pairs)
                return

            # 2. Idq targeting
            self._log("=== IDQ TARGETING ===")
            for pair in pairs:
                if not self._running:
                    break
                try:
                    final_gate_v = float(pair.get("final_gate_v") or -3.0)
                except (ValueError, TypeError):
                    final_gate_v = -3.0

                start_gate_v = last_gate_vs.get(pair["gate_id"], final_gate_v)
                ok = self._target_idq(pair, start_gate_v, final_gate_v)
                if not ok:
                    self._log("=== ABORT: Idq limit exceeded — emergency shutdown ===")
                    self._safe_shutdown(pairs)
                    return

            if not self._running:
                self._safe_shutdown(pairs)
                return

            # 3. Bias settling
            self._log(f"=== BIAS SETTLING: {bias_settle_s} s ===")
            self.after(0, lambda: self.status_lbl.config(
                text=f"Status: Bias settling ({bias_settle_s} s)...",
                foreground="orange"))
            deadline = time.time() + bias_settle_s
            while time.time() < deadline:
                if not self._running:
                    self._safe_shutdown(pairs)
                    return
                time.sleep(0.05)
            self._log("  Bias settled.")

            # 4. SigGen on
            self._log("=== CONFIGURING SIGNAL GENERATOR ===")
            self._configure_siggen(rf_settle_s)
            if not self._running:
                self._safe_shutdown(pairs)
                return

            # 5. SpecAn settings
            self._log("=== CONFIGURING SPECTRUM ANALYZER ===")
            self._configure_specan()
            if not self._running:
                self._safe_shutdown(pairs)
                return

            # 6. Measurement
            if self._sweep_enabled():
                self._log("=== POWER SWEEP START ===")
                self._run_power_sweep(rf_settle_s)
            else:
                self._log("=== ACQUIRING SINGLE TRACE ===")
                self._acquire_trace()

            if not self._running:
                self._safe_shutdown(pairs)
                return

            # 7. Ramp down
            self._log("=== RAMP DOWN START ===")
            _, ramp_down = self._get_ramp_steps()
            for pair in pairs:
                self._ramp_down(pair, ramp_down)

            self._log("=== TEST COMPLETE ===")
            session_logger.stop()
            self.after(0, lambda: self.status_lbl.config(
                text="Status: Test Complete", foreground="green"))

        except Exception as e:
            self._log(f"ERROR: {e}")
            _logger.error(f"Test sequence error: {e}", exc_info=True)
            try:
                _, ramp_down = self._get_ramp_steps()
                for pair in pairs:
                    self._ramp_down(pair, ramp_down)
            except Exception as e2:
                self._log(f"RAMP DOWN ERROR: {e2}")
            session_logger.stop()
            self.after(0, lambda: self.status_lbl.config(
                text="Status: Error - check log", foreground="red"))
        finally:
            self._running = False
            self.after(0, lambda: self.run_btn.config(state="normal"))
            self.after(0, lambda: self.abort_btn.config(state="disabled"))

    # ── Ramp up ────────────────────────────────────────────────
    def _ramp_up(self, pair: dict, ramp_steps: list) -> Optional[float]:
        """
        Execute ramp-up steps.
        Returns the last gate voltage applied, or None if overcurrent abort.
        Does NOT apply final_gate_v — handled by _target_idq().
        """
        gate_drv   = self._registry.get(pair["gate_supply"])
        drain_drv  = self._registry.get(pair["drain_supply"])
        gate_ch    = pair["gate_channel"]
        drain_ch   = pair["drain_channel"]
        gate_curr  = float(pair.get("gate_curr")  or 0.1)
        drain_curr = float(pair.get("drain_curr") or 1.0)

        # Hard current abort at 3× configured drain current
        drain_abort_a = drain_curr * 3.0

        try:
            final_gate_v = float(pair["final_gate_v"])
        except (ValueError, TypeError):
            final_gate_v = -6.0
            self._log("WARNING: No final gate V set, defaulting to -6.0 V")

        if final_gate_v > 0:
            self._log(
                f"WARNING: Final gate voltage {final_gate_v} V is positive!")

        gate_drv.set_current(gate_ch,   gate_curr)
        drain_drv.set_current(drain_ch, drain_curr)
        gate_drv.output_on(gate_ch,   True)
        drain_drv.output_on(drain_ch, True)

        last_gate_v  = 0.0
        last_drain_v = 0.0

        if self._ramp_editor is not None:
            for step in ramp_steps:
                if not self._running:
                    return last_gate_v
                supply  = step["supply"]
                voltage = step["voltage"]
                current = step["current"]
                delay_s = step["delay_s"]
                label   = step["label"]

                if supply == "gate":
                    gate_drv.set_current(gate_ch, current)
                    gate_drv.set_voltage(gate_ch, voltage)
                    last_gate_v = voltage
                    self._log(f"  RAMP [{label}]: Gate={voltage}V "
                              f"({current}A) wait={delay_s}s")
                elif supply == "drain":
                    drain_drv.set_current(drain_ch, current)
                    drain_drv.set_voltage(drain_ch, voltage)
                    last_drain_v = voltage
                    self._log(f"  RAMP [{label}]: Drain={voltage}V "
                              f"({current}A) wait={delay_s}s")

                time.sleep(delay_s)

                if self._check_current_limit(
                        drain_drv, drain_ch, drain_abort_a, label):
                    return None

                session_logger.log(
                    instrument=f"{pair['gate_supply']} / {pair['drain_supply']}",
                    channel=f"G:{gate_ch} D:{drain_ch}",
                    gate_v=last_gate_v, drain_v=last_drain_v,
                    gate_a=gate_curr,   drain_a=drain_curr,
                    notes=f"Ramp up [{label}] {supply}={voltage}V"
                )
        else:
            for step in ramp_steps:
                if not self._running:
                    return last_gate_v
                gate_v  = step["gate_v"]
                drain_v = step["drain_v"]
                wait    = step["delay_s"]
                self._log(
                    f"  RAMP: Gate={gate_v}V  Drain={drain_v}V  wait={wait}s")
                gate_drv.set_voltage(gate_ch,   gate_v)
                drain_drv.set_voltage(drain_ch, drain_v)
                last_gate_v  = gate_v
                last_drain_v = drain_v
                time.sleep(wait)

                if self._check_current_limit(
                        drain_drv, drain_ch, drain_abort_a,
                        f"gate={gate_v}V"):
                    return None

                session_logger.log(
                    instrument=f"{pair['gate_supply']} / {pair['drain_supply']}",
                    channel=f"G:{gate_ch} D:{drain_ch}",
                    gate_v=gate_v,    drain_v=drain_v,
                    gate_a=gate_curr, drain_a=drain_curr,
                    notes=f"Ramp up gate={gate_v}V drain={drain_v}V"
                )

        self._log(f"  Ramp complete — gate at {last_gate_v}V, "
                  f"drain at {last_drain_v}V")
        return last_gate_v

    # ── Current limit check ────────────────────────────────────
    def _check_current_limit(self, drain_drv, drain_ch: int,
                              limit_a: float, label: str) -> bool:
        """Returns True if limit exceeded — caller must abort."""
        try:
            idrain = drain_drv.measure_current(drain_ch)
            if idrain > limit_a:
                self._log(f"  !! OVERCURRENT [{label}]: "
                          f"{idrain*1000:.1f} mA > limit {limit_a*1000:.1f} mA")
                return True
            self._log(f"  Current OK [{label}]: {idrain*1000:.1f} mA")
        except Exception as e:
            _logger.warning(f"Current limit check failed: {e}")
        return False

    # ── Idq targeting loop ─────────────────────────────────────
    def _target_idq(self, pair: dict,
                    start_gate_v: float,
                    final_gate_v: float) -> bool:
        """
        Walk gate voltage from start_gate_v toward final_gate_v in small
        steps while monitoring drain quiescent current.

        Returns:
            True  — target reached, or no target configured (safe to continue)
            False — hard current limit exceeded (caller must abort + ramp down)
        """
        try:
            target_ma = float(pair.get("target_idq_ma") or 0)
        except (ValueError, TypeError):
            target_ma = 0

        gate_drv  = self._registry.get(pair["gate_supply"])
        drain_drv = self._registry.get(pair["drain_supply"])
        gate_ch   = pair["gate_channel"]
        drain_ch  = pair["drain_channel"]

        if target_ma <= 0:
            # No target — apply final gate voltage directly
            if gate_drv:
                gate_drv.set_voltage(gate_ch, final_gate_v)
                self._log(f"  No Idq target — gate set to {final_gate_v} V")
            return True

        try:
            tolerance_ma = float(pair.get("idq_tolerance_ma") or 5.0)
            step_mv      = float(pair.get("idq_step_mv")      or 50.0)
            max_idq_raw  = pair.get("max_idq_ma", "")
            max_idq_ma   = float(max_idq_raw) if max_idq_raw else target_ma * 3.0
        except (ValueError, TypeError):
            tolerance_ma = 5.0
            step_mv      = 50.0
            max_idq_ma   = target_ma * 3.0

        target_a    = target_ma    / 1000.0
        tolerance_a = tolerance_ma / 1000.0
        max_idq_a   = max_idq_ma   / 1000.0
        step_v      = step_mv      / 1000.0

        # Hard safety cap — never walk gate above 0V for GaN
        final_gate_v = min(final_gate_v, MAX_GATE_V_GAN)

        self._log(
            f"  Idq target: {start_gate_v:.3f}V → {final_gate_v:.3f}V | "
            f"target={target_ma:.1f} mA ±{tolerance_ma:.1f} mA | "
            f"step={step_mv:.0f} mV | abort>{max_idq_ma:.1f} mA")

        current_gate_v = start_gate_v

        for i in range(IDQ_MAX_STEPS):
            if not self._running:
                return True   # user abort — not a device fault

            # Read Idq
            try:
                idq_a  = drain_drv.measure_current(drain_ch)
                idq_ma = idq_a * 1000.0
            except Exception as e:
                self._log(f"  ERROR reading Idq: {e}")
                return False

            self.after(0, lambda gv=current_gate_v, iq=idq_ma:
                       self.status_lbl.config(
                           text=f"Status: Idq walk  "
                                f"Gate={gv:.3f}V  Idq={iq:.1f} mA",
                           foreground="orange"))

            self._log(f"  [{i+1:03d}] Gate={current_gate_v:.4f}V  "
                      f"Idq={idq_ma:.2f} mA")

            # Hard abort — protect device immediately
            if idq_a > max_idq_a:
                self._log(
                    f"  !! ABORT: Idq={idq_ma:.2f} mA exceeded hard limit "
                    f"{max_idq_ma:.1f} mA")
                session_logger.log(
                    instrument=pair["drain_supply"],
                    notes=f"IDQ ABORT: {idq_ma:.2f} mA > {max_idq_ma:.1f} mA")
                return False

            # Converged
            if abs(idq_a - target_a) <= tolerance_a:
                self._log(
                    f"  ✓ Idq converged: {idq_ma:.2f} mA  "
                    f"(target={target_ma:.1f} ±{tolerance_ma:.1f} mA)  "
                    f"Gate={current_gate_v:.4f} V")
                session_logger.log(
                    instrument=pair["drain_supply"],
                    gate_v=current_gate_v, drain_a=idq_a,
                    notes=f"Idq converged at {idq_ma:.2f} mA")
                return True

            # Overshot target — stop here, device is safe
            if idq_a > target_a:
                self._log(
                    f"  WARNING: Idq overshot ({idq_ma:.2f} mA > "
                    f"{target_ma:.1f} mA) at gate={current_gate_v:.4f} V. "
                    f"Within hard limit — continuing.")
                return True

            # Step gate toward final_gate_v
            next_gate_v = round(current_gate_v + step_v, 6)

            if next_gate_v >= final_gate_v:
                # Reached final gate V without hitting Idq target
                gate_drv.set_voltage(gate_ch, final_gate_v)
                current_gate_v = final_gate_v
                time.sleep(IDQ_STEP_SETTLE_S)
                try:
                    idq_a  = drain_drv.measure_current(drain_ch)
                    idq_ma = idq_a * 1000.0
                except Exception:
                    idq_ma = -1.0
                    idq_a  = 0.0
                self._log(
                    f"  Reached final gate V={final_gate_v} V — "
                    f"Idq={idq_ma:.2f} mA (target was {target_ma:.1f} mA). "
                    f"Continuing.")
                if idq_a > max_idq_a:
                    self._log(
                        f"  !! ABORT at final gate V: "
                        f"Idq={idq_ma:.2f} mA > {max_idq_ma:.1f} mA")
                    return False
                return True

            try:
                gate_drv.set_voltage(gate_ch, next_gate_v)
                current_gate_v = next_gate_v
            except Exception as e:
                self._log(f"  ERROR setting gate to {next_gate_v} V: {e}")
                return False

            time.sleep(IDQ_STEP_SETTLE_S)

        self._log(
            f"  WARNING: Idq did not converge after {IDQ_MAX_STEPS} steps. "
            f"Holding gate at {current_gate_v:.4f} V and continuing.")
        return True   # non-destructive — device still safely biased

    # ── Ramp down ──────────────────────────────────────────────
    def _ramp_down(self, pair: dict, ramp_steps: list):
        gate_drv  = self._registry.get(pair["gate_supply"])
        drain_drv = self._registry.get(pair["drain_supply"])
        gate_ch   = pair["gate_channel"]
        drain_ch  = pair["drain_channel"]
        gate_curr  = float(pair.get("gate_curr")  or 0.1)
        drain_curr = float(pair.get("drain_curr") or 1.0)

        self._log(f"  RAMP DOWN: {pair['gate_id']} / {pair['drain_id']}")
        last_gate_v  = 0.0
        last_drain_v = 0.0

        if self._ramp_editor is not None:
            for step in ramp_steps:
                supply  = step["supply"]
                voltage = step["voltage"]
                current = step["current"]
                delay_s = step["delay_s"]
                label   = step["label"]
                if supply == "gate":
                    gate_drv.set_current(gate_ch, current)
                    gate_drv.set_voltage(gate_ch, voltage)
                    last_gate_v = voltage
                    self._log(
                        f"  RAMP DOWN [{label}]: Gate={voltage}V wait={delay_s}s")
                elif supply == "drain":
                    drain_drv.set_current(drain_ch, current)
                    drain_drv.set_voltage(drain_ch, voltage)
                    last_drain_v = voltage
                    self._log(
                        f"  RAMP DOWN [{label}]: Drain={voltage}V wait={delay_s}s")
                session_logger.log(
                    instrument=f"{pair['gate_supply']} / {pair['drain_supply']}",
                    channel=f"G:{gate_ch} D:{drain_ch}",
                    gate_v=last_gate_v,   drain_v=last_drain_v,
                    gate_a=gate_curr,     drain_a=drain_curr,
                    notes=f"Ramp down [{label}] {supply}={voltage}V"
                )
                time.sleep(delay_s)
        else:
            for step in ramp_steps:
                gate_v  = step["gate_v"]
                drain_v = step["drain_v"]
                wait    = step["delay_s"]
                self._log(
                    f"  RAMP DOWN: Gate={gate_v}V  Drain={drain_v}V  wait={wait}s")
                gate_drv.set_voltage(gate_ch,   gate_v)
                drain_drv.set_voltage(drain_ch, drain_v)
                session_logger.log(
                    instrument=f"{pair['gate_supply']} / {pair['drain_supply']}",
                    channel=f"G:{gate_ch} D:{drain_ch}",
                    gate_v=gate_v,    drain_v=drain_v,
                    gate_a=gate_curr, drain_a=drain_curr,
                    notes=f"Ramp down gate={gate_v}V drain={drain_v}V"
                )
                time.sleep(wait)

        # Always zero and disable at end of ramp down
        gate_drv.set_voltage(gate_ch,   0.0)
        drain_drv.set_voltage(drain_ch, 0.0)
        gate_drv.output_on(gate_ch,   False)
        drain_drv.output_on(drain_ch, False)
        self._log("  Outputs OFF — ramp down complete")

    # ── SigGen / SpecAn ────────────────────────────────────────
    def _configure_siggen(self, rf_settle_s: float):
        drv = self._registry.get("RS_SMBV100B")
        if drv is None:
            self._log("WARNING: Signal generator not connected, skipping")
            return
        s = self._siggen_tab_ref.get_settings() if self._siggen_tab_ref else {}
        try:
            if s.get("freq_hz"):   drv.set_freq(float(s["freq_hz"]))
            if s.get("power_dbm"): drv.set_power(float(s["power_dbm"]))
            if s.get("waveform") and s["waveform"] not in ("None", ""):
                drv.set_waveform(s["waveform"])
            drv.rf_on(True)
            self._log(f"  SigGen RF ON — settling {rf_settle_s} s")
            self.after(0, lambda: self.status_lbl.config(
                text=f"Status: RF settling ({rf_settle_s} s)...",
                foreground="orange"))
            time.sleep(rf_settle_s)
            self._log("  RF settled.")
            session_logger.log(
                instrument="RS_SMBV100B",
                freq=s.get("freq_hz", "-"),
                power=s.get("power_dbm", "-"),
                notes=f"SigGen configured, RF ON, settled {rf_settle_s}s"
            )
        except Exception as e:
            self._log(f"  SigGen error: {e}")
            raise

    def _configure_specan(self):
        drv = self._registry.get("PXA_N9030A")
        if drv is None:
            self._log("WARNING: Spectrum analyzer not connected, skipping")
            return
        s = self._specan_tab_ref.get_settings() if self._specan_tab_ref else {}
        try:
            if s.get("center_hz"): drv.set_center(float(s["center_hz"]))
            if s.get("span_hz"):   drv.set_span(float(s["span_hz"]))
            if s.get("rbw_hz"):    drv.set_rbw(float(s["rbw_hz"]))
            if s.get("ref_dbm"):   drv.set_ref_level(float(s["ref_dbm"]))
            self._log(f"  SpecAn center={s.get('center_hz')} Hz "
                      f"span={s.get('span_hz')} Hz")
            session_logger.log(instrument="PXA_N9030A",
                               notes="SpecAn configured")
        except Exception as e:
            self._log(f"  SpecAn config error: {e}")
            raise

    def _acquire_trace(self):
        drv = self._registry.get("PXA_N9030A")
        if drv is None:
            self._log("WARNING: Spectrum analyzer not connected, skipping trace")
            return
        s       = self._specan_tab_ref.get_settings() if self._specan_tab_ref else {}
        acq_str = s.get("acq_window_s", "")
        try:
            acq_time = float(acq_str) if acq_str else None
            if acq_time:
                self._log(f"  Waiting acquisition window: {acq_time} s")
                time.sleep(acq_time)
            trace = drv.acquire_trace()
            self._log(f"  Trace acquired: {len(trace)} points")
            if hasattr(drv, "get_freq_axis"):
                freqs = drv.get_freq_axis()
            else:
                import numpy as np
                center = float(s.get("center_hz", 0))
                span   = float(s.get("span_hz",   0))
                freqs  = list(np.linspace(
                    center - span / 2, center + span / 2, len(trace)))
            session_logger.log_trace(freqs, trace, notes="Single trace acquired")
            if self._specan_tab_ref:
                self.after(0, self._specan_tab_ref._refresh_trace)
        except Exception as e:
            self._log(f"  Trace acquisition error: {e}")
            raise

    # ── Power sweep ────────────────────────────────────────────
    def _run_power_sweep(self, rf_settle_s: float):
        params = self._get_sweep_params()
        if params is None:
            return
        start_dbm, stop_dbm, step_db, dwell_s = params
        drv_siggen = self._registry.get("RS_SMBV100B")
        drv_specan = self._registry.get("PXA_N9030A")

        if drv_siggen is None:
            self._log("ERROR: Signal generator not connected — cannot sweep")
            return
        if drv_specan is None:
            self._log("ERROR: Spectrum analyzer not connected — cannot sweep")
            return

        n_pts     = int(math.floor((stop_dbm - start_dbm) / step_db)) + 1
        pin_steps = [start_dbm + i * step_db for i in range(n_pts)]
        s         = self._specan_tab_ref.get_settings() \
                    if self._specan_tab_ref else {}

        self._log(f"  Sweep: {start_dbm} → {stop_dbm} dBm, "
                  f"{step_db} dB step, {n_pts} points, {dwell_s} s dwell")

        for idx, pin in enumerate(pin_steps):
            if not self._running:
                self._log("  Sweep aborted.")
                return

            self.after(0, lambda p=pin, i=idx: self.status_lbl.config(
                text=f"Status: Sweep {i+1}/{n_pts}  Pin={p:.1f} dBm",
                foreground="orange"))

            try:
                drv_siggen.set_power(pin)
            except Exception as e:
                self._log(f"  ERROR setting Pin={pin} dBm: {e}")
                continue

            time.sleep(dwell_s)

            if not self._running:
                return

            vdrain, idrain = self._read_drain_for_pae()

            try:
                acq_str  = s.get("acq_window_s", "")
                acq_time = float(acq_str) if acq_str else None
                if acq_time:
                    time.sleep(acq_time)

                trace = drv_specan.acquire_trace()

                if trace and isinstance(trace[0], (list, tuple)):
                    amps = [p[1] for p in trace]
                else:
                    amps = list(trace)

                pout    = max(amps) if amps else None
                gain_db = round(pout - pin, 3) if pout is not None else None

                pae_pct = None
                pdc_w   = None
                if pout is not None and vdrain is not None \
                        and idrain is not None:
                    pout_w = 10 ** ((pout - 30) / 10)
                    pin_w  = 10 ** ((pin  - 30) / 10)
                    pdc_w  = vdrain * idrain
                    if pdc_w > 0:
                        pae_pct = round(
                            (pout_w - pin_w) / pdc_w * 100, 3)

                pae_str = (f"{pae_pct:.2f}%"
                           if pae_pct is not None else "N/A (no DMM)")
                self._log(
                    f"  [{idx+1}/{n_pts}] Pin={pin:.1f} dBm  "
                    f"Pout={pout:.2f} dBm  Gain={gain_db:.2f} dB  "
                    f"PDC={pdc_w:.2f} W  PAE={pae_str}")

                session_logger.log(
                    instrument="RS_SMBV100B / PXA_N9030A",
                    channel="-",
                    pin_dbm=round(pin, 3),
                    pout_dbm=round(pout, 3)  if pout    is not None else "-",
                    gain_db=gain_db          if gain_db is not None else "-",
                    pdc_w=round(pdc_w, 4)   if pdc_w   is not None else "-",
                    pae_pct=pae_pct         if pae_pct is not None else "-",
                    notes=f"Sweep point {idx+1}/{n_pts}"
                )

                if hasattr(drv_specan, "get_freq_axis"):
                    freqs = drv_specan.get_freq_axis()
                else:
                    import numpy as np
                    center = float(s.get("center_hz", 0))
                    span   = float(s.get("span_hz",   0))
                    freqs  = list(np.linspace(
                        center - span / 2, center + span / 2, len(trace)))
                session_logger.log_trace(
                    freqs, amps, notes=f"Sweep Pin={pin:.1f} dBm")

            except Exception as e:
                self._log(
                    f"  ERROR acquiring trace at Pin={pin} dBm: {e}")

        self._log("=== POWER SWEEP COMPLETE ===")

    # ── PAE DMM read ───────────────────────────────────────────
    def _read_drain_for_pae(self) -> tuple:
        if self._dmm_tab_ref is None:
            return None, None
        try:
            readings = self._dmm_tab_ref.get_latest_readings()
            vdrain, idrain = None, None
            for data in readings.values():
                val = data.get("reading", "---")
                try:    val = float(val)
                except (ValueError, TypeError): continue
                mode = data.get("mode", "")
                if mode == "VOLT:DC" and vdrain is None:
                    vdrain = val
                elif mode == "CURR:DC" and idrain is None:
                    idrain = val
            return vdrain, idrain
        except Exception as e:
            _logger.warning(f"PAE DMM read failed: {e}")
            return None, None

    # ── Emergency shutdown ─────────────────────────────────────
    def _safe_shutdown(self, pairs: list):
        self._log("=== EMERGENCY SHUTDOWN — RAMPING DOWN ALL PAIRS ===")
        _, ramp_down = self._get_ramp_steps()
        for pair in pairs:
            try:
                self._ramp_down(pair, ramp_down)
            except Exception as e:
                self._log(
                    f"  Shutdown error for {pair.get('gate_id')}: {e}")

    # ── Log helper ─────────────────────────────────────────────
    def _log(self, message: str):
        ts   = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"[{ts}] {message}\n"
        _logger.info(message)
        def _update():
            self.log_text.config(state="normal")
            self.log_text.insert(tk.END, line)
            self.log_text.see(tk.END)
            self.log_text.config(state="disabled")
        self.after(0, _update)
