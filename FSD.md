# Functional Specification Document (FSD)

## iPhone Photo Sync — v2.0 (USB)

---

## 1. Overview

iPhone Photo Sync is a Windows background service that copies today's photos and videos from an iPhone to a local folder while the iPhone is connected via USB. Files are read directly from the iPhone's camera roll (`/DCIM`) over Apple's AFC protocol using `pymobiledevice3`. No iCloud account, Apple ID or password is involved.

It consists of two components: a USB watcher and a sync engine.

---

## 2. Architecture

```
┌──────────────────────────┐
│   Windows Task Scheduler │
│   (runs at user logon)   │
└───────────┬──────────────┘
            │ launches
            v
┌──────────────────────────┐       USB detected        ┌──────────────────────────┐
│  iphone_sync_watcher.pyw │  ───────────────────────>  │   iphone_sync.py         │
│  (background watcher)    │  <───────────────────────  │   (sync engine)          │
│                          │    USB disconnected        │                          │
│  - Polls USB every 10s   │     (terminates)           │  - Connects via usbmux   │
│  - No console window     │                            │  - Copies today's media  │
│  - Logs to watcher.log   │                            │  - Preserves dates       │
└──────────────────────────┘                            │  - Polls every 120s      │
                                                        │  - Logs to sync.log      │
                                                        └──────────┬───────────────┘
                                                                   │ AFC over USB
                                                                   v
                                                        ┌──────────────────────────┐
                                                        │  iPhone /DCIM            │
                                                        │  (via Apple Mobile       │
                                                        │   Device Service usbmux) │
                                                        └──────────────────────────┘
```

---

## 3. Components

### 3.1 USB Watcher (`iphone_sync_watcher.pyw`)

**Purpose:** Detect iPhone USB connection/disconnection and manage the sync process lifecycle.

**Runtime:** Starts at Windows logon via Task Scheduler. Runs indefinitely as a background process using `pythonw.exe` (no console window).

#### Functions

| Function | Description |
|----------|-------------|
| `setup_logging()` | Initializes file-based logging to `~/.icloud_sync/watcher.log`. Creates the log directory if it doesn't exist. Log format: `YYYY-MM-DD HH:MM:SS message`. |
| `is_iphone_connected()` | Queries Windows WMI for PnP devices matching Apple's USB vendor ID (`VID_05AC`) with class `WPD` and status `OK`. Returns `True` if at least one matching device is found. Uses the Python `wmi` library to avoid spawning subprocess/terminal windows. Returns `False` on any WMI error. |
| `main()` | Main event loop. Polls `is_iphone_connected()` every 10 seconds. On state transitions: **connected** — launches `iphone_sync.py` as a subprocess with `--background` flag using `pythonw.exe` and `CREATE_NO_WINDOW`. **disconnected** — terminates the sync subprocess (graceful with 10s timeout, then force kill). If the sync process exits while the iPhone is still connected, waits 60 seconds and starts it again. |

#### Configuration Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `SYNC_SCRIPT` | `<same directory>/iphone_sync.py` | Path to the sync engine |
| `LOG_FILE` | `~/.icloud_sync/watcher.log` | Watcher log file path |
| `POLL_INTERVAL` | `10` seconds | USB detection polling interval |
| `PYTHONW` | Auto-detected `pythonw.exe` | Python interpreter without console |

---

### 3.2 Sync Engine (`iphone_sync.py`)

**Purpose:** Copy today's new photos and videos from the connected iPhone to the target directory, preserving their capture timestamps.

**Runtime:** Launched by the watcher, or manually from a console (`python iphone_sync.py`). Runs in a continuous polling loop until terminated or stopped with Ctrl+C. The `--background` argument passed by the watcher is currently ignored; behavior is identical in both cases except that console output is only shown when a console exists.

#### Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `setup_logging()` | `() -> None` | Configures the `iphone_sync` logger: a rotating file handler on `~/.icloud_sync/sync.log` (1 MB, 3 backups, format `YYYY-MM-DD HH:MM:SS LEVEL message`), plus a console handler when `sys.stdout` exists (not under `pythonw.exe`). |
| `load_state()` | `() -> dict` | Loads the sync state from `.iphone_sync_state.json` in the target directory. Returns a dict with key `synced_files` mapping sync keys to metadata. Returns empty state if the file doesn't exist. |
| `save_state(state)` | `(dict) -> None` | Persists the sync state dict to the JSON state file. Called after every 10 new downloads and at the end of each sync pass. |
| `set_file_dates_from_metadata(filepath)` | `(str) -> None` | Reads the capture time from the downloaded file and sets the Windows creation, access and modification times via `SetFileTime` (fallback `os.utime()`). Photos (`.jpg .jpeg .heic .png .tif .tiff`): EXIF `DateTimeOriginal`, then `DateTimeDigitized`, then `DateTime` (local time, via Pillow). Videos (`.mov .mp4 .m4v`): `creation_time` from the `moov/mvhd` atom, converted from UTC to local time. Dates before 2000 are ignored. Does nothing if no date is found. |
| `set_file_dates_from_stat(filepath, file_date)` | `(str, datetime) -> None` | Sets the file times to the iPhone's AFC modification date. Fallback when no metadata date could be applied. |
| `connect_iphone()` | `async () -> (LockdownClient, AfcService) \| (None, None)` | Lists USB devices via usbmux and opens a lockdown session and AFC service on the first one. Returns `(None, None)` if no iPhone is connected. Raises if the iPhone is locked or has not trusted this PC. |
| `sync_once(afc, state)` | `async (AfcService, dict) -> tuple[int, int, int]` | Executes one sync pass over `/DCIM` (see 4.1). Returns `(new_files, errors, bytes_transferred)`. |
| `main()` | `async () -> None` | Entry point. Sets up logging, loads state, then loops: connect, call `sync_once()`, log the result, sleep 120 seconds. A fresh connection is made on every pass. Exceptions in a pass are logged with traceback and the loop continues. |

#### Configuration Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `TARGET_DIR` | `D:\Dropbox\! Youtube` | Destination folder for synced media |
| `STATE_FILE` | `TARGET_DIR/.iphone_sync_state.json` | Tracks which files have been synced |
| `POLL_INTERVAL` | `120` seconds | Time between sync passes while connected |
| `LOG_FILE` | `~/.icloud_sync/sync.log` | Sync log file; output is also echoed to the console when run interactively |
| `MEDIA_EXTENSIONS` | `.jpg .jpeg .heic .heif .png .tiff .tif .dng .raw .cr2 .nef .arw .mov .mp4 .m4v` | File types to sync |

#### Sync timing

| Event | Delay until files appear |
|-------|--------------------------|
| iPhone plugged in | ≤ 10 s (watcher poll) + duration of the first pass |
| New photo taken while connected | ≤ 120 s + duration of the pass |
| iPhone unplugged | Sync stops; nothing is copied until the next connection |

---

## 4. Data Flow

### 4.1 Sync Decision Flow

```
List /DCIM, keep folders containing "APPLE" or named <digit>..._... (e.g. 100APPLE, 202410__)
│
For each file in each folder (sorted):
│
├─ starts with "." or extension not in MEDIA_EXTENSIONS? → skip
│
├─ sync_key "<folder>/<filename>" in state?  → skip (already synced)
│
├─ AFC stat fails or has no date?            → skip (logged as warning)
│
├─ st_mtime date != today?                   → skip
│
├─ local file exists with same size?         → mark as synced, skip download
│
├─ local file exists with different size?    → download as <name>_1, _2, ...
│
└─ local file does not exist                 → download (whole file into memory)
    └─ set dates from EXIF / mvhd metadata
    └─ if mtime still within 60 s of now → set dates from AFC stat date
    └─ update sync state
```

All files are written flat into `TARGET_DIR`; the iPhone folder structure is not reproduced.

### 4.2 Connection Flow

```
Watcher sees Apple WPD device (VID_05AC)
│
└─ start iphone_sync.py
    │
    └─ every 120 s:
        ├─ usbmux lists no USB device       → log "iPhone not connected"
        ├─ lockdown fails (locked/untrusted)→ log exception, retry next pass
        └─ connected                        → sync_once()
```

---

## 5. File Storage

### 5.1 Local files (private, not in git)

| File | Location | Contents |
|------|----------|----------|
| `watcher.log` | `~/.icloud_sync/` | Watcher event log (connect, disconnect, process start/stop) |
| `sync.log` (+ `.1`–`.3`) | `~/.icloud_sync/` | Sync engine log: each pass, downloaded files, error tracebacks. Rotates at 1 MB, keeps 3 backups. |
| `.iphone_sync_state.json` | Target directory | `{"synced_files": {"114APPLE/IMG_1234.JPG": {"size": 1234, "date": "...", "synced_at": "..."}}}` |

The directory name `~/.icloud_sync/` is kept from v1 for compatibility; no iCloud data is stored there any more.

### 5.2 Repository files (public)

| File | Purpose |
|------|---------|
| `iphone_sync.py` | Sync engine |
| `iphone_sync_watcher.pyw` | USB watcher (`.pyw` = no console) |
| `.gitignore` | Excludes private files |
| `README.md` | User installation guide |
| `FSD.md` | This document |

---

## 6. Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `pymobiledevice3` | >=9.0 (async API) | usbmux, lockdown and AFC access to the iPhone |
| `Pillow` | any recent | EXIF date extraction |
| `wmi` | >=1.5 | Windows USB device detection |
| `pywin32` | >=300 | Win32 API for setting file timestamps |

**System requirement:** Apple Mobile Device Service (installed with iTunes or the Apple Devices app) must be running; it provides usbmux on Windows.

**Note:** Pillow cannot open HEIC files without the `pillow-heif` plugin. Without it, `.heic` files get their timestamps from the AFC stat date instead of EXIF.

---

## 7. Error Handling

| Scenario | Behavior |
|----------|----------|
| iPhone not connected | Watcher keeps polling; sync engine logs "iPhone not connected" and retries every 120 s |
| iPhone locked or PC not trusted | Lockdown raises; exception logged with traceback, retried next pass |
| Folder cannot be listed | Logged as error, counted, folder skipped |
| File stat fails | Logged as warning, file skipped (retried next pass) |
| Download or write failure | Logged with traceback, file not added to state (retried next pass) |
| Sync process crash | Logged as "Sync crashed"; watcher restarts it after 60 s if the iPhone is still connected |
| State file unreadable | Logged with traceback; process exits and watcher restarts it |
| Duplicate filename | If same size: skip. If different size: append `_1`, `_2`, etc. suffix |

---

## 8. Security Considerations

- **No credentials.** No Apple ID, password or session token is used or stored.
- **USB trust.** Access requires the iPhone to be unlocked and to have trusted this PC; pairing records are managed by Apple Mobile Device Service.
- **Read-only on the iPhone.** The sync engine only lists, stats and reads files; it never writes to or deletes from the device.
- **All private data excluded from git** via `.gitignore`.
