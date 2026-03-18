# iPhone Photo Sync

Automatically syncs today's photos and videos from iCloud Photos to a local folder when an iPhone is connected via USB.

## How it works

- **`iphone_sync_watcher.pyw`** — Background watcher that detects iPhone USB connection/disconnection. Starts sync when iPhone is plugged in, stops when unplugged.
- **`iphone_sync.py`** — The sync engine. Connects to iCloud Photos, downloads today's new photos and videos to the target folder. Polls every 2 minutes for new files.

## Setup

### 1. Install dependencies

```bash
pip install icloudpy pymobiledevice3
```

### 2. First run (authenticate)

Run the sync script manually once to log in and cache your iCloud session:

```bash
python iphone_sync.py
```

You'll be prompted for:
- Apple ID
- Password
- 2FA code from your device

The session is cached in `~/.icloud_sync/` so you won't need to re-enter credentials unless the session expires.

### 3. Configure target directory

Edit `iphone_sync.py` and set `TARGET_DIR` to your desired folder:

```python
TARGET_DIR = r"D:\Dropbox\! Youtube"
```

### 4. Auto-start on Windows login

Register the watcher as a scheduled task:

```powershell
$pythonw = (Get-Command pythonw.exe).Source
$script = "C:\path\to\iphone_sync_watcher.pyw"
$action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$script`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 0)
Register-ScheduledTask -TaskName "iPhone Photo Sync Watcher" -Action $action -Trigger $trigger -Settings $settings -Force
```

## Private data (not committed)

All private data stays local on your machine:
- `~/.icloud_sync/config.json` — Saved Apple ID
- `~/.icloud_sync/*.session` — iCloud session cookies
- `~/.icloud_sync/watcher.log` — Watcher log
- Target folder `.iphone_sync_state.json` — Tracks synced files

## Requirements

- Python 3.10+
- Windows 10/11
- iCloud account with Photos enabled
