import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import csv

# import matplotlib
# matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

from utils.logger import get_logger
from datetime import datetime

output = os.path.join("session_logs",
                      datetime.now().strftime("%Y-%m-%d_%H-%M-%S"),
                      "data.csv")
                      
_logger = get_logger(__name__)

SESSION_LOG_DIR = "session_logs"


class ResultsViewerTab(ttk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self._rows    = []
        self._headers = []
        self._build_ui()
        self._refresh_file_list()

    def _build_ui(self):
        ttk.Label(self, text="Results Viewer",
                  font=("Segoe UI", 14, "bold")).pack(pady=10)

        # File selector
        top = ttk.Frame(self)
        top.pack(fill="x", padx=15, pady=4)
        file_frame = ttk.LabelFrame(top, text="Session Log File")
        file_frame.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.file_var   = tk.StringVar()
        self.file_combo = ttk.Combobox(file_frame, textvariable=self.file_var,
                                        state="readonly", width=55)
        self.file_combo.pack(side="left", padx=8, pady=6)
        ttk.Button(file_frame, text="Refresh",
                   command=self._refresh_file_list).pack(side="left", padx=4)
        ttk.Button(file_frame, text="Browse…",
                   command=self._browse_file).pack(side="left", padx=4)
        ttk.Button(file_frame, text="Load",
                   command=self._load_file).pack(side="left", padx=8)

        # Data table
        table_outer = ttk.LabelFrame(self, text="Data Table")
        table_outer.pack(fill="x", padx=15, pady=4)
        self.data_tree = ttk.Treeview(table_outer, show="headings", height=5)
        h_scroll = ttk.Scrollbar(table_outer, orient="horizontal",
                                  command=self.data_tree.xview)
        v_scroll = ttk.Scrollbar(table_outer, orient="vertical",
                                  command=self.data_tree.yview)
        self.data_tree.configure(xscrollcommand=h_scroll.set,
                                  yscrollcommand=v_scroll.set)
        self.data_tree.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")
        table_outer.columnconfigure(0, weight=1)

        # Plot notebook — 6 tabs
        plot_nb = ttk.Notebook(self)
        plot_nb.pack(fill="both", expand=True, padx=15, pady=6)

        self._session_tab  = ttk.Frame(plot_nb)
        self._ramp_tab     = ttk.Frame(plot_nb)
        self._pout_pin_tab = ttk.Frame(plot_nb)
        self._gain_pin_tab = ttk.Frame(plot_nb)
        self._pae_tab      = ttk.Frame(plot_nb)
        self._spectrum_tab = ttk.Frame(plot_nb)

        plot_nb.add(self._session_tab,  text="  Session Data  ")
        plot_nb.add(self._ramp_tab,     text="  Ramp Data  ")
        plot_nb.add(self._pout_pin_tab, text="  Pout vs Pin  ")
        plot_nb.add(self._gain_pin_tab, text="  Gain vs Pin  ")
        plot_nb.add(self._pae_tab,      text="  PAE vs Pin  ")
        plot_nb.add(self._spectrum_tab, text="  Spectrum  ")

        self._build_session_plot_tab()
        self._build_ramp_plot_tab()
        self._build_pout_pin_tab()
        self._build_gain_pin_tab()
        self._build_pae_tab()
        self._build_spectrum_tab()

        self.status_lbl = ttk.Label(self, text="No file loaded", foreground="gray")
        self.status_lbl.pack(pady=4)

    # ── Session Data tab ───────────────────────────────────────
    def _build_session_plot_tab(self):
        opt = ttk.Frame(self._session_tab)
        opt.pack(fill="x", padx=8, pady=6)
        ttk.Label(opt, text="X Axis:").pack(side="left", padx=(0, 4))
        self.xaxis_var = tk.StringVar(value="Step")
        ttk.Combobox(opt, textvariable=self.xaxis_var, state="readonly",
                     values=["Step", "Timestamp"], width=12).pack(side="left", padx=4)
        ttk.Label(opt, text="Series:").pack(side="left", padx=(12, 4))
        self.series_var = tk.StringVar(value="Voltage & Current")
        ttk.Combobox(opt, textvariable=self.series_var, state="readonly",
                     values=["Voltage & Current", "Power (V×I)",
                             "Voltage Only", "Current Only"]).pack(side="left", padx=4)
        ttk.Button(opt, text="Plot", command=self._plot_session).pack(side="left", padx=12)
        self.fig_s, self.ax_s = plt.subplots(figsize=(10, 3.4))
        self.fig_s.tight_layout(pad=2.5)
        canvas = FigureCanvasTkAgg(self.fig_s, master=self._session_tab)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        NavigationToolbar2Tk(canvas, self._session_tab).update()
        self.canvas_s = canvas

    # ── Ramp Data tab ──────────────────────────────────────────
    def _build_ramp_plot_tab(self):
        opt = ttk.Frame(self._ramp_tab)
        opt.pack(fill="x", padx=8, pady=6)
        ttk.Label(opt, text="Series:").pack(side="left", padx=(0, 4))
        self.ramp_series_var = tk.StringVar(value="Gate V & Drain V")
        ttk.Combobox(opt, textvariable=self.ramp_series_var, state="readonly",
                     values=["Gate V & Drain V", "Gate A & Drain A",
                             "All Four"]).pack(side="left", padx=4)
        ttk.Button(opt, text="Plot", command=self._plot_ramp).pack(side="left", padx=12)
        self.fig_r, self.ax_r = plt.subplots(figsize=(10, 3.4))
        self.fig_r.tight_layout(pad=2.5)
        canvas = FigureCanvasTkAgg(self.fig_r, master=self._ramp_tab)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        NavigationToolbar2Tk(canvas, self._ramp_tab).update()
        self.canvas_r = canvas

    # ── Pout vs Pin tab ────────────────────────────────────────
    def _build_pout_pin_tab(self):
        opt = ttk.Frame(self._pout_pin_tab)
        opt.pack(fill="x", padx=8, pady=6)
        ttk.Label(opt,
                  text="Output power vs input power with ideal linear overlay. "
                       "Compression visible where measured curve bends below ideal.",
                  foreground="gray").pack(side="left", padx=4)
        ttk.Button(opt, text="Plot", command=self._plot_pout_pin).pack(side="right", padx=12)
        self.fig_pp, self.ax_pp = plt.subplots(figsize=(10, 3.4))
        self.fig_pp.tight_layout(pad=2.5)
        canvas = FigureCanvasTkAgg(self.fig_pp, master=self._pout_pin_tab)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        NavigationToolbar2Tk(canvas, self._pout_pin_tab).update()
        self.canvas_pp = canvas

    # ── Gain vs Pin tab ────────────────────────────────────────
    def _build_gain_pin_tab(self):
        opt = ttk.Frame(self._gain_pin_tab)
        opt.pack(fill="x", padx=8, pady=6)
        ttk.Label(opt,
                  text="Gain vs input power. P1dB annotated where gain drops "
                       "1 dB below small-signal value.",
                  foreground="gray").pack(side="left", padx=4)
        ttk.Button(opt, text="Plot", command=self._plot_gain_pin).pack(side="right", padx=12)
        self.fig_gp, self.ax_gp = plt.subplots(figsize=(10, 3.4))
        self.fig_gp.tight_layout(pad=2.5)
        canvas = FigureCanvasTkAgg(self.fig_gp, master=self._gain_pin_tab)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        NavigationToolbar2Tk(canvas, self._gain_pin_tab).update()
        self.canvas_gp = canvas

    # ── PAE vs Pin tab ─────────────────────────────────────────
    def _build_pae_tab(self):
        opt = ttk.Frame(self._pae_tab)
        opt.pack(fill="x", padx=8, pady=6)
        ttk.Label(opt,
                  text="PAE = (Pout − Pin) / PDC × 100%.  "
                       "Requires VOLT:DC and CURR:DC DMM readings during sweep.",
                  foreground="gray", wraplength=700).pack(side="left", padx=4)
        ttk.Button(opt, text="Plot", command=self._plot_pae).pack(side="right", padx=12)
        self.fig_pae, self.ax_pae1 = plt.subplots(figsize=(10, 3.4))
        self.fig_pae.tight_layout(pad=2.5)
        canvas = FigureCanvasTkAgg(self.fig_pae, master=self._pae_tab)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        NavigationToolbar2Tk(canvas, self._pae_tab).update()
        self.canvas_pae = canvas

    # ── Spectrum tab ───────────────────────────────────────────
    def _build_spectrum_tab(self):
        ctrl = ttk.Frame(self._spectrum_tab)
        ctrl.pack(fill="x", padx=8, pady=6)
        ttk.Label(ctrl,
                  text="Uses Frequency(Hz) + Power(dBm) rows from the loaded "
                       "session CSV, or browse a standalone trace CSV.",
                  foreground="gray").pack(side="left", padx=4)

        btn_row = ttk.Frame(self._spectrum_tab)
        btn_row.pack(fill="x", padx=8, pady=2)
        self.trace_file_var = tk.StringVar(value="— use loaded session file —")
        ttk.Entry(btn_row, textvariable=self.trace_file_var,
                  width=60, state="readonly").pack(side="left", padx=(0, 6))
        ttk.Button(btn_row, text="Browse Trace CSV…",
                   command=self._browse_trace).pack(side="left", padx=4)
        ttk.Button(btn_row, text="Plot Spectrum",
                   command=self._plot_spectrum).pack(side="left", padx=8)
        ttk.Button(btn_row, text="Clear / Use Session",
                   command=lambda: self.trace_file_var.set(
                       "— use loaded session file —")).pack(side="left", padx=4)

        self.fig_sp, self.ax_sp = plt.subplots(figsize=(10, 3.4))
        self.fig_sp.tight_layout(pad=2.5)
        canvas = FigureCanvasTkAgg(self.fig_sp, master=self._spectrum_tab)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        NavigationToolbar2Tk(canvas, self._spectrum_tab).update()
        self.canvas_sp = canvas

    # ── File management ────────────────────────────────────────
    def _refresh_file_list(self):
        files = []
        if os.path.isdir(SESSION_LOG_DIR):
            for root_dir, dirs, filenames in os.walk(SESSION_LOG_DIR):
                for f in filenames:
                    if f == "data.csv":
                        files.append(os.path.join(root_dir, f))
        files = sorted(files, reverse=True)
        self.file_combo["values"] = files
        if files:
            self.file_combo.current(0)
        self.status_lbl.config(text=f"{len(files)} session file(s) found")

    def _browse_file(self):
        path = filedialog.askopenfilename(
            title="Open Session CSV",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")])
        if path:
            self.file_var.set(path)

    def _browse_trace(self):
        path = filedialog.askopenfilename(
            title="Open Trace CSV",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")])
        if path:
            self.trace_file_var.set(path)

    def _load_file(self):
        path = self.file_var.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showerror("File Not Found", f"Cannot find:\n{path}")
            return
        try:
            with open(path, newline="") as f:
                reader        = csv.DictReader(f)
                self._headers = reader.fieldnames or []
                self._rows    = list(reader)
            self._populate_table()
            self.status_lbl.config(
                text=f"Loaded {len(self._rows)} rows from {os.path.basename(path)}",
                foreground="green")
            _logger.info(f"Results viewer loaded: {path}")
        except Exception as e:
            messagebox.showerror("Load Error", str(e))

    def _populate_table(self):
        self.data_tree.delete(*self.data_tree.get_children())
        if not self._headers:
            return
        self.data_tree["columns"] = self._headers
        for col in self._headers:
            self.data_tree.heading(col, text=col)
            self.data_tree.column(col, width=110, anchor="center")
        for row in self._rows:
            self.data_tree.insert("", "end",
                                   values=[row.get(h, "") for h in self._headers])

    # ── Data helpers ───────────────────────────────────────────
    def _safe_parse(self, val):
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def _sweep_rows(self):
        return [r for r in self._rows
                if self._safe_parse(r.get("Pin_dBm", "")) is not None]

    def _ramp_rows(self):
        return [r for r in self._rows
                if self._safe_parse(r.get("Gate_V(V)", "")) is not None
                or self._safe_parse(r.get("Drain_V(V)", "")) is not None]

    # ── Session Data plot ──────────────────────────────────────
    def _plot_session(self):
        if not self._rows:
            messagebox.showwarning("No Data", "Load a CSV file first.")
            return
        self.ax_s.clear()
        series = self.series_var.get()

        def col(key):
            return [self._safe_parse(r.get(key, "")) or 0.0 for r in self._rows]

        volts = col("Voltage(V)")
        amps  = col("Current(A)")
        n     = len(self._rows)
        xs    = list(range(1, n + 1))

        if series == "Voltage & Current":
            ax2 = self.ax_s.twinx()
            self.ax_s.plot(xs, volts, "b-o", markersize=4, label="Voltage (V)")
            ax2.plot(xs, amps,        "r-s", markersize=4, label="Current (A)")
            self.ax_s.set_ylabel("Voltage (V)", color="blue")
            ax2.set_ylabel("Current (A)", color="red")
            l1, lb1 = self.ax_s.get_legend_handles_labels()
            l2, lb2 = ax2.get_legend_handles_labels()
            self.ax_s.legend(l1 + l2, lb1 + lb2, loc="upper left")
        elif series == "Power (V×I)":
            power = [v * a for v, a in zip(volts, amps)]
            self.ax_s.plot(xs, power, "g-^", markersize=4, label="Power (W)")
            self.ax_s.set_ylabel("Power (W)")
            self.ax_s.legend()
        elif series == "Voltage Only":
            self.ax_s.plot(xs, volts, "b-o", markersize=4, label="Voltage (V)")
            self.ax_s.set_ylabel("Voltage (V)")
            self.ax_s.legend()
        elif series == "Current Only":
            self.ax_s.plot(xs, amps, "r-s", markersize=4, label="Current (A)")
            self.ax_s.set_ylabel("Current (A)")
            self.ax_s.legend()

        self.ax_s.set_xlabel("Step")
        self.ax_s.set_title(f"{series} — {os.path.basename(self.file_var.get())}")
        self.ax_s.grid(True, linestyle="--", alpha=0.5)
        self.fig_s.tight_layout(pad=2.5)
        self.canvas_s.draw()
        self.status_lbl.config(text=f"Plotted: {series}", foreground="green")

    # ── Ramp Data plot ─────────────────────────────────────────
    def _plot_ramp(self):
        rows = self._ramp_rows()
        if not rows:
            messagebox.showwarning("No Ramp Data",
                                   "No Gate_V / Drain_V rows found.")
            return
        self.ax_r.clear()
        series = self.ramp_series_var.get()
        steps  = list(range(1, len(rows) + 1))

        def col(key):
            return [self._safe_parse(r.get(key, "")) or 0.0 for r in rows]

        gate_v  = col("Gate_V(V)")
        drain_v = col("Drain_V(V)")
        gate_a  = col("Gate_A(A)")
        drain_a = col("Drain_A(A)")

        if series in ("Gate V & Drain V", "All Four"):
            ax2 = self.ax_r.twinx()
            self.ax_r.plot(steps, gate_v,  "b-o",  markersize=5, label="Gate V")
            ax2.plot(steps,        drain_v, "r-s",  markersize=5, label="Drain V")
            self.ax_r.set_ylabel("Gate Voltage (V)", color="blue")
            ax2.set_ylabel("Drain Voltage (V)", color="red")
            if series == "All Four":
                self.ax_r.plot(steps, gate_a,  "b--^", markersize=4, label="Gate A")
                ax2.plot(steps,        drain_a, "r--D", markersize=4, label="Drain A")
            l1, lb1 = self.ax_r.get_legend_handles_labels()
            l2, lb2 = ax2.get_legend_handles_labels()
            self.ax_r.legend(l1 + l2, lb1 + lb2, loc="upper left", fontsize=8)
        elif series == "Gate A & Drain A":
            ax2 = self.ax_r.twinx()
            self.ax_r.plot(steps, gate_a,  "b-o", markersize=5, label="Gate A")
            ax2.plot(steps,        drain_a, "r-s", markersize=5, label="Drain A")
            self.ax_r.set_ylabel("Gate Current (A)", color="blue")
            ax2.set_ylabel("Drain Current (A)", color="red")
            l1, lb1 = self.ax_r.get_legend_handles_labels()
            l2, lb2 = ax2.get_legend_handles_labels()
            self.ax_r.legend(l1 + l2, lb1 + lb2, loc="upper left")

        self.ax_r.set_xlabel("Ramp Step")
        self.ax_r.set_title(f"Ramp: {series} — {os.path.basename(self.file_var.get())}")
        self.ax_r.grid(True, linestyle="--", alpha=0.5)
        self.fig_r.tight_layout(pad=2.5)
        self.canvas_r.draw()
        self.status_lbl.config(text=f"Ramp plotted: {series}", foreground="green")

    # ── Pout vs Pin plot ───────────────────────────────────────
    def _plot_pout_pin(self):
        rows = self._sweep_rows()
        if not rows:
            messagebox.showwarning("No Sweep Data",
                                   "No Pin_dBm / Pout_dBm rows found.\n"
                                   "Run a power sweep test first.")
            return

        pin_vals  = [self._safe_parse(r.get("Pin_dBm",  "")) for r in rows]
        pout_vals = [self._safe_parse(r.get("Pout_dBm", "")) for r in rows]

        pairs = [(p, q) for p, q in zip(pin_vals, pout_vals)
                 if p is not None and q is not None]
        if not pairs:
            messagebox.showwarning("Empty Data", "Pin/Pout values could not be parsed.")
            return

        pin_vals, pout_vals = zip(*sorted(pairs))

        self.ax_pp.clear()
        self.ax_pp.plot(pin_vals, pout_vals, "b-o", markersize=5,
                        linewidth=1.5, label="Measured Pout")

        ss_gain = sum(pout_vals[i] - pin_vals[i]
                      for i in range(min(3, len(pin_vals)))) / min(3, len(pin_vals))
        ideal   = [p + ss_gain for p in pin_vals]
        self.ax_pp.plot(pin_vals, ideal, "k--", linewidth=1.2,
                        label=f"Ideal linear (G={ss_gain:.1f} dB)")

        self.ax_pp.set_xlabel("Pin (dBm)")
        self.ax_pp.set_ylabel("Pout (dBm)")
        self.ax_pp.set_title(f"Pout vs Pin — {os.path.basename(self.file_var.get())}")
        self.ax_pp.legend()
        self.ax_pp.grid(True, linestyle="--", alpha=0.5)
        self.fig_pp.tight_layout(pad=2.5)
        self.canvas_pp.draw()
        self.status_lbl.config(
            text=f"Pout vs Pin plotted: {len(pin_vals)} points", foreground="green")

    # ── Gain vs Pin plot ───────────────────────────────────────
    def _plot_gain_pin(self):
        rows = self._sweep_rows()
        if not rows:
            messagebox.showwarning("No Sweep Data",
                                   "No Pin_dBm / Gain_dB rows found.\n"
                                   "Run a power sweep test first.")
            return

        pin_vals  = [self._safe_parse(r.get("Pin_dBm", "")) for r in rows]
        gain_vals = [self._safe_parse(r.get("Gain_dB", "")) for r in rows]

        pairs = [(p, g) for p, g in zip(pin_vals, gain_vals)
                 if p is not None and g is not None]
        if not pairs:
            messagebox.showwarning("Empty Data", "Pin/Gain values could not be parsed.")
            return

        pin_vals, gain_vals = zip(*sorted(pairs))

        self.ax_gp.clear()
        self.ax_gp.plot(pin_vals, gain_vals, "b-o", markersize=5,
                        linewidth=1.5, label="Gain (dB)")

        ss_gain = sum(gain_vals[:min(3, len(gain_vals))]) / min(3, len(gain_vals))

        p1db_pin  = None
        p1db_gain = None
        for p, g in zip(pin_vals, gain_vals):
            if g >= ss_gain - 1.0:
                p1db_pin  = p
                p1db_gain = g

        self.ax_gp.axhline(y=ss_gain, color="gray", linestyle="--",
                            linewidth=1.0, label=f"SS Gain = {ss_gain:.1f} dB")
        self.ax_gp.axhline(y=ss_gain - 1.0, color="orange", linestyle=":",
                            linewidth=1.0, label="SS Gain − 1 dB")

        if p1db_pin is not None:
            self.ax_gp.annotate(
                f"P1dB ≈ {p1db_pin:.1f} dBm\n(Gain = {p1db_gain:.1f} dB)",
                xy=(p1db_pin, p1db_gain),
                xytext=(20, 15), textcoords="offset points",
                arrowprops=dict(arrowstyle="->", color="red"),
                fontsize=9, color="red",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="red", alpha=0.8)
            )
            self.ax_gp.axvline(x=p1db_pin, color="red", linestyle="--",
                                linewidth=0.8, alpha=0.6)

        self.ax_gp.set_xlabel("Pin (dBm)")
        self.ax_gp.set_ylabel("Gain (dB)")
        self.ax_gp.set_title(f"Gain vs Pin — {os.path.basename(self.file_var.get())}")
        self.ax_gp.legend(fontsize=8)
        self.ax_gp.grid(True, linestyle="--", alpha=0.5)
        self.fig_gp.tight_layout(pad=2.5)
        self.canvas_gp.draw()

        p1db_str = f"P1dB ≈ {p1db_pin:.1f} dBm" if p1db_pin else "P1dB not reached in sweep range"
        self.status_lbl.config(
            text=f"Gain vs Pin plotted — {p1db_str}", foreground="green")

    # ── PAE vs Pin plot ────────────────────────────────────────
    def _plot_pae(self):
        rows = self._sweep_rows()
        if not rows:
            messagebox.showwarning("No Sweep Data",
                                   "No sweep rows found. Run a power sweep first.")
            return

        pin_vals  = [self._safe_parse(r.get("Pin_dBm",  "")) for r in rows]
        pout_vals = [self._safe_parse(r.get("Pout_dBm", "")) for r in rows]
        pae_vals  = [self._safe_parse(r.get("PAE_%",    "")) for r in rows]
        gain_vals = [self._safe_parse(r.get("Gain_dB",  "")) for r in rows]

        tuples = [(p, po, pa, g) for p, po, pa, g
                  in zip(pin_vals, pout_vals, pae_vals, gain_vals)
                  if p is not None and pa is not None]

        if not tuples:
            messagebox.showwarning("No PAE Data",
                                   "PAE_% column is empty.\n\n"
                                   "Make sure:\n"
                                   "  • DMMs are connected\n"
                                   "  • One DMM is set to VOLT:DC (drain voltage)\n"
                                   "  • One DMM is set to CURR:DC (drain current)\n"
                                   "  • A power sweep was run with this sequencer version.")
            return

        pin_vals, pout_vals, pae_vals, gain_vals = zip(*sorted(tuples))

        self.ax_pae1.clear()

        color_pae  = "#1a7a1a"
        color_gain = "#1a4a9a"

        self.ax_pae1.plot(pin_vals, pae_vals, "o-",
                          color=color_pae, linewidth=1.8,
                          markersize=5, label="PAE (%)")
        self.ax_pae1.set_xlabel("Pin (dBm)")
        self.ax_pae1.set_ylabel("PAE (%)", color=color_pae)
        self.ax_pae1.tick_params(axis="y", labelcolor=color_pae)

        ax2 = self.ax_pae1.twinx()
        ax2.plot(pin_vals, gain_vals, "s--",
                 color=color_gain, linewidth=1.4,
                 markersize=4, label="Gain (dB)")
        ax2.set_ylabel("Gain (dB)", color=color_gain)
        ax2.tick_params(axis="y", labelcolor=color_gain)

        max_pae     = max(pae_vals)
        max_pae_pin = pin_vals[pae_vals.index(max_pae)]
        self.ax_pae1.annotate(
            f"Peak PAE\n{max_pae:.1f}%\n@ {max_pae_pin:.1f} dBm",
            xy=(max_pae_pin, max_pae),
            xytext=(15, -30), textcoords="offset points",
            arrowprops=dict(arrowstyle="->", color=color_pae),
            fontsize=9, color=color_pae,
            bbox=dict(boxstyle="round,pad=0.3", fc="white",
                      ec=color_pae, alpha=0.85)
        )

        l1, lb1 = self.ax_pae1.get_legend_handles_labels()
        l2, lb2 = ax2.get_legend_handles_labels()
        self.ax_pae1.legend(l1 + l2, lb1 + lb2, loc="upper left", fontsize=8)

        self.ax_pae1.set_title(
            f"PAE & Gain vs Pin — {os.path.basename(self.file_var.get())}")
        self.ax_pae1.grid(True, linestyle="--", alpha=0.5)
        self.fig_pae.tight_layout(pad=2.5)
        self.canvas_pae.draw()
        self.status_lbl.config(
            text=f"PAE plotted — Peak PAE = {max_pae:.1f}% @ Pin = {max_pae_pin:.1f} dBm",
            foreground="green")

    # ── Spectrum plot ──────────────────────────────────────────
    def _plot_spectrum(self):
        trace_path = self.trace_file_var.get()
        if trace_path and trace_path != "— use loaded session file —":
            freqs, amps = self._load_trace_csv(trace_path)
        else:
            if not self._rows:
                messagebox.showwarning("No Data", "Load a session CSV first.")
                return
            trace_rows = [r for r in self._rows
                          if self._safe_parse(r.get("Frequency(Hz)", "")) is not None]
            if not trace_rows:
                messagebox.showwarning("No Spectrum Data",
                                       "No Frequency(Hz)/Power(dBm) rows found.")
                return
            freqs = [self._safe_parse(r.get("Frequency(Hz)", "")) for r in trace_rows]
            amps  = [self._safe_parse(r.get("Power(dBm)",    "")) or 0.0
                     for r in trace_rows]

        if not freqs:
            messagebox.showwarning("Empty Trace", "No data points found.")
            return

        self.ax_sp.clear()
        freqs_mhz = [f / 1e6 for f in freqs if f is not None]
        self.ax_sp.plot(freqs_mhz, amps, "g-", linewidth=1.2, label="Amplitude")
        self.ax_sp.set_xlabel("Frequency (MHz)")
        self.ax_sp.set_ylabel("Amplitude (dBm)")
        self.ax_sp.set_title(f"Spectrum — {os.path.basename(self.file_var.get())}")
        self.ax_sp.grid(True, linestyle="--", alpha=0.5)

        if amps:
            valid  = [(f, a) for f, a in zip(freqs_mhz, amps) if a is not None]
            peak_a = max(valid, key=lambda x: x[1])
            self.ax_sp.annotate(
                f"Peak: {peak_a[1]:.1f} dBm\n@ {peak_a[0]:.3f} MHz",
                xy=peak_a,
                xytext=(15, -25), textcoords="offset points",
                arrowprops=dict(arrowstyle="->", color="black"),
                fontsize=8, color="darkgreen"
            )

        self.ax_sp.legend()
        self.fig_sp.tight_layout(pad=2.5)
        self.canvas_sp.draw()
        self.status_lbl.config(
            text=f"Spectrum plotted: {len(freqs)} points", foreground="green")
    
    
    def refresh(self):
        """Called by run engine on completion — auto-loads the newest result."""
        self._refresh_file_list()
        files = self.file_combo["values"]
        if not files:
            return
        # Newest file is first (sorted reverse=True)
        self.file_combo.current(0)
        self._load_file()
        self.status_lbl.config(
            text=f"Auto-loaded latest run: {os.path.basename(os.path.dirname(files[0]))}",
            foreground="green")

    def _load_trace_csv(self, path: str):
        freqs, amps = [], []
        try:
            with open(path, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    for k, v in row.items():
                        if "freq" in k.lower():
                            v2 = self._safe_parse(v)
                            if v2 is not None:
                                freqs.append(v2)
                        if any(x in k.lower() for x in ("amp", "dbm", "power")):
                            v2 = self._safe_parse(v)
                            if v2 is not None:
                                amps.append(v2)
        except Exception as e:
            messagebox.showerror("Trace Load Error", str(e))
        return freqs, amps
