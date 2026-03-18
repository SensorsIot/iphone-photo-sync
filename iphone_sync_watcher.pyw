"""
iPhone Sync Watcher
Runs silently in the background. Listens for iPhone USB connect/disconnect
events and starts/stops sync accordingly. No polling needed.
Uses .pyw extension to run without a console window.
"""

import subprocess
import sys
import os
import logging
import threading
from pathlib import Path

import wmi

SYNC_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "iphone_sync.py")
LOG_FILE = os.path.join(str(Path.home()), ".icloud_sync", "watcher.log")

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
    """Check if an iPhone is currently connected."""
    try:
        w = wmi.WMI()
        devices = w.query(
            "SELECT * FROM Win32_PnPEntity WHERE PNPDeviceID LIKE '%VID_05AC%' "
            "AND PNPClass = 'WPD' AND Status = 'OK'"
        )
        return len(devices) > 0
    except Exception:
        return False


def start_sync():
    """Start the sync process."""
    return subprocess.Popen(
        [PYTHONW, SYNC_SCRIPT, "--background"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def stop_sync(proc):
    """Stop the sync process."""
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def main():
    setup_logging()
    logging.info("iPhone Sync Watcher started (event-driven)")

    sync_process = None

    # Check if iPhone is already connected at startup
    if is_iphone_connected():
        logging.info("iPhone already connected at startup - starting sync")
        sync_process = start_sync()
        logging.info(f"Sync process started (PID {sync_process.pid})")

    w = wmi.WMI()

    # Watch for USB device arrivals
    def watch_connections():
        nonlocal sync_process
        watcher = w.watch_for(
            notification_type="Creation",
            wmi_class="Win32_PnPEntity",
            delay_secs=2,
        )
        while True:
            try:
                event = watcher()
                device_id = getattr(event, "PNPDeviceID", "")
                if "VID_05AC" in device_id:
                    logging.info(f"Apple device connected: {device_id}")
                    # Small delay to let the device fully initialize
                    import time
                    time.sleep(3)
                    if is_iphone_connected() and (sync_process is None or sync_process.poll() is not None):
                        logging.info("iPhone connected - starting sync")
                        sync_process = start_sync()
                        logging.info(f"Sync process started (PID {sync_process.pid})")
            except Exception as e:
                logging.error(f"Connection watcher error: {e}")

    # Watch for USB device removals
    def watch_disconnections():
        nonlocal sync_process
        watcher = w.watch_for(
            notification_type="Deletion",
            wmi_class="Win32_PnPEntity",
            delay_secs=2,
        )
        while True:
            try:
                event = watcher()
                device_id = getattr(event, "PNPDeviceID", "")
                if "VID_05AC" in device_id:
                    logging.info(f"Apple device disconnected: {device_id}")
                    if not is_iphone_connected():
                        logging.info("iPhone disconnected - stopping sync")
                        stop_sync(sync_process)
                        sync_process = None
                        logging.info("Sync process stopped")
            except Exception as e:
                logging.error(f"Disconnection watcher error: {e}")

    t_connect = threading.Thread(target=watch_connections, daemon=True)
    t_disconnect = threading.Thread(target=watch_disconnections, daemon=True)
    t_connect.start()
    t_disconnect.start()

    # Keep main thread alive
    t_connect.join()


if __name__ == "__main__":
    main()
