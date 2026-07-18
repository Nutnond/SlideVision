# CLAUDE.md — Agent Handoff Guide

> **Read this first if you're a new agent picking up this project.** It contains everything you need to be effective immediately: project state, key decisions, commands, gotchas, and pending work.

---

## What is this project?

**SlideVision** is a native desktop app for pathologists. It composes a case overview image from multiple whole-slide images (WSI) — e.g. colon cancer resection cut into 12 blocks → 12 `.ndpi` slides → one composed PNG showing tumor distribution across the whole specimen.

**Key constraint:** WSI files are 1–10 GB each. The app **never copies** them — it reads from the user's original path via OpenSlide. Only 1024px thumbnails are cached locally.

**Display name:** `SlideVision`
**Python package name:** `slide_stitcher` (legacy — see FAQ in README)
**Current version:** 0.2.0 (MVP — Mac only, no code signing)

---

## Tech stack (locked)

| Layer | Choice |
|---|---|
| GUI | PySide6 / Qt 6 (LGPL) |
| WSI reading | OpenSlide + openslide-python |
| Image processing | Pillow, numpy |
| Persistence | Pydantic models → JSON files |
| Packaging | PyInstaller |
| Package manager | **Pixi** (replaces Homebrew for OpenSlide) |

**No web layer.** The app was originally a FastAPI + Nuxt web app; we pivoted to native because (a) GB-scale files shouldn't be HTTP-uploaded, (b) Mac native menu + Qt's QGraphicsView is the right tool for medical imaging, (c) single-language Python codebase matches OpenSlide ecosystem.

---

## Critical commands

All commands assume `cd "/Users/unuun/Desktop/CANCER SLIDE/backend"` (or the equivalent path on the new machine).

### Setup (one-time)

```bash
# Install Pixi if not present
curl -fsSL https://pixi.sh/install.sh | bash

# Install Python 3.11 + OpenSlide + PySide6 + all deps
pixi install
```

### Run in dev mode

```bash
pixi run dev
# or:
pixi run python -m slide_stitcher.main
```

Storage location: `~/Documents/SlideVision/cases/` (configurable via `STORAGE_DIR` env var).

### Regenerate icons (only if `make_icon.py` changed)

```bash
pixi run python packaging/make_icon.py
```

### Build Mac installer

```bash
pixi run pyinstaller packaging/slide_stitcher.spec --noconfirm
# Output: dist/SlideVision.app (~1 GB)
./dist/SlideVision.app/Contents/MacOS/SlideVision    # run with stderr visible
open dist/SlideVision.app                             # run via Finder
```

### Verify services still work after refactor

```bash
pixi run python -c "from slide_stitcher.services import wsi, compose, mapping; from slide_stitcher.ui.main_window import MainWindow; print('OK')"
```

---

## Project structure (where to look)

```
CANCER SLIDE/
├── README.md                              # full docs incl. System Requirements
├── CLAUDE.md                              # this file
├── .gitignore
├── .git/                                  # initialized; initial commit at 3babc01
│
└── backend/
    ├── pyproject.toml                     # Pixi project + Python deps
    ├── pixi.lock                          # COMMITTED for reproducibility
    ├── .env.example                       # STORAGE_DIR, HF_TOKEN
    │
    ├── src/slide_stitcher/                # ← Python package (legacy name)
    │   ├── main.py                        # QApplication entry, loads icon + theme
    │   ├── config.py                      # Settings (storage default: ~/Documents/SlideVision)
    │   ├── models.py                      # Pydantic: CaseMetadata, SlidePosition, etc.
    │   │
    │   ├── services/                      # PURE PYTHON — no Qt imports
    │   │   ├── wsi.py                     # OpenSlide thumbnail + native-res reader
    │   │   ├── compose.py                 # PIL composition (low + full-res w/ progress_cb)
    │   │   ├── mapping.py                 # JSON persistence
    │   │   ├── storage.py                 # Path helpers
    │   │   ├── thumbnail.py               # PIL fallback for plain images
    │   │   └── types.py                   # ThumbResult dataclass
    │   │
    │   ├── ui/                            # Qt UI layer
    │   │   ├── main_window.py             # QMainWindow, menu, splitter, FullResExportWorker
    │   │   ├── controllers/case_controller.py   # Bridge: UI ↔ services
    │   │   ├── dialogs/{new_case,crop}_dialog.py
    │   │   ├── widgets/welcome_screen.py  # Recent cases grid
    │   │   ├── widgets/case_sidebar.py    # Left panel, right-click delete
    │   │   ├── widgets/slide_canvas.py    # QGraphicsView (pinch zoom, drag pan)
    │   │   └── widgets/slide_item.py      # QGraphicsObject (rotate/resize/crop handles)
    │   │
    │   └── assets/theme.qss               # Dark theme, indigo accent
    │
    ├── packaging/
    │   ├── slide_stitcher.spec            # PyInstaller spec
    │   ├── make_icon.py                   # Pillow → .icns / .ico
    │   └── icons/                         # Generated icons (committed)
    │
    └── tests/                             # Empty — tests not yet written
```

---

## Key concepts you must understand

### 1. No-copy architecture

`SlideMetadata.original_path` stores absolute filesystem path of the user's WSI. The file is **never copied** to storage. Only 1024px thumbnails cached.

For full-res export: OpenSlide reads from `original_path` at the best pyramid level. If the user moves/renames the file, export silently skips it (logged).

### 2. Crop vs applied_crop

`SlidePosition` has two crop layers:

- **`crop_x/y/w/h`** — *current visual crop*, normalized 0–1 of the *currently-visible* slide. User adjusts via orange edge handles. Reset to `(0,0,1,1)` after Apply Crop.
- **`applied_x/y/w/h`** — *cumulative committed crop*, normalized 0–1 of the *original* WSI. Compounded on each Apply Crop (`new_applied_x = applied_x + crop_x * applied_w`, etc.).

The separation lets users crop multiple times while the export pipeline has a single source-of-truth.

### 3. Apply Crop workflow

When user presses Enter (or Edit → Apply Crop):
1. `SlideItem.apply_crop()` crops in-memory pixmap
2. Updates geometry (pos + w/h shrink to crop region)
3. Compounds `applied_x/y/w/h`
4. Resets `crop_x/y/w/h` to full
5. Saves new pixmap to disk as `thumb.png` (so future compose uses cropped version)

For full-res export, `compose.compose_image_full_res` applies `applied_crop` to the original WSI then the current visual crop.

### 4. Rotation around center

`SlideItem` uses `setTransformOriginPoint(w/2, h/2)` so rotation pivots on the slide's center, not top-left. **Critical:** call `setTransformOriginPoint` after every geometry change in `set_geometry` and `_do_resize`.

### 5. Resize math with rotation

`SlideItem._do_resize` computes the opposite-corner-fixed position by:
- Transforming scene-delta into item-local frame via `QTransform().rotate(-rotation).map(delta)`
- Tracking the opposite corner's scene position at drag start
- Recomputing new pos after rotation

Don't simplify this — it breaks when items are rotated.

### 6. Native menu bar disabled

`menubar.setNativeMenuBar(False)` in `MainWindow._build_menu`. Reason: in PyInstaller bundles without code signing, Mac native menu integration is flaky. In-window menu is reliable cross-platform.

### 7. QueuedConnection for worker signals

`FullResExportWorker` runs in a QThread. Its signals (`progress`, `finished`, `failed`) MUST be connected with `Qt.QueuedConnection` explicitly — lambda slots in PySide6 don't auto-detect cross-thread, and `QProgressDialog.setValue()` from a worker thread crashes Mac (`NSWindow should only be instantiated on the main thread`).

### 8. `shape()` must include handles

`SlideItem.shape()` returns the slide rect + (when selected) corner handles + rotate handle + crop edge handles. Without this, clicks on handles don't reach `mousePressEvent`. If you add new handle types, update `shape()` too.

---

## State of the project (as of 2026-07-19)

### ✅ Done (Phase A–E + G + extras)

- Project restructure from web app → native Qt
- Qt skeleton + case management (new/open/save/recent)
- Canvas with `QGraphicsView` (pan, zoom, drag, resize, rubber-band not yet)
- Save / Load / Export (low-res PNG)
- Mac packaging (PyInstaller → `.app`, ~1 GB)
- Rotate handle + resize-with-rotation math
- Visual crop (orange edge handles) + Apply Crop commit
- Full-resolution export (reads original WSI via OpenSlide)
- Background-threaded export with progress dialog
- Welcome screen with recent cases
- Right-click context menu on sidebar (add/remove/delete)
- Delete case action
- Custom Pillow-generated icon (.icns + .ico)
- Dark theme QSS (indigo accent)
- Filesystem storage at `~/Documents/SlideVision/`
- `PIL.MAX_IMAGE_PIXELS = None` to handle large WSI
- README (developer-focused, ~600 lines)
- Initial git commit (48 files, 3,957 lines)

### ⏸ Pending (per user — MVP sufficient, no immediate plan)

- **#14 Phase F: Windows packaging** — needs Windows machine/VM/CI
- **Tests** — `tests/` is empty; services are pure Python, easy to test
- **App size optimization** — currently 1 GB (bundles all dylibs from pixi env)
- **Code signing** — Apple Developer ID + Windows Authenticode
- **Deep zoom** — current canvas uses 1024px thumbnails; could add OpenSlide `read_region` tiling
- **Undo/Redo** — `QUndoStack`
- **Multi-select on canvas** — rubber band selection, bulk operations
- **Annotations** — drawing, measurements, labels
- **DICOM export**
- **AI suggest** — original Phase 4 (HF `phikon-v2` embeddings)

See README "Roadmap" section for priority suggestions.

---

## Gotchas / things that bit me

### Build / packaging

1. **`__file__` not defined in PyInstaller spec** — use `Path(SPECPATH)` instead.
2. **Pixi env path** — `.pixi/envs/default/` (not `.pixi/env/` as I initially assumed).
3. **Info.plist needs `NSPrincipalClass=NSApplication`** — without it, Mac doesn't recognize the bundle as a GUI app and native menu bar doesn't work.
4. **`PIL.MAX_IMAGE_PIXELS`** — default limit ~178M pixels blocks pathology WSI. Set to `None` at module load in `services/compose.py`.
5. **`return` inside `with io.BytesIO() as buf`** — easy to accidentally move `return` outside the `with` block → "I/O operation on closed file".
6. **Bundle is 1 GB** — we bundle every dylib from pixi env (~796 files). Could prune by tracking only OpenSlide's transitive deps.

### Qt / PySide6

7. **`option.state &= ~0x00008000`** — doesn't work in PySide6 (StateFlag vs int). Use `option.state &= ~QStyle.State_Selected`.
8. **`Qt.AA_DontUseNativeMenuBar`** — deprecated in Qt 6. Use `menubar.setNativeMenuBar(False)` per-window instead.
9. **Lambda slots don't auto-queue cross-thread** — use proper methods on `QObject` subclasses with explicit `Qt.QueuedConnection`.
10. **`QGraphicsView` eats plain wheel events** — for image-editor-style zoom, override `wheelEvent`. We made plain wheel = pan, ⌘+wheel = zoom, pinch gesture = zoom (trackpad).
11. **`QGraphicsItem.shape()` is the hit-test region** — if handles are outside the main shape, clicks on them don't fire `mousePressEvent`. Always include handle rects in `shape()` when selected.
12. **`prepareGeometryChange()`** — call before changing `_w`/`_h` on a `QGraphicsObject`, or the scene's BSP goes stale and the item disappears or becomes unclickable.

### macOS

13. **`open dist/SlideVision.app` swallows stderr** — run `./dist/SlideVision.app/Contents/MacOS/SlideVision` directly for debugging.
14. **`pkill -f "SlideVision"` before rebuild** — otherwise the running app holds file locks and PyInstaller can't clean `dist/`.

### Storage

15. **`storage_dir` must be absolute** — defaulting to `Path("./storage")` breaks when launched from Finder (cwd = `/`, can't write). Default is now `~/Documents/SlideVision`.

---

## How to test changes

There are no automated tests. Manual workflow:

1. Make code change
2. `pixi run python -c "from slide_stitcher.ui.main_window import MainWindow"` — verify imports
3. `pixi run dev` — quick interactive test
4. For UI changes that need the installer: `pkill -f SlideVision && rm -rf dist build && pixi run pyinstaller packaging/slide_stitcher.spec --noconfirm && ./dist/SlideVision.app/Contents/MacOS/SlideVision`
5. Capture stderr: `... 2>&1 | tee /tmp/slidevision.log`
6. To see runtime errors in the bundled app, check the log file. Paint errors show as `Error calling Python override of QGraphicsObject::paint()`.

PyInstaller build takes ~1 minute. Budget for ~5 iterations when debugging UI.

---

## When extending the app

### Adding a menu action

1. Add to `_build_menu()` in `main_window.py`:
   ```python
   edit_menu.addAction("&My Feature…", self._on_my_feature, "Ctrl+M")
   ```
2. Implement `_on_my_feature(self)` handler.
3. For keyboard reliability, also add `QShortcut` in `_build_shortcuts()` (QGraphicsView eats plain QAction shortcuts).

### Adding a new WSI format

OpenSlide already supports: `.svs, .ndpi, .mrxs, .vms, .scn, .bif, .tif, .tiff`. To extend:
1. Add extension to `WSI_EXTENSIONS` in `services/wsi.py`.
2. Add to `SLIDE_FILTER` in `widgets/case_sidebar.py`.

### Adding a service

1. Create `services/<name>.py` (pure Python, no Qt).
2. Wire into `controllers/case_controller.py` if it needs case state.
3. **Do not import PySide6 from any file under `services/`** — that breaks the "testable in isolation" property.

### Changing the theme

Edit `src/slide_stitcher/assets/theme.qss`. Loaded fresh every launch in dev mode. For bundled app, need rebuild.

### Changing the icon

Edit `packaging/make_icon.py` (Pillow-based, no SVG). Run `pixi run python packaging/make_icon.py`. Then rebuild.

---

## Memory context (from previous Claude sessions)

The previous Claude sessions saved these memory files at `~/.claude/projects/-Users-unuun-Desktop-CANCER-SLIDE/memory/` (these do NOT transfer to a new machine — context is now in this CLAUDE.md):

- **User profile**: pathologist + software engineer, Thai speaker, working on SlideVision project
- **Tech preference**: Nuxt.js for any future web work (was used in early web-app prototype, abandoned after pivot)
- **Project history**: pivoted from web app (FastAPI + Nuxt) to native (PySide6 + Qt) because GB-scale WSI files shouldn't be uploaded
- **AI suggest**: deferred — was originally Phase 4, user explicitly skipped

---

## Commit history

```
3babc01 (HEAD -> main) Initial commit: SlideVision v0.2.0
```

Single commit so far. Standard git workflow going forward — feature branches + PRs not yet configured.

---

## Quick FAQ for new agents

**Q: Why is the Python package `slide_stitcher` but the app is `SlideVision`?**
A: Legacy. The package name came from the original web prototype. Renaming would require moving every directory. Display name is set in `main.py`, `main_window.py`, `pyproject.toml`, and `packaging/slide_stitcher.spec`.

**Q: Can I run without Pixi?**
A: Yes — install Python 3.11+, then `pip install pyside6 pyinstaller openslide-python openslide pillow numpy scikit-learn pydantic-settings httpx pytest`. But you still need the OpenSlide C library installed separately (Homebrew on Mac, MSI on Windows). Pixi bundles it automatically.

**Q: Can I run on Linux?**
A: Untested. Should work — add `linux-64` to `[tool.pixi.workspace]` platforms in `pyproject.toml`, `pixi install`, build.

**Q: The app is 1 GB. Can I shrink it?**
A: Yes. The spec bundles all 796 dylibs from `.pixi/envs/default/lib/`. Pruning to just OpenSlide's transitive deps would get it to ~200 MB. Use `otool -L libopenslide.1.dylib` to trace deps.

**Q: Why two crop layers (crop + applied_crop)?**
A: `crop_*` is the pending visual crop (user can adjust before committing). `applied_*` is the cumulative committed crop in original normalized coords. The separation lets users crop multiple times while the export pipeline has a single source-of-truth.

**Q: How do I debug the bundled app?**
A: Run the executable directly (not via `open`): `./dist/SlideVision.app/Contents/MacOS/SlideVision 2>&1 | tee /tmp/log.txt`. PyInstaller errors print to stderr.

---

*Last updated: 2026-07-19 by the agent who shipped v0.2.0 MVP.*
