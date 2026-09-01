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
    "bg": "#16181d",
    "surface": "#1d2027",
    "surface_alt": "#242832",
    "border": "#333a46",
    "border_strong": "#454e5e",
    "text": "#eef1f6",
    "text_muted": "#9aa4b4",
    "text_faint": "#6c7688",
    "accent": "#3b82f6",
    "accent_hover": "#2f6fd8",
    "accent_text": "#ffffff",
    "success": "#34d399",
    "warning": "#fbbf24",
    "danger": "#f87171",
    "favourite": "#f59e0b",
    "tooltip_bg": "#0f1116",
}

LIGHT = {
    "bg": "#f6f7f9",
    "surface": "#ffffff",
    "surface_alt": "#eef0f4",
    "border": "#dfe3ea",
    "border_strong": "#c3cad6",
    "text": "#1b1f27",
    "text_muted": "#5b6472",
    "text_faint": "#8b95a5",
    "accent": "#2563eb",
    "accent_hover": "#1d4ed8",
    "accent_text": "#ffffff",
    "success": "#15803d",
    "warning": "#b45309",
    "danger": "#dc2626",
    "favourite": "#d97706",
    "tooltip_bg": "#1b1f27",
}


def palette(mode: str) -> dict:
    """Tokens for a theme name. Anything unknown follows the dark palette."""
    return LIGHT if str(mode).strip().lower() == "light" else DARK


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
            color: {c['text']};
            border: 1px solid {c['border']};
            border-radius: {RADIUS_CONTROL}px;
            padding: {SPACE_XS}px {SPACE_SM}px;
        }}

        /* Layering: a card is a lighter surface, not a heavy outline. */
        QFrame#SettingsCard, QFrame#Card {{
            background: {c['surface']};
            border: 1px solid {c['border']};
            border-radius: {RADIUS_CARD}px;
        }}
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
            border: 1px solid {c['border']};
            border-radius: {RADIUS_CARD}px;
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

        QListWidget {{
            background: transparent;
            border: 1px solid {c['border']};
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
        QProgressBar::chunk {{ border-radius: {RADIUS_CONTROL}px; }}

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
