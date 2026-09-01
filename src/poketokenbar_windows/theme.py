"""Design tokens and the application stylesheet.

Built to published guidance rather than taste:

  * An 8px spacing system - the standard recommendation for keeping rhythm
    consistent across a whole interface.
  * A 1.25 type scale, so heading sizes are related rather than arbitrary, and
    line height around 1.4 for readable body text.
  * Fluent 2's shape tokens: 4px corners on controls, 8px on cards, flyouts and
    dialogs. Windows 11 apps use elevation and layering for hierarchy, so
    surfaces are separated by tone rather than heavy borders.
  * Colour used sparingly - a calm foundation with accent reserved for the one
    thing that matters on a screen.

Everything reads from here, so a colour or radius is changed in one place
instead of being hunted through dozens of inline stylesheets.
"""
from __future__ import annotations

# --- spacing: an 8px system, with a 4px half-step for tight pairings -------
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24
SPACE_XXL = 32

# --- shape: Fluent 2 uses 4px for controls and 8px for layers --------------
RADIUS_CONTROL = 4
RADIUS_CARD = 8
RADIUS_PILL = 14

# --- type: a 1.25 scale from a 13px body ----------------------------------
TYPE_CAPTION = 11
TYPE_BODY = 13
TYPE_SUBTITLE = 16
TYPE_TITLE = 20
TYPE_HERO = 25
LINE_HEIGHT = 1.4

DARK = {
    # True neutral grey: R=G=B on every step. The previous #16181d had an
    # elevated blue channel, which is what made it read as tinted near-black
    # rather than a clean dark grey - and it cooled warm sprite colours sitting
    # on top of it.
    "bg": "#1a1a1a",            # app canvas
    "surface": "#212121",       # cards
    "surface_alt": "#292929",   # raised controls, hover, selected rows
    "border": "#3a3a3a",        # hairlines
    "border_strong": "#4d4d4d", # focus rings, emphasis
    "text": "#f2f2f2",
    "text_muted": "#a8a8a8",
    "text_faint": "#7a7a7a",
    "accent": "#3a74d6",
    "accent_hover": "#4f8cff",
    "accent_text": "#ffffff",
    "success": "#3fb950",
    "warning": "#d29922",
    "danger": "#f85149",
    "favourite": "#f0b429",
    "tooltip_bg": "#333333",
    # A tooltip carries its OWN text and border colours. Reusing "text" broke
    # the moment a palette inverted its tooltip: light mode drew #1b1b1d text
    # on a #1b1b1d background, so every tooltip popped up empty.
    "tooltip_text": "#f2f2f2",
    "tooltip_border": "#4d4d4d",
}

LIGHT = {
    "bg": "#f4f4f5",
    "surface": "#ffffff",
    "surface_alt": "#ebebed",
    "border": "#dcdce0",
    "border_strong": "#b9b9c0",
    "text": "#1b1b1d",
    "text_muted": "#5c5c63",
    "text_faint": "#84848c",
    "accent": "#2563eb",
    "accent_hover": "#1d4ed8",
    "accent_text": "#ffffff",
    "success": "#15803d",
    "warning": "#b45309",
    "danger": "#dc2626",
    "favourite": "#b45309",
    # Light mode inverts its tooltip on purpose - a dark chip reads as a
    # transient popup rather than another white card.
    "tooltip_bg": "#1b1b1d",
    "tooltip_text": "#f5f5f7",
    "tooltip_border": "#3a3a3d",
}


def windows_prefers_dark() -> bool:
    """Whether Windows is set to a dark app theme. Defaults to dark if unknown."""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return int(value) == 0
    except (ImportError, OSError, ValueError, TypeError):
        return True


def resolve_mode(mode: str) -> str:
    """Turn a stored setting into a concrete 'light' or 'dark'.

    'system' actually asks Windows rather than assuming dark, which is what it
    used to do - so Follow Windows never followed anything.
    """
    normalized = str(mode).strip().lower()
    if normalized in ("light", "dark"):
        return normalized
    return "dark" if windows_prefers_dark() else "light"


def palette(mode: str) -> dict:
    """Tokens for a theme name, resolving 'system' against Windows."""
    return LIGHT if resolve_mode(mode) == "light" else DARK


def build_stylesheet(mode: str) -> str:
    """The whole application stylesheet, assembled from tokens."""
    c = palette(mode)
    return f"""
        QWidget {{
            background: {c['bg']};
            color: {c['text']};
            font-size: {TYPE_BODY}px;
        }}
        QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
        QToolTip {{
            background: {c['tooltip_bg']};
            color: {c['tooltip_text']};
            border: 1px solid {c['tooltip_border']};
            border-radius: {RADIUS_CONTROL}px;
            padding: {SPACE_XS}px {SPACE_SM}px;
        }}

        /* Elevation by TONE. A card is a lighter surface on a darker canvas;
           it carries no outline, so screens stop reading as nested boxes. */
        QFrame#Card, QFrame#SettingsCard {{
            background: {c['surface']};
            border: none;
            border-radius: {RADIUS_CARD}px;
        }}
        QFrame#CardRaised {{
            background: {c['surface_alt']};
            border: none;
            border-radius: {RADIUS_CARD}px;
        }}
        /* An outline is reserved for the one card that is actually selected. */
        QFrame#CardActive {{
            background: {c['surface']};
            border: 1px solid {c['accent']};
            border-radius: {RADIUS_CARD}px;
        }}
        QFrame#Card QLabel, QFrame#SettingsCard QLabel,
        QFrame#CardRaised QLabel, QFrame#CardActive QLabel {{
            background: transparent;
            border: none;
        }}

        /* Status badges, toned for a dark surface instead of pastel chips
           borrowed from a light theme. */
        QLabel#BadgeNeutral, QLabel#BadgeAccent, QLabel#BadgeSuccess {{
            border-radius: {RADIUS_CONTROL}px;
            padding: 2px {SPACE_SM}px;
            font-weight: 600;
        }}
        QLabel#BadgeNeutral {{ background: {c['surface_alt']}; color: {c['text_muted']}; }}
        QLabel#BadgeAccent  {{ background: {c['accent']};      color: {c['accent_text']}; }}
        QLabel#BadgeSuccess {{ background: {c['success']};     color: {c['bg']}; }}

        QLabel#Success {{ color: {c['success']}; background: transparent; border: none; }}
        QLabel#Warning {{ color: {c['warning']}; background: transparent; border: none; }}
        QLabel#Danger  {{ color: {c['danger']};  background: transparent; border: none; }}
        QGroupBox {{
            background: {c['surface']};
            border: 1px solid {c['border']};
            border-radius: {RADIUS_CARD}px;
            margin-top: {SPACE_MD}px;
            padding: {SPACE_MD}px;
            font-weight: 600;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: {SPACE_MD}px;
            padding: 0 {SPACE_XS}px;
            color: {c['text']};
        }}

        QTabWidget::pane {{
            border: none;
            border-top: 1px solid {c['border']};
            top: -1px;
        }}
        QTabBar::tab {{
            background: transparent;
            color: {c['text_muted']};
            padding: {SPACE_SM}px {SPACE_LG}px;
            margin-right: {SPACE_XS}px;
            border: none;
            border-radius: {RADIUS_CONTROL}px;
        }}
        QTabBar::tab:selected {{
            background: {c['surface_alt']};
            color: {c['text']};
            font-weight: 600;
        }}
        QTabBar::tab:hover:!selected {{ color: {c['text']}; }}

        QPushButton {{
            background: {c['surface_alt']};
            color: {c['text']};
            border: 1px solid {c['border']};
            border-radius: {RADIUS_CONTROL}px;
            padding: {SPACE_SM}px {SPACE_MD}px;
        }}
        QPushButton:hover {{ border-color: {c['border_strong']}; }}
        QPushButton:disabled {{
            color: {c['text_faint']};
            background: transparent;
            border-color: {c['border']};
        }}
        QPushButton#Primary {{
            background: {c['accent']};
            color: {c['accent_text']};
            border: none;
            font-weight: 600;
        }}
        QPushButton#Primary:hover {{ background: {c['accent_hover']}; }}
        QPushButton#Primary:disabled {{
            background: {c['surface_alt']};
            color: {c['text_faint']};
        }}
        QPushButton#Danger {{
            background: transparent;
            color: {c['danger']};
            border: 1px solid {c['danger']};
            font-weight: 600;
        }}

        QComboBox, QSpinBox, QLineEdit {{
            background: {c['surface_alt']};
            color: {c['text']};
            border: 1px solid {c['border']};
            border-radius: {RADIUS_CONTROL}px;
            padding: {SPACE_XS}px {SPACE_SM}px;
            min-height: 22px;
        }}
        QComboBox:hover, QSpinBox:hover {{ border-color: {c['border_strong']}; }}
        QComboBox::drop-down {{ border: none; width: 20px; }}
        QComboBox QAbstractItemView {{
            background: {c['surface']};
            border: 1px solid {c['border']};
            border-radius: {RADIUS_CARD}px;
            selection-background-color: {c['accent']};
            selection-color: {c['accent_text']};
            padding: {SPACE_XS}px;
        }}

        QCheckBox {{ spacing: {SPACE_SM}px; padding: {SPACE_XS}px 0; }}
        /* Without an explicit indicator rule Qt draws the NATIVE Windows
           checkbox glyph, unthemed, on a dark background. Verified missing. */
        QCheckBox::indicator {{
            width: 16px; height: 16px;
            border: 1px solid {c['border_strong']};
            border-radius: {RADIUS_CONTROL}px;
            background: {c['surface_alt']};
        }}
        QCheckBox::indicator:checked {{
            background: {c['accent']};
            border-color: {c['accent']};
        }}
        QCheckBox::indicator:hover {{ border-color: {c['accent']}; }}
        QCheckBox:disabled {{ color: {c['text_faint']}; }}

        /* Muted text is a ROLE, not palette(mid) - that is a border colour and
           renders near-invisible on a dark background. */
        QLabel#Muted {{
            color: {c['text_muted']};
            background: transparent;
            border: none;
        }}
        QLabel#Faint {{ color: {c['text_faint']}; background: transparent; border: none; }}

        QListWidget {{
            background: transparent;
            border: none;
            border-radius: {RADIUS_CARD}px;
            padding: {SPACE_XS}px;
        }}
        QListWidget::item {{
            padding: {SPACE_XS}px {SPACE_SM}px;
            border-radius: {RADIUS_CONTROL}px;
        }}

        QProgressBar {{
            min-height: {SPACE_SM}px;
            border: none;
            border-radius: {RADIUS_CONTROL}px;
            background: {c['surface_alt']};
        }}
        /* The chunk had a radius but NO background, so every filled bar
           rendered invisible. Limit bars override this colour per severity. */
        QProgressBar::chunk {{
            background: {c['accent']};
            border-radius: {RADIUS_CONTROL}px;
        }}

        QScrollBar:vertical {{
            background: transparent; width: 10px; margin: 0;
        }}
        QScrollBar::handle:vertical {{
            background: {c['border_strong']};
            border-radius: 5px; min-height: 28px;
        }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}

        /* One visible focus treatment, applied consistently. */
        QPushButton:focus, QComboBox:focus, QSpinBox:focus, QListWidget:focus {{
            border: 1px solid {c['accent']};
        }}
    """


def muted(mode: str) -> str:
    return palette(mode)["text_muted"]


def apply_base_palette(app, mode: str) -> None:
    """Set a QPalette matching the theme.

    The stylesheet wins wherever it applies, but Qt falls back to the palette
    for anything it draws natively - system menus, some dialogs, disabled text.
    Without this those render light-on-light against a dark app.
    """
    from PySide6.QtGui import QColor, QPalette

    c = palette(mode)
    role = QPalette.ColorRole
    group = QPalette.ColorGroup
    result = QPalette()
    for target, key in (
        (role.Window, "bg"), (role.Base, "surface"),
        (role.AlternateBase, "surface_alt"), (role.Button, "surface_alt"),
        (role.ToolTipBase, "tooltip_bg"), (role.Highlight, "accent"),
        (role.WindowText, "text"), (role.Text, "text"),
        (role.ButtonText, "text"), (role.ToolTipText, "tooltip_text"),
        (role.HighlightedText, "accent_text"), (role.PlaceholderText, "text_faint"),
        (role.Mid, "border"), (role.Dark, "border_strong"),
        (role.Light, "surface_alt"), (role.Midlight, "surface_alt"),
    ):
        result.setColor(target, QColor(c[key]))
    for target in (role.WindowText, role.Text, role.ButtonText):
        result.setColor(group.Disabled, target, QColor(c["text_faint"]))
    app.setPalette(result)
