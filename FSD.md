# Functional Specification Document (FSD)

## iPhone Photo Sync — v1.0

---

## 1. Overview

iPhone Photo Sync is a Windows background service that automatically downloads today's photos and videos from iCloud Photos to a local folder whenever an iPhone is connected via USB. It consists of two components: a USB watcher and a sync engine.

---

## 2. Architecture

```
┌──────────────────────────┐
│   Windows Task Scheduler │
│   (runs at user logon)   │
└───────────┬──────────────┘
            │ launches
            v
┌──────────────────────────┐       USB detected        ┌──────────────────────┐
│  iphone_sync_watcher.pyw │  ───────────────────────>  │   iphone_sync.py     │
│  (background watcher)    │  <───────────────────────  │   (sync engine)      │
│                          │    USB disconnected        │                      │
│  - Polls USB every 15s   │     (terminates)           │  - Connects to iCloud│
│  - No console window     │                            │  - Downloads media   │
│  - Logs to file          │                            │  - Preserves dates   │
└──────────────────────────┘                            │  - Polls every 120s  │
                                                        └──────────┬───────────┘
                                                                   │
                                                                   v
                                                        ┌──────────────────────┐
                                                        │   iCloud Photos API  │
                                                        │   (via icloudpy)     │
                                                        └──────────────────────┘
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
| `is_iphone_connected()` | Queries Windows WMI for PnP devices matching Apple's USB vendor ID (`VID_05AC`) with class `WPD` and status `OK`. Returns `True` if at least one matching device is found. Uses the Python `wmi` library to avoid spawning subprocess/terminal windows. |
| `main()` | Main event loop. Polls `is_iphone_connected()` every 15 seconds. On state transitions: **connected** — launches `iphone_sync.py` as a subprocess with `--background` flag using `pythonw.exe` and `CREATE_NO_WINDOW`. **disconnected** — terminates the sync subprocess (graceful with 10s timeout, then force kill). Also monitors for unexpected sync process exits and restarts if the iPhone is still connected. |

#### Configuration Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `SYNC_SCRIPT` | `<same directory>/iphone_sync.py` | Path to the sync engine |
| `LOG_FILE` | `~/.icloud_sync/watcher.log` | Watcher log file path |
| `POLL_INTERVAL` | `15` seconds | USB detection polling interval |
| `PYTHONW` | Auto-detected `pythonw.exe` | Python interpreter without console |

---

### 3.2 Sync Engine (`iphone_sync.py`)

**Purpose:** Connect to iCloud Photos and download today's new photos and videos to the target directory.

**Runtime:** Launched by the watcher (background mode) or manually by the user (interactive mode). Runs in a continuous polling loop until terminated or stopped with Ctrl+C.

#### Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `load_state()` | `() -> dict` | Loads the sync state from `.iphone_sync_state.json` in the target directory. Returns a dict with key `synced_files` mapping sync keys to metadata. Returns empty state if file doesn't exist. |
| `save_state(state)` | `(dict) -> None` | Persists the sync state dict to the JSON state file. Called after every 5 new downloads and at the end of each sync pass. |
| `set_file_dates(filepath, created, modified)` | `(str, datetime, datetime) -> None` | Sets the Windows file creation time and modification time using the Win32 API (`SetFileTime`). Falls back to `os.utime()` if the Win32 call fails. Ensures synced files retain their original iPhone capture timestamps. |
| `download_photo(photo, local_path)` | `(PhotoAsset, str) -> int` | Downloads a single photo/video from iCloud. Tries `original` quality first, falls back to `medium`. Streams data in 1 MB chunks. Returns file size in bytes on success, `0` on failure. |
| `load_config()` | `() -> dict` | Loads saved configuration (Apple ID) from `~/.icloud_sync/config.json`. |
| `save_config(config)` | `(dict) -> None` | Saves configuration to the config file. |
| `get_apple_id()` | `() -> str` | Resolves Apple ID from (in priority order): command-line argument, saved config, interactive prompt. Saves the resolved Apple ID to config for future use. |
| `connect_icloud(apple_id, interactive)` | `(str, bool) -> ICloudPyService \| None` | Connects to iCloud. First attempts cached session (no password needed). If session expired: in interactive mode, prompts for password and 2FA code; in background mode, returns `None` (requires manual re-authentication). Trusts the session after successful 2FA to extend cookie lifetime. |
| `sync_once(api, state)` | `(ICloudPyService, dict) -> tuple[int, int, int]` | Executes one sync pass. Iterates all iCloud photos, filters to today's date and supported media extensions. For each new photo: checks sync state and file existence (with size comparison for deduplication), downloads to target directory, sets original timestamps, updates sync state. Stops scanning after 200 consecutive non-today photos. Returns `(new_files, errors, bytes_transferred)`. |
| `main()` | `() -> None` | Entry point. Determines interactive/background mode from `--background` CLI flag. Resolves Apple ID, connects to iCloud, then enters polling loop: calls `sync_once()` every 120 seconds. On error, attempts reconnection. In background mode, exits if session expires. |

#### Configuration Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `TARGET_DIR` | `D:\Dropbox\! Youtube` | Destination folder for synced media |
| `STATE_FILE` | `TARGET_DIR/.iphone_sync_state.json` | Tracks which files have been synced |
| `CONFIG_DIR` | `~/.icloud_sync/` | Session cookies and config storage |
| `POLL_INTERVAL` | `120` seconds | Time between iCloud sync passes |
| `MEDIA_EXTENSIONS` | `.jpg .jpeg .heic .heif .png .tiff .tif .dng .raw .cr2 .nef .arw .mov .mp4 .m4v` | File types to sync |

---

## 4. Data Flow

### 4.1 Sync Decision Flow

```
For each photo in iCloud:
│
├─ photo_date != today?          → skip (increment consecutive_old counter)
│   └─ consecutive_old > 200?    → stop scanning
│
├─ extension not in MEDIA_EXTENSIONS? → skip
│
├─ sync_key in state?            → skip (already synced)
│
├─ file exists with same size?   → mark as synced, skip download
│
├─ file exists with different size? → download with _N suffix
│
└─ file does not exist           → download
    └─ set creation/modification dates from photo.asset_date
    └─ update sync state
```

### 4.2 Authentication Flow

```
Start
│
├─ Cached session exists?
│   ├─ Yes, still valid  → connected
│   └─ No or expired
│       ├─ Interactive mode
│       │   ├─ Prompt password
│       │   ├─ Prompt 2FA code
│       │   ├─ Trust session (extend cookie)
│       │   └─ Connected
│       └─ Background mode
│           └─ Return None (user must run manually)
```

---

## 5. File Storage

### 5.1 Local files (private, not in git)

| File | Location | Contents |
|------|----------|----------|
| `config.json` | `~/.icloud_sync/` | `{"apple_id": "user@example.com"}` |
| Session cookies | `~/.icloud_sync/` | iCloud authentication tokens |
| `watcher.log` | `~/.icloud_sync/` | Watcher event log |
| `.iphone_sync_state.json` | Target directory | `{"synced_files": {"icloud/IMG_1234.JPG": {"size": 1234, "date": "...", "synced_at": "..."}}}` |

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
| `icloudpy` | >=0.8.0 | iCloud Photos API access |
| `wmi` | >=1.5 | Windows USB device detection |
| `pywin32` | >=300 | Win32 API for setting file timestamps |

---

## 7. Error Handling

| Scenario | Behavior |
|----------|----------|
| iPhone not found | Watcher continues polling; sync engine exits with error |
| iCloud session expired | Background mode: sync exits, watcher restarts it (which exits again until manual re-auth). Interactive mode: prompts for password |
| Download failure | Logs error, continues to next photo. Retried on next sync pass since file won't be in state |
| Sync process crash | Watcher detects exit code and restarts process if iPhone still connected |
| Network timeout | icloudpy raises exception, caught by sync loop, triggers reconnection attempt |
| File write error | Logged as error, file not added to sync state (will retry next pass) |
| Duplicate filename | If same size: skip. If different size: append `_1`, `_2`, etc. suffix |

---

## 8. Security Considerations

- **No passwords stored on disk.** Only iCloud session cookies are cached (auto-expire).
- **Apple ID stored in plaintext** in local config file — protected by Windows user permissions.
- **All private data excluded from git** via `.gitignore`.
- **2FA required** — no bypass for authentication.
- **Session trust** — after 2FA, session is trusted to reduce re-authentication frequency.
