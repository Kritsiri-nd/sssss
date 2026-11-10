"""Shopee Video Automation Web Dashboard & Server.
Provides a local web interface to manage, monitor, and execute Shopee Video uploads.
"""
import http.server
import subprocess
import json
import re
import os
import sys
import time
import threading
import urllib.parse
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.resolve()
LOG_FILE = BASE_DIR / "shopee_web_server.log"
if sys.stdout is None or not hasattr(sys.stdout, "write"):
    sys.stdout = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
if sys.stderr is None or not hasattr(sys.stderr, "write"):
    sys.stderr = open(LOG_FILE, "a", encoding="utf-8", buffering=1)

PREPARE_SCRIPT = BASE_DIR / "shopee_prepare.py"
TOUCH_SCRIPT = BASE_DIR / "shopee_touch.py"
SCRCPY_EXE = BASE_DIR / "scrcpy-5.0.1" / "scrcpy-win64-v5.0.1" / "scrcpy.exe"
PROGRESS_FILE = BASE_DIR / "batch_progress.json"
REVIEW_DIR = BASE_DIR / "reviews"
REVIEW_DIR.mkdir(parents=True, exist_ok=True)

PYTHON_EXE = str(Path(sys.executable).with_name("pythonw.exe"))
if not Path(PYTHON_EXE).exists():
    PYTHON_EXE = sys.executable
BUNDLED_ADB = BASE_DIR / "scrcpy-5.0.1" / "scrcpy-win64-v5.0.1" / "adb.exe"
if BUNDLED_ADB.exists():
    ADB_PATH = str(BUNDLED_ADB)
elif Path(r"C:\Users\krits\.gemini\antigravity\scratch\platform-tools\adb.exe").exists():
    ADB_PATH = r"C:\Users\krits\.gemini\antigravity\scratch\platform-tools\adb.exe"
else:
    ADB_PATH = "adb"
os.environ["ADB"] = str(ADB_PATH)

# Auto-detect queue directory
if Path(r"D:\shopee-post").exists():
    DEFAULT_QUEUE_DIR = r"D:\shopee-post"
elif (Path.home() / "OneDrive" / "Desktop" / "shopee-post").exists():
    DEFAULT_QUEUE_DIR = str(Path.home() / "OneDrive" / "Desktop" / "shopee-post")
elif (Path.home() / "Desktop" / "shopee-post").exists():
    DEFAULT_QUEUE_DIR = str(Path.home() / "Desktop" / "shopee-post")
else:
    DEFAULT_QUEUE_DIR = r"D:\shopee-post"
PORT = 8090
FLAGS_NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0x08000000

# Global State
worker_thread = None
worker_stop_event = threading.Event()
worker_lock = threading.Lock()

worker_state = {
    "is_running": False,
    "current_item": None,
    "current_index": 0,
    "total_items": 0,
    "percent": 0,
    "status_message": "พร้อมทำงาน (Idle)",
    "queue_dir": DEFAULT_QUEUE_DIR,
    "delay_minutes": 0,
    "countdown_seconds": 0,
    "logs": []
}

# Live Screenshot Cache State
latest_screenshot_lock = threading.Lock()
latest_screenshot_bytes = b""
last_screenshot_request_time = 0

# Video Generator Jobs State
video_jobs = {}
video_jobs_lock = threading.Lock()

def log_message(msg):
    timestamp = time.strftime("%H:%M:%S")
    entry = f"[{timestamp}] {msg}"
    print(entry, flush=True)
    with worker_lock:
        worker_state["logs"].append(entry)
        if len(worker_state["logs"]) > 300:
            worker_state["logs"].pop(0)

def calc_real_percentage(voltage_mv):
    curve = [
        (4400, 100), (4350, 95), (4250, 85), (4150, 75),
        (4050, 65), (3950, 52), (3850, 42), (3780, 28),
        (3700, 18), (3600, 8), (3400, 0)
    ]
    if voltage_mv >= 4400:
        return 100
    if voltage_mv <= 3400:
        return 0
    for i in range(len(curve) - 1):
        v_high, p_high = curve[i]
        v_low, p_low = curve[i+1]
        if v_low <= voltage_mv <= v_high:
            ratio = (voltage_mv - v_low) / (v_high - v_low)
            return round(p_low + ratio * (p_high - p_low), 1)
    return 50.0

def get_device_info():
    info = {
        "connected": False,
        "device_id": "",
        "battery_pct": 0,
        "voltage_v": 0.0,
        "screen_ready": False,
        "screen_status": "ไม่ได้เชื่อมต่อ"
    }
    try:
        res = subprocess.run([ADB_PATH, "devices"], capture_output=True, text=True, timeout=5, creationflags=FLAGS_NO_WINDOW)
        lines = [l.strip() for l in res.stdout.splitlines() if l.strip() and not l.startswith("List of")]
        connected_devs = [l.split()[0] for l in lines if "\tdevice" in l]
        if not connected_devs:
            return info
        info["connected"] = True
        info["device_id"] = connected_devs[0]

        # Battery & Voltage
        bat_res = subprocess.run([ADB_PATH, "-s", info["device_id"], "shell", "dumpsys", "battery"],
                                 capture_output=True, text=True, timeout=5, creationflags=FLAGS_NO_WINDOW)
        m_volt = re.search(r"voltage:\s*(\d+)", bat_res.stdout)
        if m_volt:
            v_mv = int(m_volt.group(1))
            info["voltage_v"] = round(v_mv / 1000.0, 3)
            info["battery_pct"] = calc_real_percentage(v_mv)

        # Quick check for Shopee Live & Video screen
        focus_res = subprocess.run([ADB_PATH, "-s", info["device_id"], "shell", "dumpsys", "window", "displays"],
                                   capture_output=True, text=True, timeout=5, creationflags=FLAGS_NO_WINDOW)
        if "ShopeeLiveVideoPlayerActivity" in focus_res.stdout or "shopee" in focus_res.stdout.lower():
            info["screen_ready"] = True
            info["screen_status"] = "พร้อมสำหรับการโพสต์"
        else:
            info["screen_ready"] = False
            info["screen_status"] = "หน้าจอแอปอื่น"
    except Exception as e:
        info["screen_status"] = str(e)
    return info

def load_progress():
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"completed": [], "failed": {}}

def save_progress(progress):
    try:
        PROGRESS_FILE.write_text(json.dumps(progress, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"Error saving progress: {e}")

def scan_queue(queue_dir_str):
    queue_path = Path(queue_dir_str)
    if not queue_path.exists():
        return []
    
    subdirs = sorted([d for d in queue_path.iterdir() if d.is_dir()])
    progress = load_progress()
    items = []

    for idx, d in enumerate(subdirs, 1):
        if d.name.startswith("_") or d.name.startswith("."):
            continue # Skip templates and hidden folders
        video_files = list(d.glob("*.mp4"))
        notes_file = d / "product_notes.json"
        if not notes_file.exists():
            notes_file = d / "notes.json"
        
        has_video = len(video_files) > 0
        has_notes = notes_file.exists() or (d / "notes.txt").exists()
        
        img_files = list(d.glob("*.jpg")) + list(d.glob("*.png")) + list(d.glob("*.jpeg"))
        image_count = len(img_files)

        title = d.name
        url = ""
        caption = ""
        if notes_file.exists():
            try:
                data = json.loads(notes_file.read_text(encoding="utf-8-sig"))
                title = data.get("title", d.name)
                url = data.get("shopee_url", "")
                caps = data.get("captions", [])
                caption = caps[0] if caps else ""
            except Exception:
                pass
        elif (d / "notes.txt").exists():
            try:
                lines = (d / "notes.txt").read_text(encoding="utf-8-sig").splitlines()
                url = lines[0].strip() if len(lines) > 0 else ""
                caption = lines[1].strip() if len(lines) > 1 else ""
            except Exception:
                pass

        if d.name in progress.get("completed", []):
            status = "completed"
        elif not has_video:
            status = "no_video"
        elif d.name in progress.get("failed", {}):
            status = "failed"
        else:
            status = "pending"

        items.append({
            "index": idx,
            "folder_name": d.name,
            "title": title,
            "url": url,
            "caption": caption,
            "has_video": has_video,
            "image_count": image_count,
            "video_name": video_files[0].name if video_files else "",
            "status": status,
            "review_image_exists": (REVIEW_DIR / f"{idx:02d}_{d.name}.png").exists() or (REVIEW_DIR / f"{d.name}.png").exists()
        })
    return items

def reset_to_live_and_video():
    """
    Bulletproof reset to ensure Shopee is 100% on the Live & Video feed:
    1. If any sub-activity (editor, review, search, product, camera) is detected, force-restart Shopee.
    2. If top is HomeActivity, tap Live & Video tab (0.582, 0.920).
    3. If already clean on ReactActivity / ReactTransparentActivity, dismiss any soft keyboard.
    4. Otherwise, clean restart Shopee.
    """
    try:
        activities = subprocess.check_output(
            [ADB_PATH, "shell", "dumpsys", "activity", "activities"],
            timeout=5, creationflags=FLAGS_NO_WINDOW
        ).decode(errors="replace")
        
        sub_activities = [
            "PublishVideoActivity",
            "SSZMultipleEditActivity",
            "SSZBasePreviewActivity",
            "SSZMediaActivity"
        ]
        has_sub_activity = any(act in activities for act in sub_activities)
        top_line = next((line for line in activities.splitlines() if "topResumedActivity" in line), "")
        
        # Only clean if no sub-activities and top is Home or React with minimal activity stack
        if not has_sub_activity and ("ReactActivity" in top_line or "ReactTransparentActivity" in top_line) and activities.count("ActivityRecord{") <= 3:
            # Dismiss any keyboard
            subprocess.run([PYTHON_EXE, str(TOUCH_SCRIPT), "0.766", "0.977"], timeout=8, capture_output=True, creationflags=FLAGS_NO_WINDOW)
            time.sleep(0.5)
            res = subprocess.run([PYTHON_EXE, str(PREPARE_SCRIPT), "--phone-status"],
                                 capture_output=True, text=True, timeout=12, encoding="utf-8", creationflags=FLAGS_NO_WINDOW)
            if "Shopee Live & Video is ready" in res.stdout:
                return True

        if not has_sub_activity and "HomeActivity" in top_line:
            subprocess.run([PYTHON_EXE, str(TOUCH_SCRIPT), "0.582", "0.920"], timeout=8, capture_output=True, creationflags=FLAGS_NO_WINDOW)
            time.sleep(1.5)
            res = subprocess.run([PYTHON_EXE, str(PREPARE_SCRIPT), "--phone-status"],
                                 capture_output=True, text=True, timeout=12, encoding="utf-8", creationflags=FLAGS_NO_WINDOW)
            if "Shopee Live & Video is ready" in res.stdout:
                return True

        # Any sub-activity, stacked activities, or unfamiliar screen: CLEAN RESTART
        log_message("🔄 เคลียร์หน้าจอ: รีสตาร์ต Shopee กลับมาที่หน้า Live & Video...")
        subprocess.run([ADB_PATH, "shell", "am", "force-stop", "com.shopee.th"],
                       timeout=5, capture_output=True, creationflags=FLAGS_NO_WINDOW)
        time.sleep(0.8)
        subprocess.run([ADB_PATH, "shell", "monkey", "-p", "com.shopee.th", "-c", "android.intent.category.LAUNCHER", "1"],
                       timeout=5, capture_output=True, creationflags=FLAGS_NO_WINDOW)
        time.sleep(3.5)
        
        # Switch to Live & Video tab
        subprocess.run([PYTHON_EXE, str(TOUCH_SCRIPT), "0.582", "0.920"], timeout=8, capture_output=True, creationflags=FLAGS_NO_WINDOW)
        time.sleep(1.5)
        
        res = subprocess.run([PYTHON_EXE, str(PREPARE_SCRIPT), "--phone-status"],
                             capture_output=True, text=True, timeout=15, encoding="utf-8", creationflags=FLAGS_NO_WINDOW)
        if "Shopee Live & Video is ready" in res.stdout:
            log_message("✅ รีสตาร์ต Shopee กลับมาที่หน้า Live & Video สำเร็จ")
            return True
    except Exception as e:
        log_message(f"⚠️ รีเซ็ตหน้าจอขัดข้อง: {e}")

    return False

def worker_task(items_to_post, queue_dir_str, delay_minutes):
    global worker_state
    queue_path = Path(queue_dir_str)
    total = len(items_to_post)
    progress = load_progress()

    log_message(f"=== เริ่มต้นการโพสต์ {total} รายการ (ดีเลย์ {delay_minutes} นาทีต่อคลิป) ===")
    
    for i, item_name in enumerate(items_to_post, 1):
        if worker_stop_event.is_set():
            log_message("⏹️ ได้รับคำสั่งหยุดการทำงาน (Stopped by user)")
            break
        
        with worker_lock:
            worker_state["current_item"] = item_name
            worker_state["current_index"] = i
            worker_state["percent"] = round(((i - 1) / total) * 100)
            worker_state["status_message"] = f"กำลังโพสต์ [{i}/{total}]: {item_name}..."

        item_folder = queue_path / item_name
        review_path = REVIEW_DIR / f"{item_name}.png"
        
        log_message(f"▶️ [{i}/{total}] กำลังเตรียมและโพสต์: {item_name}")
        reset_to_live_and_video()
        
        cmd = [
            PYTHON_EXE,
            str(PREPARE_SCRIPT),
            str(item_folder),
            "--publish",
            "--review",
            str(review_path)
        ]
        
        success = False
        for attempt in range(1, 3):
            if worker_stop_event.is_set():
                break
            if attempt > 1:
                log_message(f"🔄 กำลังรีเซ็ตหน้าจอมือถือก่อนลองใหม่ครั้งที่ {attempt}...")
                reset_to_live_and_video()
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", creationflags=FLAGS_NO_WINDOW)
                for line in proc.stdout:
                    l = line.strip()
                    if l:
                        if "Touch ->" not in l and "Sent touch" not in l and "adb" not in l.lower():
                            log_message(f"  {l}")
                proc.wait()
                if proc.returncode == 0:
                    success = True
                    break
                else:
                    log_message(f"⚠️ ครั้งที่ {attempt} ไม่สำเร็จ")
                    time.sleep(2)
            except Exception as e:
                log_message(f"❌ Error during post: {e}")
                time.sleep(2)

        if success:
            log_message(f"✅ [{i}/{total}] โพสต์สำเร็จ: {item_name}")
            if item_name not in progress.get("completed", []):
                progress.setdefault("completed", []).append(item_name)
            if item_name in progress.get("failed", {}):
                del progress["failed"][item_name]
            save_progress(progress)
        else:
            log_message(f"❌ [{i}/{total}] โพสต์ล้มเหลว: {item_name}")
            progress.setdefault("failed", {})[item_name] = "Failed after retry"
            save_progress(progress)

        with worker_lock:
            worker_state["percent"] = round((i / total) * 100)

        # Delay between items if not last
        if i < total and not worker_stop_event.is_set() and delay_minutes > 0:
            wait_total_secs = int(delay_minutes * 60)
            log_message(f"⏳ เว้นช่วง {delay_minutes} นาที ก่อนเริ่มคลิปถัดไป...")
            for s in range(wait_total_secs, 0, -1):
                if worker_stop_event.is_set():
                    break
                with worker_lock:
                    worker_state["countdown_seconds"] = s
                    worker_state["status_message"] = f"รอเวลาพัก {s // 60:02d}:{s % 60:02d} นาที ก่อนโพสต์คลิปต่อไป..."
                time.sleep(1.0)
            with worker_lock:
                worker_state["countdown_seconds"] = 0

    log_message("🎉 การประมวลผลคิวทั้งหมดเสร็จสิ้นแล้ว!")
    with worker_lock:
        worker_state["is_running"] = False
        worker_state["current_item"] = None
        worker_state["status_message"] = "ทำงานเสร็จสิ้น (Completed)"

def launch_scrcpy_window():
    try:
        subprocess.run(["taskkill", "/F", "/IM", "scrcpy.exe"], capture_output=True, creationflags=FLAGS_NO_WINDOW)
        time.sleep(0.4)
        if not SCRCPY_EXE.exists():
            return False, f"ไม่พบไฟล์: {SCRCPY_EXE}"
        cmd = [
            str(SCRCPY_EXE),
            "-s", "4HZHZDBAYTPBNZTW",
            "--window-title", "Xiaomi 12T (Shopee Live)",
            "--always-on-top",
            "--stay-awake",
            "--no-audio",
            "--window-x", "1440",
            "--window-y", "40",
            "--window-width", "460",
            "--window-height", "1000"
        ]
        subprocess.Popen(cmd, creationflags=FLAGS_NO_WINDOW)
        return True, "เปิดหน้าต่าง scrcpy ประกบข้างขวาจอเรียบร้อยแล้ว (สามารถใช้เมาส์คลิก ลากเลื่อนจอ และพิมพ์คีย์บอร์ดได้ทันที)"
    except Exception as e:
        return False, str(e)

# Background Screenshot Caching Thread
def screenshot_caching_worker():
    global latest_screenshot_bytes
    while True:
        try:
            now = time.time()
            # Only poll ADB if requested in the last 15 seconds
            if now - last_screenshot_request_time < 15:
                res = subprocess.run([ADB_PATH, "-s", "4HZHZDBAYTPBNZTW", "exec-out", "screencap", "-p"],
                                     capture_output=True, timeout=5, creationflags=FLAGS_NO_WINDOW)
                if res.returncode == 0 and len(res.stdout) > 1000 and res.stdout.startswith(b"\x89PNG"):
                    with latest_screenshot_lock:
                        latest_screenshot_bytes = res.stdout
                time.sleep(0.3)
            else:
                time.sleep(1.0)
        except Exception:
            time.sleep(1.0)

# --- HTTP Request Handler ---
class DashboardHandler(http.server.BaseHTTPRequestHandler):
    def end_json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        global last_screenshot_request_time, latest_screenshot_bytes
        url = urllib.parse.urlparse(self.path)
        path = url.path
        params = urllib.parse.parse_qs(url.query)

        if path == "/api/status":
            dev = get_device_info()
            with worker_lock:
                st = dict(worker_state)
            st["device"] = dev
            self.end_json(st)

        elif path == "/api/queue":
            qdir = params.get("dir", [worker_state["queue_dir"]])[0]
            items = scan_queue(qdir)
            self.end_json({"queue_dir": qdir, "items": items})

        elif path == "/api/screenshot":
            last_screenshot_request_time = time.time()
            with latest_screenshot_lock:
                data = latest_screenshot_bytes
            if data:
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.end_headers()
                self.wfile.write(data)
            else:
                try:
                    res = subprocess.run([ADB_PATH, "-s", "4HZHZDBAYTPBNZTW", "exec-out", "screencap", "-p"],
                                         capture_output=True, timeout=6, creationflags=FLAGS_NO_WINDOW)
                    if res.returncode == 0 and res.stdout.startswith(b"\x89PNG"):
                        with latest_screenshot_lock:
                            latest_screenshot_bytes = res.stdout
                        self.send_response(200)
                        self.send_header("Content-Type", "image/png")
                        self.send_header("Content-Length", str(len(res.stdout)))
                        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                        self.end_headers()
                        self.wfile.write(res.stdout)
                    else:
                        self.end_json({"error": "Failed to capture initial screen"}, 500)
                except Exception as e:
                    self.end_json({"error": str(e)}, 500)

        elif path.startswith("/api/review/"):
            item_name = path.replace("/api/review/", "").strip()
            review_file = REVIEW_DIR / f"{item_name}.png"
            if not review_file.exists():
                matches = list(REVIEW_DIR.glob(f"*{item_name}*.png"))
                if matches:
                    review_file = matches[0]
            if review_file.exists():
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                self.wfile.write(review_file.read_bytes())
            else:
                self.end_json({"error": "Review image not found"}, 404)

        elif path == "/api/video_status" or path.startswith("/api/video_status"):
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            fn = params.get("folder_name", [""])[0]
            with video_jobs_lock:
                if fn:
                    self.end_json({fn: video_jobs.get(fn, {"status": "idle", "message": ""})})
                else:
                    self.end_json(video_jobs)

        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_DASHBOARD.encode("utf-8"))

    def do_POST(self):
        global worker_thread, worker_stop_event
        url = urllib.parse.urlparse(self.path)
        path = url.path
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            body = json.loads(post_data.decode("utf-8"))
        except Exception:
            body = {}

        if path == "/api/start":
            with worker_lock:
                if worker_state["is_running"]:
                    self.end_json({"error": "กำลังทำงานอยู่แล้ว"}, 400)
                    return
                items = body.get("items", [])
                if not items:
                    self.end_json({"error": "กรุณาเลือกคลิปอย่างน้อย 1 คลิป"}, 400)
                    return
                qdir = body.get("queue_dir", DEFAULT_QUEUE_DIR)
                delay = float(body.get("delay_minutes", 0))

                worker_stop_event.clear()
                worker_state["is_running"] = True
                worker_state["queue_dir"] = qdir
                worker_state["delay_minutes"] = delay
                worker_state["total_items"] = len(items)
                worker_state["percent"] = 0
                worker_state["status_message"] = "เริ่มต้นคิว..."

                worker_thread = threading.Thread(target=worker_task, args=(items, qdir, delay), daemon=True)
                worker_thread.start()

            self.end_json({"success": True, "message": "เริ่มกระบวนการโพสต์เรียบร้อย"})

        elif path == "/api/stop":
            worker_stop_event.set()
            with worker_lock:
                worker_state["status_message"] = "กำลังหยุดการทำงาน..."
            log_message("⏹️ คำสั่งขอหยุดระบบได้รับแล้ว กำลังออกจากขั้นตอนปัจจุบัน...")
            self.end_json({"success": True, "message": "ส่งคำสั่งหยุดเรียบร้อย"})

        elif path == "/api/reset_screen":
            threading.Thread(target=reset_to_live_and_video, daemon=True).start()
            self.end_json({"success": True, "message": "กำลังรีเซ็ตหน้าจอโทรศัพท์..."})

        elif path == "/api/launch_scrcpy":
            ok, msg = launch_scrcpy_window()
            self.end_json({"success": ok, "message": msg})

        elif path == "/api/touch":
            action = body.get("action", "tap")
            if action == "tap":
                x = float(body.get("x", 0.5))
                y = float(body.get("y", 0.5))
                def _do_tap():
                    subprocess.run([PYTHON_EXE, str(TOUCH_SCRIPT), f"{x:.3f}", f"{y:.3f}"], capture_output=True, creationflags=FLAGS_NO_WINDOW)
                threading.Thread(target=_do_tap, daemon=True).start()
            elif action == "swipe":
                x1 = float(body.get("x1", 0.5))
                y1 = float(body.get("y1", 0.75))
                x2 = float(body.get("x2", 0.5))
                y2 = float(body.get("y2", 0.25))
                def _do_swipe():
                    subprocess.run([PYTHON_EXE, str(TOUCH_SCRIPT), f"{x1:.3f}", f"{y1:.3f}", "--swipe-to", f"{x2:.3f}", f"{y2:.3f}"], capture_output=True, creationflags=FLAGS_NO_WINDOW)
                threading.Thread(target=_do_swipe, daemon=True).start()
            self.end_json({"success": True})

        elif path == "/api/requeue":
            folder_name = body.get("folder_name", "")
            if folder_name:
                progress = load_progress()
                changed = False
                if folder_name in progress.get("completed", []):
                    progress["completed"].remove(folder_name)
                    changed = True
                if folder_name in progress.get("failed", {}):
                    del progress["failed"][folder_name]
                    changed = True
                if changed:
                    save_progress(progress)
                    log_message(f"🔄 ย้ายรายการ '{folder_name}' กลับไปรอโพสต์เรียบร้อย")
                    self.end_json({"success": True, "message": f"ย้าย '{folder_name}' กลับไปรอโพสต์แล้ว"})
                    return
            self.end_json({"error": "ไม่พบรายการที่ระบุในประวัติ"}, 400)

        elif path == "/api/requeue_all":
            progress = load_progress()
            count = len(progress.get("completed", []))
            progress["completed"] = []
            progress["failed"] = {}
            save_progress(progress)
            log_message(f"🔄 ย้ายคลิปทั้งหมด ({count} คลิป) กลับมารอโพสต์ใหม่เรียบร้อย")
            self.end_json({"success": True, "message": f"ย้าย {count} รายการกลับมารอโพสต์แล้ว"})

        elif path == "/api/import_shopee":
            urls_raw = body.get("url", "").strip()
            max_imgs = int(body.get("max_images", 5))
            if not urls_raw:
                self.end_json({"error": "กรุณาระบุลิงก์สินค้า Shopee"}, 400)
                return

            urls = [u.strip() for u in re.split(r'[\r\n,]+', urls_raw) if u.strip().startswith("http")]
            if not urls:
                self.end_json({"error": "ไม่พบรูปแบบลิงก์ URL ที่ถูกต้อง (ต้องขึ้นต้นด้วย http:// หรือ https://)"}, 400)
                return

            try:
                from shopee_importer import import_shopee_product
                qdir = Path(worker_state["queue_dir"])
                results = []
                for u in urls:
                    log_message(f"📥 กำลังดึงสินค้า Shopee: {u}")
                    res = import_shopee_product(u, max_images=max_imgs, queue_dir=qdir)
                    log_message(f"✅ สำเร็จ: [{res['index']}] {res['title']} -> {res['folder_name']}")
                    results.append(res)
                
                self.end_json({"success": True, "results": results})
            except Exception as e:
                log_message(f"❌ ดึงข้อมูลสินค้าล้มเหลว: {e}")
                self.end_json({"error": str(e)}, 500)

        elif path == "/api/open_folder":
            folder_name = body.get("folder_name", "")
            qdir = Path(worker_state["queue_dir"])
            target = qdir / folder_name if folder_name else qdir
            if target.exists():
                os.startfile(str(target))
                self.end_json({"success": True})
            else:
                self.end_json({"error": "ไม่พบโฟลเดอร์"}, 404)

        elif path == "/api/generate_video":
            folder_name = body.get("folder_name", "").strip()
            if not folder_name:
                self.end_json({"error": "กรุณาระบุชื่อโฟลเดอร์สินค้า"}, 400)
                return

            with video_jobs_lock:
                if folder_name in video_jobs and video_jobs[folder_name].get("status") == "running":
                    self.end_json({"status": "already_running", "message": "งานสร้างคลิปโฟลเดอร์นี้กำลังรันอยู่แล้ว"})
                    return
                video_jobs[folder_name] = {"status": "running", "step": 1, "message": "🎬 กำลังเตรียมข้อมูลและเวิร์กโฟลว์..."}

            def run_video_job(fn):
                try:
                    log_message(f"🎬 เริ่มสร้างคลิป Hand-Shopee ให้สินค้า: {fn}")
                    from shopee_video_generator import generate_full_video
                    qdir = Path(worker_state["queue_dir"])
                    target_dir = qdir / fn
                    
                    def cb(msg):
                        with video_jobs_lock:
                            if fn in video_jobs:
                                video_jobs[fn]["message"] = msg
                        log_message(f"[{fn}] {msg}")

                    final_out = generate_full_video(target_dir, progress_callback=cb)
                    with video_jobs_lock:
                        video_jobs[fn] = {"status": "done", "step": 4, "message": "✅ สร้างคลิปเสร็จสมบูรณ์! พร้อมโพสต์", "file": final_out}
                    log_message(f"🎉 สร้างคลิปสำเร็จ: {fn} -> final_10s.mp4")
                except Exception as ex:
                    with video_jobs_lock:
                        video_jobs[fn] = {"status": "error", "message": f"❌ ล้มเหลว: {ex}", "error": str(ex)}
                    log_message(f"❌ ทำคลิปล้มเหลว [{fn}]: {ex}")

            threading.Thread(target=run_video_job, args=(folder_name,), daemon=True).start()
            self.end_json({"success": True, "message": f"ส่งคำสั่งสร้างคลิป Hand-Shopee ให้ {folder_name} แล้ว"})

        else:
            self.end_json({"error": "Not Found"}, 404)

    def log_message(self, format, *args):
        pass # Quiet console

HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="th" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Shopee Video Auto-Poster Dashboard</title>
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
  <style>
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: #0f172a; }
    ::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: #475569; }
    #phone-frame-container:fullscreen {
      border: none !important;
      border-radius: 0 !important;
      padding: 0 !important;
      background: #000 !important;
      width: 100vw !important;
      height: 100vh !important;
      display: flex !important;
      align-items: center !important;
      justify-content: center !important;
    }
    #phone-frame-container:fullscreen img {
      border-radius: 0 !important;
      max-height: 100vh !important;
      object-contain: contain;
    }
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen font-sans flex flex-col antialiased selection:bg-orange-500 selection:text-white">

  <!-- Header Bar -->
  <header class="bg-slate-900 border-b border-slate-800 sticky top-0 z-50 shadow-lg px-6 py-3.5">
    <div class="w-full flex flex-wrap items-center justify-between gap-4">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-amber-500 to-orange-600 flex items-center justify-center text-xl shadow-md shadow-orange-500/20">
          🛍️
        </div>
        <div>
          <h1 class="text-lg font-bold tracking-tight text-white flex items-center gap-2">
            Shopee Video Auto-Poster
            <span class="text-[11px] bg-orange-500/20 text-orange-400 border border-orange-500/30 px-2 py-0.5 rounded-full font-semibold">Pro</span>
          </h1>
          <p class="text-xs text-slate-400">ระบบควบคุมการโพสต์คลิปพร้อมแนบตะกร้าสินค้าอัตโนมัติ</p>
        </div>
      </div>

      <!-- Device Badge & Health -->
      <div class="flex items-center gap-2 text-xs">
        <!-- Phone Device -->
        <div id="device-pill" class="flex items-center gap-2 bg-slate-800/80 border border-slate-700/60 px-3 py-1.5 rounded-lg">
          <span class="w-2.5 h-2.5 rounded-full bg-slate-500 animate-pulse" id="dot-device"></span>
          <span id="text-device" class="font-medium">กำลังตรวจสอบอุปกรณ์...</span>
        </div>

        <!-- Battery -->
        <div class="flex items-center gap-1.5 bg-slate-800/80 border border-slate-700/60 px-3 py-1.5 rounded-lg">
          <span>🔋</span>
          <span id="text-battery" class="font-semibold text-emerald-400">--%</span>
        </div>

        <!-- Quick Realtime scrcpy -->
        <button id="btn-header-scrcpy" onclick="launchScrcpy()" title="เปิดหน้าต่างจอสด Real-time 60 FPS (scrcpy)" class="bg-gradient-to-r from-teal-500/20 to-emerald-500/20 hover:from-teal-500/30 hover:to-emerald-500/30 text-teal-300 border border-teal-500/40 px-2.5 py-1.5 rounded-lg transition text-xs flex items-center gap-1 font-semibold">
          <span>⚡</span> จอสด 60 FPS
        </button>

        <!-- Quick Reset Screen -->
        <button onclick="resetScreen()" title="แตะย้อนกลับไปหน้า Live & Video" class="bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 px-2.5 py-1.5 rounded-lg transition text-xs flex items-center gap-1">
          🔄 คืนหน้า Feed
        </button>
      </div>
    </div>
  </header>

  <!-- Main Container (Full Width 3-Column Layout: Left Queue, Center Control/Log, Right Live Screen) -->
  <main class="w-full px-4 sm:px-6 py-4 flex-1 grid grid-cols-1 lg:grid-cols-12 gap-5">

    <!-- COLUMN 1 (Left 5 Cols): Queue Manager -->
    <section id="col-queue" class="lg:col-span-5 flex flex-col gap-3">
      
      <!-- Queue Path Selector & Quick Filters & View Switcher -->
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-4 shadow-xl space-y-3">
        <div class="flex flex-col sm:flex-row gap-2 items-center justify-between">
          <div class="w-full">
            <label class="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1">โฟลเดอร์คิวคลิป (Queue Folder)</label>
            <div class="flex gap-2">
              <input type="text" id="input-folder" class="bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200 flex-1 focus:outline-none focus:border-orange-500 transition font-mono" />
              <button onclick="loadQueue()" class="bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 px-4 py-2 rounded-xl text-xs font-medium transition flex items-center gap-1 whitespace-nowrap">
                🔄 โหลดคิว
              </button>
            </div>
          </div>
        </div>

        <!-- Global Stats Summary -->
        <div class="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-800/80 text-xs">
          <div class="text-slate-400" id="stats-counter">
            ทั้งหมด: <b class="text-slate-200" id="stat-total">0</b> | 
            🎬 รอทำคลิป: <b class="text-sky-400" id="stat-novideo">0</b> | 
            ⏳ พร้อมโพสต์: <b class="text-amber-400" id="stat-pending">0</b> | 
            ✅ โพสต์แล้ว: <b class="text-emerald-400" id="stat-completed">0</b> | 
            เลือกอยู่: <b class="text-orange-400" id="selected-count">0</b>
          </div>
        </div>

        <!-- View Switcher Tabs (คู่กัน / รอทำคลิป / พร้อมโพสต์ / โพสต์แล้ว) -->
        <div class="grid grid-cols-4 gap-1.5 bg-slate-950/80 p-1 rounded-xl border border-slate-800/90 text-xs font-medium">
          <button id="tab-btn-split" onclick="switchQueueView('split')" class="py-1.5 px-1.5 rounded-lg transition flex items-center justify-center gap-1 bg-orange-500/20 text-orange-400 border border-orange-500/40 font-semibold shadow-sm">
            <span>⚸</span> คู่กัน
          </button>
          <button id="tab-btn-novideo" onclick="switchQueueView('novideo')" class="py-1.5 px-1.5 rounded-lg transition flex items-center justify-center gap-1 text-slate-400 hover:text-white border border-transparent">
            <span>🎬</span> รอคลิป <span id="tab-badge-novideo" class="px-1.5 py-0.2 rounded-full text-[10px] bg-sky-500/20 text-sky-300 ml-0.5">0</span>
          </button>
          <button id="tab-btn-pending" onclick="switchQueueView('pending')" class="py-1.5 px-1.5 rounded-lg transition flex items-center justify-center gap-1 text-slate-400 hover:text-white border border-transparent">
            <span>⏳</span> พร้อมโพสต์ <span id="tab-badge-pending" class="px-1.5 py-0.2 rounded-full text-[10px] bg-amber-500/20 text-amber-300 ml-0.5">0</span>
          </button>
          <button id="tab-btn-completed" onclick="switchQueueView('completed')" class="py-1.5 px-1.5 rounded-lg transition flex items-center justify-center gap-1 text-slate-400 hover:text-white border border-transparent">
            <span>✅</span> โพสต์แล้ว <span id="tab-badge-completed" class="px-1.5 py-0.2 rounded-full text-[10px] bg-emerald-500/20 text-emerald-300 ml-0.5">0</span>
          </button>
        </div>
      </div>

      <!-- Shopee Product Auto-Importer Card (Qwen 3.8 AI) -->
      <div class="bg-gradient-to-br from-slate-900 via-slate-900 to-orange-950/20 border border-orange-500/30 rounded-2xl p-4 shadow-xl space-y-3">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="text-base">📥</span>
            <h2 class="text-xs font-bold text-orange-400 uppercase tracking-wider">นำเข้าสินค้าจาก Shopee (Qwen 3.8 AI)</h2>
          </div>
          <span class="text-[10px] bg-orange-500/20 text-orange-300 border border-orange-500/30 px-2 py-0.5 rounded-full font-medium">Auto Scraper</span>
        </div>

        <div class="space-y-2">
          <div class="flex gap-2">
            <input type="text" id="input-shopee-url" onkeydown="if(event.key==='Enter') importShopeeProduct()" placeholder="วางลิงก์ Shopee ที่นี่ (เช่น https://s.shopee.co.th/... หรือ shopee.co.th/product/...)" class="bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200 flex-1 focus:outline-none focus:border-orange-500 transition placeholder:text-slate-600 font-mono" />
            <select id="select-max-images" class="bg-slate-950 border border-slate-800 rounded-xl px-2.5 py-2 text-xs text-slate-300 focus:outline-none focus:border-orange-500">
              <option value="3">3 รูป</option>
              <option value="5" selected>5 รูป</option>
              <option value="8">8 รูป</option>
            </select>
          </div>

          <div class="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2">
            <div class="text-[11px] text-slate-400 truncate flex-1" id="import-status-text">
              วางลิงก์ Shopee แล้วกดปุ่มเพื่อดูดรูป HD และให้ Qwen 3.8 แต่งแคปชัน
            </div>
            <button id="btn-import-shopee" onclick="importShopeeProduct()" class="bg-gradient-to-r from-orange-500 to-amber-500 hover:from-orange-600 hover:to-amber-600 text-white px-4 py-2 rounded-xl text-xs font-bold transition flex items-center gap-1.5 shadow-md shadow-orange-500/20 whitespace-nowrap disabled:opacity-50">
              <span>⚡</span> ดึงสินค้า & แต่งสคริปต์
            </button>
          </div>
        </div>
      </div>

      <!-- BOX 0: รอทำคลิป (No Video) -->
      <div id="box-novideo" class="bg-slate-900 border border-sky-500/30 rounded-2xl p-4 shadow-xl flex flex-col transition-all">
        <div class="flex items-center justify-between pb-2 mb-2 border-b border-slate-800/80">
          <div class="flex items-center gap-2">
            <h2 class="text-xs font-bold text-sky-400 uppercase tracking-wider flex items-center gap-1.5">
              <span>🎬</span> สินค้ารอทำคลิป (ยังไม่มีวิดีโอ .mp4)
            </h2>
            <span id="badge-novideo-count" class="text-[10px] bg-sky-500/20 text-sky-300 border border-sky-500/30 px-2 py-0.5 rounded-full font-semibold">0 สินค้า</span>
          </div>
          <span class="text-[11px] text-slate-500">เปิดโฟลเดอร์เพื่อใส่คลิป</span>
        </div>

        <div class="overflow-y-auto pr-1 space-y-2.5 transition-all" id="items-novideo-list" style="max-height: 220px;">
          <div class="text-center py-6 text-slate-500 text-xs">ไม่มีสินค้ารอทำคลิป</div>
        </div>
      </div>

      <!-- BOX 1: พร้อมโพสต์ (Pending Queue) -->
      <div id="box-pending" class="bg-slate-900 border border-slate-800 rounded-2xl p-4 shadow-xl flex flex-col transition-all">
        <div class="flex items-center justify-between pb-2 mb-2 border-b border-slate-800/80">
          <div class="flex items-center gap-2">
            <h2 class="text-xs font-bold text-slate-200 uppercase tracking-wider flex items-center gap-1.5">
              <span>⏳</span> รายการพร้อมโพสต์ (มีคลิปแล้ว)
            </h2>
            <span id="badge-pending-count" class="text-[10px] bg-amber-500/20 text-amber-300 border border-amber-500/30 px-2 py-0.5 rounded-full font-semibold">0 คลิป</span>
          </div>
          <!-- Quick Selection Controls for Pending only -->
          <div class="flex items-center gap-2 text-xs">
            <button onclick="selectAllPending(true)" class="text-orange-400 hover:text-orange-300 transition font-medium">เลือกทั้งหมด</button>
            <span class="text-slate-600">•</span>
            <button onclick="selectAllPending(false)" class="text-slate-400 hover:text-white transition underline">ล้างการเลือก</button>
          </div>
        </div>

        <div class="overflow-y-auto pr-1 space-y-2.5 transition-all" id="items-pending-list" style="max-height: 250px;">
          <div class="text-center py-8 text-slate-500 text-xs">กำลังโหลดรายการพร้อมโพสต์...</div>
        </div>
      </div>

        <div class="overflow-y-auto pr-1 space-y-2.5 transition-all" id="items-pending-list" style="max-height: 290px;">
          <div class="text-center py-8 text-slate-500 text-xs">กำลังโหลดรายการรอโพสต์...</div>
        </div>
      </div>

      <!-- BOX 2: โพสต์แล้ว (Completed Posts) -->
      <div id="box-completed" class="bg-slate-900 border border-slate-800 rounded-2xl p-4 shadow-xl flex flex-col transition-all">
        <div class="flex items-center justify-between pb-2 mb-2 border-b border-slate-800/80">
          <div class="flex items-center gap-2">
            <h2 class="text-xs font-bold text-slate-200 uppercase tracking-wider flex items-center gap-1.5">
              <span>✅</span> โพสต์สำเร็จแล้ว
            </h2>
            <span id="badge-completed-count" class="text-[10px] bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 px-2 py-0.5 rounded-full font-semibold">0 คลิป</span>
          </div>
          <div class="flex items-center gap-2 text-[11px]">
            <span class="text-slate-500 hidden sm:inline">โพสต์แล้ว (ล็อกไม่ให้เลือกซ้ำ)</span>
            <button onclick="requeueAllCompleted()" title="ย้ายคลิปที่โพสต์แล้วทั้งหมดกลับมารอโพสต์ใหม่" class="text-slate-400 hover:text-amber-400 transition text-[11px] underline ml-1">
              ย้ายกลับทั้งหมด
            </button>
          </div>
        </div>

        <div class="overflow-y-auto pr-1 space-y-2.5 transition-all" id="items-completed-list" style="max-height: 250px;">
          <div class="text-center py-8 text-slate-500 text-xs">ยังไม่มีคลิปที่โพสต์สำเร็จ</div>
        </div>
      </div>

    </section>

    <!-- COLUMN 2 (Center 4 Cols): Control Panel & Logs -->
    <section id="col-controls" class="lg:col-span-4 flex flex-col gap-4">

      <!-- Control Box -->
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-xl space-y-4">
        <h2 class="text-sm font-bold text-slate-200 uppercase tracking-wider flex items-center gap-2">
          <span>⚡</span> แผงควบคุมการโพสต์ (Control Panel)
        </h2>

        <!-- Delay Interval Selector -->
        <div>
          <label class="text-xs text-slate-400 font-medium block mb-1.5">ระยะห่างระหว่างคลิป (Delay)</label>
          <div class="grid grid-cols-6 gap-2 text-xs">
            <button type="button" onclick="setDelay(0)" class="delay-btn border py-2 rounded-xl font-medium transition" data-delay="0">ทันที</button>
            <button type="button" onclick="setDelay(1)" class="delay-btn border py-2 rounded-xl font-medium transition" data-delay="1">1 นาที</button>
            <button type="button" onclick="setDelay(5)" class="delay-btn border py-2 rounded-xl font-medium transition" data-delay="5">5 นาที</button>
            <button type="button" onclick="setDelay(10)" class="delay-btn border py-2 rounded-xl font-medium transition" data-delay="10">10 นาที</button>
            <button type="button" onclick="setDelay(15)" class="delay-btn border py-2 rounded-xl font-medium transition" data-delay="15">15 นาที</button>
            <button type="button" onclick="setDelay(30)" class="delay-btn border py-2 rounded-xl font-medium transition" data-delay="30">30 นาที</button>
          </div>
        </div>

        <!-- Standing Rules Notice -->
        <div class="bg-slate-950/80 border border-slate-800 rounded-xl p-3 text-[11px] text-slate-400 space-y-1">
          <div class="text-slate-300 font-semibold mb-0.5">🔒 กฎมาตรฐานที่ถูกล็อกไว้เสมอ:</div>
          <p>✓ ปิด Reuse Permission เสมอ (ป้องกันคนดูดคลิป)</p>
          <p>✓ เปิด AI-generated Content Disclosure เสมอ</p>
          <p>✓ แนบลิงก์สินค้าจาก Shopee ตรงโฟลเดอร์ 100%</p>
        </div>

        <!-- Action Buttons -->
        <div class="pt-1 flex gap-2">
          <button id="btn-start" onclick="startPosting()" class="flex-1 bg-gradient-to-r from-orange-500 to-amber-500 hover:from-orange-600 hover:to-amber-600 text-white font-bold py-3 px-4 rounded-xl shadow-lg shadow-orange-500/20 transition flex items-center justify-center gap-2 text-sm disabled:opacity-50">
            <span>🚀</span> เริ่มโพสต์คลิปที่เลือก
          </button>
          <button id="btn-stop" onclick="stopPosting()" disabled class="bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border border-rose-500/40 font-semibold py-3 px-4 rounded-xl transition text-sm flex items-center justify-center gap-1.5 disabled:opacity-30">
            <span>⏹️</span> หยุด
          </button>
        </div>

        <!-- Progress Bar & Status -->
        <div class="space-y-1.5 pt-1">
          <div class="flex justify-between text-xs">
            <span class="text-slate-400 truncate pr-2" id="status-text">พร้อมทำงาน (Idle)</span>
            <span class="text-orange-400 font-bold" id="progress-pct">0%</span>
          </div>
          <div class="w-full bg-slate-950 rounded-full h-2.5 overflow-hidden border border-slate-800">
            <div id="progress-bar" class="bg-gradient-to-r from-orange-500 to-amber-400 h-full rounded-full transition-all duration-300" style="width: 0%"></div>
          </div>
        </div>
      </div>

      <!-- Live Terminal Console Logs (Taller & Fills the remaining height) -->
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-4 shadow-xl flex-1 flex flex-col min-h-[360px]">
        <div class="flex items-center justify-between mb-2">
          <h3 class="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
            <span>💻</span> บันทึกการทำงานสด (Execution Log)
          </h3>
          <span class="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
        </div>
        <div id="log-box" class="bg-slate-950 border border-slate-800/80 rounded-xl p-3 font-mono text-[11px] text-slate-300 flex-1 overflow-y-auto space-y-1 max-h-[calc(100vh-480px)]">
          <div class="text-slate-500">รอคำสั่งเริ่มการทำงาน...</div>
        </div>
      </div>

    </section>

    <!-- COLUMN 3 (Right 3 Cols): Full-Height Live Screen in the Red Box! -->
    <section id="col-live-screen" class="lg:col-span-3 flex flex-col">
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-4 shadow-xl flex flex-col h-[calc(100vh-100px)] sticky top-20 space-y-3">
        
        <!-- Header -->
        <div class="flex items-center justify-between pb-2 border-b border-slate-800/80">
          <div class="flex items-center gap-2">
            <h3 class="text-xs font-bold text-slate-200 uppercase tracking-wider flex items-center gap-1.5">
              <span>📱</span> จอมือถือสด (Live Screen)
            </h3>
            <span id="stream-badge" class="flex items-center gap-1 text-[10px] bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 px-2 py-0.5 rounded-full font-semibold">
              <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span> Live
            </span>
          </div>
          <div class="flex items-center gap-2 text-[11px]">
            <button id="btn-toggle-stream" onclick="toggleStream()" class="text-slate-400 hover:text-white underline">พักสตรีม</button>
            <span class="text-slate-600">•</span>
            <button onclick="toggleFullscreen()" class="text-orange-400 hover:text-orange-300 font-medium">⛶ ขยายเต็มจอ</button>
          </div>
        </div>

        <!-- Control Hint Banner -->
        <div class="bg-amber-500/10 border border-amber-500/20 rounded-xl px-2.5 py-1.5 text-[11px] text-amber-300 text-center flex items-center justify-center gap-1.5 shadow-sm">
          <span>🖱️</span>
          <span>คลิก/ลาก เพื่อแตะจอ | หมุนลูกกลิ้งเมาส์เลื่อนคลิป</span>
        </div>

        <!-- Phone Mockup Frame (Interactive!) -->
        <div id="phone-frame-container" class="bg-black border-[6px] border-slate-800 rounded-[38px] shadow-2xl p-2.5 flex flex-col items-center justify-between flex-1 overflow-hidden relative group">
          <!-- Top Speaker / Dynamic Island -->
          <div class="w-20 h-2 bg-slate-900 rounded-full mb-1.5 flex items-center justify-center">
            <div class="w-1.5 h-1.5 rounded-full bg-slate-950"></div>
          </div>
          
          <!-- Screen Image filling full available height (With Mouse Control!) -->
          <div id="touch-feedback-container" class="w-full flex-1 flex items-center justify-center overflow-hidden rounded-[26px] bg-slate-950 relative cursor-pointer select-none">
            <img id="live-screen-img" src="/api/screenshot" onmousedown="onScreenMouseDown(event)" onmouseup="onScreenMouseUp(event)" onwheel="onScreenWheel(event)" class="object-contain h-full w-full rounded-[24px] pointer-events-auto" alt="Xiaomi 12T Screen Preview" draggable="false" onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22100%22 height=%22100%22><text y=%2250%%22 x=%2250%%22 text-anchor=%22middle%22 fill=%22gray%22 font-size=%2212%22>กำลังเชื่อมต่อสัญญาณ...</text></svg>'" />
          </div>

          <!-- Bottom Navigation Bar -->
          <div class="w-24 h-1 bg-slate-700/60 rounded-full mt-2"></div>
        </div>

        <!-- Bottom Quick Actions -->
        <div class="pt-1 flex flex-col gap-2">
          <div class="flex gap-2">
            <button onclick="launchScrcpy()" class="flex-1 bg-gradient-to-r from-teal-500 to-emerald-600 hover:from-teal-600 hover:to-emerald-700 text-white font-semibold py-2.5 px-3 rounded-xl shadow-md transition text-xs flex items-center justify-center gap-1.5">
              <span>⚡</span> เปิด scrcpy ประกบข้างขวา (60 FPS)
            </button>
            <button onclick="resetScreen()" title="คืนหน้าจอ Feed Shopee" class="bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 px-3 py-2.5 rounded-xl transition text-xs flex items-center gap-1 whitespace-nowrap">
              🔄 คืนหน้า Feed
            </button>
          </div>
          <div class="text-[10px] text-center text-slate-400 font-mono">
            💡 กดปุ่มเขียวเพื่อเปิด scrcpy คุมสด 60 FPS ลากเลื่อนและพิมพ์คีย์บอร์ดได้ทันที
          </div>
        </div>

      </div>
    </section>

  </main>

  <script>
    let queueItems = [];
    let selectedDelay = 0;
    let isPosting = false;
    let lastRunningIndex = -1;

    // Fullscreen Toggle
    function toggleFullscreen() {
      const elem = document.getElementById('phone-frame-container');
      if (!document.fullscreenElement) {
        if (elem.requestFullscreen) {
          elem.requestFullscreen();
        } else if (elem.webkitRequestFullscreen) {
          elem.webkitRequestFullscreen();
        }
      } else {
        if (document.exitFullscreen) {
          document.exitFullscreen();
        }
      }
    }

    // Mouse Interaction for In-Browser Phone Frame
    let dragStartX = 0, dragStartY = 0, dragStartTime = 0;

    function onScreenMouseDown(e) {
      dragStartX = e.offsetX;
      dragStartY = e.offsetY;
      dragStartTime = Date.now();
    }

    function onScreenMouseUp(e) {
      const img = document.getElementById('live-screen-img');
      const rect = img.getBoundingClientRect();
      const dx = e.offsetX - dragStartX;
      const dy = e.offsetY - dragStartY;
      const dist = Math.hypot(dx, dy);

      const relX1 = Math.min(Math.max(dragStartX / rect.width, 0.05), 0.95);
      const relY1 = Math.min(Math.max(dragStartY / rect.height, 0.05), 0.95);
      const relX2 = Math.min(Math.max(e.offsetX / rect.width, 0.05), 0.95);
      const relY2 = Math.min(Math.max(e.offsetY / rect.height, 0.05), 0.95);

      if (dist > 25) {
        // Drag / Swipe
        showRipple(e.offsetX, e.offsetY, 'ลากเลื่อน');
        fetch('/api/touch', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ action: 'swipe', x1: relX1, y1: relY1, x2: relX2, y2: relY2 })
        });
      } else {
        // Click / Tap
        showRipple(e.offsetX, e.offsetY, 'แตะ');
        fetch('/api/touch', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ action: 'tap', x: relX2, y: relY2 })
        });
      }
      setTimeout(refreshScreen, 1200);
    }

    function onScreenWheel(e) {
      e.preventDefault();
      const isDown = e.deltaY > 0;
      showRipple(e.offsetX, e.offsetY, isDown ? '⬇ ถัดไป' : '⬆ ก่อนหน้า');
      fetch('/api/touch', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          action: 'swipe',
          x1: 0.5,
          y1: isDown ? 0.78 : 0.22,
          x2: 0.5,
          y2: isDown ? 0.22 : 0.78
        })
      });
      setTimeout(refreshScreen, 1200);
    }

    function showRipple(x, y, text) {
      const container = document.getElementById('touch-feedback-container');
      if (!container) return;
      const tag = document.createElement('div');
      tag.className = 'absolute bg-orange-500 text-white text-[10px] font-bold px-2 py-0.5 rounded-full pointer-events-none transform -translate-x-1/2 -translate-y-1/2 shadow-lg animate-ping z-20';
      tag.style.left = x + 'px';
      tag.style.top = y + 'px';
      tag.textContent = text || '👆';
      container.appendChild(tag);
      setTimeout(() => tag.remove(), 600);
    }

    // Set Delay
    function setDelay(mins) {
      selectedDelay = mins;
      document.querySelectorAll('.delay-btn').forEach(btn => {
        if (parseFloat(btn.dataset.delay) === mins) {
          btn.className = 'delay-btn border py-2 rounded-xl font-medium transition bg-orange-500/20 text-orange-400 border-orange-500/50';
        } else {
          btn.className = 'delay-btn border py-2 rounded-xl font-medium transition bg-slate-950 border-slate-800 text-slate-400 hover:text-white';
        }
      });
    }
    setDelay(0);

    // Fetch Status Loop
    async function updateStatus() {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();

        // Update Device
        const dev = data.device || {};
        const devDot = document.getElementById('dot-device');
        const devText = document.getElementById('text-device');
        const batText = document.getElementById('text-battery');

        if (dev.connected) {
          devDot.className = 'w-2.5 h-2.5 rounded-full bg-emerald-400';
          devText.textContent = dev.screen_ready ? 'Xiaomi 12T (พร้อมโพสต์)' : 'Xiaomi 12T (ต่อสายแล้ว)';
          batText.textContent = dev.battery_pct + '% (' + dev.voltage_v + 'V)';
        } else {
          devDot.className = 'w-2.5 h-2.5 rounded-full bg-rose-500';
          devText.textContent = 'ไม่พบโทรศัพท์ (ADB Disconnected)';
          batText.textContent = '--%';
        }

        // Worker state
        const prevRunning = isPosting;
        isPosting = data.is_running;
        document.getElementById('btn-start').disabled = isPosting;
        document.getElementById('btn-stop').disabled = !isPosting;

        document.getElementById('status-text').textContent = data.status_message || 'พร้อมทำงาน';
        document.getElementById('progress-pct').textContent = data.percent + '%';
        document.getElementById('progress-bar').style.width = data.percent + '%';

        // Auto reload queue if finished or if current item changed
        if (prevRunning && !isPosting) {
          loadQueue();
        } else if (isPosting && data.current_index && data.current_index !== lastRunningIndex) {
          lastRunningIndex = data.current_index;
          loadQueue();
        }

        // Render Logs
        const logBox = document.getElementById('log-box');
        if (data.logs && data.logs.length > 0) {
          const atBottom = logBox.scrollHeight - logBox.scrollTop <= logBox.clientHeight + 50;
          logBox.innerHTML = data.logs.map(l => {
            let color = 'text-slate-300';
            if (l.includes('✅') || l.includes('[SUCCESS]')) color = 'text-emerald-400 font-semibold';
            if (l.includes('❌') || l.includes('⚠️')) color = 'text-rose-400 font-semibold';
            if (l.includes('▶️') || l.includes('⏳')) color = 'text-amber-300';
            return `<div class="${color}">${l}</div>`;
          }).join('');
          if (atBottom) logBox.scrollTop = logBox.scrollHeight;
        }

      } catch (err) {
        console.error("Status update error:", err);
      }
    }

    // Smooth In-browser Live Stream
    let isStreamActive = true;
    let isFetchingFrame = false;

    function fetchNextFrame() {
      if (!isStreamActive) return;
      if (isFetchingFrame) return;
      isFetchingFrame = true;
      const img = document.getElementById('live-screen-img');
      const tempImg = new Image();
      tempImg.onload = () => {
        img.src = tempImg.src;
        isFetchingFrame = false;
        if (isStreamActive) {
          setTimeout(fetchNextFrame, 300); // 300ms interval for smooth live updates
        }
      };
      tempImg.onerror = () => {
        isFetchingFrame = false;
        if (isStreamActive) {
          setTimeout(fetchNextFrame, 1500);
        }
      };
      tempImg.src = '/api/screenshot?t=' + Date.now();
    }

    function toggleStream() {
      isStreamActive = !isStreamActive;
      const btn = document.getElementById('btn-toggle-stream');
      const badge = document.getElementById('stream-badge');
      if (isStreamActive) {
        btn.textContent = 'พักสตรีม';
        badge.className = 'flex items-center gap-1 text-[10px] bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 px-2 py-0.5 rounded-full font-semibold';
        badge.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span> Live';
        fetchNextFrame();
      } else {
        btn.textContent = 'เล่นสตรีม';
        badge.className = 'flex items-center gap-1 text-[10px] bg-slate-800 text-slate-400 border border-slate-700 px-2 py-0.5 rounded-full font-semibold';
        badge.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-slate-500"></span> Paused';
      }
    }

    function refreshScreen() {
      if (!isFetchingFrame) fetchNextFrame();
    }

    // Reset phone screen to Live & Video
    async function resetScreen() {
      await fetch('/api/reset_screen', { method: 'POST' });
      setTimeout(refreshScreen, 1500);
    }

    // Launch realtime scrcpy window
    async function launchScrcpy() {
      try {
        const res = await fetch('/api/launch_scrcpy', { method: 'POST' });
        const data = await res.json();
        if (data.message) {
          alert(data.message);
        }
      } catch (err) {
        alert("เกิดข้อผิดพลาดในการเปิด scrcpy: " + err);
      }
    }

    // Queue View Toggle State: 'split', 'novideo', 'pending', 'completed'
    let currentQueueView = 'split';

    function switchQueueView(mode) {
      currentQueueView = mode;
      const btnSplit = document.getElementById('tab-btn-split');
      const btnNovideo = document.getElementById('tab-btn-novideo');
      const btnPending = document.getElementById('tab-btn-pending');
      const btnCompleted = document.getElementById('tab-btn-completed');
      
      const boxNovideo = document.getElementById('box-novideo');
      const boxPending = document.getElementById('box-pending');
      const boxCompleted = document.getElementById('box-completed');
      
      const listNovideo = document.getElementById('items-novideo-list');
      const listPending = document.getElementById('items-pending-list');
      const listCompleted = document.getElementById('items-completed-list');

      const activeClass = 'py-1.5 px-1.5 rounded-lg transition flex items-center justify-center gap-1 bg-orange-500/20 text-orange-400 border border-orange-500/40 font-semibold shadow-sm';
      const inactiveClass = 'py-1.5 px-1.5 rounded-lg transition flex items-center justify-center gap-1 text-slate-400 hover:text-white border border-transparent';

      if (btnSplit) btnSplit.className = (mode === 'split') ? activeClass : inactiveClass;
      if (btnNovideo) btnNovideo.className = (mode === 'novideo') ? activeClass : inactiveClass;
      if (btnPending) btnPending.className = (mode === 'pending') ? activeClass : inactiveClass;
      if (btnCompleted) btnCompleted.className = (mode === 'completed') ? activeClass : inactiveClass;

      const noVideoCount = queueItems.filter(i => !i.has_video && i.status !== 'completed').length;

      if (mode === 'split') {
        if (boxNovideo) boxNovideo.style.display = noVideoCount > 0 ? 'flex' : 'none';
        if (boxPending) boxPending.style.display = 'flex';
        if (boxCompleted) boxCompleted.style.display = 'flex';
        if (listNovideo) listNovideo.style.maxHeight = '200px';
        if (listPending) listPending.style.maxHeight = '240px';
        if (listCompleted) listCompleted.style.maxHeight = '220px';
      } else if (mode === 'novideo') {
        if (boxNovideo) boxNovideo.style.display = 'flex';
        if (boxPending) boxPending.style.display = 'none';
        if (boxCompleted) boxCompleted.style.display = 'none';
        if (listNovideo) listNovideo.style.maxHeight = 'calc(100vh - 280px)';
      } else if (mode === 'pending') {
        if (boxNovideo) boxNovideo.style.display = 'none';
        if (boxPending) boxPending.style.display = 'flex';
        if (boxCompleted) boxCompleted.style.display = 'none';
        if (listPending) listPending.style.maxHeight = 'calc(100vh - 280px)';
      } else if (mode === 'completed') {
        if (boxNovideo) boxNovideo.style.display = 'none';
        if (boxPending) boxPending.style.display = 'none';
        if (boxCompleted) boxCompleted.style.display = 'flex';
        if (listCompleted) listCompleted.style.maxHeight = 'calc(100vh - 280px)';
      }
    }

    // Open Folder in Windows File Explorer
    async function openFolder(folderName) {
      try {
        await fetch('/api/open_folder', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ folder_name: folderName })
        });
      } catch (err) {
        alert('ไม่สามารถเปิดโฟลเดอร์ได้: ' + err);
      }
    }

    // Auto Video Generation with Hand-Shopee
    const videoPolling = {};
    async function generateVideo(folderName) {
      const btn = document.getElementById(`btn-gen-${folderName}`);
      const prog = document.getElementById(`prog-${folderName}`);
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<span class="animate-spin inline-block mr-1">⏳</span> กำลังส่งคำสั่ง...`;
        btn.className = "bg-slate-700 text-slate-300 px-2.5 py-0.5 rounded-lg text-[10px] font-medium flex items-center gap-1 whitespace-nowrap cursor-not-allowed";
      }
      if (prog) {
        prog.classList.remove('hidden');
        prog.innerText = "⏳ กำลังเชื่อมต่อ ComfyUI...";
      }
      try {
        const res = await fetch('/api/generate_video', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ folder_name: folderName })
        });
        const data = await res.json();
        if (!res.ok) {
          alert('เกิดข้อผิดพลาด: ' + (data.error || 'ไม่สามารถเริ่มทำคลิปได้'));
          loadQueue();
          return;
        }
        pollVideoStatus(folderName);
      } catch (err) {
        alert('เชื่อมต่อเซิร์ฟเวอร์ไม่ได้: ' + err.message);
        loadQueue();
      }
    }

    function pollVideoStatus(folderName) {
      if (videoPolling[folderName]) return;
      videoPolling[folderName] = setInterval(async () => {
        try {
          const res = await fetch('/api/video_status?folder_name=' + encodeURIComponent(folderName));
          const data = await res.json();
          const job = data[folderName];
          const btn = document.getElementById(`btn-gen-${folderName}`);
          const prog = document.getElementById(`prog-${folderName}`);
          if (job) {
            if (prog) {
              prog.classList.remove('hidden');
              prog.innerText = job.message || "กำลังประมวลผล...";
            }
            if (job.status === 'done') {
              clearInterval(videoPolling[folderName]);
              delete videoPolling[folderName];
              if (btn) {
                btn.className = "bg-emerald-600 text-white px-2.5 py-0.5 rounded-lg text-[10px] font-semibold";
                btn.innerText = "✅ เสร็จแล้ว!";
              }
              setTimeout(() => { loadQueue(); }, 1200);
            } else if (job.status === 'error') {
              clearInterval(videoPolling[folderName]);
              delete videoPolling[folderName];
              if (btn) {
                btn.disabled = false;
                btn.className = "bg-rose-600 text-white px-2.5 py-0.5 rounded-lg text-[10px]";
                btn.innerText = "❌ ลองใหม่";
              }
            } else if (job.status === 'running') {
              if (btn) {
                btn.disabled = true;
                btn.innerHTML = `<span class="animate-spin inline-block mr-1">⏳</span> กำลังทำคลิป...`;
              }
            }
          }
        } catch (e) {}
      }, 3000);
    }

    // Load Queue
    async function loadQueue() {
      const folder = document.getElementById('input-folder').value.trim();
      const listNovideo = document.getElementById('items-novideo-list');
      const listPending = document.getElementById('items-pending-list');
      const listCompleted = document.getElementById('items-completed-list');
      if (listNovideo) listNovideo.innerHTML = '<div class="text-center py-6 text-slate-500 text-xs">กำลังสแกน...</div>';
      if (listPending) listPending.innerHTML = '<div class="text-center py-8 text-slate-500 text-xs">กำลังสแกนโฟลเดอร์...</div>';
      if (listCompleted) listCompleted.innerHTML = '<div class="text-center py-8 text-slate-500 text-xs">กำลังสแกนโฟลเดอร์...</div>';

      try {
        const res = await fetch('/api/queue?dir=' + encodeURIComponent(folder));
        const data = await res.json();
        queueItems = data.items || [];
        renderQueue();
      } catch (err) {
        if (listPending) listPending.innerHTML = `<div class="text-center py-8 text-rose-400 text-xs">โหลดคิวล้มเหลว: ${err}</div>`;
      }
    }

    // Render Queue Items (Split into No-Video, Ready, and Completed Boxes)
    function renderQueue() {
      const listNovideo = document.getElementById('items-novideo-list');
      const listPending = document.getElementById('items-pending-list');
      const listCompleted = document.getElementById('items-completed-list');

      const noVideoItems = queueItems.filter(i => !i.has_video && i.status !== 'completed');
      const readyItems = queueItems.filter(i => i.has_video && (i.status === 'pending' || i.status === 'failed'));
      const completedItems = queueItems.filter(i => i.status === 'completed');

      // Update counters & badges
      const statTotal = document.getElementById('stat-total');
      const statNovideo = document.getElementById('stat-novideo');
      const statPending = document.getElementById('stat-pending');
      const statCompleted = document.getElementById('stat-completed');
      if (statTotal) statTotal.textContent = queueItems.length;
      if (statNovideo) statNovideo.textContent = noVideoItems.length;
      if (statPending) statPending.textContent = readyItems.length;
      if (statCompleted) statCompleted.textContent = completedItems.length;

      const badgeNovideo = document.getElementById('badge-novideo-count');
      const badgePending = document.getElementById('badge-pending-count');
      const badgeCompleted = document.getElementById('badge-completed-count');
      if (badgeNovideo) badgeNovideo.textContent = `${noVideoItems.length} สินค้า`;
      if (badgePending) badgePending.textContent = `${readyItems.length} คลิป`;
      if (badgeCompleted) badgeCompleted.textContent = `${completedItems.length} คลิป`;

      const tabBadgeNovideo = document.getElementById('tab-badge-novideo');
      const tabBadgePending = document.getElementById('tab-badge-pending');
      const tabBadgeCompleted = document.getElementById('tab-badge-completed');
      if (tabBadgeNovideo) tabBadgeNovideo.textContent = noVideoItems.length;
      if (tabBadgePending) tabBadgePending.textContent = readyItems.length;
      if (tabBadgeCompleted) tabBadgeCompleted.textContent = completedItems.length;

      // Adjust visibility of box-novideo in split view
      const boxNovideo = document.getElementById('box-novideo');
      if (currentQueueView === 'split' && boxNovideo) {
        boxNovideo.style.display = noVideoItems.length > 0 ? 'flex' : 'none';
      }

      // 1. Render No-Video Items (Waiting for .mp4)
      if (!noVideoItems.length) {
        if (listNovideo) {
          listNovideo.innerHTML = `
            <div class="text-center py-6 text-slate-500 text-xs">
              <div>✨ ไม่มีสินค้ารอทำคลิป</div>
              <div class="text-[10px] text-slate-600 mt-0.5">ทุกรายการมีไฟล์วิดีโอ .mp4 ครบแล้ว</div>
            </div>
          `;
        }
      } else if (listNovideo) {
        listNovideo.innerHTML = noVideoItems.map(item => {
          return `
            <div class="bg-slate-950/70 border border-sky-950/70 hover:border-sky-500/40 rounded-xl p-3 flex items-start gap-3 transition">
              <div class="mt-0.5 w-6 h-6 rounded-lg bg-sky-500/20 text-sky-400 border border-sky-500/30 flex items-center justify-center text-xs flex-shrink-0 font-bold">
                📷
              </div>
              
              <div class="flex-1 min-w-0">
                <div class="flex items-center justify-between gap-2">
                  <span class="text-xs font-bold text-slate-200 truncate">[${item.index}] ${item.title}</span>
                  <span class="bg-sky-500/20 text-sky-300 border border-sky-500/30 px-2 py-0.5 rounded text-[10px] font-semibold whitespace-nowrap">🎬 รอทำคลิป</span>
                </div>

                <div class="text-[11px] text-slate-400 truncate mt-0.5">📁 ${item.folder_name}</div>
                
                <div class="text-[11px] text-slate-500 truncate mt-1">
                  💬 ${item.caption || 'ไม่มีแคปชัน'}
                </div>

                <div class="flex items-center justify-between gap-2 mt-2 pt-1.5 border-t border-slate-900 text-[11px]">
                  <div class="flex items-center gap-2">
                    <span class="text-sky-300 flex items-center gap-1 font-medium text-[10px]">🖼️ ${item.image_count || 0} ภาพ HD</span>
                    <span class="text-slate-600">•</span>
                    <span class="text-amber-400 text-[10px]">⚠️ ขาดไฟล์วิดีโอ .mp4</span>
                  </div>
                  <div class="flex items-center gap-2">
                    ${item.url ? `<a href="${item.url}" target="_blank" class="text-orange-400 hover:text-orange-300 flex items-center gap-1 text-[10px]">🔗 Shopee</a>` : ''}
                    <button onclick="openFolder('${item.folder_name}')" title="เปิดโฟลเดอร์ในคอม" class="bg-sky-500/20 hover:bg-sky-500/30 text-sky-300 border border-sky-500/40 px-2 py-0.5 rounded-lg text-[10px] transition font-medium flex items-center gap-1 whitespace-nowrap">
                      <span>📁</span> โฟลเดอร์
                    </button>
                    <button id="btn-gen-${item.folder_name}" onclick="generateVideo('${item.folder_name}')" title="รันสกิล Hand-Shopee อัตโนมัติ: Qwen ➔ Gemini TTS ➔ MiniMax H3 ➔ Render" class="bg-gradient-to-r from-orange-500 to-amber-600 hover:from-orange-600 hover:to-amber-700 text-white font-semibold px-2.5 py-0.5 rounded-lg text-[10px] shadow transition flex items-center gap-1 whitespace-nowrap">
                      <span>🎬</span> ทำคลิป Hand-Shopee
                    </button>
                  </div>
                </div>
                <div id="prog-${item.folder_name}" class="hidden text-[10px] text-amber-300 bg-amber-500/10 border border-amber-500/20 rounded px-2 py-1 mt-1.5 flex items-center gap-1.5">
                </div>
              </div>
            </div>
          `;
        }).join('');
      }

      // 2. Render Ready Items (With Checkboxes)
      if (!readyItems.length) {
        listPending.innerHTML = `
          <div class="text-center py-8 text-slate-500 text-xs space-y-1">
            <div class="text-xl">🎉</div>
            <div class="font-semibold text-slate-300">ไม่มีคลิปรอโพสต์</div>
            <div class="text-[10px] text-slate-500">ใส่คลิป .mp4 ในโฟลเดอร์เพื่อส่งขึ้นคิวโพสต์</div>
          </div>
        `;
      } else {
        listPending.innerHTML = readyItems.map(item => {
          const isFailed = item.status === 'failed';
          const badge = isFailed
            ? '<span class="bg-rose-500/20 text-rose-400 border border-rose-500/30 px-2 py-0.5 rounded text-[10px] font-semibold whitespace-nowrap">❌ ไม่ผ่าน</span>'
            : '<span class="bg-amber-500/20 text-amber-300 border border-amber-500/30 px-2 py-0.5 rounded text-[10px] whitespace-nowrap">⏳ พร้อมโพสต์</span>';

          return `
            <div class="bg-slate-950/70 border border-slate-800/80 hover:border-orange-500/40 rounded-xl p-3 flex items-start gap-3 transition">
              <input type="checkbox" class="pending-item-checkbox mt-1 accent-orange-500 w-4 h-4 cursor-pointer" data-folder="${item.folder_name}" checked onchange="updateSelectedCount()" />
              
              <div class="flex-1 min-w-0">
                <div class="flex items-center justify-between gap-2">
                  <span class="text-xs font-bold text-slate-200 truncate">[${item.index}] ${item.title}</span>
                  ${badge}
                </div>

                <div class="text-[11px] text-slate-400 truncate mt-0.5">📁 ${item.folder_name} (🎥 ${item.video_name})</div>
                
                <div class="text-[11px] text-slate-500 truncate mt-1">
                  💬 ${item.caption || 'ไม่มีแคปชัน'}
                </div>

                <div class="flex items-center justify-between gap-2 mt-2 pt-1.5 border-t border-slate-900 text-[11px]">
                  <div class="flex items-center gap-3">
                    ${item.url ? `<a href="${item.url}" target="_blank" class="text-orange-400 hover:text-orange-300 flex items-center gap-1">🔗 ลิงก์สินค้า Shopee</a>` : '<span class="text-slate-600">ไม่มีลิงก์สินค้า</span>'}
                    ${item.review_image_exists ? `<a href="/api/review/${item.folder_name}" target="_blank" class="text-teal-400 hover:text-teal-300 flex items-center gap-1">📸 ดูภาพหน้ารีวิว</a>` : ''}
                  </div>
                  <button onclick="openFolder('${item.folder_name}')" class="text-slate-400 hover:text-slate-200 text-[10px] flex items-center gap-1">
                    📁 โฟลเดอร์
                  </button>
                </div>
              </div>
            </div>
          `;
        }).join('');
      }

      // Render Completed Items (NO Checkbox!)
      if (!completedItems.length) {
        listCompleted.innerHTML = `
          <div class="text-center py-8 text-slate-500 text-xs">
            <div class="text-2xl mb-1">📦</div>
            <div>ยังไม่มีคลิปที่โพสต์สำเร็จในโฟลเดอร์นี้</div>
          </div>
        `;
      } else {
        listCompleted.innerHTML = completedItems.map(item => {
          return `
            <div class="bg-slate-950/70 border border-emerald-950/60 hover:border-emerald-500/40 rounded-xl p-3 flex items-start gap-3 transition">
              <div class="mt-0.5 w-5 h-5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 flex items-center justify-center text-xs flex-shrink-0 font-bold">
                ✓
              </div>
              
              <div class="flex-1 min-w-0">
                <div class="flex items-center justify-between gap-2">
                  <span class="text-xs font-bold text-slate-200 truncate">[${item.index}] ${item.title}</span>
                  <span class="bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 px-2 py-0.5 rounded text-[10px] font-semibold whitespace-nowrap">✅ สำเร็จแล้ว</span>
                </div>

                <div class="text-[11px] text-slate-400 truncate mt-0.5">📁 ${item.folder_name}</div>
                
                <div class="text-[11px] text-slate-500 truncate mt-1">
                  💬 ${item.caption || 'ไม่มีแคปชัน'}
                </div>

                <div class="flex items-center justify-between gap-2 mt-2 pt-1.5 border-t border-slate-900 text-[11px]">
                  <div class="flex items-center gap-3">
                    ${item.url ? `<a href="${item.url}" target="_blank" class="text-orange-400 hover:text-orange-300 flex items-center gap-1">🔗 ลิงก์สินค้า Shopee</a>` : '<span class="text-slate-600">ไม่มีลิงก์สินค้า</span>'}
                    ${item.review_image_exists ? `<a href="/api/review/${item.folder_name}" target="_blank" class="text-teal-400 hover:text-teal-300 flex items-center gap-1">📸 ดูภาพหน้ารีวิว</a>` : ''}
                  </div>
                  <button onclick="requeueItem('${item.folder_name}')" title="ย้ายคลิปนี้กลับไปที่ช่องรอโพสต์ใหม่" class="text-slate-400 hover:text-amber-400 bg-slate-900 hover:bg-slate-800 border border-slate-800 px-2 py-0.5 rounded text-[10px] transition flex items-center gap-1 whitespace-nowrap">
                    <span>🔄</span> นำกลับมารอโพสต์ใหม่
                  </button>
                </div>
              </div>
            </div>
          `;
        }).join('');
      }

      updateSelectedCount();
    }

    function updateSelectedCount() {
      const checked = document.querySelectorAll('.pending-item-checkbox:checked').length;
      const selEl = document.getElementById('selected-count');
      if (selEl) selEl.textContent = checked;
    }

    function selectAllPending(val) {
      document.querySelectorAll('.pending-item-checkbox').forEach(cb => cb.checked = val);
      updateSelectedCount();
    }

    // Re-queue single item back to pending
    async function requeueItem(folderName) {
      if (!confirm(`ต้องการย้ายคลิป "${folderName}" กลับมารอโพสต์ใหม่หรือไม่?`)) return;
      try {
        const res = await fetch('/api/requeue', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ folder_name: folderName })
        });
        const data = await res.json();
        if (data.success) {
          await loadQueue();
        } else {
          alert(data.error || 'ไม่สามารถย้ายได้');
        }
      } catch (err) {
        alert('เกิดข้อผิดพลาด: ' + err);
      }
    }

    // Re-queue all completed items back to pending
    async function requeueAllCompleted() {
      const completed = queueItems.filter(i => i.status === 'completed');
      if (!completed.length) {
        alert('ไม่มีรายการที่โพสต์แล้ว');
        return;
      }
      if (!confirm(`ต้องการย้ายคลิปที่โพสต์แล้วทั้งหมด (${completed.length} คลิป) กลับมารอโพสต์ใหม่หรือไม่?`)) return;
      try {
        const res = await fetch('/api/requeue_all', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
          await loadQueue();
        } else {
          alert(data.error || 'ไม่สามารถย้ายได้');
        }
      } catch (err) {
        alert('เกิดข้อผิดพลาด: ' + err);
      }
    }

    // Start Posting (Only posts checked items in Pending box)
    async function startPosting() {
      const checkedBoxes = Array.from(document.querySelectorAll('.pending-item-checkbox:checked'));
      const items = checkedBoxes.map(cb => cb.dataset.folder);

      if (!items.length) {
        alert('กรุณาเลือกคลิปอย่างน้อย 1 คลิปในช่องรอโพสต์');
        return;
      }

      if (!confirm(`ยืนยันการเริ่มโพสต์ ${items.length} คลิปตามคิวที่เลือก?`)) {
        return;
      }

      const folder = document.getElementById('input-folder').value.trim();
      const payload = {
        items: items,
        queue_dir: folder,
        delay_minutes: selectedDelay
      };

      try {
        const res = await fetch('/api/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.error) alert(data.error);
        else updateStatus();
      } catch (err) {
        alert("เกิดข้อผิดพลาดในการสั่งรัน: " + err);
      }
    }

    // Import Shopee Product via Qwen AI
    async function importShopeeProduct() {
      const urlInput = document.getElementById('input-shopee-url');
      const maxImagesSelect = document.getElementById('select-max-images');
      const btn = document.getElementById('btn-import-shopee');
      const statusText = document.getElementById('import-status-text');

      const rawUrl = urlInput.value.trim();
      if (!rawUrl) {
        alert('กรุณากรอกหรือวางลิงก์สินค้า Shopee');
        urlInput.focus();
        return;
      }

      btn.disabled = true;
      btn.innerHTML = '<span class="inline-block animate-spin mr-1">⏳</span> กำลังดึงข้อมูล...';
      statusText.className = 'text-[11px] text-amber-300 truncate flex-1 animate-pulse';
      statusText.textContent = '🔍 กำลังเปิดหน้าสินค้า Shopee และให้ Qwen 3.8 เขียนสคริปต์...';

      try {
        const res = await fetch('/api/import_shopee', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            url: rawUrl,
            max_images: parseInt(maxImagesSelect.value, 10)
          })
        });
        const data = await res.json();
        if (data.error) {
          statusText.className = 'text-[11px] text-rose-400 truncate flex-1 font-medium';
          statusText.textContent = '❌ ดึงข้อมูลไม่สำเร็จ: ' + data.error;
          alert('ดึงข้อมูลไม่สำเร็จ: ' + data.error);
        } else {
          const results = data.results || [];
          const count = results.length;
          statusText.className = 'text-[11px] text-emerald-400 truncate flex-1 font-semibold';
          if (count === 1) {
            const item = results[0];
            statusText.textContent = `🎉 สำเร็จ! [${item.index}] ${item.title.substring(0, 30)}... (โหลด ${item.images_count} รูป)`;
          } else {
            statusText.textContent = `🎉 สำเร็จ! นำเข้าแล้ว ${count} รายการ`;
          }
          urlInput.value = '';
          await loadQueue();
        }
      } catch (err) {
        statusText.className = 'text-[11px] text-rose-400 truncate flex-1';
        statusText.textContent = '❌ เกิดข้อผิดพลาด: ' + err;
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<span>⚡</span> ดึงสินค้า & แต่งสคริปต์';
      }
    }

    // Stop Posting
    async function stopPosting() {
      if (confirm('คุณต้องการหยุดการโพสต์คิวนี้ใช่หรือไม่? (ระบบจะหยุดหลังจากจบคลิปที่กำลังรันอยู่)')) {
        await fetch('/api/stop', { method: 'POST' });
        updateStatus();
      }
    }

    // Check if running in All-in-One Embedded App
    const urlParams = new URLSearchParams(window.location.search);
    const isEmbedded = urlParams.get('embedded') === '1';
    if (isEmbedded) {
      const colLive = document.getElementById('col-live-screen');
      if (colLive) colLive.style.display = 'none';
      const colQ = document.getElementById('col-queue');
      const colC = document.getElementById('col-controls');
      if (colQ) colQ.className = 'lg:col-span-6 flex flex-col gap-4';
      if (colC) colC.className = 'lg:col-span-6 flex flex-col gap-4';
      const scrcpyBtn = document.getElementById('btn-header-scrcpy');
      if (scrcpyBtn) {
        scrcpyBtn.innerHTML = '<span>⚡</span> เปิดจอสดแยก';
        scrcpyBtn.title = 'เปิดหน้าต่างจอสด scrcpy 60 FPS แยกต่างหาก';
      }
      isStreamActive = false; // Turn off screenshot polling since real scrcpy is right there
    }

    // Initial load
    document.getElementById('input-folder').value = "C:\\\\Users\\\\krits\\\\OneDrive\\\\Desktop\\\\shopee-post";
    loadQueue();
    updateStatus();
    if (!isEmbedded) fetchNextFrame();
    setInterval(updateStatus, 2000);
  </script>
</body>
</html>
"""

def run():
    try:
        http.server.ThreadingHTTPServer.allow_reuse_address = True
        print(f"============================================================")
        print(f"🚀 Shopee Video Poster Dashboard starting on http://localhost:{PORT}")
        print(f"============================================================")
        # Start screenshot worker thread
        threading.Thread(target=screenshot_caching_worker, daemon=True).start()
        with http.server.ThreadingHTTPServer(("", PORT), DashboardHandler) as httpd:
            httpd.serve_forever()
    except Exception:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run()
