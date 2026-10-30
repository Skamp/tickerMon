"""Centralized display-scaling setup for tickerMon.

This module is intentionally importable WITHOUT PySide6/Qt so it can run at
the very top of ``main.py``, before Qt is loaded. Qt reads its scaling
environment variables when ``QApplication`` is constructed, so everything in
``apply_scaling_env()`` must happen before the first Qt import.

Three entry points (all called from ``main.py``):

* ``apply_scaling_env(config_path)``  - before Qt is imported; seeds the
  default ``ui_scale`` into the config on Python >= 3.13 (once, never
  overwriting an existing value), pins the DPI scale-factor rounding policy,
  resolves the optional scale override (``TICKERMON_SCALE`` env var or
  ``ui_scale`` config value) into ``QT_SCALE_FACTOR``, and best-effort
  requests Per-Monitor-V2 DPI awareness on Windows.
* ``setup_display_scaling(app)``      - after ``QApplication`` exists; pins
  the explicit application-wide default font so text no longer depends on
  whatever system/Qt default each machine resolves to. The family is resolved
  against the fonts actually installed on the machine.
* ``print_diagnostics(app)``          - used by the ``--debug-dpi`` startup
  flag; prints toolkit versions, operating system, screen DPI metrics, the
  effective font and the process DPI awareness state.
"""

import ctypes
import json
import logging
import os
import platform
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger(__name__)

DEBUG_FLAG = "--debug-dpi"

SCALE_ENV_VAR = "TICKERMON_SCALE"
CONFIG_SCALE_KEY = "ui_scale"
FONT_FAMILY_ENV_VAR = "TICKERMON_FONT_FAMILY"
FONT_POINT_ENV_VAR = "TICKERMON_FONT_POINT"

FONT_FAMILY_CANDIDATES = ("Segoe UI", "Noto Sans", "DejaVu Sans", "Ubuntu")
DEFAULT_FONT_POINT_SIZE = 9.0
DEFAULT_ROUNDING_POLICY = "PassThrough"

DEFAULT_SEEDED_UI_SCALE = 1.5
SEED_MIN_PYTHON = (3, 13)

_ROUNDING_ENV_VAR = "QT_SCALE_FACTOR_ROUNDING_POLICY"
_SCALE_ENV_VAR = "QT_SCALE_FACTOR"

_QT_ENV_VARS = (
    SCALE_ENV_VAR,
    _SCALE_ENV_VAR,
    _ROUNDING_ENV_VAR,
    "QT_SCREEN_SCALE_FACTORS",
    "QT_FONT_DPI",
    "QT_AUTO_SCREEN_SCALE_FACTOR",
    "QT_ENABLE_HIGHDPI_SCALING",
    FONT_FAMILY_ENV_VAR,
    FONT_POINT_ENV_VAR,
)


def parse_positive_float(raw: Any) -> Optional[float]:
    """Parses a positive, finite float; returns None for anything invalid."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0 or value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def resolve_scale_factor(env_raw: Any, config_raw: Any) -> Optional[float]:
    """Returns the scale override with precedence env (TICKERMON_SCALE) > config."""
    for raw in (env_raw, config_raw):
        value = parse_positive_float(raw)
        if value is not None:
            return value
    return None


def consume_debug_flag(argv: list) -> bool:
    """Removes ``--debug-dpi`` from argv (so Qt never sees it); True if present."""
    found = False
    while DEBUG_FLAG in argv:
        argv.remove(DEBUG_FLAG)
        found = True
    return found


def _read_scale_from_config(config_path: Optional[Path]) -> Any:
    """Reads only the ``ui_scale`` key; tolerates a missing/corrupt file."""
    if config_path is None:
        return None
    try:
        data = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict):
        return data.get(CONFIG_SCALE_KEY)
    return None


def should_seed_default_scale(version_info: Any) -> bool:
    """True for Python >= 3.13, where the default ui_scale gets seeded."""
    try:
        return tuple(version_info[:2]) >= SEED_MIN_PYTHON
    except (TypeError, IndexError):
        return False


def seed_default_scale(
    config_path: Optional[Path], version_info: Any = None
) -> bool:
    """Writes ``DEFAULT_SEEDED_UI_SCALE`` into the config (Python >= 3.13).

    Runs before scale resolution so the value already applies on the same
    launch. Rules: an existing ``ui_scale`` is never overwritten, a corrupt
    or non-object config is left untouched, and a missing file is created.
    Returns True only when the config was actually written.
    """
    if config_path is None:
        return False
    if version_info is None:
        version_info = sys.version_info
    if not should_seed_default_scale(version_info):
        return False

    path = Path(config_path)
    data = {}  # type: Dict[str, Any]
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning(
                "Not seeding %s: unreadable config (%s)", CONFIG_SCALE_KEY, exc
            )
            return False
        if not isinstance(loaded, dict):
            logger.warning(
                "Not seeding %s: config is not a JSON object", CONFIG_SCALE_KEY
            )
            return False
        if CONFIG_SCALE_KEY in loaded:
            return False
        data = loaded

    data[CONFIG_SCALE_KEY] = DEFAULT_SEEDED_UI_SCALE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=4), encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write %s: %s", CONFIG_SCALE_KEY, exc)
        return False

    logger.info(
        "Seeded %s=%g into %s (Python >= %s)",
        CONFIG_SCALE_KEY,
        DEFAULT_SEEDED_UI_SCALE,
        path,
        ".".join(str(part) for part in SEED_MIN_PYTHON),
    )
    return True


def resolve_font_family(
    available_families: Iterable[str],
    candidates: Iterable[str] = FONT_FAMILY_CANDIDATES,
) -> Optional[str]:
    """Returns the first preferred font family that is installed, else None."""
    installed = {name.lower() for name in available_families}
    for family in candidates:
        if family.lower() in installed:
            return family
    return None


def _request_windows_pm_v2() -> bool:
    """Best-effort Per-Monitor-V2 DPI awareness on Windows, before Qt starts.

    Fails silently when the process awareness was already locked (e.g. by an
    embedded manifest or a compatibility "override high DPI scaling" setting);
    ``--debug-dpi`` reports the resulting state either way.
    """
    if sys.platform != "win32":
        return False
    try:
        return bool(
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        )
    except (AttributeError, OSError, ValueError):
        return False


def apply_scaling_env(config_path: Optional[Path] = None) -> Optional[float]:
    """Pins Qt's DPI/scaling policy. MUST run before PySide6 is imported.

    Seeds the default ``ui_scale`` into the config first (Python >= 3.13
    only), so the seeded value is picked up by the resolution below on the
    very same launch. Returns the forced scale factor (QT_SCALE_FACTOR) or
    None when the OS default should be used.
    """
    os.environ.setdefault(_ROUNDING_ENV_VAR, DEFAULT_ROUNDING_POLICY)
    _request_windows_pm_v2()
    seed_default_scale(config_path)

    scale = resolve_scale_factor(
        os.environ.get(SCALE_ENV_VAR),
        _read_scale_from_config(config_path),
    )
    if scale is not None:
        os.environ[_SCALE_ENV_VAR] = "%g" % scale

    return scale


def scaling_summary() -> str:
    """Short one-line description of the active scaling environment."""
    parts = [
        "%s=%s" % (name, os.environ[name])
        for name in (_ROUNDING_ENV_VAR, _SCALE_ENV_VAR)
        if name in os.environ
    ]
    return ", ".join(parts) if parts else "Qt defaults (no overrides set)"


def effective_scale_factor() -> float:
    """Returns the active Qt scale override (``QT_SCALE_FACTOR``), or 1.0.

    Read after ``apply_scaling_env()`` so UI code can size windows against
    the same factor Qt will apply (seeded ``ui_scale`` or ``TICKERMON_SCALE``).
    """
    return parse_positive_float(os.environ.get(_SCALE_ENV_VAR)) or 1.0


def setup_display_scaling(app: Any) -> Any:
    """Sets the explicit application-wide default font (after QApplication).

    The font family/size are pinned so text renders identically instead of
    inheriting each machine's system default. The family is resolved against
    the fonts actually installed, so Linux gets a real family instead of an
    undefined fallback behind the Windows-only ``Segoe UI`` name. Point sizes
    still scale with the pinned DPI policy, keeping chart axis text (which
    uses the app font) and every non-QSS-styled widget consistent with the
    rest of the UI.
    """
    from PySide6.QtGui import QFont, QFontDatabase

    requested = os.environ.get(FONT_FAMILY_ENV_VAR)
    if requested:
        family = requested
        source = "env"
    else:
        try:
            installed = list(QFontDatabase.families())
        except AttributeError:  # pragma: no cover - very old PySide6
            installed = list(QFontDatabase().families())
        family = resolve_font_family(installed)
        source = "installed" if family else "system default"
        if family is None:
            family = QFont().defaultFamily() or None

    point_size = parse_positive_float(os.environ.get(FONT_POINT_ENV_VAR))
    if point_size is None:
        point_size = DEFAULT_FONT_POINT_SIZE

    font = QFont(family) if family else QFont()
    font.setPointSizeF(point_size)
    app.setFont(font)
    logger.info(
        "Display font pinned: %s @ %gpt (resolved from %s)",
        font.family(),
        point_size,
        source,
    )
    return font


def _windows_dpi_awareness() -> str:
    """Describes the process DPI awareness state; best-effort and fail-safe."""
    if sys.platform != "win32":
        return "n/a (not Windows)"
    labels = {
        -1: "DPI_AWARENESS_CONTEXT_UNAWARE",
        -2: "DPI_AWARENESS_CONTEXT_SYSTEM_AWARE",
        -3: "DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE (v1)",
        -4: "DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2",
        -5: "DPI_AWARENESS_CONTEXT_UNAWARE_GDISCALED",
    }
    try:
        user32 = ctypes.windll.user32
        user32.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        user32.AreDpiAwarenessContextsEqual.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.AreDpiAwarenessContextsEqual.restype = ctypes.c_bool
        ctx = user32.GetThreadDpiAwarenessContext()
        if ctx:
            for value, name in labels.items():
                if user32.AreDpiAwarenessContextsEqual(ctx, ctypes.c_void_p(value)):
                    return name
    except (AttributeError, OSError, ValueError):
        pass
    try:
        awareness = ctypes.c_int()
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        hr = ctypes.windll.shcore.GetProcessDpiAwareness(handle, ctypes.byref(awareness))
        if hr == 0:
            return {0: "Unaware", 1: "System aware", 2: "Per-monitor aware"}.get(
                awareness.value, "Unknown (%d)" % awareness.value
            )
    except (AttributeError, OSError, ValueError):
        pass
    return "Unknown"


def _screen_metrics(app: Any) -> Dict[str, Any]:
    screen = app.primaryScreen()
    if screen is None:
        return {"screen": "no primary screen available"}
    geometry = screen.geometry()
    return {
        "screen": screen.name(),
        "screen geometry": "%dx%d" % (geometry.width(), geometry.height()),
        "devicePixelRatio": screen.devicePixelRatio(),
        "logicalDotsPerInch": screen.logicalDotsPerInch(),
        "physicalDotsPerInch": screen.physicalDotsPerInch(),
    }


def log_startup_metrics(app: Any) -> None:
    """Logs the key screen/DPI/font metrics on every startup (log only).

    Unlike ``print_diagnostics`` this needs no ``--debug-dpi`` flag and
    prints no banner - it writes one ``Screen metrics: ...`` line through
    the regular logging setup (logs/app.log + console).
    """
    parts = ["%s=%s" % (key, value) for key, value in _screen_metrics(app).items()]
    font = app.font()
    parts.append("font=%s@%gpt" % (font.family(), font.pointSizeF()))
    parts.append("scaling=%s" % scaling_summary())
    parts.append("qt_scale=%s" % os.environ.get(_SCALE_ENV_VAR, "<unset>"))
    logger.info("Screen metrics: %s", " | ".join(parts))


def print_diagnostics(app: Any) -> None:
    """Prints the startup DPI/scaling report triggered by ``--debug-dpi``."""
    lines = ["", "=== tickerMon DPI / scaling diagnostics (--debug-dpi) ==="]

    lines.append("Python: %s" % sys.version.replace("\n", " "))
    lines.append("Executable: %s" % sys.executable)
    lines.append("Platform: %s" % sys.platform)
    lines.append("Operating system: %s" % platform.platform())

    try:
        import PySide6

        lines.append("PySide6: %s" % PySide6.__version__)
    except Exception as exc:  # pragma: no cover - diagnostics only
        lines.append("PySide6: unavailable (%s)" % exc)
    try:
        from PySide6 import QtCore

        lines.append("Qt runtime: %s" % QtCore.qVersion())
    except Exception as exc:  # pragma: no cover - diagnostics only
        lines.append("Qt runtime: unavailable (%s)" % exc)
    try:
        import pyqtgraph

        lines.append("pyqtgraph: %s" % pyqtgraph.__version__)
    except Exception as exc:  # pragma: no cover - diagnostics only
        lines.append("pyqtgraph: unavailable (%s)" % exc)

    for key, value in sorted(_screen_metrics(app).items()):
        lines.append("%s: %s" % (key, value))

    font = app.font()
    metrics = app.fontMetrics()
    try:
        from PySide6.QtGui import QFontInfo

        resolved_family = QFontInfo(font).family()
    except Exception:  # pragma: no cover - diagnostics only
        resolved_family = font.family()
    lines.append(
        "application font: %s @ %gpt (resolved=%s, pixelSize=%s, metrics.height=%d)"
        % (
            font.family(),
            font.pointSizeF(),
            resolved_family,
            font.pixelSize(),
            metrics.height(),
        )
    )
    lines.append("widget style: %s" % app.style().objectName())
    lines.append("Windows DPI awareness: %s" % _windows_dpi_awareness())
    lines.append(
        "QT_SCALE_FACTOR: %s" % os.environ.get(_SCALE_ENV_VAR, "<unset / OS default>")
    )
    for name in _QT_ENV_VARS:
        if name in os.environ:
            lines.append("env %s=%s" % (name, os.environ[name]))
    lines.append("===========================================================")

    report = "\n".join(lines)
    print(report, flush=True)
    logger.info("DPI diagnostics:\n%s", report)
