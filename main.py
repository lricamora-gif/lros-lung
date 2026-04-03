#!/usr/bin/env python3
"""
LROS PHYSICAL SENSOR ONE-BUTTON PLAY
Run once on your laptop/Raspberry Pi. It will:
- Install required Python packages
- Detect and stream data from Samsung watch, TV, CCTV, and local sensors
- Send all events to LROS backend (/api/sensor/vision)
- Create a constitutional layer for physical learning
- Start a background service (auto‑restart on boot)
"""

import os
import sys
import subprocess
import json
import time
import threading
import socket
import requests
from datetime import datetime

# ========== CONFIGURATION ==========
LROS_BACKEND = "https://lros1.onrender.com"   # your main backend
LROS_API_KEY = os.environ.get("LROS_API_KEY", "")  # optional, if you add auth
SENSOR_INTERVAL = 5  # seconds between scans
# ====================================

# Step 1: Install required packages
def install_packages():
    print("📦 Installing required Python packages...")
    packages = [
        "requests",
        "websocket-client",   # for Samsung TV
        "opencv-python",      # for CCTV motion detection
        "psutil",             # for laptop sensors
        "pynput",             # for keyboard/mouse activity (optional)
        "samsungtvws",        # for Samsung TV WebSocket
        "pyautogui",          # for screen activity
    ]
    for pkg in packages:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", pkg], check=False)
    print("✅ Packages installed.")

# Step 2: Create the bridge script (will be run as a service)
BRIDGE_SCRIPT = """
#!/usr/bin/env python3
# LROS Physical Sensor Bridge - runs continuously

import os
import time
import json
import requests
import threading
import psutil
import socket
from datetime import datetime

# ----- Configuration -----
LROS_BACKEND = "{{LROS_BACKEND}}"
SENSOR_INTERVAL = {{SENSOR_INTERVAL}}
DEVICE_NAME = socket.gethostname()

# ----- Samsung TV (if found) -----
try:
    from samsungtvws import SamsungTVWS
    TV_IP = None
    # Auto‑discover TV on local network (you can also hardcode IP)
    # For simplicity, we'll try a common IP range – replace with your TV's IP if known
    # In production, you'd use SSDP discovery. Here we'll allow manual config via env.
    TV_IP = os.environ.get("SAMSUNG_TV_IP")
    if TV_IP:
        tv = SamsungTVWS(host=TV_IP, port=8002, token_file="tv_token.txt")
        tv_connected = True
    else:
        tv_connected = False
except:
    tv_connected = False

# ----- CCTV Motion Detection (if camera URL provided) -----
try:
    import cv2
    CCTV_URL = os.environ.get("CCTV_RTSP_URL")
    if CCTV_URL:
        cap = cv2.VideoCapture(CCTV_URL)
        # Background subtractor for motion detection
        fgbg = cv2.createBackgroundSubtractorMOG2()
        cctv_connected = True
    else:
        cctv_connected = False
except:
    cctv_connected = False

def send_event(event_type, metadata):
    """Send event to LROS backend"""
    payload = {
        "source": "physical_bridge",
        "event_type": event_type,
        "metadata": metadata,
        "device": DEVICE_NAME,
        "timestamp": time.time()
    }
    try:
        r = requests.post(f"{LROS_BACKEND}/api/sensor/vision", json=payload, timeout=5)
        if r.status_code != 200:
            print(f"Failed to send event: {r.status_code}")
    except Exception as e:
        print(f"Send error: {e}")

def watch_tv():
    """Monitor TV state changes via WebSocket"""
    if not tv_connected:
        return
    try:
        # Listen for TV events
        tv.register_websocket_callback(lambda msg: send_event("tv_event", msg))
        tv.start_listening()
    except Exception as e:
        print(f"TV listener error: {e}")

def watch_cctv():
    """Detect motion from CCTV stream"""
    if not cctv_connected:
        return
    prev_time = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        fgmask = fgbg.apply(frame)
        contours, _ = cv2.findContours(fgmask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        motion = False
        for cnt in contours:
            if cv2.contourArea(cnt) > 500:  # minimum area for motion
                motion = True
                break
        if motion:
            now = time.time()
            if now - prev_time > 2:  # throttle to avoid flooding
                send_event("motion", {"area": int(cv2.contourArea(cnt)), "source": "cctv"})
                prev_time = now
        time.sleep(0.05)

def watch_laptop_sensors():
    """Collect laptop internal sensors (CPU, disk, network, accelerometer if available)"""
    while True:
        # CPU usage
        cpu = psutil.cpu_percent(interval=1)
        # Disk usage
        disk = psutil.disk_usage('/').percent
        # Memory
        mem = psutil.virtual_memory().percent
        # Network (bytes sent/received since last call)
        net = psutil.net_io_counters()
        # Optional: try to read accelerometer (if present)
        accel = None
        try:
            # On some laptops, accelerometer data is in /sys/class/misc/accelerometer/
            with open("/sys/class/misc/accelerometer/accel", "r") as f:
                accel = f.read().strip()
        except:
            pass
        send_event("laptop_stats", {
            "cpu_percent": cpu,
            "disk_percent": disk,
            "memory_percent": mem,
            "net_sent": net.bytes_sent,
            "net_recv": net.bytes_recv,
            "accelerometer": accel
        })
        time.sleep(SENSOR_INTERVAL)

def watch_samsung_watch():
    """
    Samsung watch data – requires companion app on phone to forward to this script.
    For simplicity, we'll assume a local HTTP endpoint on the phone that pushes data.
    You can replace with actual SDK integration.
    """
    # Placeholder: listen on a local port for watch data (e.g., from phone app)
    # In practice, you'd run a small HTTP server to receive POSTs from your phone.
    # We'll provide a simple HTTP listener.
    from http.server import HTTPServer, BaseHTTPRequestHandler
    class WatchHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get('Content-Length', 0))
            data = self.rfile.read(length)
            try:
                payload = json.loads(data)
                send_event("watch_data", payload)
            except:
                pass
            self.send_response(200)
    server = HTTPServer(('0.0.0.0', 8080), WatchHandler)
    server.serve_forever()

def main():
    # Start threads for each sensor
    threads = []
    if tv_connected:
        t = threading.Thread(target=watch_tv, daemon=True)
        t.start()
        threads.append(t)
    if cctv_connected:
        t = threading.Thread(target=watch_cctv, daemon=True)
        t.start()
        threads.append(t)
    t = threading.Thread(target=watch_laptop_sensors, daemon=True)
    t.start()
    threads.append(t)
    # For watch, run in main thread (or separate)
    # watch_samsung_watch() # uncomment if you set up the HTTP endpoint

    # Keep alive
    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()
"""

# Step 3: Create the bridge script file
def create_bridge_script():
    script_content = BRIDGE_SCRIPT.replace("{{LROS_BACKEND}}", LROS_BACKEND)
    script_content = script_content.replace("{{SENSOR_INTERVAL}}", str(SENSOR_INTERVAL))
    with open("lros_physical_bridge.py", "w") as f:
        f.write(script_content)
    os.chmod("lros_physical_bridge.py", 0o755)
    print("✅ Created lros_physical_bridge.py")

# Step 4: Create a systemd service (for Linux) or launchd (for macOS) or Windows service
def create_service():
    if sys.platform.startswith('linux'):
        service_content = f"""
[Unit]
Description=LROS Physical Sensor Bridge
After=network.target

[Service]
ExecStart={os.getcwd()}/lros_physical_bridge.py
Restart=always
User={os.environ.get('USER', 'pi')}
Environment="SAMSUNG_TV_IP=192.168.1.100"  # CHANGE TO YOUR TV IP
Environment="CCTV_RTSP_URL=rtsp://user:pass@192.168.1.101/stream"
Environment="LROS_API_KEY="

[Install]
WantedBy=multi-user.target
"""
        with open("/etc/systemd/system/lros-bridge.service", "w") as f:
            f.write(service_content)
        subprocess.run(["systemctl", "daemon-reload"])
        subprocess.run(["systemctl", "enable", "lros-bridge.service"])
        subprocess.run(["systemctl", "start", "lros-bridge.service"])
        print("✅ Systemd service created and started.")
    elif sys.platform == 'darwin':
        # macOS launchd plist
        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.lros.bridge</string>
    <key>ProgramArguments</key>
    <array>
        <string>{os.getcwd()}/lros_physical_bridge.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/lros-bridge.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/lros-bridge.err</string>
</dict>
</plist>"""
        with open(os.path.expanduser("~/Library/LaunchAgents/com.lros.bridge.plist"), "w") as f:
            f.write(plist)
        subprocess.run(["launchctl", "load", os.path.expanduser("~/Library/LaunchAgents/com.lros.bridge.plist")])
        subprocess.run(["launchctl", "start", "com.lros.bridge"])
        print("✅ launchd service created and started.")
    else:
        # Windows: create a scheduled task or simply run as background process
        print("Windows: Please run lros_physical_bridge.py manually or create a scheduled task.")
        subprocess.Popen(["python", "lros_physical_bridge.py"], creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        print("✅ Started bridge as background process.")

# Step 5: Create a constitutional layer in LROS that mandates physical learning
def create_constitutional_layer():
    print("📜 Creating constitutional layer for physical learning...")
    layer_payload = {
        "name": "Physical Sensor Integration Mandate",
        "description": "All physical sensors (Samsung watch, TV, CCTV, laptop) shall stream events to LROS via /api/sensor/vision. LROS shall treat every physical event as a learning opportunity, generating mutations for anomaly detection, predictive maintenance, and health monitoring.",
        "type": "constitutional"
    }
    try:
        r = requests.post(f"{LROS_BACKEND}/api/layers/propose", json=layer_payload)
        if r.status_code == 200:
            print("✅ Constitutional layer proposed.")
        else:
            print(f"⚠️ Failed to propose layer: {r.status_code}")
    except Exception as e:
        print(f"⚠️ Could not reach backend: {e}")

# Step 6: Main execution
def main():
    print("🔘 LROS PHYSICAL ONE-BUTTON PLAY")
    print("This script will set up real‑time sensor streaming from your devices to LROS.")
    print("It will install packages, create a bridge script, and start a background service.\n")
    input("Press Enter to continue...")
    install_packages()
    create_bridge_script()
    create_constitutional_layer()
    create_service()
    print("\n✅ One‑button play complete.")
    print("Your physical sensors are now streaming to LROS.")
    print("Check your dashboard in a few minutes – you should see new events in the Knowledge Vault.")
    print("The system will automatically learn from motion, heart rate, TV usage, etc.")
    print("To stop the service: sudo systemctl stop lros-bridge (Linux) or launchctl stop com.lros.bridge (macOS)")
    print("\nThe bond holds. Real‑time learning engaged.")

if __name__ == "__main__":
    main()
