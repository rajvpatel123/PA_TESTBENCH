# tabs/signal_generator_tab.py
import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from utils.logger import get_logger
from utils.freq_entry import FreqEntry

_logger = get_logger(__name__)

# Roots searched by the waveform file browser.
# On the instrument PC, waveforms are typically under C:/Users or C:/user.
WAVEFORM_ROOTS = [r"C:\Users", r"C:\user", r"C:\users",
                  r"D:\Users", r"D:\user"]
WAVEFORM_EXTS  = {".wv", ".iq", ".bin", ".csv"}


class SignalGeneratorTab(ttk.Frame):

    DRIVER_NAME = "RS_SMBV100B"

    def __init__(self, parent, driver_registry: dict):
        super().__init__(parent)
        self._registry = driver_registry
        self._build_ui()

    def set_driver_registry(self, registry: dict):
        self._registry = registry

    def _get_driver(self):
        drv = self._registry.get(self.DRIVER_NAME)
        if drv is None:
            messagebox.showerror(
                "Not Connected",
                f"{self.DRIVER_NAME} not connected.\n"
                "Go to Device Manager and click Connect All.")
        return drv

    # ── UI ─────────────────────────────────────────────────────
    def _build_ui(self):
        ttk.Label(self, text="Signal Generator - R&S SMBV100B",
                  font=("Segoe UI", 14, "bold")).pack(pady=10)

        main = ttk.Frame(self)
        main.pack(fill="both", expand=True, padx=15, pady=5)

        self._build_left(main)
        self._build_right(main)

        self.status_lbl = ttk.Label(self, text="Status: Idle",
                                     foreground="gray")
        self.status_lbl.pack(pady=5)

    # ── LEFT: RF Settings ──────────────────────────────────────
    def _build_left(self, parent):
        left = ttk.LabelFrame(parent, text="RF Settings")
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))

        # Frequency
        freq_frame = ttk.Frame(left)
        freq_frame.pack(fill="x", padx=10, pady=8)
        ttk.Label(freq_frame, text="Frequency:",
                  width=18, anchor="e").pack(side="left")
        self.freq_fe = FreqEntry(freq_frame, width=14, default_unit="MHz")
        self.freq_fe.pack(side="left", padx=5)

        # Power
        power_frame = ttk.Frame(left)
        power_frame.pack(fill="x", padx=10, pady=8)
        ttk.Label(power_frame, text="Power Level:",
                  width=18, anchor="e").pack(side="left")
        self.power_var = tk.StringVar(value="")
        ttk.Entry(power_frame, textvariable=self.power_var,
                  width=16).pack(side="left", padx=5)
        ttk.Label(power_frame, text="dBm").pack(side="left")

        # Modulation
        mod_frame = ttk.Frame(left)
        mod_frame.pack(fill="x", padx=10, pady=8)
        ttk.Label(mod_frame, text="Modulation:",
                  width=18, anchor="e").pack(side="left")
        self.mod_var = tk.StringVar(value="")
        ttk.Combobox(
            mod_frame, textvariable=self.mod_var, width=14,
            values=["None", "AM", "FM", "PM", "IQ", "ARB"],
            state="readonly").pack(side="left", padx=5)

        ttk.Button(left, text="Apply Settings",
                   command=self._apply_settings).pack(
                   pady=10, padx=10, fill="x")

        ttk.Separator(left, orient="horizontal").pack(
            fill="x", padx=10, pady=5)

        # RF toggle
        rf_frame = ttk.Frame(left)
        rf_frame.pack(fill="x", padx=10, pady=8)
        ttk.Label(rf_frame, text="RF Output:",
                  width=18, anchor="e").pack(side="left")
        self.rf_state_var = tk.StringVar(value="OFF")
        self.rf_btn = ttk.Button(rf_frame, text="RF OFF",
                                  command=self._toggle_rf)
        self.rf_btn.pack(side="left", padx=5)
        self.rf_status_lbl = ttk.Label(rf_frame, text="RF is OFF",
                                        foreground="red")
        self.rf_status_lbl.pack(side="left", padx=10)

        ttk.Separator(left, orient="horizontal").pack(
            fill="x", padx=10, pady=5)

        # Presets
        preset_frame = ttk.LabelFrame(left, text="Quick Presets")
        preset_frame.pack(fill="x", padx=10, pady=5)
        ttk.Button(preset_frame, text="1 GHz / 0 dBm",
                   command=lambda: self._apply_preset(1e9, 0)).pack(
                   side="left", padx=5, pady=5)
        ttk.Button(preset_frame, text="2.4 GHz / -10 dBm",
                   command=lambda: self._apply_preset(2.4e9, -10)).pack(
                   side="left", padx=5, pady=5)
        ttk.Button(preset_frame, text="5.8 GHz / -20 dBm",
                   command=lambda: self._apply_preset(5.8e9, -20)).pack(
                   side="left", padx=5, pady=5)

    # ── RIGHT: Waveform Management ─────────────────────────────
    def _build_right(self, parent):
        right = ttk.LabelFrame(parent, text="Waveform Management")
        right.pack(side="right", fill="both", expand=True)

        # ── File browser section ──────────────────────────────
        fb_lf = ttk.LabelFrame(right, text="Browse Machine Waveform Files")
        fb_lf.pack(fill="both", expand=True, padx=8, pady=(6, 4))
        fb_lf.rowconfigure(1, weight=1)
        fb_lf.columnconfigure(0, weight=1)

        # Root selector
        root_row = ttk.Frame(fb_lf)
        root_row.grid(row=0, column=0, columnspan=2,
                      sticky="ew", padx=6, pady=(4, 2))
        ttk.Label(root_row, text="Root folder:").pack(side="left", padx=(0, 4))
        self._fb_root_var = tk.StringVar()
        self._fb_root_cb  = ttk.Combobox(
            root_row, textvariable=self._fb_root_var,
            values=self._get_available_roots(),
            state="readonly", width=22)
        self._fb_root_cb.pack(side="left", padx=(0, 4))
        if self._fb_root_cb["values"]:
            self._fb_root_cb.current(0)
        self._fb_root_cb.bind("<<ComboboxSelected>>",
                               lambda e: self._fb_populate_tree())
        ttk.Button(root_row, text="Custom…",
                   command=self._fb_browse_custom).pack(side="left", padx=2)
        ttk.Button(root_row, text="↺",
                   command=self._fb_populate_tree,
                   width=3).pack(side="left", padx=2)

        # Tree + scrollbars
        tree_frame = ttk.Frame(fb_lf)
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=6, pady=(2, 4))
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        self._fb_tree = ttk.Treeview(
            tree_frame, columns=("size",), show="tree headings", height=10)
        self._fb_tree.heading("#0",    text="Name", anchor="w")
        self._fb_tree.heading("size",  text="Size", anchor="e")
        self._fb_tree.column("#0",    width=260, anchor="w")
        self._fb_tree.column("size",  width=70,  anchor="e")
        fb_vsb = ttk.Scrollbar(tree_frame, orient="vertical",
                                command=self._fb_tree.yview)
        fb_hsb = ttk.Scrollbar(tree_frame, orient="horizontal",
                                command=self._fb_tree.xview)
        self._fb_tree.configure(
            yscrollcommand=fb_vsb.set, xscrollcommand=fb_hsb.set)
        self._fb_tree.grid(row=0, column=0, sticky="nsew")
        fb_vsb.grid(row=0, column=1, sticky="ns")
        fb_hsb.grid(row=1, column=0, sticky="ew")

        # Expand folder on click
        self._fb_tree.bind("<<TreeviewOpen>>",  self._fb_on_expand)
        self._fb_tree.bind("<Double-1>",        self._fb_on_double_click)

        # File browser action buttons
        fb_btn = ttk.Frame(fb_lf)
        fb_btn.grid(row=2, column=0, sticky="ew", padx=6, pady=(0, 6))
        ttk.Button(fb_btn, text="Load to Device",
                   command=self._fb_upload_selected).pack(
                   side="left", padx=(0, 4))
        ttk.Button(fb_btn, text="Set as Active Waveform",
                   command=self._fb_set_active).pack(
                   side="left", padx=4)

        self._fb_selected_path: str = ""
        self._fb_selected_lbl = ttk.Label(
            fb_lf, text="Selected: (none)", foreground="gray")
        self._fb_selected_lbl.grid(
            row=3, column=0, sticky="w", padx=6, pady=(0, 4))

        # Populate on startup
        self._fb_populate_tree()

        # ── Waveforms on device ───────────────────────────────
        dev_lf = ttk.LabelFrame(right, text="Waveforms on Device")
        dev_lf.pack(fill="x", padx=8, pady=(0, 6))

        ttk.Button(dev_lf, text="↺  Refresh Waveform List",
                   command=self._refresh_waveforms).pack(
                   fill="x", padx=8, pady=(6, 4))

        self.waveform_list = tk.Listbox(dev_lf, height=6, width=40)
        self.waveform_list.pack(fill="x", padx=8, pady=4)

        wf_btn_frame = ttk.Frame(dev_lf)
        wf_btn_frame.pack(fill="x", padx=8, pady=4)
        ttk.Button(wf_btn_frame, text="Select Waveform",
                   command=self._select_waveform).pack(side="left", padx=5)
        ttk.Button(wf_btn_frame, text="Delete Waveform",
                   command=self._delete_waveform).pack(side="left", padx=5)

        self.selected_wf_lbl = ttk.Label(
            dev_lf, text="Selected: None", foreground="gray")
        self.selected_wf_lbl.pack(padx=8, pady=(0, 6))

    # ── File browser logic ─────────────────────────────────────
    def _get_available_roots(self) -> list:
        """Return only roots that actually exist on this machine."""
        return [r for r in WAVEFORM_ROOTS if os.path.isdir(r)]

    def _fb_browse_custom(self):
        chosen = filedialog.askdirectory(title="Select root folder")
        if chosen:
            chosen = os.path.normpath(chosen)
            vals   = list(self._fb_root_cb["values"])
            if chosen not in vals:
                vals.append(chosen)
                self._fb_root_cb["values"] = vals
            self._fb_root_var.set(chosen)
            self._fb_populate_tree()

    def _fb_populate_tree(self):
        root = self._fb_root_var.get()
        if not root or not os.path.isdir(root):
            return
        self._fb_tree.delete(*self._fb_tree.get_children())
        self._fb_insert_dir("", root, top_level=True)

    def _fb_insert_dir(self, parent_iid: str, path: str,
                       top_level: bool = False):
        """Insert one directory level into the tree."""
        try:
            entries = sorted(os.scandir(path),
                             key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return
        for entry in entries:
            if entry.is_dir():
                iid = self._fb_tree.insert(
                    parent_iid, "end",
                    text=entry.name,
                    values=("",),
                    open=False,
                    tags=("dir",))
                # Insert a dummy child so the expand arrow appears
                self._fb_tree.insert(iid, "end", text="loading…",
                                      tags=("placeholder",))
                self._fb_tree.item(iid, tags=("dir",))
                # Store full path in iid
                self._fb_tree.item(iid, tags=("dir", entry.path))
            elif os.path.splitext(entry.name)[1].lower() in WAVEFORM_EXTS:
                size_kb = entry.stat().st_size // 1024
                self._fb_tree.insert(
                    parent_iid, "end",
                    text=entry.name,
                    values=(f"{size_kb} KB" if size_kb else "< 1 KB",),
                    tags=("file", entry.path))

    def _fb_on_expand(self, event=None):
        """Lazy-load directory contents on first expand."""
        iid = self._fb_tree.focus()
        if not iid:
            return
        children = self._fb_tree.get_children(iid)
        if len(children) == 1:
            first_tags = self._fb_tree.item(children[0], "tags")
            if "placeholder" in first_tags:
                # Find the real path from our tag storage
                full_path = self._fb_get_path(iid)
                if full_path and os.path.isdir(full_path):
                    self._fb_tree.delete(children[0])
                    self._fb_insert_dir(iid, full_path)

    def _fb_get_path(self, iid: str) -> str:
        """Recover full filesystem path stored in the item's tags."""
        tags = self._fb_tree.item(iid, "tags")
        for tag in tags:
            if os.sep in tag or (len(tag) > 2 and tag[1] == ":"):
                return tag
        # Fallback: reconstruct from tree hierarchy
        parts = []
        node  = iid
        while node:
            parts.insert(0, self._fb_tree.item(node, "text"))
            node = self._fb_tree.parent(node)
        root = self._fb_root_var.get()
        return os.path.join(root, *parts[1:]) if parts else root

    def _fb_on_double_click(self, event=None):
        """Select a waveform file on double-click."""
        iid = self._fb_tree.focus()
        if not iid:
            return
        tags = self._fb_tree.item(iid, "tags")
        if "file" in tags:
            path = self._fb_get_path(iid)
            if path and os.path.isfile(path):
                self._fb_selected_path = path
                self._fb_selected_lbl.config(
                    text=f"Selected: {os.path.basename(path)}",
                    foreground="#1a5c1a")

    def _fb_upload_selected(self):
        """Upload the currently highlighted file to the instrument."""
        if not self._fb_selected_path:
            # Try to get from current selection
            iid = self._fb_tree.focus()
            if iid:
                self._fb_on_double_click()
        path = self._fb_selected_path
        if not path or not os.path.isfile(path):
            messagebox.showwarning(
                "No File", "Double-click a waveform file first.")
            return
        drv = self._get_driver()
        if drv is None:
            return
        try:
            drv.upload_waveform(path)
            self.status_lbl.config(
                text=f"Status: Uploaded {os.path.basename(path)}",
                foreground="green")
            _logger.info(f"SigGen uploaded waveform: {path}")
            self._refresh_waveforms()
        except Exception as e:
            messagebox.showerror("Upload Error", str(e))
            _logger.error(f"SigGen waveform upload failed: {e}")

    def _fb_set_active(self):
        """Set a file already on the instrument as the active waveform."""
        iid = self._fb_tree.focus()
        if not iid:
            return
        tags = self._fb_tree.item(iid, "tags")
        if "file" not in tags:
            messagebox.showwarning(
                "Not a file", "Select a waveform file in the tree first.")
            return
        path = self._fb_get_path(iid)
        name = os.path.basename(path)
        drv  = self._get_driver()
        if drv is None:
            return
        try:
            drv.set_waveform(name)
            self.selected_wf_lbl.config(
                text=f"Selected: {name}", foreground="green")
            self.status_lbl.config(
                text=f"Status: Active waveform → {name}", foreground="green")
            _logger.info(f"SigGen active waveform: {name}")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            _logger.error(f"SigGen set active waveform failed: {e}")

    # ── Settings ───────────────────────────────────────────────
    def _apply_settings(self):
        drv = self._get_driver()
        if drv is None:
            return
        freq_hz = self.freq_fe.get_hz()
        if freq_hz is None:
            messagebox.showwarning("Missing Values", "Enter a frequency.")
            return
        power_str = self.power_var.get().strip()
        if not power_str:
            messagebox.showwarning("Missing Values", "Enter a power level.")
            return
        try:
            power = float(power_str)
        except ValueError:
            messagebox.showerror("Invalid Input", "Power must be a number.")
            return
        try:
            drv.set_freq(freq_hz)
            drv.set_power(power)
            self.status_lbl.config(
                text=f"Status: Set {freq_hz/1e6:.3f} MHz / {power} dBm",
                foreground="green")
            _logger.info(f"SigGen: freq={freq_hz} Hz, power={power} dBm")
        except Exception as e:
            messagebox.showerror("Hardware Error", str(e))
            _logger.error(f"SigGen apply settings failed: {e}")

    def _apply_preset(self, freq: float, power: float):
        self.freq_fe.set_hz(freq)
        self.power_var.set(str(power))
        self._apply_settings()

    # ── RF toggle ──────────────────────────────────────────────
    def _toggle_rf(self):
        drv = self._get_driver()
        if drv is None:
            return
        new_state = "OFF" if self.rf_state_var.get() == "ON" else "ON"
        try:
            drv.rf_on(new_state == "ON")
            self.rf_state_var.set(new_state)
            self.rf_btn.config(text=f"RF {new_state}")
            color = "green" if new_state == "ON" else "red"
            self.rf_status_lbl.config(
                text=f"RF is {new_state}", foreground=color)
            self.status_lbl.config(
                text=f"Status: RF {new_state}", foreground=color)
            _logger.info(f"SigGen RF {new_state}")
        except Exception as e:
            messagebox.showerror("Hardware Error", str(e))
            _logger.error(f"SigGen RF toggle failed: {e}")

    # ── Waveforms on device ────────────────────────────────────
    def _refresh_waveforms(self):
        drv = self._get_driver()
        if drv is None:
            return
        try:
            waveforms = drv.list_waveforms() \
                if hasattr(drv, "list_waveforms") else []
            self.waveform_list.delete(0, tk.END)
            for wf in waveforms:
                self.waveform_list.insert(tk.END, wf)
            self.status_lbl.config(
                text=f"Status: {len(waveforms)} waveform(s) on device",
                foreground="green")
            _logger.info(
                f"SigGen waveform list refreshed: {len(waveforms)} items")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            _logger.error(f"SigGen waveform list failed: {e}")

    def _select_waveform(self):
        drv = self._get_driver()
        if drv is None:
            return
        sel = self.waveform_list.curselection()
        if not sel:
            messagebox.showwarning(
                "No Selection", "Select a waveform from the list.")
            return
        wf_name = self.waveform_list.get(sel[0])
        try:
            drv.set_waveform(wf_name)
            self.selected_wf_lbl.config(
                text=f"Selected: {wf_name}", foreground="green")
            self.status_lbl.config(
                text=f"Status: Waveform set to {wf_name}",
                foreground="green")
            _logger.info(f"SigGen waveform selected: {wf_name}")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            _logger.error(f"SigGen set waveform failed: {e}")

    def _delete_waveform(self):
        drv = self._get_driver()
        if drv is None:
            return
        sel = self.waveform_list.curselection()
        if not sel:
            messagebox.showwarning(
                "No Selection", "Select a waveform to delete.")
            return
        wf_name = self.waveform_list.get(sel[0])
        if not messagebox.askyesno(
                "Confirm Delete",
                f"Delete waveform '{wf_name}' from device?"):
            return
        try:
            if hasattr(drv, "delete_waveform"):
                drv.delete_waveform(wf_name)
            self.waveform_list.delete(sel[0])
            self.status_lbl.config(
                text=f"Status: Deleted {wf_name}", foreground="gray")
            _logger.info(f"SigGen waveform deleted: {wf_name}")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            _logger.error(f"SigGen delete waveform failed: {e}")

    # ── get_settings / load_settings ──────────────────────────
    def get_settings(self) -> dict:
        return {
            "freq_hz":    self.freq_fe.get_hz(),
            "power_dbm":  self.power_var.get(),
            "modulation": self.mod_var.get(),
            "rf_on":      self.rf_state_var.get() == "ON",
            "waveform":   self.selected_wf_lbl.cget("text").replace(
                              "Selected: ", ""),
        }

    def load_settings(self, settings: dict):
        if settings.get("freq_hz"):
            self.freq_fe.set_hz(float(settings["freq_hz"]))
        self.power_var.set(settings.get("power_dbm", ""))
        self.mod_var.set(settings.get("modulation", ""))
        rf = settings.get("rf_on", False)
        self.rf_state_var.set("ON" if rf else "OFF")
        self.selected_wf_lbl.config(
            text=f"Selected: {settings.get('waveform', 'None')}")
