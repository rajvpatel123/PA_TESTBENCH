import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json
import os
import copy
from utils.logger import get_logger
from run_engine import RunEngine
from datetime import datetime

_logger = get_logger(__name__)

PSU_CHANNEL_MAP = {
    "Keysight_E36234A":      2,
    "Keysight_E36233A":      2,
    "Agilent_E3648A_GPIB15": 2,
    "Agilent_E3648A_GPIB11": 2,
    "HP_6633B":              1,
}

ACTION_CATEGORIES = {
    "Biasing": [
        ("Set Gate Bias",     "set_gate_bias"),
        ("Set Drain Bias",    "set_drain_bias"),
        ("Ramp Up",           "ramp_up"),
        ("Ramp Down",         "ramp_down"),
        ("Output ON",         "output_on"),
        ("Output OFF",        "output_off"),
        ("Bias Sweep",        "bias_sweep"),
        ("Idq Optimize",      "idq_optimize"),
    ],
    "Measurement": [
        ("Power Sweep",          "power_sweep"),
        ("Perform Measurement",  "perform_measurement"),
        ("Gain Compression",     "gain_compression"),
        ("ACPR",                 "acpr"),
        ("Harmonics",            "harmonics"),
        ("PAE Sweep",            "pae_sweep"),
        ("Frequency Sweep",      "freq_sweep"),
        ("Load Measurement",     "load_measurement"),
        ("Save Results",         "save_results"),
    ],
    "Flow": [
        ("Group",             "group"),
        ("Loop",              "loop"),
        ("Wait",              "wait"),
        ("Message",           "message"),
        ("Conditional Abort", "cond_abort"),
    ],
    "SCPI": [
        ("SCPI Command",   "scpi_command"),
        ("SCPI Poll Loop", "scpi_poll"),
    ],
}

ACTION_DEFAULTS = {
    "set_gate_bias":  {"channel": "", "mode": "CV", "voltage": -3.0, "ocp": 0.1, "current": 0.01, "ovp": 5.0},
    "set_drain_bias": {"channel": "", "mode": "CV", "voltage": 28.0, "ocp": 2.0, "current": 1.0,  "ovp": 35.0,
                       "target_idq_ma": None, "tolerance_ma": 5, "gate_step_mv": 50, "hard_abort_ma": None},
    "ramp_up":             {"use_ramp_editor": True},
    "ramp_down":           {"use_ramp_editor": True},
    "output_on":           {"channel": ""},
    "output_off":          {"channel": ""},
    "bias_sweep":          {"channel": "", "start": -6.0, "stop": -2.0, "step": 0.5, "dwell_ms": 500},
    "idq_optimize":        {"drain_channel": "", "gate_channel": "",
                            "target_ma": 100.0, "tolerance_ma": 5.0,
                            "step_mv": 50.0, "max_ma": ""},
    "power_sweep":         {"start_dbm": -20.0, "stop_dbm": 10.0, "step_db": 1.0, "dwell_ms": 200, "drain_channel": "","drain_channel": ""},
    "perform_measurement": {"notes": ""},
    "gain_compression":    {"compression_db": 1.0, "start_dbm": -20.0, "stop_dbm": 20.0, "step_db": 0.5},
    "acpr":                {"center_hz": 1e9, "offset_hz": 5e6, "bw_hz": 1e6},
    "harmonics":           {"fundamental_hz": 1e9, "num_harmonics": 3},
    "pae_sweep":           {"start_dbm": -20.0, "stop_dbm": 10.0, "step_db": 1.0, "dwell_ms": 200},
    "freq_sweep":          {"start_hz": 1e9, "stop_hz": 4e9, "step_hz": 500e6, "power_dbm": 0.0},
    "load_measurement":    {"filepath": ""},
    "save_results":        {"filename": ""},
    "group":               {"label": "Group", "collapsed": False},
    "loop":                {"count": 3, "label": "Loop"},
    "wait":                {"seconds": 1.0, "label": ""},
    "message":             {"text": ""},
    "cond_abort":          {"channel": "", "threshold_ma": 500.0, "condition": ">"},
    "scpi_command":        {"instrument": "", "command": ""},
    "scpi_poll":           {"instrument": "", "query": "", "expected": "", "timeout_s": 10.0},
}

PLAN_FILE_EXT = ".axplan"
UNTITLED      = "Untitled"


class SweepPlanTab(ttk.Frame):

    def __init__(self, parent, driver_registry: dict):
        super().__init__(parent)
        self._registry     = driver_registry
        self._plan         = []
        self._current_file = None
        self._selected_idx = None
        self._sidebar_open = {}
        self._build_ui()
        self._aliases = {}
        self._engine   = None
        self._ramp_tab = None

    def set_driver_registry(self, registry: dict):
        self._registry = registry

    def set_ramp_tab_ref(self, ramp_tab):
        self._ramp_tab = ramp_tab

    # ══════════════════════════════════════════════════════════
    #  UI BUILD
    # ══════════════════════════════════════════════════════════
    def _build_ui(self):
        toolbar = ttk.Frame(self, relief="flat")
        toolbar.pack(fill="x", padx=6, pady=(6, 2))

        ttk.Button(toolbar, text="⬜ New",
                   command=self._new_plan).pack(side="left", padx=(0, 3))
        ttk.Button(toolbar, text="📂 Open",
                   command=self._open_plan).pack(side="left", padx=3)
        ttk.Button(toolbar, text="💾 Save",
                   command=self._save_plan).pack(side="left", padx=3)
        ttk.Button(toolbar, text="💾 Save As",
                   command=self._save_plan_as).pack(side="left", padx=3)

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)

        tk.Button(toolbar, text="  ▶  Run Plan  ",
                  bg="#1a7a1a", fg="white",
                  activebackground="#145a14", activeforeground="white",
                  font=("Segoe UI", 10, "bold"),
                  command=self._run_plan).pack(side="left", padx=3)
        tk.Button(toolbar, text="  ■  Stop  ",
                  bg="#8b0000", fg="white",
                  activebackground="#5a0000", activeforeground="white",
                  font=("Segoe UI", 10, "bold"),
                  command=self._stop_plan).pack(side="left", padx=3)

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)

        self._run_status_var = tk.StringVar(value="● Idle")
        self._run_status_lbl = tk.Label(toolbar, textvariable=self._run_status_var,
                                        fg="gray", font=("Segoe UI", 10, "bold"))
        self._run_status_lbl.pack(side="left", padx=4)

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Label(toolbar, text="Title:").pack(side="left", padx=(0, 4))
        self._title_var = tk.StringVar(value=UNTITLED)
        ttk.Entry(toolbar, textvariable=self._title_var, width=28).pack(side="left", padx=3)

        self._file_lbl = ttk.Label(toolbar, text="[unsaved]",
                                   foreground="gray", font=("Segoe UI", 8))
        self._file_lbl.pack(side="right", padx=8)

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=6)

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=6, pady=4)

        self._sidebar = ttk.Frame(body, width=190)
        self._sidebar.pack(side="left", fill="y", padx=(0, 4))
        self._sidebar.pack_propagate(False)
        self._build_sidebar()

        ttk.Separator(body, orient="vertical").pack(side="left", fill="y", padx=2)

        center = ttk.Frame(body)
        center.pack(side="left", fill="both", expand=True, padx=4)
        self._build_plan_list(center)

        ttk.Separator(body, orient="vertical").pack(side="left", fill="y", padx=2)

        self._props_frame = ttk.Frame(body, width=400)
        self._props_frame.pack(side="right", fill="y", padx=(4, 0))
        self._props_frame.pack_propagate(False)
        self._build_props_panel()

        self._status_var = tk.StringVar(value="Ready")
        ttk.Label(self, textvariable=self._status_var,
                  foreground="gray", font=("Segoe UI", 8)).pack(
                  anchor="w", padx=8, pady=(0, 4))

    def _set_run_status(self, state: str):
        styles = {
            "running":  ("● Running",  "#1a7a1a"),
            "stopped":  ("■ Stopped",  "#8b0000"),
            "complete": ("✔ Complete", "#1a5276"),
            "error":    ("✘ Error",    "#922b21"),
            "idle":     ("● Idle",     "gray"),
        }
        text, color = styles.get(state, ("● Idle", "gray"))
        self._run_status_var.set(text)
        self._run_status_lbl.config(fg=color)

    # ── Sidebar ────────────────────────────────────────────────
    def _build_sidebar(self):
        ttk.Label(self._sidebar, text="Actions",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=6, pady=(6, 2))

        container = ttk.Frame(self._sidebar)
        container.pack(fill="both", expand=True)

        scroll_canvas = tk.Canvas(container, highlightthickness=0)
        vsb = ttk.Scrollbar(container, orient="vertical", command=scroll_canvas.yview)
        scroll_canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        scroll_canvas.pack(side="left", fill="both", expand=True)

        inner = ttk.Frame(scroll_canvas)
        canvas_window = scroll_canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner_configure(event):
            scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all"))

        def _on_canvas_configure(event):
            scroll_canvas.itemconfig(canvas_window, width=event.width)

        inner.bind("<Configure>", _on_inner_configure)
        scroll_canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        scroll_canvas.bind("<MouseWheel>", _on_mousewheel)
        inner.bind("<MouseWheel>", _on_mousewheel)

        for category, actions in ACTION_CATEGORIES.items():
            self._sidebar_open[category] = True
            self._build_sidebar_category(inner, category, actions)

    def _build_sidebar_category(self, parent, category: str, actions: list):
        cat_frame = ttk.LabelFrame(parent, text="")
        cat_frame.pack(fill="x", padx=4, pady=2)

        header    = ttk.Frame(cat_frame)
        header.pack(fill="x")
        arrow_var = tk.StringVar(value="▼")
        arrow_lbl = ttk.Label(header, textvariable=arrow_var, width=2)
        arrow_lbl.pack(side="left", padx=(4, 0))
        ttk.Label(header, text=category,
                  font=("Segoe UI", 9, "bold")).pack(side="left", padx=4)

        action_container = ttk.Frame(cat_frame)
        action_container.pack(fill="x")

        def toggle():
            self._sidebar_open[category] = not self._sidebar_open[category]
            if self._sidebar_open[category]:
                action_container.pack(fill="x")
                arrow_var.set("▼")
            else:
                action_container.pack_forget()
                arrow_var.set("▶")

        header.bind("<Button-1>",    lambda e: toggle())
        arrow_lbl.bind("<Button-1>", lambda e: toggle())

        for display_name, action_type in actions:
            ttk.Button(
                action_container,
                text=f"  + {display_name}",
                command=lambda at=action_type, dn=display_name: self._add_step(at, dn)
            ).pack(fill="x", padx=6, pady=1)

    # ── Plan list ──────────────────────────────────────────────
    def _build_plan_list(self, parent):
        ttk.Label(parent, text="Sweep Plan",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 2))

        cols = ("#", "Step", "Summary")
        self.plan_tree = ttk.Treeview(parent, columns=cols, show="headings", height=22)
        self.plan_tree.heading("#",       text="#")
        self.plan_tree.heading("Step",    text="Step")
        self.plan_tree.heading("Summary", text="Summary")
        self.plan_tree.column("#",       width=40,  anchor="center")
        self.plan_tree.column("Step",    width=160, anchor="w")
        self.plan_tree.column("Summary", width=380, anchor="w")

        vsb = ttk.Scrollbar(parent, orient="vertical", command=self.plan_tree.yview)
        self.plan_tree.configure(yscrollcommand=vsb.set)
        self.plan_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.plan_tree.bind("<<TreeviewSelect>>", self._on_plan_select)
        self.plan_tree.bind("<Double-1>",          self._on_plan_double_click)

        row_btns = ttk.Frame(parent)
        row_btns.pack(fill="x", pady=4)
        ttk.Button(row_btns, text="🗑 Delete",
                   command=self._delete_step).pack(side="left", padx=3)
        ttk.Button(row_btns, text="⬆ Move Up",
                   command=lambda: self._move_step(-1)).pack(side="left", padx=3)
        ttk.Button(row_btns, text="⬇ Move Down",
                   command=lambda: self._move_step(1)).pack(side="left", padx=3)
        ttk.Button(row_btns, text="📋 Duplicate",
                   command=self._duplicate_step).pack(side="left", padx=3)

    # ── Properties panel shell ─────────────────────────────────
    def _build_props_panel(self):
        ttk.Label(self._props_frame, text="Properties",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=6, pady=(6, 2))

        canvas = tk.Canvas(self._props_frame, highlightthickness=0)
        vsb    = ttk.Scrollbar(self._props_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._props_inner = ttk.Frame(canvas)
        self._props_canvas_id = canvas.create_window((0, 0), window=self._props_inner, anchor="nw")

        def _on_frame_resize(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(self._props_canvas_id, width=event.width)

        self._props_inner.bind("<Configure>", _on_frame_resize)
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(self._props_canvas_id, width=e.width))

        self._show_props_placeholder()

    def _show_props_placeholder(self):
        for w in self._props_inner.winfo_children():
            w.destroy()
        ttk.Label(self._props_inner,
                  text="Select a step to\nedit its properties",
                  foreground="gray", font=("Segoe UI", 9),
                  justify="center").pack(expand=True, pady=40)

    # ══════════════════════════════════════════════════════════
    #  PROPERTIES DISPATCHER
    # ══════════════════════════════════════════════════════════
    def _show_props(self, idx: int):
        for w in self._props_inner.winfo_children():
            w.destroy()
        step = self._plan[idx]
        t    = step["type"]

        ttk.Label(self._props_inner, text=step["display_name"],
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=8, pady=(8, 0))
        ttk.Separator(self._props_inner, orient="horizontal").pack(fill="x", padx=8, pady=6)

        builders = {
            "set_gate_bias":        self._props_set_gate_bias,
            "set_drain_bias":       self._props_set_drain_bias,
            "ramp_up":              self._props_ramp_updown,
            "ramp_down":            self._props_ramp_updown,
            "output_on":            self._props_output_onoff,
            "output_off":           self._props_output_onoff,
            "bias_sweep":           self._props_bias_sweep,
            "idq_optimize":         self._props_idq_optimize,
            "power_sweep":          self._props_power_sweep,
            "perform_measurement":  self._props_perform_measurement,
            "gain_compression":     self._props_gain_compression,
            "acpr":                 self._props_acpr,
            "harmonics":            self._props_harmonics,
            "pae_sweep":            self._props_pae_sweep,
            "freq_sweep":           self._props_freq_sweep,
            "load_measurement":     self._props_load_measurement,
            "save_results":         self._props_save_results,
            # ── Flow ──────────────────────────────────────────
            "group":                self._props_group,
            "loop":                 self._props_loop,
            "wait":                 self._props_wait,
            "message":              self._props_message,
            "cond_abort":           self._props_cond_abort,
            # ── SCPI ──────────────────────────────────────────
            "scpi_command":         self._props_scpi_command,
            "scpi_poll":            self._props_scpi_poll,
        }

        builders.get(t, self._props_generic)(idx)

    # ══════════════════════════════════════════════════════════
    #  SHARED HELPERS
    # ══════════════════════════════════════════════════════════
    def get_channel_options(self) -> list:
        options = []
        for name, nch in PSU_CHANNEL_MAP.items():
            connected = name in self._registry
            tag   = "" if connected else " (not connected)"
            alias = self._aliases.get(name, "")
            label = f"{alias}  [{name}]" if alias else name
            for ch in range(1, nch + 1):
                options.append(f"{label}  CH{ch}{tag}")
        return options

    def _get_instrument_options(self) -> list:
        """Return all keys currently in the driver registry for SCPI dropdowns."""
        return sorted(self._registry.keys()) if self._registry else []

    def _field_row(self, parent, label: str, var: tk.Variable,
                   row: int, hint: str = "", width: int = 16):
        ttk.Label(parent, text=label, anchor="e",
                  width=20).grid(row=row, column=0, padx=(8, 4), pady=4, sticky="e")
        ent = ttk.Entry(parent, textvariable=var, width=width)
        ent.grid(row=row, column=1, padx=(0, 8), pady=4, sticky="w")
        if hint:
            ttk.Label(parent, text=hint, foreground="gray",
                      font=("Segoe UI", 8)).grid(row=row, column=2, padx=(0, 8), sticky="w")
        return ent

    def _channel_row(self, parent, label: str, var: tk.StringVar, row: int):
        ttk.Label(parent, text=label, anchor="e",
                  width=20).grid(row=row, column=0, padx=(8, 4), pady=4, sticky="e")
        cb = ttk.Combobox(parent, textvariable=var,
                          values=self.get_channel_options(),
                          width=28, state="normal")
        cb.grid(row=row, column=1, columnspan=2, padx=(0, 8), pady=4, sticky="w")
        ttk.Label(parent, text="Type or select — no pairing required",
                  foreground="gray", font=("Segoe UI", 7)).grid(
                  row=row + 1, column=1, columnspan=2, padx=(0, 8), sticky="w")

    def _instrument_row(self, parent, label: str, var: tk.StringVar, row: int):
        """Combobox row populated from the live driver registry."""
        ttk.Label(parent, text=label, anchor="e",
                  width=20).grid(row=row, column=0, padx=(8, 4), pady=4, sticky="e")
        cb = ttk.Combobox(parent, textvariable=var,
                          values=self._get_instrument_options(),
                          width=28, state="normal")
        cb.grid(row=row, column=1, columnspan=2, padx=(0, 8), pady=4, sticky="w")
        ttk.Label(parent, text="Type instrument name or select from connected",
                  foreground="gray", font=("Segoe UI", 7)).grid(
                  row=row + 1, column=1, columnspan=2, padx=(0, 8), sticky="w")

    def _apply_btn(self, parent, row: int, fn):
        ttk.Button(parent, text="Apply to Step", command=fn).grid(
            row=row, column=0, columnspan=3, pady=12, padx=8, sticky="ew")

    # ══════════════════════════════════════════════════════════
    #  BIASING PROPERTY PANELS
    # ══════════════════════════════════════════════════════════
    def _props_set_gate_bias(self, idx: int):
        p = self._plan[idx]["params"]
        f = ttk.Frame(self._props_inner)
        f.pack(fill="x", padx=4)

        ttk.Label(f, text="Output Mode", font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, columnspan=3, padx=8, pady=(8, 2), sticky="w")

        modevar = tk.StringVar(value=p.get("mode", "CV"))
        ttk.Radiobutton(f, text="CV — Constant Voltage", variable=modevar, value="CV").grid(
            row=1, column=0, columnspan=3, padx=16, sticky="w")
        ttk.Radiobutton(f, text="CC — Constant Current", variable=modevar, value="CC").grid(
            row=2, column=0, columnspan=3, padx=16, sticky="w")

        ttk.Separator(f, orient="horizontal").grid(
            row=3, column=0, columnspan=3, sticky="ew", padx=8, pady=6)

        ttk.Label(f, text="Values", font=("Segoe UI", 9, "bold")).grid(
            row=4, column=0, columnspan=3, padx=8, pady=(0, 2), sticky="w")

        chvar   = tk.StringVar(value=p.get("channel", ""))
        voltvar = tk.StringVar(value=str(p.get("voltage", -3.0)))
        ocpvar  = tk.StringVar(value=str(p.get("ocp", 0.1)))
        currvar = tk.StringVar(value=str(p.get("current", 0.01)))
        ovpvar  = tk.StringVar(value=str(p.get("ovp", 5.0)))

        self._channel_row(f, "Channel", chvar, 5)

        cv_frame = ttk.Frame(f)
        cv_frame.grid(row=7, column=0, columnspan=3, sticky="ew")
        self._field_row(cv_frame, "Set Voltage (V):", voltvar, 0, hint="Negative for GaN gate")
        self._field_row(cv_frame, "OCP Limit (A):", ocpvar, 1, hint="Current protection")
        warnlbl = ttk.Label(cv_frame, text="", foreground="orange",
                            font=("Segoe UI", 8), wraplength=220)
        warnlbl.grid(row=2, column=0, columnspan=3, padx=8, pady=(0, 4))

        def check_volt(*_):
            try:
                v = float(voltvar.get())
                warnlbl.config(text="Gate voltage is positive — GaN gate should be ≤ 0 V" if v > 0 else "")
            except ValueError:
                warnlbl.config(text="Enter a valid number", foreground="red")
        voltvar.trace_add("write", check_volt)
        check_volt()

        cc_frame = ttk.Frame(f)
        cc_frame.grid(row=7, column=0, columnspan=3, sticky="ew")
        self._field_row(cc_frame, "Set Current (A):", currvar, 0)
        self._field_row(cc_frame, "OVP Limit (V):", ovpvar, 1, hint="Voltage protection")

        def toggle_mode(*_):
            if modevar.get() == "CV":
                cc_frame.grid_remove()
                cv_frame.grid()
            else:
                cv_frame.grid_remove()
                cc_frame.grid()

        modevar.trace_add("write", toggle_mode)
        toggle_mode()

        def apply():
            try:
                if modevar.get() == "CV":
                    v = float(voltvar.get())
                    a = float(ocpvar.get())
                    if v > 0 and not messagebox.askyesno(
                            "Gate Warning",
                            f"Gate voltage {v} V is positive. GaN gate should normally be ≤ 0 V. Continue?"):
                        return
                    self._plan[idx]["params"].update(mode="CV", channel=chvar.get(), voltage=v, ocp=a)
                else:
                    c = float(currvar.get())
                    o = float(ovpvar.get())
                    self._plan[idx]["params"].update(mode="CC", channel=chvar.get(), current=c, ovp=o)
            except ValueError:
                messagebox.showerror("Invalid Input", "All fields must be numbers.")
                return
            self._refresh_plan_tree()
            self._set_status(f"Step {idx+1} updated — Gate bias")

        self._apply_btn(f, 8, apply)

    def _props_set_drain_bias(self, idx: int):
        p = self._plan[idx]["params"]
        f = ttk.Frame(self._props_inner)
        f.pack(fill="x", padx=4)

        ttk.Label(f, text="Output Mode", font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, columnspan=3, padx=8, pady=(8, 2), sticky="w")

        modevar = tk.StringVar(value=p.get("mode", "CV"))
        ttk.Radiobutton(f, text="CV — Constant Voltage", variable=modevar, value="CV").grid(
            row=1, column=0, columnspan=3, padx=16, sticky="w")
        ttk.Radiobutton(f, text="CC — Constant Current", variable=modevar, value="CC").grid(
            row=2, column=0, columnspan=3, padx=16, sticky="w")

        ttk.Separator(f, orient="horizontal").grid(
            row=3, column=0, columnspan=3, sticky="ew", padx=8, pady=6)

        ttk.Label(f, text="Values", font=("Segoe UI", 9, "bold")).grid(
            row=4, column=0, columnspan=3, padx=8, pady=(0, 2), sticky="w")

        chvar   = tk.StringVar(value=p.get("channel", ""))
        voltvar = tk.StringVar(value=str(p.get("voltage", 28.0)))
        ocpvar  = tk.StringVar(value=str(p.get("ocp", 2.0)))
        currvar = tk.StringVar(value=str(p.get("current", 1.0)))
        ovpvar  = tk.StringVar(value=str(p.get("ovp", 35.0)))

        self._channel_row(f, "Channel", chvar, 5)

        cv_frame = ttk.Frame(f)
        cv_frame.grid(row=7, column=0, columnspan=3, sticky="ew")
        self._field_row(cv_frame, "Set Voltage (V):", voltvar, 0)
        self._field_row(cv_frame, "OCP Limit (A):", ocpvar, 1, hint="Current protection")
        warnlbl = ttk.Label(cv_frame, text="", foreground="orange",
                            font=("Segoe UI", 8), wraplength=220)
        warnlbl.grid(row=2, column=0, columnspan=3, padx=8, pady=(0, 4))

        def check_volt(*_):
            try:
                v = float(voltvar.get())
                if v > 60:
                    warnlbl.config(text="Drain voltage > 60 V — check supply rating", foreground="red")
                elif v < 0:
                    warnlbl.config(text="Negative drain voltage", foreground="orange")
                else:
                    warnlbl.config(text="")
            except ValueError:
                pass
        voltvar.trace_add("write", check_volt)
        check_volt()

        cc_frame = ttk.Frame(f)
        cc_frame.grid(row=7, column=0, columnspan=3, sticky="ew")
        self._field_row(cc_frame, "Set Current (A):", currvar, 0)
        self._field_row(cc_frame, "OVP Limit (V):", ovpvar, 1, hint="Voltage protection")

        def toggle_mode(*_):
            if modevar.get() == "CV":
                cc_frame.grid_remove()
                cv_frame.grid()
            else:
                cv_frame.grid_remove()
                cc_frame.grid()

        modevar.trace_add("write", toggle_mode)
        toggle_mode()

        ttk.Separator(f, orient="horizontal").grid(
            row=8, column=0, columnspan=3, sticky="ew", padx=8, pady=8)

        ttk.Label(f, text="Idq Targeting  (Drain channel only)",
                  font=("Segoe UI", 9, "bold")).grid(
                  row=9, column=0, columnspan=3, padx=8, pady=(0, 2), sticky="w")
        ttk.Label(f, text="Set on the DRAIN channel. The sequencer walks gate voltage\n"
                          "toward final gate V while monitoring drain current.",
                  foreground="gray", font=("Segoe UI", 7), justify="left").grid(
                  row=10, column=0, columnspan=3, padx=8, sticky="w")

        targetvar = tk.StringVar(value=str(p.get("target_idq_ma", "")))
        tolvar    = tk.StringVar(value=str(p.get("tolerance_ma", 5)))
        stepvar   = tk.StringVar(value=str(p.get("gate_step_mv", 50)))
        abortvar  = tk.StringVar(value=str(p.get("hard_abort_ma", "")))

        self._field_row(f, "Target Idq (mA):", targetvar, 11, hint="Leave blank to skip")
        self._field_row(f, "Tolerance ± (mA):", tolvar,   12, hint="Default: 5 mA")
        self._field_row(f, "Gate Step Size (mV):", stepvar, 13, hint="Default: 50 mV")
        self._field_row(f, "Hard Abort > (mA):", abortvar, 14, hint="Leave blank = 3× target")

        def apply():
            try:
                if modevar.get() == "CV":
                    v = float(voltvar.get())
                    a = float(ocpvar.get())
                    self._plan[idx]["params"].update(mode="CV", channel=chvar.get(), voltage=v, ocp=a)
                else:
                    c = float(currvar.get())
                    o = float(ovpvar.get())
                    self._plan[idx]["params"].update(mode="CC", channel=chvar.get(), current=c, ovp=o)
                self._plan[idx]["params"].update(
                    target_idq_ma=float(targetvar.get()) if targetvar.get().strip() else None,
                    tolerance_ma=float(tolvar.get()),
                    gate_step_mv=float(stepvar.get()),
                    hard_abort_ma=float(abortvar.get()) if abortvar.get().strip() else None,
                )
            except ValueError:
                messagebox.showerror("Invalid Input", "All fields must be numbers.")
                return
            self._refresh_plan_tree()
            self._set_status(f"Step {idx+1} updated — Drain bias")

        self._apply_btn(f, 15, apply)

    def _props_ramp_updown(self, idx: int):
        p = self._plan[idx]["params"]
        f = ttk.Frame(self._props_inner)
        f.pack(fill="x", padx=4)

        use_var = tk.BooleanVar(value=p.get("use_ramp_editor", True))
        ttk.Checkbutton(f, text="Use steps from Ramp Editor tab",
                        variable=use_var).grid(row=0, column=0, columnspan=3,
                                               padx=8, pady=(4, 8), sticky="w")
        ttk.Label(f, text="When checked the sequencer executes the steps\n"
                          "currently saved in the Ramp Editor.\n"
                          "Uncheck to override with a manual voltage below.",
                  foreground="gray", font=("Segoe UI", 8), justify="left").grid(
                  row=1, column=0, columnspan=3, padx=8, pady=(0, 8), sticky="w")

        ch_var   = tk.StringVar(value=p.get("channel", ""))
        volt_var = tk.StringVar(value=str(p.get("voltage", 0.0)))
        ocp_var  = tk.StringVar(value=str(p.get("ocp", 1.0)))

        override_frame = ttk.LabelFrame(f, text="Manual Override")
        override_frame.grid(row=2, column=0, columnspan=3, padx=8, pady=4, sticky="ew")
        self._channel_row(override_frame, "Channel:", ch_var, 0)
        self._field_row(override_frame, "Voltage (V):", volt_var, 2)
        self._field_row(override_frame, "OCP (A):", ocp_var, 3)

        def _toggle_override(*_):
            state = "disabled" if use_var.get() else "normal"
            for child in override_frame.winfo_children():
                try:
                    child.configure(state=state)
                except tk.TclError:
                    pass

        use_var.trace_add("write", _toggle_override)
        _toggle_override()

        def apply():
            self._plan[idx]["params"]["use_ramp_editor"] = use_var.get()
            if not use_var.get():
                try:
                    self._plan[idx]["params"].update({
                        "channel": ch_var.get(),
                        "voltage": float(volt_var.get()),
                        "ocp":     float(ocp_var.get()),
                    })
                except ValueError:
                    messagebox.showerror("Invalid Input", "Voltage and OCP must be numbers.")
                    return
            self._refresh_plan_tree()
            self._set_status(f"Step {idx+1}: {'Ramp Editor' if use_var.get() else 'Manual override'}")

        self._apply_btn(f, 3, apply)

    def _props_output_onoff(self, idx: int):
        p  = self._plan[idx]["params"]
        t  = self._plan[idx]["type"]
        f  = ttk.Frame(self._props_inner)
        f.pack(fill="x", padx=4)

        is_on = (t == "output_on")
        color = "#1a7a1a" if is_on else "#8b0000"
        tk.Label(f, text="ON" if is_on else "OFF",
                 bg=color, fg="white", font=("Segoe UI", 14, "bold"),
                 width=6).grid(row=0, column=0, columnspan=3, padx=8, pady=(4, 8))
        ttk.Label(f, text="Turn ON the selected channel output" if is_on
                  else "Turn OFF the selected channel output",
                  foreground="gray", font=("Segoe UI", 8)).grid(
                  row=1, column=0, columnspan=3, padx=8, pady=(0, 8))

        ch_var = tk.StringVar(value=p.get("channel", ""))
        self._channel_row(f, "Channel:", ch_var, 2)

        def apply():
            self._plan[idx]["params"]["channel"] = ch_var.get()
            self._refresh_plan_tree()
            self._set_status(f"Step {idx+1}: Output {'ON' if is_on else 'OFF'} → {ch_var.get()}")

        self._apply_btn(f, 4, apply)

    def _props_bias_sweep(self, idx: int):
        p = self._plan[idx]["params"]
        f = ttk.Frame(self._props_inner)
        f.pack(fill="x", padx=4)

        ch_var    = tk.StringVar(value=p.get("channel", ""))
        start_var = tk.StringVar(value=str(p.get("start",   -6.0)))
        stop_var  = tk.StringVar(value=str(p.get("stop",    -2.0)))
        step_var  = tk.StringVar(value=str(p.get("step",     0.5)))
        dwell_var = tk.StringVar(value=str(p.get("dwell_ms", 500)))
        drain_var = tk.StringVar(value=str(p.get("drain_channel", "")))
        freq_var  = tk.StringVar(value=str(p.get("freq_ghz", "")))
        
        self._channel_row(f, "Channel:",  ch_var,   0)
        self._field_row(f, "Start (V):",  start_var, 2, hint="e.g. -6.0")
        self._field_row(f, "Stop (V):",   stop_var,  3, hint="e.g. -2.0")
        self._field_row(f, "Step (V):",   step_var,  4, hint="e.g. 0.5")
        self._field_row(f, "Dwell (ms):", dwell_var, 5, hint="Settle time per point")
        self._field_row(f, "Freq (GHz):",  freq_var,  4, hint="e.g. 2.4  — logged to CSV")
        
        ttk.Separator(f, orient="horizontal").grid(
            row=5, column=0, columnspan=3, sticky="ew", padx=8, pady=6)
        ttk.Label(f, text="DC Logging", font=("Segoe UI", 9, "bold")).grid(
            row=6, column=0, columnspan=3, padx=8, sticky="w")
        ttk.Label(f, text="Select drain channel to log Vdd, Idd, PAE, DE per point.",
                  foreground="gray", font=("Segoe UI", 7), justify="left").grid(
                  row=7, column=0, columnspan=3, padx=8, sticky="w")
        self._channel_row(f, "Drain Channel:", drain_var, 8)


        preview_lbl = ttk.Label(f, text="", foreground="gray", font=("Segoe UI", 8))
        preview_lbl.grid(row=6, column=0, columnspan=3, padx=8, pady=(0, 4))

        def _update_preview(*_):
            try:
                n = abs(float(stop_var.get()) - float(start_var.get())) / float(step_var.get())
                preview_lbl.config(text=f"≈ {int(n)+1} points  est. {(int(n)+1)*int(dwell_var.get())/1000:.1f} s")
            except (ValueError, ZeroDivisionError):
                preview_lbl.config(text="")

        for v in (start_var, stop_var, step_var, dwell_var):
            v.trace_add("write", _update_preview)
        _update_preview()

        def apply():
            try:
                params = {
                    "start_dbm":     float(start_var.get()),
                    "stop_dbm":      float(stop_var.get()),
                    "step_db":       float(step_var.get()),
                    "dwell_ms":      int(dwell_var.get()),
                    "freq_ghz":      freq_var.get().strip(),
                    "drain_channel": drain_var.get().strip(),
                }
            except ValueError:
                messagebox.showerror("Invalid Input", "All fields must be valid numbers.")
                return
            if params["step_db"] <= 0:
                messagebox.showerror("Invalid Step", "Step must be > 0.")
                return
            self._get_step(path)["params"].update(params)
            self._refresh_plan_tree()
            self._set_status(f"Step {self._path_label(path)} updated: Power sweep")
        self._apply_btn(f, 11, apply)


    def _props_idq_optimize(self, idx: int):
        p = self._plan[idx]["params"]
        f = ttk.Frame(self._props_inner)
        f.pack(fill="x", padx=4)

        ttk.Label(f, text="Walks gate voltage until drain current\n"
                          "reaches the target Idq ± tolerance.",
                  foreground="gray", font=("Segoe UI", 8), justify="left").grid(
                  row=0, column=0, columnspan=3, padx=8, pady=(0, 8), sticky="w")

        drain_ch_var = tk.StringVar(value=p.get("drain_channel", ""))
        gate_ch_var  = tk.StringVar(value=p.get("gate_channel",  ""))
        target_var   = tk.StringVar(value=str(p.get("target_ma",    100.0)))
        tol_var      = tk.StringVar(value=str(p.get("tolerance_ma",   5.0)))
        step_var     = tk.StringVar(value=str(p.get("step_mv",        50.0)))
        max_var      = tk.StringVar(value=str(p.get("max_ma",          "")))

        self._channel_row(f, "Drain Channel:", drain_ch_var, 1)
        self._channel_row(f, "Gate Channel:",  gate_ch_var,  3)
        self._field_row(f, "Target Idq (mA):", target_var, 5)
        self._field_row(f, "Tolerance (mA):",  tol_var,    6, hint="Default ±5 mA")
        self._field_row(f, "Gate Step (mV):",  step_var,   7, hint="Default 50 mV")
        self._field_row(f, "Abort if > (mA):", max_var,    8, hint="Blank = 3× target")

        def apply():
            try:
                params = {
                    "drain_channel": drain_ch_var.get(),
                    "gate_channel":  gate_ch_var.get(),
                    "target_ma":     float(target_var.get()),
                    "tolerance_ma":  float(tol_var.get()),
                    "step_mv":       float(step_var.get()),
                    "max_ma": float(max_var.get()) if max_var.get().strip() else "",
                }
            except ValueError:
                messagebox.showerror("Invalid Input", "All numeric fields must be valid numbers.")
                return
            self._plan[idx]["params"].update(params)
            self._refresh_plan_tree()
            self._set_status(f"Step {idx+1} updated: Idq optimize {params['target_ma']} mA")

        self._apply_btn(f, 9, apply)

    # ══════════════════════════════════════════════════════════
    #  MEASUREMENT PROPERTY PANELS
    # ══════════════════════════════════════════════════════════
    def _props_power_sweep(self, idx: int):
        p = self._plan[idx]["params"]
        f = ttk.Frame(self._props_inner)
        f.pack(fill="x", padx=4)

        ttk.Label(f, text="Sweeps input power from Start to Stop.\n"
                          "Records Pout, Gain, and PDC at each point.",
                  foreground="gray", font=("Segoe UI", 8), justify="left").grid(
                  row=0, column=0, columnspan=3, padx=8, pady=(0, 8), sticky="w")

        start_var = tk.StringVar(value=str(p.get("start_dbm", -20.0)))
        stop_var  = tk.StringVar(value=str(p.get("stop_dbm",   10.0)))
        step_var  = tk.StringVar(value=str(p.get("step_db",     1.0)))
        dwell_var = tk.StringVar(value=str(p.get("dwell_ms",   200)))

        self._field_row(f, "Start (dBm):", start_var, 1, hint="e.g. -20")
        self._field_row(f, "Stop (dBm):",  stop_var,  2, hint="e.g. 10")
        self._field_row(f, "Step (dB):",   step_var,  3, hint="e.g. 1.0")
        self._field_row(f, "Dwell (ms):",  dwell_var, 4, hint="Per point settle")

        preview_lbl = ttk.Label(f, text="", foreground="gray", font=("Segoe UI", 8))
        preview_lbl.grid(row=5, column=0, columnspan=3, padx=8, pady=(0, 4))

        def _update_preview(*_):
            try:
                n = abs(float(stop_var.get()) - float(start_var.get())) / float(step_var.get())
                preview_lbl.config(text=f"≈ {int(n)+1} points  est. {(int(n)+1)*int(dwell_var.get())/1000:.1f} s")
            except (ValueError, ZeroDivisionError):
                preview_lbl.config(text="")

        for v in (start_var, stop_var, step_var, dwell_var):
            v.trace_add("write", _update_preview)
        _update_preview()

        def apply():
            try:
                params = {
                    "start_dbm": float(start_var.get()),
                    "stop_dbm":  float(stop_var.get()),
                    "step_db":   float(step_var.get()),
                    "dwell_ms":  int(dwell_var.get()),
                }
            except ValueError:
                messagebox.showerror("Invalid Input", "All fields must be valid numbers.")
                return
            if params["step_db"] <= 0:
                messagebox.showerror("Invalid Step", "Step must be greater than 0.")
                return
            self._plan[idx]["params"].update(params)
            self._refresh_plan_tree()
            self._set_status(f"Step {idx+1} updated: Power sweep")

        self._apply_btn(f, 6, apply)

    def _props_perform_measurement(self, idx: int):
        p = self._plan[idx]["params"]
        f = ttk.Frame(self._props_inner)
        f.pack(fill="x", padx=4)

        ttk.Label(f, text="Triggers a single acquisition from the\n"
                          "Spectrum Analyzer at the current settings.",
                  foreground="gray", font=("Segoe UI", 8), justify="left").grid(
                  row=0, column=0, columnspan=3, padx=8, pady=(0, 8), sticky="w")

        notes_var = tk.StringVar(value=p.get("notes", ""))
        self._field_row(f, "Notes / Label:", notes_var, 1,
                        hint="Logged to session CSV", width=22)

        def apply():
            self._plan[idx]["params"]["notes"] = notes_var.get()
            self._refresh_plan_tree()
            self._set_status(f"Step {idx+1} updated: Perform measurement")

        self._apply_btn(f, 2, apply)

    def _props_gain_compression(self, idx: int):
        p = self._plan[idx]["params"]
        f = ttk.Frame(self._props_inner)
        f.pack(fill="x", padx=4)

        ttk.Label(f, text="Sweeps Pin upward and finds the point\n"
                          "where gain drops by the specified amount.",
                  foreground="gray", font=("Segoe UI", 8), justify="left").grid(
                  row=0, column=0, columnspan=3, padx=8, pady=(0, 8), sticky="w")

        comp_var  = tk.StringVar(value=str(p.get("compression_db", 1.0)))
        start_var = tk.StringVar(value=str(p.get("start_dbm",    -20.0)))
        stop_var  = tk.StringVar(value=str(p.get("stop_dbm",      20.0)))
        step_var  = tk.StringVar(value=str(p.get("step_db",        0.5)))

        self._field_row(f, "Compression (dB):", comp_var,  1, hint="Typically 1 dB")
        self._field_row(f, "Start (dBm):",      start_var, 2)
        self._field_row(f, "Stop (dBm):",       stop_var,  3)
        self._field_row(f, "Step (dB):",        step_var,  4)

        def apply():
            try:
                params = {
                    "compression_db": float(comp_var.get()),
                    "start_dbm":      float(start_var.get()),
                    "stop_dbm":       float(stop_var.get()),
                    "step_db":        float(step_var.get()),
                }
            except ValueError:
                messagebox.showerror("Invalid Input", "All fields must be valid numbers.")
                return
            self._plan[idx]["params"].update(params)
            self._refresh_plan_tree()
            self._set_status(f"Step {idx+1} updated: P{params['compression_db']}dB compression")

        self._apply_btn(f, 5, apply)

    def _props_acpr(self, idx: int):
        p = self._plan[idx]["params"]
        f = ttk.Frame(self._props_inner)
        f.pack(fill="x", padx=4)

        ttk.Label(f, text="Measures Adjacent Channel Power Ratio\n"
                          "using the Spectrum Analyzer.",
                  foreground="gray", font=("Segoe UI", 8), justify="left").grid(
                  row=0, column=0, columnspan=3, padx=8, pady=(0, 8), sticky="w")

        center_var = tk.StringVar(value=str(p.get("center_hz", 1e9) / 1e9))
        offset_var = tk.StringVar(value=str(p.get("offset_hz", 5e6) / 1e6))
        bw_var     = tk.StringVar(value=str(p.get("bw_hz",     1e6) / 1e6))

        self._field_row(f, "Center Freq (GHz):",    center_var, 1)
        self._field_row(f, "Channel Offset (MHz):", offset_var, 2, hint="Distance to adj channel")
        self._field_row(f, "Channel BW (MHz):",     bw_var,     3, hint="Integration bandwidth")

        def apply():
            try:
                params = {
                    "center_hz": float(center_var.get()) * 1e9,
                    "offset_hz": float(offset_var.get()) * 1e6,
                    "bw_hz":     float(bw_var.get())     * 1e6,
                }
            except ValueError:
                messagebox.showerror("Invalid Input", "All fields must be valid numbers.")
                return
            self._plan[idx]["params"].update(params)
            self._refresh_plan_tree()
            self._set_status(f"Step {idx+1} updated: ACPR")

        self._apply_btn(f, 4, apply)

    def _props_harmonics(self, idx: int):
        p = self._plan[idx]["params"]
        f = ttk.Frame(self._props_inner)
        f.pack(fill="x", padx=4)

        ttk.Label(f, text="Measures 2nd and 3rd (and higher) harmonic\n"
                          "levels relative to the fundamental.",
                  foreground="gray", font=("Segoe UI", 8), justify="left").grid(
                  row=0, column=0, columnspan=3, padx=8, pady=(0, 8), sticky="w")

        fund_var = tk.StringVar(value=str(p.get("fundamental_hz", 1e9) / 1e9))
        n_var    = tk.StringVar(value=str(p.get("num_harmonics", 3)))

        self._field_row(f, "Fundamental (GHz):", fund_var, 1)
        self._field_row(f, "Num Harmonics:",     n_var,    2, hint="2 = 2nd only,  3 = 2nd+3rd")

        def apply():
            try:
                params = {
                    "fundamental_hz": float(fund_var.get()) * 1e9,
                    "num_harmonics":  int(n_var.get()),
                }
            except ValueError:
                messagebox.showerror("Invalid Input", "All fields must be valid numbers.")
                return
            self._plan[idx]["params"].update(params)
            self._refresh_plan_tree()
            self._set_status(f"Step {idx+1} updated: Harmonics")

        self._apply_btn(f, 3, apply)

    def _props_pae_sweep(self, idx: int):
        p = self._plan[idx]["params"]
        f = ttk.Frame(self._props_inner)
        f.pack(fill="x", padx=4)

        ttk.Label(f, text="Sweeps Pin and records Pout, Gain,\nPDC, and PAE at each point.",
                  foreground="gray", font=("Segoe UI", 8), justify="left").grid(
                  row=0, column=0, columnspan=3, padx=8, pady=(0, 8), sticky="w")

        start_var = tk.StringVar(value=str(p.get("start_dbm", -20.0)))
        stop_var  = tk.StringVar(value=str(p.get("stop_dbm",   10.0)))
        step_var  = tk.StringVar(value=str(p.get("step_db",     1.0)))
        dwell_var = tk.StringVar(value=str(p.get("dwell_ms",   200)))

        self._field_row(f, "Start (dBm):", start_var, 1)
        self._field_row(f, "Stop (dBm):",  stop_var,  2)
        self._field_row(f, "Step (dB):",   step_var,  3)
        self._field_row(f, "Dwell (ms):",  dwell_var, 4)

        ttk.Label(f, text="⚠ Requires DMM live polling to be active\n"
                          "for accurate PDC / PAE calculation.",
                  foreground="orange", font=("Segoe UI", 8), justify="left").grid(
                  row=5, column=0, columnspan=3, padx=8, pady=(4, 4), sticky="w")

        def apply():
            try:
                params = {
                    "start_dbm": float(start_var.get()),
                    "stop_dbm":  float(stop_var.get()),
                    "step_db":   float(step_var.get()),
                    "dwell_ms":  int(dwell_var.get()),
                }
            except ValueError:
                messagebox.showerror("Invalid Input", "All fields must be valid numbers.")
                return
            self._plan[idx]["params"].update(params)
            self._refresh_plan_tree()
            self._set_status(f"Step {idx+1} updated: PAE sweep")

        self._apply_btn(f, 6, apply)

    def _props_freq_sweep(self, idx: int):
        p = self._plan[idx]["params"]
        f = ttk.Frame(self._props_inner)
        f.pack(fill="x", padx=4)

        ttk.Label(f, text="Outer loop — steps the signal generator\n"
                          "frequency and performs a power sweep at each.",
                  foreground="gray", font=("Segoe UI", 8), justify="left").grid(
                  row=0, column=0, columnspan=3, padx=8, pady=(0, 8), sticky="w")

        start_var = tk.StringVar(value=str(p.get("start_hz", 1e9)   / 1e9))
        stop_var  = tk.StringVar(value=str(p.get("stop_hz",  4e9)   / 1e9))
        step_var  = tk.StringVar(value=str(p.get("step_hz",  500e6) / 1e6))
        pwr_var   = tk.StringVar(value=str(p.get("power_dbm", 0.0)))

        self._field_row(f, "Start (GHz):", start_var, 1)
        self._field_row(f, "Stop (GHz):",  stop_var,  2)
        self._field_row(f, "Step (MHz):",  step_var,  3)
        self._field_row(f, "Power (dBm):", pwr_var,   4, hint="Fixed Pin at each freq")

        preview_lbl = ttk.Label(f, text="", foreground="gray", font=("Segoe UI", 8))
        preview_lbl.grid(row=5, column=0, columnspan=3, padx=8, pady=(0, 4))

        def _update_preview(*_):
            try:
                n = abs(float(stop_var.get()) - float(start_var.get())) * 1e3 / float(step_var.get())
                preview_lbl.config(text=f"≈ {int(n)+1} frequency points")
            except (ValueError, ZeroDivisionError):
                preview_lbl.config(text="")

        for v in (start_var, stop_var, step_var):
            v.trace_add("write", _update_preview)
        _update_preview()

        def apply():
            try:
                params = {
                    "start_hz":  float(start_var.get()) * 1e9,
                    "stop_hz":   float(stop_var.get())  * 1e9,
                    "step_hz":   float(step_var.get())  * 1e6,
                    "power_dbm": float(pwr_var.get()),
                }
            except ValueError:
                messagebox.showerror("Invalid Input", "All fields must be valid numbers.")
                return
            self._plan[idx]["params"].update(params)
            self._refresh_plan_tree()
            self._set_status(f"Step {idx+1} updated: Frequency sweep")

        self._apply_btn(f, 6, apply)

    def _props_load_measurement(self, idx: int):
        p = self._plan[idx]["params"]
        f = ttk.Frame(self._props_inner)
        f.pack(fill="x", padx=4)

        ttk.Label(f, text="Load a previously saved result file\n"
                          "into the current session for comparison.",
                  foreground="gray", font=("Segoe UI", 8), justify="left").grid(
                  row=0, column=0, columnspan=3, padx=8, pady=(0, 8), sticky="w")

        path_var = tk.StringVar(value=p.get("filepath", ""))
        self._field_row(f, "File path:", path_var, 1, width=22)

        def browse():
            path = filedialog.askopenfilename(
                title="Select Measurement File",
                filetypes=[("CSV", "*.csv"), ("JSON", "*.json"), ("All Files", "*.*")])
            if path:
                path_var.set(path)

        ttk.Button(f, text="Browse…", command=browse).grid(row=1, column=2, padx=4, pady=4)

        def apply():
            self._plan[idx]["params"]["filepath"] = path_var.get()
            self._refresh_plan_tree()
            self._set_status(f"Step {idx+1} updated: Load measurement")

        self._apply_btn(f, 2, apply)

    def _props_save_results(self, idx: int):
        p = self._plan[idx]["params"]
        f = ttk.Frame(self._props_inner)
        f.pack(fill="x", padx=4)

        ttk.Label(f, text="Write current session results to CSV\nat this point in the plan.",
                  foreground="gray", font=("Segoe UI", 8), justify="left").grid(
                  row=0, column=0, columnspan=3, padx=8, pady=(0, 8), sticky="w")

        name_var = tk.StringVar(value=p.get("filename", ""))
        self._field_row(f, "Filename:", name_var, 1, hint="Blank = auto timestamp", width=22)

        ttk.Label(f, text="File saved to session_logs/[timestamp]/",
                  foreground="gray", font=("Segoe UI", 8)).grid(
                  row=2, column=0, columnspan=3, padx=8, pady=(0, 4), sticky="w")

        def apply():
            self._plan[idx]["params"]["filename"] = name_var.get()
            self._refresh_plan_tree()
            self._set_status(f"Step {idx+1} updated: Save results")

        self._apply_btn(f, 3, apply)

    # ══════════════════════════════════════════════════════════
    #  FLOW PROPERTY PANELS
    # ══════════════════════════════════════════════════════════
    def _props_group(self, idx: int):
        p = self._plan[idx]["params"]
        f = ttk.Frame(self._props_inner)
        f.pack(fill="x", padx=4)

        ttk.Label(f, text="Visual grouping only — no runtime effect.\n"
                          "Use to organise related steps together.",
                  foreground="gray", font=("Segoe UI", 8), justify="left").grid(
                  row=0, column=0, columnspan=3, padx=8, pady=(0, 8), sticky="w")

        label_var     = tk.StringVar(value=p.get("label", "Group"))
        collapsed_var = tk.BooleanVar(value=p.get("collapsed", False))

        self._field_row(f, "Group Label:", label_var, 1, hint="Shown in plan tree", width=22)
        ttk.Checkbutton(f, text="Collapsed by default",
                        variable=collapsed_var).grid(
                        row=2, column=0, columnspan=3, padx=12, pady=4, sticky="w")

        def apply():
            self._plan[idx]["params"]["label"]     = label_var.get()
            self._plan[idx]["params"]["collapsed"] = collapsed_var.get()
            self._plan[idx]["display_name"]        = label_var.get() or "Group"
            self._refresh_plan_tree()
            self._set_status(f"Step {idx+1} updated: Group '{label_var.get()}'")

        self._apply_btn(f, 3, apply)

    def _props_loop(self, idx: int):
        p = self._plan[idx]["params"]
        f = ttk.Frame(self._props_inner)
        f.pack(fill="x", padx=4)

        ttk.Label(f, text="Repeat all steps inside this loop block\n"
                          "N times before continuing.",
                  foreground="gray", font=("Segoe UI", 8), justify="left").grid(
                  row=0, column=0, columnspan=3, padx=8, pady=(0, 8), sticky="w")

        count_var = tk.IntVar(value=int(p.get("count", 3)))
        label_var = tk.StringVar(value=p.get("label", "Loop"))

        ttk.Label(f, text="Iterations:", anchor="e", width=20).grid(
            row=1, column=0, padx=(8, 4), pady=4, sticky="e")
        spin = ttk.Spinbox(f, from_=1, to=9999, textvariable=count_var, width=8)
        spin.grid(row=1, column=1, padx=(0, 8), pady=4, sticky="w")
        ttk.Label(f, text="times", foreground="gray",
                  font=("Segoe UI", 8)).grid(row=1, column=2, sticky="w")

        self._field_row(f, "Label:", label_var, 2, hint="Optional label", width=22)

        preview_lbl = ttk.Label(f, text="", foreground="#1a5276", font=("Segoe UI", 9, "bold"))
        preview_lbl.grid(row=3, column=0, columnspan=3, padx=8, pady=(2, 6))

        def _update_preview(*_):
            try:
                preview_lbl.config(text=f"↺  ×{count_var.get()}")
            except (ValueError, tk.TclError):
                preview_lbl.config(text="")

        count_var.trace_add("write", _update_preview)
        _update_preview()

        def apply():
            try:
                c = int(count_var.get())
                if c < 1:
                    raise ValueError
            except (ValueError, tk.TclError):
                messagebox.showerror("Invalid Input", "Iterations must be a whole number ≥ 1.")
                return
            self._plan[idx]["params"]["count"] = c
            self._plan[idx]["params"]["label"] = label_var.get()
            self._refresh_plan_tree()
            self._set_status(f"Step {idx+1} updated: Loop ×{c}")

        self._apply_btn(f, 4, apply)

    def _props_wait(self, idx: int):
        p = self._plan[idx]["params"]
        f = ttk.Frame(self._props_inner)
        f.pack(fill="x", padx=4)

        ttk.Label(f, text="Pause execution for the specified duration\n"
                          "before moving to the next step.",
                  foreground="gray", font=("Segoe UI", 8), justify="left").grid(
                  row=0, column=0, columnspan=3, padx=8, pady=(0, 8), sticky="w")

        secs_var  = tk.StringVar(value=str(p.get("seconds", 1.0)))
        label_var = tk.StringVar(value=p.get("label", ""))

        self._field_row(f, "Duration (s):", secs_var,  1, hint="Supports decimals, e.g. 0.5")
        self._field_row(f, "Label:",        label_var, 2, hint="Optional — shown in summary", width=22)

        preview_lbl = ttk.Label(f, text="", foreground="gray", font=("Segoe UI", 8))
        preview_lbl.grid(row=3, column=0, columnspan=3, padx=8, pady=(0, 4))

        def _update_preview(*_):
            try:
                s = float(secs_var.get())
                preview_lbl.config(text=f"≈ {s/60:.1f} min" if s >= 60 else f"{s:.3g} s")
            except ValueError:
                preview_lbl.config(text="")

        secs_var.trace_add("write", _update_preview)
        _update_preview()

        def apply():
            try:
                s = float(secs_var.get())
                if s < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Invalid Input", "Duration must be a positive number.")
                return
            self._plan[idx]["params"]["seconds"] = s
            self._plan[idx]["params"]["label"]   = label_var.get()
            self._refresh_plan_tree()
            self._set_status(f"Step {idx+1} updated: Wait {s} s")

        self._apply_btn(f, 4, apply)

    def _props_message(self, idx: int):
        p = self._plan[idx]["params"]
        f = ttk.Frame(self._props_inner)
        f.pack(fill="x", padx=4)

        ttk.Label(f, text="Log a text message to the run console\n"
                          "and session CSV at this point in the plan.",
                  foreground="gray", font=("Segoe UI", 8), justify="left").grid(
                  row=0, column=0, columnspan=3, padx=8, pady=(0, 8), sticky="w")

        ttk.Label(f, text="Message:", anchor="e", width=20).grid(
            row=1, column=0, padx=(8, 4), pady=(4, 0), sticky="ne")

        txt_frame = ttk.Frame(f)
        txt_frame.grid(row=1, column=1, columnspan=2, padx=(0, 8), pady=4, sticky="ew")

        txt = tk.Text(txt_frame, width=28, height=4, wrap="word", font=("Segoe UI", 9))
        txt.pack(side="left", fill="both", expand=True)
        txt_sb = ttk.Scrollbar(txt_frame, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=txt_sb.set)
        txt_sb.pack(side="right", fill="y")

        txt.insert("1.0", p.get("text", ""))

        ttk.Label(f, text="Appears in the run log and output CSV.",
                  foreground="gray", font=("Segoe UI", 7)).grid(
                  row=2, column=1, columnspan=2, padx=(0, 8), sticky="w")

        def apply():
            self._plan[idx]["params"]["text"] = txt.get("1.0", "end").strip()
            self._refresh_plan_tree()
            self._set_status(f"Step {idx+1} updated: Message")

        self._apply_btn(f, 3, apply)

    def _props_cond_abort(self, idx: int):
        p = self._plan[idx]["params"]
        f = ttk.Frame(self._props_inner)
        f.pack(fill="x", padx=4)

        ttk.Label(f, text="Monitor a PSU channel's current draw.\n"
                          "Abort the run immediately if the condition is met.",
                  foreground="gray", font=("Segoe UI", 8), justify="left").grid(
                  row=0, column=0, columnspan=3, padx=8, pady=(0, 8), sticky="w")

        ch_var        = tk.StringVar(value=p.get("channel",      ""))
        threshold_var = tk.StringVar(value=str(p.get("threshold_ma", 500.0)))
        cond_var      = tk.StringVar(value=p.get("condition",    ">"))

        self._channel_row(f, "Monitor Channel:", ch_var, 1)

        ttk.Label(f, text="Abort Condition:", anchor="e", width=20).grid(
            row=3, column=0, padx=(8, 4), pady=4, sticky="e")

        cond_frame = ttk.Frame(f)
        cond_frame.grid(row=3, column=1, columnspan=2, padx=(0, 8), pady=4, sticky="w")

        ttk.Label(cond_frame, text="Current").pack(side="left", padx=(0, 4))
        cond_cb = ttk.Combobox(cond_frame, textvariable=cond_var,
                               values=[">", "<", ">=", "<="],
                               width=5, state="readonly")
        cond_cb.pack(side="left", padx=4)
        thresh_entry = ttk.Entry(cond_frame, textvariable=threshold_var, width=8)
        thresh_entry.pack(side="left", padx=4)
        ttk.Label(cond_frame, text="mA").pack(side="left")

        summary_lbl = ttk.Label(f, text="", foreground="#922b21",
                                font=("Segoe UI", 9, "bold"))
        summary_lbl.grid(row=4, column=0, columnspan=3, padx=8, pady=(2, 6))

        def _update_summary(*_):
            try:
                summary_lbl.config(
                    text=f"Abort if I {cond_var.get()} {threshold_var.get()} mA")
            except Exception:
                pass

        cond_var.trace_add("write",      _update_summary)
        threshold_var.trace_add("write", _update_summary)
        _update_summary()

        ttk.Label(f, text="⚠  Run will hard-stop and log the abort reason.",
                  foreground="orange", font=("Segoe UI", 8)).grid(
                  row=5, column=0, columnspan=3, padx=8, pady=(0, 6), sticky="w")

        def apply():
            try:
                thr = float(threshold_var.get())
            except ValueError:
                messagebox.showerror("Invalid Input", "Threshold must be a number in mA.")
                return
            self._plan[idx]["params"].update(
                channel=ch_var.get(),
                threshold_ma=thr,
                condition=cond_var.get(),
            )
            self._refresh_plan_tree()
            self._set_status(
                f"Step {idx+1} updated: Abort if I {cond_var.get()} {thr} mA")

        self._apply_btn(f, 6, apply)

    # ══════════════════════════════════════════════════════════
    #  SCPI PROPERTY PANELS
    # ══════════════════════════════════════════════════════════
    def _props_scpi_command(self, idx: int):
        p = self._plan[idx]["params"]
        f = ttk.Frame(self._props_inner)
        f.pack(fill="x", padx=4)

        ttk.Label(f, text="Send a single SCPI write command to any\n"
                          "connected instrument. No response expected.",
                  foreground="gray", font=("Segoe UI", 8), justify="left").grid(
                  row=0, column=0, columnspan=3, padx=8, pady=(0, 8), sticky="w")

        inst_var = tk.StringVar(value=p.get("instrument", ""))
        cmd_var  = tk.StringVar(value=p.get("command",    ""))

        self._instrument_row(f, "Instrument:", inst_var, 1)
        self._field_row(f, "SCPI Command:", cmd_var, 3,
                        hint='e.g. ":OUTP ON"', width=26)

        ttk.Label(f, text='Examples:  ":FREQ 2.4GHz"  |  ":POW -10dBm"  |  "*RST"',
                  foreground="gray", font=("Segoe UI", 7)).grid(
                  row=4, column=0, columnspan=3, padx=8, pady=(0, 4), sticky="w")

        def apply():
            inst = inst_var.get().strip()
            cmd  = cmd_var.get().strip()
            if not inst:
                messagebox.showerror("Missing Instrument",
                                     "Enter or select an instrument name.")
                return
            if not cmd:
                messagebox.showerror("Missing Command", "Enter a SCPI command string.")
                return
            self._plan[idx]["params"]["instrument"] = inst
            self._plan[idx]["params"]["command"]    = cmd
            self._refresh_plan_tree()
            self._set_status(f"Step {idx+1} updated: SCPI → {inst}")

        self._apply_btn(f, 5, apply)

    def _props_scpi_poll(self, idx: int):
        p = self._plan[idx]["params"]
        f = ttk.Frame(self._props_inner)
        f.pack(fill="x", padx=4)

        ttk.Label(f, text="Repeatedly query an instrument until the\n"
                          "response matches 'Expected' or timeout expires.",
                  foreground="gray", font=("Segoe UI", 8), justify="left").grid(
                  row=0, column=0, columnspan=3, padx=8, pady=(0, 8), sticky="w")

        inst_var     = tk.StringVar(value=p.get("instrument", ""))
        query_var    = tk.StringVar(value=p.get("query",      ""))
        expected_var = tk.StringVar(value=p.get("expected",   ""))
        timeout_var  = tk.StringVar(value=str(p.get("timeout_s", 10.0)))

        self._instrument_row(f, "Instrument:", inst_var, 1)
        self._field_row(f, "Query:",       query_var,    3, hint='e.g. ":STAT?"',  width=22)
        self._field_row(f, "Expected:",    expected_var, 4,
                        hint="Blank = pass on first response", width=22)
        self._field_row(f, "Timeout (s):", timeout_var,  5, hint="Default 10 s")

        ttk.Label(f, text="Polls every 250 ms until match or timeout.\n"
                          "Run aborts if timeout is exceeded.",
                  foreground="gray", font=("Segoe UI", 7), justify="left").grid(
                  row=6, column=0, columnspan=3, padx=8, pady=(2, 4), sticky="w")

        def apply():
            inst = inst_var.get().strip()
            qry  = query_var.get().strip()
            if not inst:
                messagebox.showerror("Missing Instrument",
                                     "Enter or select an instrument name.")
                return
            if not qry:
                messagebox.showerror("Missing Query", "Enter the SCPI query string.")
                return
            try:
                t = float(timeout_var.get())
                if t <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Invalid Timeout",
                                     "Timeout must be a positive number of seconds.")
                return
            self._plan[idx]["params"].update(
                instrument=inst,
                query=qry,
                expected=expected_var.get().strip(),
                timeout_s=t,
            )
            self._refresh_plan_tree()
            self._set_status(f"Step {idx+1} updated: SCPI Poll → {inst}")

        self._apply_btn(f, 7, apply)

    # ══════════════════════════════════════════════════════════
    #  GENERIC FALLBACK (safety net for unknown future types)
    # ══════════════════════════════════════════════════════════
    def _props_generic(self, idx: int):
        step = self._plan[idx]
        f    = ttk.Frame(self._props_inner)
        f.pack(fill="x", padx=4)

        ttk.Label(f, text="Parameters",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=8, pady=(0, 4))

        for key, val in step["params"].items():
            row = ttk.Frame(f)
            row.pack(fill="x", pady=2, padx=8)
            ttk.Label(row, text=f"{key}:", width=20, anchor="e").pack(side="left")
            var = tk.StringVar(value=str(val))
            ent = ttk.Entry(row, textvariable=var, width=18)
            ent.pack(side="left", padx=4)

            def _save(k=key, v=var, i=idx):
                raw = v.get()
                try:
                    stored = float(raw) if "." in raw else int(raw)
                except ValueError:
                    stored = raw
                self._plan[i]["params"][k] = stored
                self._refresh_plan_tree()

            ent.bind("<Return>",   lambda e, fn=_save: fn())
            ent.bind("<FocusOut>", lambda e, fn=_save: fn())

    # ══════════════════════════════════════════════════════════
    #  PLAN MANIPULATION
    # ══════════════════════════════════════════════════════════
    def _add_step(self, action_type: str, display_name: str):
        step = {
            "type":         action_type,
            "display_name": display_name,
            "params":       dict(ACTION_DEFAULTS.get(action_type, {})),
        }
        if self._selected_idx is not None:
            self._plan.insert(self._selected_idx + 1, step)
            new_idx = self._selected_idx + 1
        else:
            self._plan.append(step)
            new_idx = len(self._plan) - 1
        self._refresh_plan_tree()
        self._select_plan_row(new_idx)
        self._set_status(f"Added: {display_name}")

    def _delete_step(self):
        if self._selected_idx is None:
            return
        idx  = self._selected_idx
        name = self._plan[idx]["display_name"]
        if messagebox.askyesno("Delete Step", f"Delete '{name}'?"):
            self._plan.pop(idx)
            self._selected_idx = None
            self._refresh_plan_tree()
            self._show_props_placeholder()
            self._set_status(f"Deleted: {name}")

    def _move_step(self, direction: int):
        if self._selected_idx is None:
            return
        idx     = self._selected_idx
        new_idx = idx + direction
        if 0 <= new_idx < len(self._plan):
            self._plan[idx], self._plan[new_idx] = self._plan[new_idx], self._plan[idx]
            self._refresh_plan_tree()
            self._select_plan_row(new_idx)

    def _duplicate_step(self):
        if self._selected_idx is None:
            return
        step = copy.deepcopy(self._plan[self._selected_idx])
        self._plan.insert(self._selected_idx + 1, step)
        self._refresh_plan_tree()
        self._select_plan_row(self._selected_idx + 1)
        self._set_status(f"Duplicated: {step['display_name']}")

    # ══════════════════════════════════════════════════════════
    #  TREE HELPERS
    # ══════════════════════════════════════════════════════════
    def _refresh_plan_tree(self):
        self.plan_tree.delete(*self.plan_tree.get_children())
        for i, step in enumerate(self._plan):
            self.plan_tree.insert("", "end", iid=str(i),
                                  values=(i + 1, step["display_name"], _step_summary(step)))

    def _select_plan_row(self, idx: int):
        iid = str(idx)
        self.plan_tree.selection_set(iid)
        self.plan_tree.see(iid)
        self._selected_idx = idx

    def _on_plan_select(self, event):
        sel = self.plan_tree.selection()
        if sel:
            self._selected_idx = int(sel[0])
            self._show_props(self._selected_idx)

    def _on_plan_double_click(self, event):
        sel = self.plan_tree.selection()
        if sel:
            self._selected_idx = int(sel[0])
            self._show_props(self._selected_idx)

    # ══════════════════════════════════════════════════════════
    #  FILE I/O
    # ══════════════════════════════════════════════════════════
    def _new_plan(self):
        if self._plan:
            if not messagebox.askyesno("New Plan", "Discard current plan and start new?"):
                return
        self._plan         = []
        self._current_file = None
        self._title_var.set(UNTITLED)
        self._selected_idx = None
        self._refresh_plan_tree()
        self._show_props_placeholder()
        self._update_file_label()
        self._set_status("New plan created.")

    def _open_plan(self):
        path = filedialog.askopenfilename(
            title="Open Sweep Plan",
            filetypes=[("Axiro Plan", f"*{PLAN_FILE_EXT}"),
                       ("JSON", "*.json"),
                       ("All Files", "*.*")])
        if not path:
            return
        try:
            with open(path, "r") as f:
                data = json.load(f)
            self._plan         = data.get("steps", [])
            self._title_var.set(data.get("title", UNTITLED))
            self._current_file = path
            self._selected_idx = None
            self._refresh_plan_tree()
            self._show_props_placeholder()
            self._update_file_label()
            self._set_status(
                f"Opened: {os.path.basename(path)}  ({len(self._plan)} steps)", "green")
            _logger.info(f"Sweep plan loaded: {path}")
        except Exception as e:
            messagebox.showerror("Open Error", str(e))
            _logger.error(f"Failed to open plan {path}: {e}")

    def _save_plan(self):
        if self._current_file:
            self._write_plan(self._current_file)
        else:
            self._save_plan_as()

    def _save_plan_as(self):
        path = filedialog.asksaveasfilename(
            title="Save Sweep Plan",
            defaultextension=PLAN_FILE_EXT,
            filetypes=[("Axiro Plan", f"*{PLAN_FILE_EXT}"), ("JSON", "*.json")])
        if path:
            self._current_file = path
            self._write_plan(path)

    def _write_plan(self, path: str):
        data = {
            "title":   self._title_var.get(),
            "steps":   self._plan,
            "version": "1.0",
        }
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            self._update_file_label()
            self._set_status(
                f"Saved: {os.path.basename(path)}  ({len(self._plan)} steps)", "green")
            _logger.info(f"Sweep plan saved: {path}")
        except Exception as e:
            messagebox.showerror("Save Error", str(e))
            _logger.error(f"Failed to save plan {path}: {e}")

    def _update_file_label(self):
        if self._current_file:
            self._file_lbl.config(
                text=f"[{os.path.basename(self._current_file)}]", foreground="gray")
        else:
            self._file_lbl.config(text="[unsaved]", foreground="orange")

    # ══════════════════════════════════════════════════════════
    #  RUN / STOP
    # ══════════════════════════════════════════════════════════
    def _run_plan(self):
        if not self._plan:
            messagebox.showwarning("Empty Plan", "Add steps to the plan before running.")
            return
        plan_rows = self.get_sweep_plan_rows()
        output    = os.path.join(
            "results", f"sweep_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        self._engine = RunEngine(
            driver_registry=self._registry,
            ramp_tab=self._ramp_tab,
            on_complete=self._on_run_complete,
            on_step=self._on_step_update,
            on_error=self._on_run_error,
        )
        self._reset_row_highlights()
        self._engine.start(plan_rows, output)
        self._set_run_status("running")
        self._set_status("Running plan...", "green")

    def _stop_plan(self):
        if self._engine:
            self._engine.stop()
        self._set_run_status("stopped")
        self._set_status("Stopped.", "red")

    def _on_run_complete(self):
        self._set_run_status("complete")
        self._set_status("Run complete.", "green")
        if hasattr(self, "_results_tab"):
            self._results_tab.refresh()

    def _on_run_error(self, msg: str):
        self._set_run_status("error")
        self._set_status(f"Error: {msg}", "red")

    def _on_step_update(self, iid: str, status: str):
        if not self.plan_tree.exists(iid):
            return
        tag_map = {
            "running": ("#1a5276", "white"),
            "done":    ("#1e8449", "white"),
            "error":   ("#922b21", "white"),
        }
        if status in tag_map:
            bg, fg = tag_map[status]
            self.plan_tree.tag_configure(status, background=bg, foreground=fg)
            self.plan_tree.item(iid, tags=(status,))
            if status == "running":
                self.plan_tree.see(iid)
        if not self.plan_tree.exists(iid):
            return
        if status == "running":
            self.plan_tree.tag_configure("running", background="#1a5276", foreground="white")
            self.plan_tree.item(iid, tags=("running",))
            self.plan_tree.see(iid)
        elif status == "done":
            self.plan_tree.tag_configure("done", background="#1e8449", foreground="white")
            self.plan_tree.item(iid, tags=("done",))
        elif status == "error":
            self.plan_tree.tag_configure("error", background="#922b21", foreground="white")
            self.plan_tree.item(iid, tags=("error",))

    def _reset_row_highlights(self):
        for iid in self.plan_tree.get_children():
            self.plan_tree.item(iid, tags=())

    # ══════════════════════════════════════════════════════════
    #  UTILITIES
    # ══════════════════════════════════════════════════════════
    def _set_status(self, msg: str, color: str = "gray"):
        self._status_var.set(msg)

    def set_results_tab_ref(self, results_tab):
        self._results_tab = results_tab

    def set_aliases(self, alias_map: dict):
        self._aliases = alias_map

    def get_plan(self) -> list:
        return list(self._plan)

    def get_sweep_plan_rows(self) -> list:
        return self._serialize_steps(self._plan)

    def _serialize_steps(self, steps: list) -> list:
        rows = []
        for step in steps:
            t = step.get("type", "")
            p = step.get("params", {})

            if t == "loop":
                rows.append({
                    "command":  "LOOP",
                    "params":   {"count": int(p.get("count", 1)), "label": p.get("label", "")},
                    "children": self._serialize_steps(step.get("children", [])),
                })

            elif t == "group":
                rows.append({
                    "command":  "GROUP",
                    "params":   {"label": p.get("label", ""), "collapsed": p.get("collapsed", False)},
                    "children": self._serialize_steps(step.get("children", [])),
                })

            elif t == "set_gate_bias":
                rows.append({"command": "SET_BIAS", "params": {
                    "channel": p.get("channel", ""), "mode": p.get("mode", "CV"),
                    "voltage": p.get("voltage", 0.0), "ocp": p.get("ocp", 0.1),
                    "current": p.get("current", 0.01), "ovp": p.get("ovp", 5.0),
                }})

            elif t == "set_drain_bias":
                rows.append({"command": "SET_BIAS", "params": {
                    "channel": p.get("channel", ""), "mode": p.get("mode", "CV"),
                    "voltage": p.get("voltage", 0.0), "ocp": p.get("ocp", 2.0),
                    "current": p.get("current", 1.0), "ovp": p.get("ovp", 35.0),
                    "target_idq_ma": p.get("target_idq_ma"),
                    "tolerance_ma":  p.get("tolerance_ma", 5),
                    "gate_step_mv":  p.get("gate_step_mv", 50),
                    "hard_abort_ma": p.get("hard_abort_ma"),
                }})

            elif t in ("ramp_up", "ramp_down"):
                rows.append({"command": "RAMP", "params": {
                    "use_ramp_editor": p.get("use_ramp_editor", True),
                    "channel":         p.get("channel", ""),
                    "voltage":         p.get("voltage", 0.0),
                    "ocp":             p.get("ocp", 1.0),
                    "direction":       "up" if t == "ramp_up" else "down",
                }})

            elif t == "output_on":
                rows.append({"command": "OUTPUT_ON",  "params": {"channel": p.get("channel", "")}})

            elif t == "output_off":
                rows.append({"command": "OUTPUT_OFF", "params": {"channel": p.get("channel", "")}})

            elif t == "power_sweep":
                rows.append({"command": "POWER_SWEEP", "params": {
                    "start_dbm":     p.get("start_dbm",    -20.0),
                    "stop_dbm":      p.get("stop_dbm",      10.0),
                    "step_db":       p.get("step_db",        1.0),
                    "dwell_ms":      p.get("dwell_ms",      200),
                    "freq_ghz":      p.get("freq_ghz",       ""),
                    "drain_channel": p.get("drain_channel",  ""),
                }})


            elif t == "perform_measurement":
                rows.append({"command": "MEASURE", "params": p})

            elif t == "save_results":
                rows.append({"command": "SAVE_RESULTS", "params": p})

            elif t == "wait":
                rows.append({"command": "WAIT", "params": {"seconds": p.get("seconds", 1.0)}})

            elif t == "message":
                rows.append({"command": "MESSAGE", "params": {"text": p.get("text", "")}})

            elif t == "cond_abort":
                rows.append({"command": "COND_ABORT", "params": {
                    "channel":      p.get("channel", ""),
                    "threshold_ma": float(p.get("threshold_ma", 500.0)),
                    "condition":    p.get("condition", ">"),
                }})

            elif t == "scpi_command":
                rows.append({"command": "SCPI_COMMAND", "params": {
                    "instrument": p.get("instrument", ""),
                    "command":    p.get("command", ""),
                }})

            elif t == "scpi_poll":
                rows.append({"command": "SCPI_POLL", "params": {
                    "instrument": p.get("instrument", ""),
                    "query":      p.get("query", ""),
                    "expected":   p.get("expected", ""),
                    "timeout_s":  float(p.get("timeout_s", 10.0)),
                }})

            else:
                rows.append({"command": t.upper(), "params": p})

        return rows



# ══════════════════════════════════════════════════════════════
#  STEP SUMMARY LINES  (module level)
# ══════════════════════════════════════════════════════════════
def _step_summary(step: dict) -> str:
    t = step.get("type", "")
    p = step.get("params", {})

    if t == "set_gate_bias":
        return (f"Gate: {p.get('channel','?')}  →  "
                f"{p.get('voltage','?')} V  OCP {p.get('ocp','?')} A")
    if t == "set_drain_bias":
        return (f"Drain: {p.get('channel','?')}  →  "
                f"{p.get('voltage','?')} V  OCP {p.get('ocp','?')} A")
    if t == "ramp_up":
        src = "Ramp Editor" if p.get("use_ramp_editor", True) \
              else f"Manual  {p.get('channel','?')} → {p.get('voltage','?')} V"
        return f"Ramp Up  [{src}]"
    if t == "ramp_down":
        src = "Ramp Editor" if p.get("use_ramp_editor", True) \
              else f"Manual  {p.get('channel','?')} → {p.get('voltage','?')} V"
        return f"Ramp Down  [{src}]"
    if t == "output_on":
        return f"Output ON  →  {p.get('channel','?')}"
    if t == "output_off":
        return f"Output OFF  →  {p.get('channel','?')}"
    if t == "bias_sweep":
        return (f"{p.get('channel','?')}  "
                f"{p.get('start','?')} → {p.get('stop','?')} V  "
                f"step {p.get('step','?')} V  dwell {p.get('dwell_ms','?')} ms")
    if t == "idq_optimize":
        return (f"Idq  drain={p.get('drain_channel','?')}  "
                f"gate={p.get('gate_channel','?')}  "
                f"target {p.get('target_ma','?')} mA  "
                f"±{p.get('tolerance_ma','?')} mA")
    if t == "power_sweep":
        return (f"{p.get('start_dbm','?')} → {p.get('stop_dbm','?')} dBm  "
                f"step {p.get('step_db','?')} dB  dwell {p.get('dwell_ms','?')} ms")
    if t == "perform_measurement":
        return f"Acquire trace  {p.get('notes','')}"
    if t == "gain_compression":
        return f"P{p.get('compression_db','?')}dB compression point"
    if t == "acpr":
        return (f"ACPR  offset {p.get('offset_hz',0)/1e6:.1f} MHz  "
                f"BW {p.get('bw_hz',0)/1e6:.1f} MHz")
    if t == "harmonics":
        return (f"Harmonics  f={p.get('fundamental_hz',0)/1e9:.3f} GHz  "
                f"N={p.get('num_harmonics','?')}")
    if t == "pae_sweep":
        return (f"PAE sweep  "
                f"{p.get('start_dbm','?')} → {p.get('stop_dbm','?')} dBm")
    if t == "freq_sweep":
        return (f"{p.get('start_hz',0)/1e9:.2f} → "
                f"{p.get('stop_hz',0)/1e9:.2f} GHz  "
                f"step {p.get('step_hz',0)/1e6:.0f} MHz")
    if t == "load_measurement":
        return f"Load: {p.get('filepath','(none)')}"
    if t == "save_results":
        return f"Save: {p.get('filename','(auto)')}"
    if t == "group":
        return f"Group: {p.get('label','')}"
    if t == "loop":
        return f"Loop ×{p.get('count','?')}  {p.get('label','')}"
    if t == "wait":
        return f"Wait {p.get('seconds','?')} s  {p.get('label','')}"
    if t == "message":
        return f'Log: "{p.get("text","")}"'
    if t == "cond_abort":
        return (f"Abort if {p.get('channel','?')} current "
                f"{p.get('condition','>')} {p.get('threshold_ma','?')} mA")
    if t == "scpi_command":
        return f"{p.get('instrument','?')}  ←  {p.get('command','')}"
    if t == "scpi_poll":
        return (f"{p.get('instrument','?')}  query: {p.get('query','')}  "
                f"expect: {p.get('expected','')}  timeout: {p.get('timeout_s','?')} s")
    return str(p)
