"""
iPhone Photo & Video Sync Tool
Continuously syncs today's photos and videos from iPhone via USB.
Uses pymobiledevice3 (Apple AFC protocol) - no iCloud login needed.
Polls every 2 minutes for new photos.
"""

import asyncio
import os
import sys
import json
import struct
import time
from datetime import datetime, date, timedelta
from pathlib import Path

from PIL import Image
from PIL.ExifTags import Base as ExifBase
import pywintypes
import win32file
import win32con

from pymobiledevice3.usbmux import select_devices_by_connection_type
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.afc import AfcService

# Target directory
TARGET_DIR = r"D:\Dropbox\! Youtube"
# State file to track synced files
STATE_FILE = os.path.join(TARGET_DIR, ".iphone_sync_state.json")
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


def set_file_dates_from_metadata(filepath):
    """Read EXIF (photos) or MP4/MOV atom (videos) and set file timestamps."""
    dt = None
    ext = os.path.splitext(filepath)[1].lower()

    # Photos: read EXIF
    if ext in (".jpg", ".jpeg", ".heic", ".png", ".tif", ".tiff"):
        try:
            img = Image.open(filepath)
            exif = img.getexif()
            for tag in [36867, 36868, 306]:  # DateTimeOriginal, DateTimeDigitized, DateTime
                val = exif.get(tag)
                if val:
                    dt = datetime.strptime(val, "%Y:%m:%d %H:%M:%S")
                    break
        except Exception:
            pass

    # Videos: read mvhd atom
    elif ext in (".mov", ".mp4", ".m4v"):
        try:
            with open(filepath, "rb") as f:
                while True:
                    pos = f.tell()
                    header = f.read(8)
                    if len(header) < 8:
                        break
                    size = struct.unpack(">I", header[:4])[0]
                    box_type = header[4:8]
                    if size == 0:
                        break
                    if size == 1:
                        f.read(8)
                        size = struct.unpack(">Q", f.read(8))[0]
                    if box_type == b"moov":
                        moov_end = pos + size
                        while f.tell() < moov_end:
                            ipos = f.tell()
                            ih = f.read(8)
                            if len(ih) < 8:
                                break
                            isize = struct.unpack(">I", ih[:4])[0]
                            if ih[4:8] == b"mvhd":
                                version = struct.unpack(">B", f.read(1))[0]
                                f.read(3)
                                ct = struct.unpack(">I" if version == 0 else ">Q", f.read(4 if version == 0 else 8))[0]
                                if ct > 0:
                                    dt = datetime(1904, 1, 1) + timedelta(seconds=ct)
                                break
                            else:
                                if isize <= 8:
                                    break
                                f.seek(ipos + isize)
                        break
                    else:
                        f.seek(pos + size)
        except Exception:
            pass

    if dt and dt.year >= 2000:
        try:
            ts = pywintypes.Time(dt)
            handle = win32file.CreateFile(
                filepath, win32con.GENERIC_WRITE,
                win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                None, win32con.OPEN_EXISTING,
                win32con.FILE_ATTRIBUTE_NORMAL, None,
            )
            win32file.SetFileTime(handle, ts, ts, ts)
            handle.Close()
        except Exception:
            try:
                os.utime(filepath, (dt.timestamp(), dt.timestamp()))
            except Exception:
                pass


def set_file_dates_from_stat(filepath, file_date):
    """Set file timestamps from AFC stat date."""
    try:
        ts = pywintypes.Time(file_date)
        handle = win32file.CreateFile(
            filepath, win32con.GENERIC_WRITE,
            win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
            None, win32con.OPEN_EXISTING,
            win32con.FILE_ATTRIBUTE_NORMAL, None,
        )
        win32file.SetFileTime(handle, ts, ts, ts)
        handle.Close()
    except Exception:
        try:
            os.utime(filepath, (file_date.timestamp(), file_date.timestamp()))
        except Exception:
            pass


async def connect_iphone():
    """Connect to iPhone via USB."""
    devices = await select_devices_by_connection_type(connection_type="USB")
    if not devices:
        return None, None
    lockdown = await create_using_usbmux(serial=devices[0].serial)
    afc = AfcService(lockdown)
    return lockdown, afc


async def sync_once(afc, state):
    """Run one sync pass via USB. Returns (new_files, errors, bytes)."""
    today = date.today()
    synced = state["synced_files"]
    os.makedirs(TARGET_DIR, exist_ok=True)

    total_new = 0
    total_errors = 0
    total_bytes = 0

    all_entries = await afc.listdir("/DCIM")
    folders = sorted([f for f in all_entries if "APPLE" in f or (f[0].isdigit() and "_" in f)])

    for folder in folders:
        folder_path = f"/DCIM/{folder}"
        try:
            files = await afc.listdir(folder_path)
        except Exception:
            total_errors += 1
            continue

        media_files = sorted([
            f for f in files
            if not f.startswith(".") and os.path.splitext(f)[1].lower() in MEDIA_EXTENSIONS
        ])

        for filename in media_files:
            remote_path = f"{folder_path}/{filename}"
            sync_key = f"{folder}/{filename}"

            if sync_key in synced:
                continue

            # Get file date from iPhone
            try:
                st = await afc.stat(remote_path)
                mtime = st.get("st_mtime", st.get("st_birthtime"))
                if isinstance(mtime, datetime):
                    file_date = mtime
                else:
                    continue
            except Exception:
                continue

            # Only sync today's files
            if file_date.date() != today:
                continue

            # Target path
            local_path = os.path.join(TARGET_DIR, filename)

            # Skip if already exists with same size
            try:
                remote_size = st.get("st_size", 0)
                if isinstance(remote_size, int) and remote_size > 0 and os.path.exists(local_path):
                    if os.path.getsize(local_path) == remote_size:
                        synced[sync_key] = {"size": remote_size, "date": file_date.isoformat(), "synced_at": datetime.now().isoformat()}
                        continue
            except Exception:
                pass

            if os.path.exists(local_path):
                base, ext_str = os.path.splitext(filename)
                counter = 1
                while os.path.exists(local_path):
                    local_path = os.path.join(TARGET_DIR, f"{base}_{counter}{ext_str}")
                    counter += 1

            # Download via USB
            try:
                data = await afc.get_file_contents(remote_path)
                with open(local_path, "wb") as f:
                    f.write(data)

                file_size = len(data)

                # Set timestamps from metadata (EXIF/MP4), fallback to AFC stat
                set_file_dates_from_metadata(local_path)
                # Verify dates were set, fallback to stat date
                local_mtime = datetime.fromtimestamp(os.path.getmtime(local_path))
                if abs((local_mtime - datetime.now()).total_seconds()) < 60:
                    # Dates weren't set from metadata, use stat date
                    set_file_dates_from_stat(local_path, file_date)

                total_bytes += file_size
                total_new += 1
                synced[sync_key] = {
                    "size": file_size,
                    "date": file_date.isoformat(),
                    "synced_at": datetime.now().isoformat(),
                }
                size_mb = file_size / (1024 * 1024)
                print(f"  [{total_new}] {filename} ({size_mb:.1f} MB)")

                if total_new % 10 == 0:
                    save_state(state)

            except Exception as e:
                print(f"  ERROR {filename}: {e}")
                total_errors += 1

    save_state(state)
    return total_new, total_errors, total_bytes


async def main():
    print("iPhone Photo & Video Sync (USB)")
    print("=" * 50)
    print(f"Target:   {TARGET_DIR}")
    print(f"Interval: every {POLL_INTERVAL}s\n")

    state = load_state()
    run = 1

    while True:
        now = datetime.now().strftime("%H:%M:%S")
        today = date.today()
        print(f"[{now}] Sync #{run} - checking for new photos from {today}...")

        try:
            lockdown, afc = await connect_iphone()
            if afc is None:
                print(f"[{now}] iPhone not connected")
            else:
                print(f"[{now}] Connected to {lockdown.display_name}")
                new_files, errors, new_bytes = await sync_once(afc, state)
                if new_files > 0:
                    mb = new_bytes / (1024 * 1024)
                    print(f"[{now}] Synced {new_files} new file(s) ({mb:.1f} MB)")
                else:
                    print(f"[{now}] No new files")
                if errors > 0:
                    print(f"[{now}] {errors} error(s)")
        except Exception as e:
            print(f"[{now}] Error: {e}")

        run += 1
        print(f"  Next check in {POLL_INTERVAL}s (Ctrl+C to stop)\n")
        try:
            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            print("\nStopped by user.")
            break


if __name__ == "__main__":
    asyncio.run(main())
