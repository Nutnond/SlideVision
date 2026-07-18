# SlideVision

**Native desktop app for pathologists** — reconstruct a pathology case overview (e.g. colon cancer resection, mastectomy with multiple blocks) by stitching multiple whole-slide images (WSI) into a single composed image, without uploading or copying GB-scale source files.

Built with **PySide6/Qt 6** + **OpenSlide** + **Pixi**. Cross-platform installers for Mac (`.app`/`.dmg`) and Windows (`.exe`/`.msi`). Offline by design — no cloud, no account.

---

## Why this exists

When a pathologist examines a long specimen (colon, breast, soft tissue), the lab cuts it into multiple blocks → each block becomes one slide (`.ndpi` / `.svs` / `.mrxs`). To see tumor distribution, margin involvement, or overall case topology, the pathologist has to mentally stitch slides together while flipping between them in a viewer.

**SlideVision** lets the pathologist drag slides onto a canvas, arrange them in anatomical order, optionally rotate/trim each one, and export a single composed overview PNG at full diagnostic resolution.

The composed image can be used for:
- Case overview in a report
- Tumor distribution map
- Teaching / case conference
- Quick visual review without opening each slide

---

## System Requirements

### End users (running the installer)

| Platform | Minimum | Recommended |
|---|---|---|
| **macOS** | 11.0 Big Sur (Intel or Apple Silicon) | 13.0 Ventura+ on Apple Silicon (M1/M2/M3) |
| **Windows** | Windows 10 64-bit (build 19041+) | Windows 11 64-bit |
| **Linux** | Untested; should work with Qt 6 system libs | Ubuntu 22.04+ or Fedora 38+ |

**Hardware:**

| Resource | Minimum | Recommended |
|---|---|---|
| **RAM** | 8 GB | 16 GB+ (32 GB+ for 5+ slides at native resolution) |
| **Disk** | 2 GB free (app + caches) | 10+ GB free (per-case thumbnails, exports) |
| **CPU** | Dual-core 2 GHz | Quad-core 2.5 GHz+ |
| **Display** | 1366×768 | 1920×1080+ (4K recommended for pathology review) |
| **GPU** | Not required | Any (Qt uses software rendering by default) |

**Per-slide memory:** Each native-resolution export holds one slide at full WSI resolution in memory. A 50000×50000 RGB slide ≈ 7.5 GB RAM. The export caps output at 30000×30000 to mitigate OOM.

**Storage growth:** Each case directory is ~10–20 MB (1024px thumbnails + JSON metadata). Original WSI files stay wherever the user keeps them — not duplicated.

### Developers (building from source)

In addition to the above:

| Tool | Version | Why |
|---|---|---|
| **Pixi** | 0.40+ | Python + native library manager (replaces Homebrew for OpenSlide) |
| **Git** | 2.30+ | Version control |
| **PyInstaller** | 6.21+ (installed via Pixi) | Bundles Python app into native executable |
| **iconutil** (Mac only) | system-provided | Generates `.icns` from icon set |
| **Inno Setup** (Windows only) | 6.2+ | Generates `.exe` installer |

**Cross-compilation:** Not supported. Mac `.app` must be built on Mac; Windows `.exe` must be built on Windows. Use a VM (Parallels, UTM) or CI (GitHub Actions matrix) to produce both.

**Code signing:** Not required for POC. Production deployment needs:
- **Apple Developer ID** ($99/year) — for Mac notarization (Gatekeeper)
- **Windows Authenticode** certificate ($100–400/year) — for SmartScreen reputation

---



## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  SlideVision.app (.app bundle on Mac, .exe on Windows)    │
│                                                           │
│  ┌────────────────────────────────────────────────────┐  │
│  │  PySide6 Qt 6 GUI                                  │  │
│  │  • Welcome screen (recent cases + New Case)        │  │
│  │  • Case sidebar (thumbnails, right-click delete)   │  │
│  │  • QGraphicsView canvas (zoom/pan/drag/resize)     │  │
│  │  • Menu bar (File/Edit/View/Help)                  │  │
│  └───────────────┬────────────────────────────────────┘  │
│                  │ direct Python calls (no HTTP)          │
│  ┌───────────────▼────────────────────────────────────┐  │
│  │  Services (pure Python, no Qt dependency)          │  │
│  │  • wsi.py — OpenSlide thumbnail generation         │  │
│  │  • compose.py — PIL composition (low + full-res)   │  │
│  │  • mapping.py — case + position JSON persistence   │  │
│  │  • storage.py — filesystem layout helpers          │  │
│  │  • thumbnail.py — PIL fallback for plain images    │  │
│  └───────────────┬────────────────────────────────────┘  │
│                  │                                         │
│  ┌───────────────▼────────────────────────────────────┐  │
│  │  Storage                                           │  │
│  │  ~/Documents/SlideVision/cases/<case_id>/          │  │
│  │    case.json    — CaseMetadata + slides[]           │  │
│  │    mapping.json — SlidePosition[]                   │  │
│  │    composed.png — last export                       │  │
│  │    slides/<slide_id>/thumb.png                      │  │
│  │  (original WSI files stay at user-chosen path)      │  │
│  └────────────────────────────────────────────────────┘  │
│                                                           │
│  Bundled native libs:                                     │
│  • libopenslide (WSI reading, all major formats)          │
│  • Qt plugins (cocoa/windows, image formats)              │
│  • Pillow, numpy, scikit-learn                            │
└──────────────────────────────────────────────────────────┘
```

**Key design decisions:**

| Decision | Rationale |
|---|---|
| **Native Qt over web** | Direct file access (no copy of GB-scale WSI), native performance, deep-zoom potential, industry-standard for medical imaging |
| **Pixi over Homebrew** | Per-project isolated Python + native libs — no system pollution, reproducible via `pixi.lock` |
| **Filesystem storage over DB** | Easy backup, inspectable, no migration headaches; cases are independent directories |
| **Reference slides by path** | Original WSI files (potentially 5+ GB) stay in user's archive; only 1024px thumbnails cached locally |
| **Service/UI separation** | Services are pure Python (no Qt) — testable in isolation, reusable for CLI/scripts later |
| **PyInstaller over Electron** | Single-language codebase (Python matches OpenSlide ecosystem), smaller binary, native performance |

---

## Tech stack

| Layer | Library | Version (locked in `pyproject.toml`) |
|---|---|---|
| GUI | PySide6 (Qt 6) | 6.11.x |
| WSI reading | openslide-python + openslide | 1.4.6 / 4.0.1 |
| Image processing | Pillow | 12.x |
| Math/array | numpy + scikit-learn | 2.x / 1.9.x |
| Persistence | Pydantic + Pydantic-settings | 2.x |
| Packaging | PyInstaller | 6.21.x |
| Package manager | Pixi | latest |

---

## Project structure

```
CANCER SLIDE/
├── README.md                       # this file
├── backend/                        # entire app codebase
│   ├── pyproject.toml              # Pixi project + Python deps
│   ├── pixi.lock                   # reproducible env lock
│   ├── .env.example                # STORAGE_DIR, HF_TOKEN
│   │
│   ├── src/slide_stitcher/         # ← Python package (legacy name, kept to avoid moves)
│   │   ├── main.py                 # QApplication entry; loads icon + theme + MainWindow
│   │   ├── config.py               # Settings (storage_dir default: ~/Documents/SlideVision)
│   │   ├── models.py               # Pydantic: CaseMetadata, SlideMetadata, SlidePosition, Mapping
│   │   │
│   │   ├── services/               # Pure-Python business logic (no Qt)
│   │   │   ├── wsi.py              # OpenSlide thumbnail + native-resolution reader
│   │   │   ├── thumbnail.py        # PIL fallback for plain images
│   │   │   ├── compose.py          # PIL composition (low-res + full-res with progress_cb)
│   │   │   ├── mapping.py          # JSON persistence of case + mapping
│   │   │   ├── storage.py          # Path helpers (case_dir, thumb_path, etc.)
│   │   │   └── types.py            # ThumbResult dataclass
│   │   │
│   │   ├── ui/                     # Qt UI layer
│   │   │   ├── main_window.py      # QMainWindow, menu, splitter (sidebar + canvas)
│   │   │   ├── controllers/
│   │   │   │   └── case_controller.py   # Bridge: UI ↔ services, Qt signals
│   │   │   ├── dialogs/
│   │   │   │   ├── new_case_dialog.py   # Modal: name a new case
│   │   │   │   └── crop_dialog.py       # Modal: numeric crop sliders
│   │   │   └── widgets/
│   │   │       ├── welcome_screen.py    # Shown when no case loaded (recent + New)
│   │   │       ├── case_sidebar.py      # Left panel: thumb list + context menu
│   │   │       ├── slide_canvas.py      # QGraphicsView: zoom/pan/gesture
│   │   │       └── slide_item.py        # QGraphicsObject: drag/resize/rotate/crop
│   │   │
│   │   └── assets/
│   │       └── theme.qss           # Qt Style Sheet (dark theme, indigo accent)
│   │
│   ├── packaging/                  # Build pipeline
│   │   ├── slide_stitcher.spec     # PyInstaller spec (Mac + Windows)
│   │   ├── make_icon.py            # Pillow script → .icns + .ico
│   │   └── icons/                  # Generated icons (committed)
│   │
│   └── storage/                    # Local dev storage (gitignored in real repo)
│       └── cases/                  # Created on first run
│
└── (no separate frontend/ — killed when we pivoted from web to native)
```

---

## Development setup

### Prerequisites

- **macOS 12+** (Apple Silicon or Intel) — for Mac builds
- **Windows 10/11** — for Windows builds (cannot cross-compile)
- ~2 GB free disk for Pixi env + build artifacts

### Install Pixi (one-time, user-local)

```bash
curl -fsSL https://pixi.sh/install.sh | bash
# Restart shell or: export PATH="$HOME/.pixi/bin:$PATH"
pixi --version  # should print 0.7x.0 or later
```

Pixi installs to `~/.pixi/bin/` — does **not** touch Homebrew or system Python.

### Clone & install

```bash
cd "/Users/unuun/Desktop/CANCER SLIDE/backend"
pixi install                   # creates .pixi/envs/default/
```

This installs Python 3.11, OpenSlide (with native dylib), PySide6, Pillow, and all other deps from `pixi.lock`.

### Run in dev mode

```bash
cd backend
pixi run python -m slide_stitcher.main
# or via the task shortcut:
pixi run dev
```

The app opens. Storage defaults to `~/Documents/SlideVision/`.

### Verify services work (no Qt)

```bash
pixi run python -c "from slide_stitcher.services import wsi, compose, mapping; print('OK')"
```

---

## Build the installer

### Mac (.app + .dmg)

```bash
cd backend

# 1. Regenerate icons (only if you edited make_icon.py)
pixi run python packaging/make_icon.py

# 2. Build .app via PyInstaller
pixi run pyinstaller packaging/slide_stitcher.spec --noconfirm
# Output: backend/dist/SlideVision.app (≈ 1 GB)

# 3. Launch to test
open dist/SlideVision.app
# or run executable directly to see stderr:
./dist/SlideVision.app/Contents/MacOS/SlideVision
```

To create a distributable `.dmg`:
```bash
hdiutil create -volname SlideVision -srcfolder dist/SlideVision.app -ov -format UDZO dist/SlideVision.dmg
```

For pretty drag-to-Applications DMGs, use [create-dmg](https://github.com/sindresorhus/create-dmg).

### Windows (.exe + .msi)

**Must run on Windows** (PyInstaller cannot cross-compile). Steps:

```powershell
cd backend
pixi install
pixi run pyinstaller packaging/slide_stitcher.spec --noconfirm
# Output: dist/SlideVision/ (directory with .exe + dependencies)
```

For a single-file installer, wrap with [Inno Setup](https://jrsoftware.org/isinfo.php):
- Spec template lives at `packaging/windows/installer.iss` (to be added)
- Result: `dist/SlideVision-Setup.exe`

---

## Code organization

### Services layer (`slide_stitcher/services/`)

Pure Python, no Qt imports. Safe to unit-test, reuse in scripts.

**`wsi.py`**
- `generate_thumbnail(path, max_dim=1024) -> ThumbResult` — opens via OpenSlide, falls back to PIL for plain images
- Returns `(png_bytes, orig_w, orig_h, thumb_w, thumb_h, is_wsi)`

**`compose.py`**
- `compose_image(case, mapping, scale=1.0)` — low-res export using cached thumbnails
- `compose_image_full_res(case, mapping, progress_cb=None)` — high-res export reading each original at native resolution via OpenSlide pyramid levels; capped at 30000×30000 to avoid OOM
- `read_original_sized(path, target_w, target_h, is_wsi)` — picks the best OpenSlide pyramid level for the target size
- `_apply_applied_crop(img, pos)` + `_apply_crop(img, pos)` — applies cumulative committed crop then current visual crop
- `_paste_position(pos, img, min_x, min_y, scale)` — handles rotation by pasting at center

**`mapping.py`** — JSON persistence of `case.json` + `mapping.json` per case directory.

**`storage.py`** — path helpers; no I/O beyond `mkdir`.

### Models (`slide_stitcher/models.py`)

Pydantic `BaseModel` subclasses. Serialize to JSON for persistence.

```python
SlideMetadata:
  id, case_id, filename, original_filename, original_path,
  width, height, thumb_width, thumb_height, has_wsi, created_at

CaseMetadata:
  id, name, slides: list[SlideMetadata], created_at

SlidePosition:                # one per placed slide on the canvas
  id, x, y, w, h,
  rotation,
  crop_x, crop_y, crop_w, crop_h,           # current visual crop (0..1, normalized)
  applied_x, applied_y, applied_w, applied_h # cumulative committed crop in original coords

Mapping:
  case_id, slides: list[SlidePosition]
```

### UI layer (`slide_stitcher/ui/`)

Qt-based. References services but never imports them at module top-level inside `services/` (services stay Qt-free).

**`main_window.py`** — `QMainWindow` with:
- Welcome screen ↔ workspace toggle (no case → welcome; case loaded → splitter)
- Menu bar (File/Edit/View/Help) — set to non-native via `setNativeMenuBar(False)` for PyInstaller reliability
- `FullResExportWorker(QObject)` — QThread-based background export with progress signal
- Keyboard shortcuts via `QShortcut` with `Qt.ApplicationShortcut` context (because QGraphicsView eats plain `QAction` shortcuts)

**`widgets/welcome_screen.py`** — Recent cases grid + New Case + Browse buttons. Replaces the canvas when no case is loaded.

**`widgets/case_sidebar.py`** — Left panel. `QListWidget` in `IconMode`. Right-click context menu for "Add to canvas / Remove from canvas / Delete from case".

**`widgets/slide_canvas.py`** — `QGraphicsView` subclass:
- Plain wheel = pan (default `super().wheelEvent`)
- ⌘+wheel = zoom (mouse fallback)
- **Pinch gesture** (trackpad) = zoom
- Drag empty area = pan
- Drag slide item = move
- Scene rect fixed at `(-5000, -5000, 10000, 10000)` so positions are predictable

**`widgets/slide_item.py`** — `QGraphicsObject` subclass with custom `paint()`:
- Always shows full pixmap + dim overlay outside current crop region
- When selected: 4 corner resize handles (white), 4 edge crop handles (orange), 1 top rotate handle (blue circle)
- Rotation around center via `setTransformOriginPoint(w/2, h/2)`
- Resize math accounts for rotation by transforming scene-delta into item-local frame
- `apply_crop()` — commits current visual crop: shrinks geometry, crops in-memory pixmap, compounds `applied_x/y/w/h`, resets visual crop to full

**`controllers/case_controller.py`** — `QObject` that emits signals (`caseLoaded`, `slidesAdded`, `slideRemoved`, `dirtyChanged`, etc.). UI widgets connect to these signals; controller calls services directly.

### Theme (`assets/theme.qss`)

Qt Style Sheet — dark theme with indigo (`#4f46e5`) accent. Loaded by `main.py:_load_theme()` from either `sys._MEIPASS/assets/theme.qss` (frozen) or `src/slide_stitcher/assets/theme.qss` (dev).

### Icons (`packaging/make_icon.py`)

Pillow script that draws the icon programmatically (no SVG dependency):
- Gradient background (indigo → violet)
- 4 white rounded cells in 2×2 grid (the "stitched slides" metaphor)
- Pink accent dot in top-right cell
- Generates `.icns` (via `iconutil`) and `.ico` (via Pillow) at standard sizes

---

## Data flow

### Create case + add slides

```
User clicks "+ New Case" on Welcome
  → MainWindow._on_new_case()
  → NewCaseDialog.exec() returns name
  → CaseController.new_case(name)
     → services.mapping.save_case(case)
     → emits caseLoaded signal
  → MainWindow._on_case_loaded()
     → shows workspace (hides welcome)

User clicks "+ Add Slides…"
  → QFileDialog.getOpenFileNames() returns paths
  → CaseController.register_slides(paths)
     → for each path:
         services.wsi.generate_thumbnail(path)  # no copy of original
         write thumb.png to storage
         append SlideMetadata to case.slides (original_path stored, not file bytes)
     → services.mapping.save_case(case)
     → emits slidesAdded signal
  → CaseSidebar._on_slides_added() adds QListWidgetItems
```

### Place + edit slide on canvas

```
User clicks thumbnail in sidebar
  → CaseSidebar.slideClicked signal
  → MainWindow._on_slide_clicked(slide_id)
  → SlideCanvas.add_slide(slide, pixmap)  # creates SlideItem at viewport center
     → SlideItem added to QGraphicsScene
     → canvas positions dict updated

User drags corner handle
  → SlideItem.mousePressEvent detects handle "tl/tr/bl/br"
  → mouseMoveEvent → _do_resize() — accounts for rotation via QTransform
  → mouseReleaseEvent → resized signal
  → MainWindow._on_canvas_slide_resized → controller.mark_dirty()

User drags orange edge handle
  → _do_crop_drag() updates crop_x/y/w/h, redraws dim overlay
  → User presses Enter
  → MainWindow._on_apply_crop → SlideCanvas.apply_crop_selected()
     → SlideItem.apply_crop() commits, shrinks geometry, compounds applied_crop
     → MainWindow saves new pixmap to disk thumb
```

### Export (full-resolution)

```
User: File → Export Full-Quality PNG (⌘⇧E)
  → MainWindow._on_export_full_res()
  → Creates QThread + FullResExportWorker
  → Connects progress/finished/failed signals with Qt.QueuedConnection
  → Shows QProgressDialog (modal)
  → Worker.run() in background:
      compose_image_full_res(case, mapping, progress_cb=...)
        for each slide:
          read_original_sized(original_path, target_w, target_h, is_wsi)
          apply_applied_crop, apply_crop, resize, rotate, paste
        save PNG to disk
      emit progress(5..99), finished(w, h)
  → Main thread: _on_export_progress updates dialog
  → _on_fullres_finished hides dialog, shows success message
```

---

## Key concepts

### `original_path` (no-copy architecture)

`SlideMetadata.original_path` stores the **absolute filesystem path** of the user's WSI file. The file is **never copied** into storage — only a 1024px thumbnail is cached at `storage/cases/<case_id>/slides/<slide_id>/thumb.png`.

For full-resolution export, OpenSlide reads from `original_path` at the best pyramid level for the target size.

If the user moves/renames/deletes the original file, future exports fail gracefully (logged, skipped).

### Crop vs applied_crop

- `crop_x/y/w/h` — **current visual crop**, normalized 0–1 of the *currently-visible* slide. Adjustable via orange edge handles. Reset to `(0,0,1,1)` after Apply Crop.
- `applied_x/y/w/h` — **cumulative committed crop**, normalized 0–1 of the *original* WSI. Compounded on each Apply Crop.

This separation lets users crop multiple times (e.g. coarse crop → fine crop) while the export pipeline has a single source-of-truth for "what part of the original to render."

### Why `setNativeMenuBar(False)`

On Mac, Qt prefers the native menu bar at top of screen. In a PyInstaller bundle without code signing, this can be flaky (menu doesn't appear, or duplicate menus). Setting `setNativeMenuBar(False)` forces an in-window menu bar — reliable across platforms.

### Why `Qt.QueuedConnection` for worker signals

`QProgressDialog.setValue()` must be called from the main thread (Mac requires `NSWindow` instantiation on main thread). Lambda slots in PySide6 may not auto-detect cross-thread, so explicit `Qt.QueuedConnection` is required.

---

## Extending the app

### Add a new menu action

1. Add to `_build_menu()` in `main_window.py`:
   ```python
   edit_menu.addAction("&My Feature…", self._on_my_feature, "Ctrl+M")
   ```
2. Implement `_on_my_feature(self)` handler.
3. If the action targets the canvas, add a `QShortcut` to `_build_shortcuts()` for keyboard reliability (QGraphicsView eats plain `QAction` shortcuts).

### Add a new WSI format

OpenSlide already supports: `.svs`, `.ndpi`, `.mrxs`, `.vms`, `.scn`, `.bif`, `.tif`, `.tiff`. To extend:

1. Add the extension to `WSI_EXTENSIONS` in `services/wsi.py`.
2. If OpenSlide can't open it, fall back to PIL via `services/thumbnail.py`.
3. Add the extension to the file dialog filter in `widgets/case_sidebar.py:SLIDE_FILTER`.

### Add a new service

1. Create `services/<name>.py` with pure-Python functions (no Qt imports).
2. Add tests in `tests/test_<name>.py`.
3. Wire into `controllers/case_controller.py` if it needs to interact with case state.

### Change the storage location

Set the `STORAGE_DIR` env var (or edit `.env`):

```bash
STORAGE_DIR=/path/to/custom/location pixi run dev
```

End users can set this in a `.env` file next to the executable (rare — default `~/Documents/SlideVision` is sensible).

### Theme tweaks

Edit `src/slide_stitcher/assets/theme.qss`. The QSS is loaded fresh on every app launch — no rebuild needed between iterations in dev mode.

For the app icon, edit `packaging/make_icon.py` (Pillow drawing), run `pixi run python packaging/make_icon.py`, then rebuild.

---

## Known limitations

- **No undo/redo** — deferred from Phase D. Adding `QUndoStack` would be the right path.
- **No multi-slide selection on canvas** — sidebar supports multi-select (Shift/Ctrl-click), canvas does not.
- **No annotations** — measuring, drawing, labels are out of scope for v0.2.
- **No deep-zoom** — current canvas uses 1024px thumbnails. True WSI deep-zoom (tile-based, OpenSlide `read_region` on demand) is a future v0.3.
- **No code signing** — Mac `.app` is ad-hoc signed (Gatekeeper may complain on first launch; user right-clicks → Open). Windows `.exe` is unsigned (SmartScreen warning). Production needs Apple Developer ID + Windows Authenticode.
- **App size 1 GB** — bundles all dylibs from pixi env (most are unused). Could prune by tracking only OpenSlide transitive deps.
- **No auto-update** — Sparkle (Mac) / WinSparkle (Windows) integration planned for later.
- **AI suggest not implemented** — original plan included cloud-based slide arrangement suggestion via `owkin/phikon-v2` embeddings. Skipped per user request.

---

## Testing

```bash
cd backend
pixi run pytest                    # placeholder — no tests written yet
```

Services are pure Python and trivially testable. A minimal smoke test:

```python
# tests/test_services.py
from pathlib import Path
from slide_stitcher.services import wsi

def test_thumbnail_for_plain_image(tmp_path: Path):
    from PIL import Image
    img = Image.new("RGB", (2000, 1500), (200, 100, 50))
    img.save(tmp_path / "t.png")
    result = wsi.generate_thumbnail(tmp_path / "t.png", max_dim=512)
    assert result.thumb_w <= 512
    assert result.thumb_h <= 512
```

UI tests would need `pytest-qt` — not yet added.

---

## Build artifacts reference

| Path | Purpose |
|---|---|
| `backend/.pixi/envs/default/` | Pixi-managed Python env (gitignored) |
| `backend/storage/` | Dev storage (gitignored) |
| `backend/build/` | PyInstaller intermediate (gitignored) |
| `backend/dist/SlideVision.app` | Built Mac app (gitignored) |
| `backend/dist/SlideVision/` | Built Windows app dir (gitignored) |
| `backend/packaging/icons/` | Generated icons (committed) |
| `~/Documents/SlideVision/cases/` | User data (runtime) |

---

## FAQ

**Q: Why is the package named `slide_stitcher` but the app is `SlideVision`?**
A: The Python package name is a legacy from the original web-app prototype. Renaming would require moving every directory. Display name (`SlideVision`) is set in `main.py`, `main_window.py`, `pyproject.toml` (authors), and `packaging/slide_stitcher.spec` (bundle name). Internal imports use `slide_stitcher.*`.

**Q: Can I run without Pixi?**
A: Yes, with a regular Python 3.11+ venv: `pip install -e . pyside6 pyinstaller openslide-python openslide pillow numpy scikit-learn pydantic-settings httpx pytest`. But you still need the OpenSlide C library installed separately (Homebrew on Mac, MSI on Windows). Pixi bundles it automatically.

**Q: Does it work on Linux?**
A: Untested but should — add `linux-64` to `[tool.pixi.workspace]` platforms and rebuild. Qt for Linux is well-supported.

**Q: Can it handle 100+ slides in one case?**
A: Yes for storage. UI performance may degrade — QGraphicsScene is fast but `QListWidget` icon mode starts to stutter past ~50 items. Consider paginating or switching to `QListView` + custom model for v0.3.

**Q: How do I report a bug or contribute?**
A: Internal project — no public repo yet. Coordinate with the pathologist-owner directly.

---

## Roadmap (informal)

- [ ] **v0.3** — Deep-zoom rendering via OpenSlide `read_region` tiling
- [ ] **v0.3** — Undo/redo stack (`QUndoCommand` per drag/resize/rotate/crop)
- [ ] **v0.3** — Multi-select on canvas (rubber band), bulk operations
- [ ] **v0.4** — Annotations: freehand drawing, text labels, measurements (mm)
- [ ] **v0.4** — DICOM export (in addition to PNG)
- [ ] **v0.5** — AI suggest (HF Inference API + `phikon-v2` embeddings)
- [ ] **v0.5** — Code signing (Apple Developer ID, Windows Authenticode)
- [ ] **v0.6** — Auto-update (Sparkle / WinSparkle)
- [ ] **v1.0** — First public release

---

*Last updated: 2026-07-19*
