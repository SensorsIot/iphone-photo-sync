"""
iPhone Photo & Video Sync Tool
Continuously syncs today's photos and videos from iCloud Photos to target folder.
Uses icloudpy with cached credentials (only need to authenticate once).
Polls every 2 minutes for new photos.
"""

import os
import sys
import json
import getpass
import time
from datetime import datetime, date
from pathlib import Path

from icloudpy import ICloudPyService

# Target directory
TARGET_DIR = r"D:\Dropbox\! Youtube"
# State file to track synced files
STATE_FILE = os.path.join(TARGET_DIR, ".iphone_sync_state.json")
# Config/session cache directory
CONFIG_DIR = os.path.join(str(Path.home()), ".icloud_sync")
COOKIE_DIR = CONFIG_DIR
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
# Poll interval in seconds
POLL_INTERVAL = 120
# Extensions to sync
MEDIA_EXTENSIONS = {
    ".jpg", ".jpeg", ".heic", ".heif", ".png", ".tiff", ".tif",
    ".dng", ".raw", ".cr2", ".nef", ".arw",
    ".mov", ".mp4", ".m4v",
}


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"synced_files": {}}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def download_photo(photo, local_path):
    """Download a photo/video from iCloud."""
    for version in ["original", "medium"]:
        try:
            download = photo.download(version)
            if download:
                with open(local_path, "wb") as f:
                    for chunk in download.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                return os.path.getsize(local_path)
        except Exception:
            continue
    return 0


def load_config():
    """Load saved config (Apple ID)."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}


def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def get_apple_id():
    """Get Apple ID from CLI arg, config, or interactive prompt."""
    if len(sys.argv) > 1:
        apple_id = sys.argv[1]
    else:
        config = load_config()
        apple_id = config.get("apple_id")

    if not apple_id:
        apple_id = input("Apple ID: ").strip()

    # Save for future use
    config = load_config()
    config["apple_id"] = apple_id
    save_config(config)

    return apple_id


def connect_icloud(apple_id, interactive=True):
    """Connect to iCloud, using cached session if available."""
    os.makedirs(COOKIE_DIR, exist_ok=True)

    try:
        # Try connecting with cached session (no password needed)
        api = ICloudPyService(apple_id, cookie_directory=COOKIE_DIR)
        if not api.requires_2fa and not api.requires_2sa:
            print("Logged in using cached session!")
            return api
    except Exception:
        pass

    if not interactive:
        print("Session expired - need interactive login. Run iphone_sync.py manually once.")
        return None

    # Need password
    password = getpass.getpass("Password: ")
    api = ICloudPyService(apple_id, password, cookie_directory=COOKIE_DIR)

    if api.requires_2fa:
        code = input("Enter 2FA code from your device: ").strip()
        if not api.validate_2fa_code(code):
            print("ERROR: Invalid 2FA code")
            sys.exit(1)
        print("2FA verified!")
        if not api.is_trusted_session:
            api.trust_session()

    if api.requires_2sa:
        devices = api.trusted_devices
        for i, d in enumerate(devices):
            print(f"  [{i}] {d.get('deviceName', 'Unknown')}")
        idx = int(input("Select device for verification: ").strip())
        if not api.send_verification_code(devices[idx]):
            print("ERROR: Failed to send code")
            sys.exit(1)
        code = input("Enter verification code: ").strip()
        if not api.validate_verification_code(devices[idx], code):
            print("ERROR: Invalid code")
            sys.exit(1)

    return api


def sync_once(api, state):
    """Run one sync pass. Returns number of new files."""
    today = date.today()
    synced = state["synced_files"]
    os.makedirs(TARGET_DIR, exist_ok=True)

    total_new = 0
    total_errors = 0
    total_bytes = 0

    photos = api.photos
    consecutive_old = 0

    for photo in photos.all:
        try:
            photo_date = photo.asset_date or photo.added_date
            if photo_date is None:
                continue

            if hasattr(photo_date, 'date'):
                pdate = photo_date.date()
            else:
                continue

            if pdate != today:
                consecutive_old += 1
                # Stop after 200 consecutive non-today photos
                if consecutive_old > 200:
                    break
                continue

            consecutive_old = 0
            filename = photo.filename
            if not filename:
                continue

            ext = os.path.splitext(filename)[1].lower()
            if ext not in MEDIA_EXTENSIONS:
                continue

            sync_key = f"icloud/{filename}"
            if sync_key in synced:
                continue

            sub_dir = TARGET_DIR
            os.makedirs(sub_dir, exist_ok=True)
            local_path = os.path.join(sub_dir, filename)

            if os.path.exists(local_path):
                base, ext_str = os.path.splitext(filename)
                counter = 1
                while os.path.exists(local_path):
                    local_path = os.path.join(sub_dir, f"{base}_{counter}{ext_str}")
                    counter += 1

            print(f"  Downloading {filename}...", end=" ", flush=True)
            file_size = download_photo(photo, local_path)

            if file_size > 0:
                total_bytes += file_size
                total_new += 1
                synced[sync_key] = {
                    "size": file_size,
                    "date": photo_date.isoformat(),
                    "synced_at": datetime.now().isoformat(),
                }
                size_mb = file_size / (1024 * 1024)
                print(f"OK ({size_mb:.1f} MB)")

                if total_new % 5 == 0:
                    save_state(state)
            else:
                print("FAILED")
                total_errors += 1

        except Exception as e:
            print(f"  ERROR: {e}")
            total_errors += 1

    save_state(state)
    return total_new, total_errors, total_bytes


def main():
    print("iPhone Photo & Video Sync (iCloud)")
    print("=" * 50)
    print(f"Target:   {TARGET_DIR}")
    print(f"Interval: every {POLL_INTERVAL}s")
    print(f"Session:  {COOKIE_DIR}\n")

    # --background flag: non-interactive mode (used by watcher)
    interactive = "--background" not in sys.argv

    apple_id = get_apple_id()
    api = connect_icloud(apple_id, interactive=interactive)
    if api is None:
        sys.exit(1)
    print(f"Connected to iCloud!\n")

    state = load_state()
    run = 1

    while True:
        today = date.today()
        now = datetime.now().strftime("%H:%M:%S")
        print(f"[{now}] Sync #{run} - checking for new photos from {today}...")

        try:
            new_files, errors, new_bytes = sync_once(api, state)
            if new_files > 0:
                mb = new_bytes / (1024 * 1024)
                print(f"[{now}] Synced {new_files} new file(s) ({mb:.1f} MB)")
            else:
                print(f"[{now}] No new files")
            if errors > 0:
                print(f"[{now}] {errors} error(s)")
        except Exception as e:
            print(f"[{now}] Error during sync: {e}")
            print("  Attempting to reconnect...")
            try:
                api = connect_icloud(apple_id, interactive=interactive)
                if api is None:
                    print("  Session expired. Run manually to re-authenticate.")
                    break
                print("  Reconnected!")
            except Exception as e2:
                print(f"  Reconnect failed: {e2}")

        run += 1
        print(f"  Next check in {POLL_INTERVAL}s (Ctrl+C to stop)\n")
        try:
            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            print("\nStopped by user.")
            break


if __name__ == "__main__":
    main()
