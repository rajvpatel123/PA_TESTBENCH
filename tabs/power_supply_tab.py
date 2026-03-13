import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
from utils.logger import get_logger
from utils.live_poll_manager import LivePollManager

_logger = get_logger(__name__)

# channels= must match actual hardware:
#   Keysight E36234A  -> 4 channels
#   Keysight E36233A  -> 2 channels
#   Agilent E3648A    -> 2 channels
#   HP 6633B          -> 1 channel
POWER_SUPPLIES = [
    {"name": "Keysight_E36234A", "channels": 4},
    {"name": "Keysight_E36233A", "channels": 2},
    {"name": "Agilent_E3648A_GPIB15", "channels": 2},
    {"name": "Agilent_E3648A_GPIB11", "channels": 2},
    {"name": "HP_6633B", "channels": 1},
]

ALIASES_FILE = "instrument_aliases.json"
READBACK_INTERVAL_MS = 1500
UI_REFRESH_MS = 250


class PowerSupplyTab(ttk.Frame):
    def __init__(self, parent, driver_registry: dict):
        super().__init__(parent)
        self._registry = driver_registry
        self._channels = {}
        self._pairs = []
        self._alias_map = self._load_aliases()

        self._ui_refresh_job = None
        self._poll_manager = LivePollManager(
            registry_getter=lambda: self._registry,
            channels_getter=lambda: self._channels,
        )

        self._build_ui()

    def set_driver_registry(self, registry: dict):
        self._registry = registry

    def set_aliases(self, alias_map: dict):
        self._alias_map = alias_map
        self._populate_channels()

    def stop_polling(self):
        self._stop_live_readback()

    # ── Alias helpers ──────────────────────────────────────────
    def _load_aliases(self) -> dict:
        if os.path.exists(ALIASES_FILE):
            try:
                with open(ALIASES_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _ch_label(self, supply_name: str, ch: int) -> str:
        alias = self._alias_map.get(supply_name, "")
        if alias:
            return f"{alias} CH{ch}  ({supply_name})"
        return f"{supply_name} CH{ch}"

    # ── UI ─────────────────────────────────────────────────────
    def _build_ui(self):
        ttk.Label(
            self,
            text="Power Supply Configuration",
            font=("Segoe UI", 14, "bold"),
        ).pack(pady=10)

        main_frame = ttk.Frame(self)
        main_frame.pack(fill="both", expand=True, padx=10, pady=5)

        # ── LEFT: channel table ────────────────────────────────
        left = ttk.LabelFrame(main_frame, text="Supply Channels")
        left.pack(side="left", fill="both", expand=True, padx=(0, 5))

        cols = ("Channel", "Role", "Mode", "Set V", "Set A", "Prot Limit", "Meas V", "Meas A", "Output")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", height=14)

        col_widths = {
            "Channel": 250,
            "Role": 70,
            "Mode": 50,
            "Set V": 80,
            "Set A": 80,
            "Prot Limit": 100,
            "Meas V": 90,
            "Meas A": 90,
            "Output": 65,
        }

        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=col_widths[col], anchor="center")

        self.tree.pack(fill="both", expand=True, padx=5, pady=5)
        self.tree.bind("<Double-1>", self._on_row_double_click)

        ttk.Label(
            left,
            text="Double-click a row to configure  |  Meas V / Meas A update during live readback",
            foreground="gray",
        ).pack(pady=2)

        # ── Set / On / Off buttons ─────────────────────────────
        act_frame = ttk.LabelFrame(left, text="Channel Actions  (select a row first)")
        act_frame.pack(fill="x", padx=5, pady=4)

        row_a = ttk.Frame(act_frame)
        row_a.pack(fill="x", padx=10, pady=6)

        ttk.Button(row_a, text="Set Values", command=self._set_selected).pack(side="left", padx=(0, 6))
        ttk.Label(
            row_a,
            text="Sends V / I + protection limit to hardware. Output state unchanged.",
            foreground="gray",
        ).pack(side="left")

        row_b = ttk.Frame(act_frame)
        row_b.pack(fill="x", padx=10, pady=(0, 8))

        tk.Button(
            row_b,
            text="  ON  ",
            bg="#1a7a1a",
            fg="white",
            activebackground="#145a14",
            activeforeground="white",
            font=("Segoe UI", 10, "bold"),
            command=self._output_on_selected,
        ).pack(side="left", padx=(0, 6))

        tk.Button(
            row_b,
            text="  OFF  ",
            bg="#8b0000",
            fg="white",
            activebackground="#5a0000",
            activeforeground="white",
            font=("Segoe UI", 10, "bold"),
            command=self._output_off_selected,
        ).pack(side="left", padx=(0, 12))

        ttk.Label(
            row_b,
            text="ON enables output.  OFF disables output.",
            foreground="gray",
        ).pack(side="left")

        # ── Readback ───────────────────────────────────────────
        rb_frame = ttk.Frame(left)
        rb_frame.pack(fill="x", padx=5, pady=4)

        ttk.Label(rb_frame, text="Readback interval (ms):").pack(side="left", padx=(0, 5))
        self.rb_interval_var = tk.StringVar(value=str(READBACK_INTERVAL_MS))
        ttk.Entry(rb_frame, textvariable=self.rb_interval_var, width=7).pack(side="left", padx=5)

        self.rb_btn = ttk.Button(rb_frame, text="Start Live Readback", command=self._toggle_readback)
        self.rb_btn.pack(side="left", padx=10)

        ttk.Button(rb_frame, text="Read Once", command=self._read_once).pack(side="left", padx=5)

        # ── RIGHT: pairing panel ───────────────────────────────
        right = ttk.LabelFrame(main_frame, text="Gate / Drain Pairing")
        right.pack(side="right", fill="y", padx=(5, 0))

        ttk.Label(right, text="Available Gate channels:").pack(anchor="w", padx=5, pady=(10, 0))
        self.gate_list = tk.Listbox(
            right,
            height=6,
            width=38,
            selectmode="single",
            exportselection=False,
        )
        self.gate_list.pack(padx=5, pady=2)

        ttk.Label(right, text="Available Drain channels:").pack(anchor="w", padx=5, pady=(8, 0))
        self.drain_list = tk.Listbox(
            right,
            height=6,
            width=38,
            selectmode="single",
            exportselection=False,
        )
        self.drain_list.pack(padx=5, pady=2)

        ttk.Button(right, text="Pair Selected", command=self._pair_selected).pack(fill="x", padx=5, pady=4)
        ttk.Button(right, text="Unpair Selected", command=self._unpair_selected).pack(fill="x", padx=5, pady=2)

        ttk.Separator(right, orient="horizontal").pack(fill="x", padx=5, pady=8)

        ttk.Label(right, text="Active Pairs:", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=5)
        self.pairs_list = tk.Listbox(right, height=5, width=38)
        self.pairs_list.pack(padx=5, pady=2)

        self.status_lbl = ttk.Label(self, text="Status: Idle", foreground="gray")
        self.status_lbl.pack(pady=5)

        self._populate_channels()

    def _populate_channels(self):
        existing = {k: v for k, v in self._channels.items()}
        self.tree.delete(*self.tree.get_children())
        self._channels.clear()

        for ps in POWER_SUPPLIES:
            name = ps["name"]
            for ch in range(1, ps["channels"] + 1):
                ch_id = f"{name}_CH{ch}"
                ch_label = self._ch_label(name, ch)
                prev = existing.get(ch_id, {})

                self._channels[ch_id] = {
                    "supply": name,
                    "channel": ch,
                    "label": ch_label,
                    "role": prev.get("role", "None"),
                    "mode": prev.get("mode", "CV"),
                    "pair": prev.get("pair", None),
                    "volt_var": prev.get("volt_var", tk.StringVar(value="")),
                    "curr_var": prev.get("curr_var", tk.StringVar(value="")),
                    "ovp_var": prev.get("ovp_var", tk.StringVar(value="")),
                    "ocp_var": prev.get("ocp_var", tk.StringVar(value="")),
                    "target_idq_ma": prev.get("target_idq_ma", tk.StringVar(value="")),
                    "idq_tolerance_ma": prev.get("idq_tolerance_ma", tk.StringVar(value="5")),
                    "idq_step_mv": prev.get("idq_step_mv", tk.StringVar(value="50")),
                    "max_idq_ma": prev.get("max_idq_ma", tk.StringVar(value="")),
                }

                self.tree.insert(
                    "",
                    "end",
                    iid=ch_id,
                    values=(ch_label, self._channels[ch_id]["role"], self._channels[ch_id]["mode"], "", "", "", "---", "---", "OFF"),
                )

                self._poll_manager.ensure_channel(ch_id)

        self._poll_manager.remove_missing_channels(self._channels.keys())
        self._refresh_pairing_lists()

    # ── Edit dialog ────────────────────────────────────────────
    def _on_row_double_click(self, event):
        sel = self.tree.selection()
        if sel:
            self._open_edit_dialog(sel[0])

    def _open_edit_dialog(self, ch_id: str):
        info = self._channels[ch_id]
        dialog = tk.Toplevel(self)
        dialog.title(f"Configure: {info['label']}")
        dialog.grab_set()
        dialog.resizable(False, False)

        ttk.Label(dialog, text=info["label"], font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, columnspan=2, padx=15, pady=10
        )

        role_var = tk.StringVar(value=info["role"])
        mode_var = tk.StringVar(value=info["mode"])

        role_frame = ttk.LabelFrame(dialog, text="Role")
        role_frame.grid(row=1, column=0, columnspan=2, padx=12, pady=4, sticky="ew")
        ttk.Label(role_frame, text="Role:", width=14, anchor="e").grid(row=0, column=0, padx=8, pady=6, sticky="e")
        ttk.Combobox(
            role_frame,
            textvariable=role_var,
            values=["None", "Gate", "Drain"],
            state="readonly",
            width=14,
        ).grid(row=0, column=1, padx=8, pady=6, sticky="w")

        mode_frame = ttk.LabelFrame(dialog, text="Output Mode")
        mode_frame.grid(row=2, column=0, columnspan=2, padx=12, pady=4, sticky="ew")

        ttk.Radiobutton(
            mode_frame,
            text="CV — Constant Voltage",
            variable=mode_var,
            value="CV",
            command=lambda: _refresh_val_rows(),
        ).grid(row=0, column=0, padx=12, pady=(8, 2), sticky="w")

        ttk.Label(
            mode_frame,
            text="You set: Voltage (V)  +  OCP Limit (A)\nSupply holds the voltage. Trips off if current exceeds OCP.",
            foreground="gray",
            justify="left",
        ).grid(row=1, column=0, padx=28, pady=(0, 6), sticky="w")

        ttk.Radiobutton(
            mode_frame,
            text="CC — Constant Current",
            variable=mode_var,
            value="CC",
            command=lambda: _refresh_val_rows(),
        ).grid(row=2, column=0, padx=12, pady=(4, 2), sticky="w")

        ttk.Label(
            mode_frame,
            text="You set: Current (A)  +  OVP Limit (V)\nSupply holds the current. Trips off if voltage exceeds OVP.",
            foreground="gray",
            justify="left",
        ).grid(row=3, column=0, padx=28, pady=(0, 8), sticky="w")

        vals_frame = ttk.LabelFrame(dialog, text="Values")
        vals_frame.grid(row=3, column=0, columnspan=2, padx=12, pady=4, sticky="ew")

        lbl_volt = ttk.Label(vals_frame, text="Set Voltage (V):", width=20, anchor="e")
        ent_volt = ttk.Entry(vals_frame, textvariable=info["volt_var"], width=14)
        lbl_ocp = ttk.Label(vals_frame, text="OCP Limit (A):", width=20, anchor="e")
        ent_ocp = ttk.Entry(vals_frame, textvariable=info["ocp_var"], width=14)

        lbl_curr = ttk.Label(vals_frame, text="Set Current (A):", width=20, anchor="e")
        ent_curr = ttk.Entry(vals_frame, textvariable=info["curr_var"], width=14)
        lbl_ovp = ttk.Label(vals_frame, text="OVP Limit (V):", width=20, anchor="e")
        ent_ovp = ttk.Entry(vals_frame, textvariable=info["ovp_var"], width=14)

        gate_warn = ttk.Label(
            vals_frame,
            text="Gate voltage must be negative for GaN (e.g. -3.0 V)",
            foreground="orange",
        )

        def _refresh_val_rows():
            for w in (lbl_volt, ent_volt, lbl_ocp, ent_ocp, lbl_curr, ent_curr, lbl_ovp, ent_ovp, gate_warn):
                w.grid_remove()

            if mode_var.get() == "CV":
                lbl_volt.grid(row=0, column=0, padx=8, pady=5, sticky="e")
                ent_volt.grid(row=0, column=1, padx=8, pady=5, sticky="w")
                lbl_ocp.grid(row=1, column=0, padx=8, pady=5, sticky="e")
                ent_ocp.grid(row=1, column=1, padx=8, pady=5, sticky="w")
                gate_warn.grid(row=2, column=0, columnspan=2, padx=8, pady=(0, 6))
            else:
                lbl_curr.grid(row=0, column=0, padx=8, pady=5, sticky="e")
                ent_curr.grid(row=0, column=1, padx=8, pady=5, sticky="w")
                lbl_ovp.grid(row=1, column=0, padx=8, pady=5, sticky="e")
                ent_ovp.grid(row=1, column=1, padx=8, pady=5, sticky="w")

        _refresh_val_rows()

        idq_frame = ttk.LabelFrame(dialog, text="Idq Targeting  (Drain channel only)")
        idq_frame.grid(row=4, column=0, columnspan=2, padx=12, pady=4, sticky="ew")

        def idq_row(parent, label, var, row, hint=""):
            ttk.Label(parent, text=label, width=22, anchor="e").grid(row=row, column=0, padx=8, pady=4, sticky="e")
            ttk.Entry(parent, textvariable=var, width=12).grid(row=row, column=1, padx=8, pady=4, sticky="w")
            if hint:
                ttk.Label(parent, text=hint, foreground="gray").grid(row=row, column=2, padx=4, sticky="w")

        idq_row(idq_frame, "Target Idq (mA):", info["target_idq_ma"], 0, "Leave blank to skip")
        idq_row(idq_frame, "Tolerance \u00b1 (mA):", info["idq_tolerance_ma"], 1, "Default: 5 mA")
        idq_row(idq_frame, "Gate Step Size (mV):", info["idq_step_mv"], 2, "Default: 50 mV")
        idq_row(idq_frame, "Hard Abort > (mA):", info["max_idq_ma"], 3, "Leave blank = 3\u00d7 target")

        ttk.Label(
            idq_frame,
            text="Set on the DRAIN channel. The sequencer walks gate voltage\ntoward final gate V while monitoring drain current.",
            foreground="gray",
        ).grid(row=4, column=0, columnspan=3, padx=8, pady=(0, 6))

        btn_frame = ttk.Frame(dialog)
        btn_frame.grid(row=5, column=0, columnspan=2, pady=10)

        def _apply_meta():
            info["role"] = role_var.get()
            info["mode"] = mode_var.get()
            self._update_tree_row(ch_id)
            self._refresh_pairing_lists()

        def apply():
            _apply_meta()
            dialog.destroy()

        def set_now():
            _apply_meta()
            dialog.destroy()
            self._set_channel_values(ch_id)

        def set_and_on():
            _apply_meta()
            dialog.destroy()
            self._set_channel_values(ch_id)
            self._channel_output(ch_id, True)

        ttk.Button(btn_frame, text="Apply (no hardware)", command=apply).pack(side="left", padx=6)
        ttk.Button(btn_frame, text="Set Values", command=set_now).pack(side="left", padx=6)
        ttk.Button(btn_frame, text="Set + ON", command=set_and_on).pack(side="left", padx=6)

    def _update_tree_row(self, ch_id: str):
        info = self._channels[ch_id]
        mode = info["mode"]
        vals = list(self.tree.item(ch_id, "values"))

        if mode == "CV":
            set_v = info["volt_var"].get()
            set_a = ""
            prot = f"OCP {info['ocp_var'].get()} A" if info["ocp_var"].get() else ""
        else:
            set_v = ""
            set_a = info["curr_var"].get()
            prot = f"OVP {info['ovp_var'].get()} V" if info["ovp_var"].get() else ""

        self.tree.item(
            ch_id,
            values=(
                info["label"],
                info["role"],
                mode,
                set_v,
                set_a,
                prot,
                vals[6],
                vals[7],
                vals[8],
            ),
        )

    # ── Pairing ────────────────────────────────────────────────
    def _refresh_pairing_lists(self):
        paired_ids = {g for g, d in self._pairs} | {d for g, d in self._pairs}
        self.gate_list.delete(0, tk.END)
        self.drain_list.delete(0, tk.END)

        for ch_id, info in self._channels.items():
            if ch_id in paired_ids:
                continue
            if info["role"] == "Gate":
                self.gate_list.insert(tk.END, info["label"])
            elif info["role"] == "Drain":
                self.drain_list.insert(tk.END, info["label"])

    def _label_to_id(self, label: str):
        for ch_id, info in self._channels.items():
            if info["label"] == label:
                return ch_id
        return None

    def _pair_selected(self):
        gate_sel = self.gate_list.curselection()
        drain_sel = self.drain_list.curselection()

        if not gate_sel or not drain_sel:
            messagebox.showwarning("Select Both", "Select one Gate and one Drain channel.")
            return

        gate_label = self.gate_list.get(gate_sel[0])
        drain_label = self.drain_list.get(drain_sel[0])
        gate_id = self._label_to_id(gate_label)
        drain_id = self._label_to_id(drain_label)

        if gate_id is None or drain_id is None:
            messagebox.showerror("Error", "Could not resolve channel IDs.")
            return

        self._pairs.append((gate_id, drain_id))
        self._channels[gate_id]["pair"] = drain_id
        self._channels[drain_id]["pair"] = gate_id

        self.pairs_list.insert(
            tk.END,
            f"GATE: {self._channels[gate_id]['label']}  <->  DRAIN: {self._channels[drain_id]['label']}",
        )
        self._refresh_pairing_lists()
        self.status_lbl.config(text=f"Paired {gate_label} <-> {drain_label}", foreground="green")
        _logger.info(f"Paired Gate={gate_id} Drain={drain_id}")

    def _unpair_selected(self):
        sel = self.pairs_list.curselection()
        if not sel:
            messagebox.showwarning("No Selection", "Select a pair to remove.")
            return

        idx = sel[0]
        gate_id, drain_id = self._pairs[idx]
        self._channels[gate_id]["pair"] = None
        self._channels[drain_id]["pair"] = None
        self._pairs.pop(idx)
        self.pairs_list.delete(idx)
        self._refresh_pairing_lists()
        self.status_lbl.config(text=f"Unpaired {gate_id} <-> {drain_id}", foreground="gray")
        _logger.info(f"Unpaired Gate={gate_id} Drain={drain_id}")

    # ── Hardware actions ───────────────────────────────────────
    def _get_selected_ch_id(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("No Selection", "Select a channel row first.")
            return None
        return sel[0]

    def _set_selected(self):
        ch_id = self._get_selected_ch_id()
        if ch_id:
            self._set_channel_values(ch_id)

    def _output_on_selected(self):
        ch_id = self._get_selected_ch_id()
        if ch_id:
            self._channel_output(ch_id, True)

    def _output_off_selected(self):
        ch_id = self._get_selected_ch_id()
        if ch_id:
            self._channel_output(ch_id, False)

    def _set_channel_values(self, ch_id: str):
        info = self._channels[ch_id]
        drv = self._registry.get(info["supply"])
        if drv is None:
            messagebox.showerror("Not Connected", f"{info['supply']} not in driver registry.")
            return

        try:
            if info["mode"] == "CV":
                volt_str = info["volt_var"].get().strip()
                ocp_str = info["ocp_var"].get().strip()

                if not volt_str:
                    messagebox.showwarning("Missing Value", f"Enter a voltage for {ch_id}.")
                    return

                volts = float(volt_str)
                if info["role"] == "Gate" and volts > 0:
                    if not messagebox.askyesno(
                        "Gate Warning",
                        f"Gate voltage {volts} V is positive.\nGate should normally be negative for GaN.\nSend anyway?",
                    ):
                        return

                drv.set_voltage(info["channel"], volts)
                if ocp_str:
                    drv.set_ocp(info["channel"], float(ocp_str))

                self.status_lbl.config(
                    text=f"Set {info['label']}: {volts} V  | OCP = {ocp_str or 'unchanged'} A",
                    foreground="blue",
                )
                _logger.info(f"Set {ch_id} CV: {volts} V  OCP={ocp_str}")
            else:
                curr_str = info["curr_var"].get().strip()
                ovp_str = info["ovp_var"].get().strip()

                if not curr_str:
                    messagebox.showwarning("Missing Value", f"Enter a current for {ch_id}.")
                    return

                amps = float(curr_str)
                drv.set_current(info["channel"], amps)
                if ovp_str:
                    drv.set_ovp(info["channel"], float(ovp_str))

                self.status_lbl.config(
                    text=f"Set {info['label']}: {amps} A  | OVP = {ovp_str or 'unchanged'} V",
                    foreground="blue",
                )
                _logger.info(f"Set {ch_id} CC: {amps} A  OVP={ovp_str}")

            self._update_tree_row(ch_id)

        except ValueError:
            messagebox.showerror("Invalid Input", "Values must be numbers.")
        except Exception as e:
            messagebox.showerror("Hardware Error", str(e))
            _logger.error(f"Set values failed {ch_id}: {e}")

    def _channel_output(self, ch_id: str, enable: bool):
        info = self._channels[ch_id]
        drv = self._registry.get(info["supply"])
        if drv is None:
            messagebox.showerror("Not Connected", f"{info['supply']} not in driver registry.")
            return

        try:
            # Fix: pass enable bool explicitly — driver signature is output_on(channel, enable)
            drv.output_on(info["channel"], enable)

            state = "ON" if enable else "OFF"
            vals = list(self.tree.item(ch_id, "values"))
            vals[8] = state
            self.tree.item(ch_id, values=vals)

            color = "green" if enable else "gray"
            self.status_lbl.config(text=f"{info['label']} output {state}", foreground=color)
            _logger.info(f"{ch_id} output {state}")

        except Exception as e:
            messagebox.showerror("Hardware Error", str(e))
            _logger.error(f"Output toggle failed {ch_id}: {e}")

    # ── Live readback ──────────────────────────────────────────
    def _toggle_readback(self):
        if self._poll_manager.is_running():
            self._stop_live_readback()
        else:
            self._start_live_readback()

    def _start_live_readback(self):
        try:
            interval_ms = int(self.rb_interval_var.get())
            if interval_ms < 100:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid Interval", "Interval must be an integer >= 100 ms.")
            return

        self._poll_manager.start(interval_ms)
        self.rb_btn.config(text="Stop Live Readback")
        self.status_lbl.config(text="Status: Readback running...", foreground="orange")
        self._schedule_ui_refresh()

    def _stop_live_readback(self):
        self._poll_manager.stop()
        self.rb_btn.config(text="Start Live Readback")
        self.status_lbl.config(text="Status: Readback stopped", foreground="gray")

        if self._ui_refresh_job is not None:
            try:
                self.after_cancel(self._ui_refresh_job)
            except Exception:
                pass
            self._ui_refresh_job = None

    def _read_once(self):
        self._poll_manager.poll_once()
        self._refresh_readback_ui()
        self.status_lbl.config(text="Status: Readback complete", foreground="green")

    def _schedule_ui_refresh(self):
        if self._ui_refresh_job is not None:
            try:
                self.after_cancel(self._ui_refresh_job)
            except Exception:
                pass

        self._ui_refresh_job = self.after(UI_REFRESH_MS, self._refresh_readback_ui)

    def _refresh_readback_ui(self):
        snapshot = self._poll_manager.get_cache_snapshot()

        for ch_id, cache in snapshot.items():
            if not self.tree.exists(ch_id):
                continue

            vals = list(self.tree.item(ch_id, "values"))
            vals[6] = cache.get("meas_v", "---")
            vals[7] = cache.get("meas_a", "---")
            self.tree.item(ch_id, values=vals)

        if self._poll_manager.is_running():
            self._schedule_ui_refresh()
        else:
            self._ui_refresh_job = None

    # ── Sequencer API ──────────────────────────────────────────
    def get_pairs(self) -> list:
        result = []
        for gate_id, drain_id in self._pairs:
            gi = self._channels[gate_id]
            di = self._channels[drain_id]

            if gi["mode"] == "CV":
                final_gate_v = gi["volt_var"].get()
                gate_curr = gi["ocp_var"].get()
            else:
                final_gate_v = "0"
                gate_curr = gi["curr_var"].get()

            if di["mode"] == "CV":
                drain_curr = di["ocp_var"].get()
            else:
                drain_curr = di["curr_var"].get()

            result.append(
                {
                    "gate_id": gate_id,
                    "drain_id": drain_id,
                    "gate_supply": gi["supply"],
                    "gate_channel": gi["channel"],
                    "drain_supply": di["supply"],
                    "drain_channel": di["channel"],
                    "final_gate_v": final_gate_v,
                    "gate_curr": gate_curr,
                    "drain_curr": drain_curr,
                    "target_idq_ma": di["target_idq_ma"].get(),
                    "idq_tolerance_ma": di["idq_tolerance_ma"].get(),
                    "idq_step_mv": di["idq_step_mv"].get(),
                    "max_idq_ma": di["max_idq_ma"].get(),
                }
            )
        return result
