import os
import sys
from pathlib import Path


def _setup_native_lib_path() -> None:
    """Tell OpenSlide where to find its native libs when running as PyInstaller bundle."""
    if not getattr(sys, "frozen", False):
        return
    candidates: list[Path] = []
    if hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "lib")
    candidates.append(Path(sys.executable).resolve().parent / "lib")
    candidates.append(Path(sys.executable).resolve().parent / "_internal" / "lib")
    if sys.platform == "darwin":
        candidates.append(Path(sys.executable).resolve().parent.parent / "Frameworks" / "lib")
        env_var = "DYLD_LIBRARY_PATH"
    elif sys.platform == "win32":
        env_var = "PATH"
    else:
        env_var = "LD_LIBRARY_PATH"
    sep = os.pathsep
    existing = os.environ.get(env_var, "")
    for c in candidates:
        if c.exists() and c.is_dir():
            os.environ[env_var] = (
                f"{c}{sep}{existing}" if existing else str(c)
            )
            return


_setup_native_lib_path()

import sys  # noqa: E402

from PySide6.QtCore import QFile  # noqa: E402
from PySide6.QtGui import QIcon, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from slide_stitcher.ui.main_window import MainWindow  # noqa: E402


def _resource_path(relative: str) -> Path:
    """Locate a bundled resource (icon, qss) in dev mode or PyInstaller bundle."""
    candidates: list[Path] = []
    if hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / relative)
    here = Path(__file__).resolve().parent
    candidates.append(here / relative)
    candidates.append(here.parent.parent / "packaging" / "icons" / relative)
    candidates.append(here / "assets" / relative)
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def _load_icon() -> QIcon:
    icon = QIcon()
    paths = [
        _resource_path("icon_512.png"),
        _resource_path("icon_1024.png"),
        _resource_path("icon.icns"),
    ]
    for p in paths:
        if p.exists():
            pix = QPixmap(str(p))
            if not pix.isNull():
                icon.addPixmap(pix)
                break
    return icon


def _load_theme(app: QApplication) -> None:
    qss_path = _resource_path("assets/theme.qss")
    if not qss_path.exists():
        qss_path = _resource_path("theme.qss")
    if qss_path.exists():
        f = QFile(str(qss_path))
        if f.open(QFile.ReadOnly | QFile.Text):
            app.setStyleSheet(bytes(f.readAll()).decode("utf-8"))
            f.close()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("SlideVision")
    app.setApplicationVersion("0.2.0")
    app.setOrganizationName("SlideVision")
    app.setWindowIcon(_load_icon())
    _load_theme(app)

    window = MainWindow()
    window.show()
    window.raise_()
    window.activateWindow()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
