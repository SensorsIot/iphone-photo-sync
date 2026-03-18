"""
iPhone Sync Watcher
Runs silently in the background. Starts sync when iPhone is connected,
stops when disconnected. Uses .pyw extension to run without a console window.
"""

import subprocess
import time
import sys
import os
import logging
from pathlib import Path

import wmi

SYNC_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "iphone_sync.py")
LOG_FILE = os.path.join(str(Path.home()), ".icloud_sync", "watcher.log")
POLL_INTERVAL = 15  # seconds between USB checks

# Use pythonw.exe to avoid any console windows
PYTHONW = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
if not os.path.exists(PYTHONW):
    PYTHONW = sys.executable


def setup_logging():
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def is_iphone_connected():
    """Check if an iPhone is connected via USB using WMI (no subprocess/terminal)."""
    try:
        w = wmi.WMI()
        # Apple vendor ID is 05AC
        devices = w.query(
            "SELECT * FROM Win32_PnPEntity WHERE PNPDeviceID LIKE '%VID_05AC%' "
            "AND PNPClass = 'WPD' AND Status = 'OK'"
        )
        return len(devices) > 0
    except Exception:
        return False


def main():
    setup_logging()
    logging.info("iPhone Sync Watcher started")

    sync_process = None
    was_connected = False

    while True:
        try:
            connected = is_iphone_connected()

            if connected and not was_connected:
                # iPhone just connected
                logging.info("iPhone connected - starting sync")
                sync_process = subprocess.Popen(
                    [PYTHONW, SYNC_SCRIPT, "--background"],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                logging.info(f"Sync process started (PID {sync_process.pid})")

            elif not connected and was_connected:
                # iPhone just disconnected
                logging.info("iPhone disconnected - stopping sync")
                if sync_process and sync_process.poll() is None:
                    sync_process.terminate()
                    try:
                        sync_process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        sync_process.kill()
                    logging.info("Sync process stopped")
                sync_process = None

            # Check if sync process crashed and restart if phone still connected
            if connected and sync_process and sync_process.poll() is not None:
                logging.info(f"Sync process exited ({sync_process.returncode}), restarting...")
                sync_process = subprocess.Popen(
                    [PYTHONW, SYNC_SCRIPT, "--background"],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )

            was_connected = connected

        except Exception as e:
            logging.error(f"Error: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
