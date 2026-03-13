# utils/ui_theme.py
import tkinter as tk
from tkinter import ttk

APP_COLORS = {
    "bg": "#F4F6F8",
    "panel": "#FFFFFF",
    "panel_alt": "#FAFBFC",
    "border": "#D9E0E7",
    "text": "#1F2933",
    "muted": "#6B7280",
    "header": "#0F172A",
    "accent": "#2563EB",
    "accent_hover": "#1D4ED8",
    "success": "#15803D",
    "warning": "#B45309",
    "danger": "#B91C1C",
    "info": "#0F766E",
    "row_alt": "#F8FAFC",
    "selected": "#E8F0FE",
}

APP_FONTS = {
    "title": ("Segoe UI", 16, "bold"),
    "section": ("Segoe UI", 11, "bold"),
    "body": ("Segoe UI", 10),
    "body_bold": ("Segoe UI", 10, "bold"),
    "small": ("Segoe UI", 9),
    "small_bold": ("Segoe UI", 9, "bold"),
}


def apply_app_theme(root):
    style = ttk.Style(root)

    try:
        style.theme_use("clam")
    except Exception:
        pass

    root.configure(bg=APP_COLORS["bg"])

    # Base ttk styles
    style.configure(
        ".",
        background=APP_COLORS["bg"],
        foreground=APP_COLORS["text"],
        font=APP_FONTS["body"],
    )

    style.configure(
        "TFrame",
        background=APP_COLORS["bg"],
    )

    style.configure(
        "Panel.TFrame",
        background=APP_COLORS["panel"],
        relief="flat",
    )

    style.configure(
        "PanelAlt.TFrame",
        background=APP_COLORS["panel_alt"],
        relief="flat",
    )

    style.configure(
        "Card.TLabelframe",
        background=APP_COLORS["panel"],
        borderwidth=1,
        relief="solid",
    )
    style.configure(
        "Card.TLabelframe.Label",
        background=APP_COLORS["panel"],
        foreground=APP_COLORS["text"],
        font=APP_FONTS["section"],
    )

    style.configure(
        "TLabel",
        background=APP_COLORS["bg"],
        foreground=APP_COLORS["text"],
        font=APP_FONTS["body"],
    )

    style.configure(
        "Muted.TLabel",
        background=APP_COLORS["bg"],
        foreground=APP_COLORS["muted"],
        font=APP_FONTS["small"],
    )

    style.configure(
        "Title.TLabel",
        background=APP_COLORS["bg"],
        foreground=APP_COLORS["header"],
        font=APP_FONTS["title"],
    )

    style.configure(
        "Section.TLabel",
        background=APP_COLORS["bg"],
        foreground=APP_COLORS["header"],
        font=APP_FONTS["section"],
    )

    style.configure(
        "StatValue.TLabel",
        background=APP_COLORS["panel"],
        foreground=APP_COLORS["header"],
        font=APP_FONTS["title"],
    )

    style.configure(
        "StatLabel.TLabel",
        background=APP_COLORS["panel"],
        foreground=APP_COLORS["muted"],
        font=APP_FONTS["small"],
    )

    style.configure(
        "TButton",
        padding=(10, 6),
        font=APP_FONTS["body"],
    )

    style.configure(
        "Primary.TButton",
        padding=(12, 7),
        font=APP_FONTS["body_bold"],
    )

    style.configure(
        "Danger.TButton",
        padding=(10, 6),
        font=APP_FONTS["body_bold"],
    )

    style.configure(
        "TEntry",
        padding=6,
    )

    style.configure(
        "TCombobox",
        padding=4,
    )

    style.configure(
        "Treeview",
        background=APP_COLORS["panel"],
        fieldbackground=APP_COLORS["panel"],
        foreground=APP_COLORS["text"],
        bordercolor=APP_COLORS["border"],
        rowheight=28,
        font=APP_FONTS["body"],
    )
    style.map(
        "Treeview",
        background=[("selected", APP_COLORS["selected"])],
        foreground=[("selected", APP_COLORS["text"])],
    )

    style.configure(
        "Treeview.Heading",
        background="#EEF2F7",
        foreground=APP_COLORS["header"],
        bordercolor=APP_COLORS["border"],
        relief="flat",
        padding=(8, 8),
        font=APP_FONTS["small_bold"],
    )

    style.configure(
        "TNotebook",
        background=APP_COLORS["bg"],
        borderwidth=0,
        tabmargins=(4, 0, 4, 0),
    )
    style.configure(
        "TNotebook.Tab",
        padding=(14, 8),
        font=APP_FONTS["body"],
        background="#E5E7EB",
        foreground=APP_COLORS["text"],
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", APP_COLORS["panel"])],
        foreground=[("selected", APP_COLORS["header"])],
    )


def style_treeview_zebra(tree: ttk.Treeview):
    tree.tag_configure("odd", background=APP_COLORS["panel"])
    tree.tag_configure("even", background=APP_COLORS["row_alt"])
    tree.tag_configure("status_ok", foreground=APP_COLORS["success"])
    tree.tag_configure("status_warn", foreground=APP_COLORS["warning"])
    tree.tag_configure("status_err", foreground=APP_COLORS["danger"])


def apply_zebra_tags(tree: ttk.Treeview):
    for i, iid in enumerate(tree.get_children("")):
        current_tags = list(tree.item(iid, "tags"))
        current_tags = [t for t in current_tags if t not in ("odd", "even")]
        current_tags.append("even" if i % 2 else "odd")
        tree.item(iid, tags=tuple(current_tags))


def make_header(parent, title: str, subtitle: str = ""):
    wrapper = ttk.Frame(parent, style="Panel.TFrame")
    wrapper.pack(fill="x", padx=12, pady=(12, 8))

    title_lbl = ttk.Label(wrapper, text=title, style="Title.TLabel")
    title_lbl.pack(anchor="w")

    if subtitle:
        sub_lbl = ttk.Label(wrapper, text=subtitle, style="Muted.TLabel")
        sub_lbl.pack(anchor="w", pady=(2, 0))

    return wrapper


def make_stat_card(parent, label: str, value: str):
    card = ttk.Frame(parent, style="Panel.TFrame")
    card.configure(padding=12)

    ttk.Label(card, text=value, style="StatValue.TLabel").pack(anchor="w")
    ttk.Label(card, text=label, style="StatLabel.TLabel").pack(anchor="w", pady=(4, 0))

    return card


def set_status_label(label_widget, text: str, tone: str = "muted"):
    color_map = {
        "muted": APP_COLORS["muted"],
        "success": APP_COLORS["success"],
        "warning": APP_COLORS["warning"],
        "danger": APP_COLORS["danger"],
        "info": APP_COLORS["info"],
    }
    label_widget.config(text=text, foreground=color_map.get(tone, APP_COLORS["muted"]))