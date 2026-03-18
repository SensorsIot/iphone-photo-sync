# :iphone: iPhone Photo Sync

Automatically sync today's photos and videos from your iPhone to your PC — no cables, no manual transfers. Just plug in your iPhone and everything lands in your chosen folder.

---

## :sparkles: Features

- :camera: **Auto-syncs photos & videos** — JPG, HEIC, PNG, MOV, MP4, and more
- :cloud: **Uses iCloud** — downloads originals even if they're not stored locally on iPhone
- :electric_plug: **Plug & Play** — starts syncing when you connect your iPhone, stops when you unplug
- :ghost: **Runs silently** — no terminal windows, no popups
- :date: **Preserves dates** — keeps original creation and modification timestamps
- :arrows_counterclockwise: **Smart sync** — tracks what's already been copied, never downloads duplicates
- :lock: **Private** — credentials stay on your PC, never uploaded anywhere

---

## :package: Requirements

- **Windows 10 or 11**
- **Python 3.10+** ([Download](https://www.python.org/downloads/))
- **iCloud account** with Photos enabled on your iPhone

---

## :rocket: Installation

### Step 1: Download the project

```bash
git clone https://github.com/SensorsIot/iphone-photo-sync.git
cd iphone-photo-sync
```

Or download the ZIP from GitHub and extract it to a folder of your choice.

### Step 2: Install Python dependencies

Open a terminal (Command Prompt or PowerShell) and run:

```bash
pip install icloudpy wmi pywin32
```

### Step 3: Configure the target folder

Open `iphone_sync.py` in a text editor and change the target directory on line 24:

```python
TARGET_DIR = r"D:\Your\Target\Folder"
```

### Step 4: First-time login

Run the sync script once manually to authenticate with iCloud:

```bash
python iphone_sync.py
```

You will be asked for:

| Prompt | What to enter |
|--------|---------------|
| **Apple ID** | Your Apple ID email (find it in iPhone Settings > tap your name) |
| **Password** | Your Apple ID password (typed hidden) |
| **2FA Code** | The 6-digit code that appears on your iPhone |

:white_check_mark: Your session is now cached — you won't need to enter this again unless it expires.

### Step 5: Set up automatic startup

Open PowerShell **as Administrator** and run:

```powershell
$pythonw = (Get-Command pythonw.exe).Source
$script = "C:\path\to\iphone_sync_watcher.pyw"   # <-- change this to your actual path
$action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$script`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 0)
Register-ScheduledTask -TaskName "iPhone Photo Sync Watcher" -Action $action -Trigger $trigger -Settings $settings -Description "Auto-syncs iPhone photos when connected" -Force
```

:white_check_mark: The watcher will now start automatically every time you log in to Windows.

---

## :arrow_forward: Usage

Once installed, **there's nothing to do**. Just use your iPhone normally:

1. :electric_plug: **Plug in your iPhone** via USB
2. :hourglass_flowing_sand: The watcher detects it within 15 seconds
3. :cloud: It connects to iCloud and downloads today's new photos and videos
4. :arrows_counterclockwise: It checks for new photos every 2 minutes while connected
5. :x: **Unplug your iPhone** — sync stops automatically

### Manual sync

If you want to run a one-time sync without the watcher:

```bash
python iphone_sync.py
```

Press `Ctrl+C` to stop.

---

## :file_folder: Where things are stored

| What | Where |
|------|-------|
| :framed_picture: Synced photos & videos | Your configured `TARGET_DIR` |
| :key: iCloud session (cookies) | `%USERPROFILE%\.icloud_sync\` |
| :bust_in_silhouette: Apple ID (email only) | `%USERPROFILE%\.icloud_sync\config.json` |
| :page_facing_up: Sync state (filenames) | `TARGET_DIR\.iphone_sync_state.json` |
| :scroll: Watcher log | `%USERPROFILE%\.icloud_sync\watcher.log` |

:lock: **Nothing private is uploaded to GitHub.** The `.gitignore` excludes all credential and state files.

---

## :wrench: Troubleshooting

| Problem | Solution |
|---------|----------|
| "Session expired" message | Run `python iphone_sync.py` manually to re-authenticate |
| No photos syncing | Make sure iCloud Photos is enabled on your iPhone (Settings > Photos > iCloud Photos) |
| Watcher not starting | Check Task Scheduler > "iPhone Photo Sync Watcher" is enabled |
| Terminal window flashing | Make sure the scheduled task uses `pythonw.exe`, not `python.exe` |
| Duplicate files | Delete `TARGET_DIR\.iphone_sync_state.json` and re-run to rebuild the state |

### Check the watcher log

```bash
type %USERPROFILE%\.icloud_sync\watcher.log
```

---

## :wastebasket: Uninstall

1. Remove the scheduled task:
   ```powershell
   Unregister-ScheduledTask -TaskName "iPhone Photo Sync Watcher" -Confirm:$false
   ```

2. Delete the session cache:
   ```bash
   rmdir /s %USERPROFILE%\.icloud_sync
   ```

3. Delete the project folder.

---

## :balance_scale: License

MIT License. Free to use, modify, and share.

---

## :raised_hands: Credits

Built with [icloudpy](https://github.com/mandarons/icloudpy) and [pymobiledevice3](https://github.com/doronz88/pymobiledevice3).
