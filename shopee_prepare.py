"""Prepare one Shopee Video draft from a product folder. Run from Live & Video."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from shopee_touch import TouchSession


ADB = os.environ.get("ADB", "adb")
TOUCH = Path(__file__).with_name("shopee_touch.py")
PACKAGE = "com.shopee.th"
TOUCH_SESSION = None
FLAGS_NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0x08000000


def adb(*args):
    return subprocess.check_output([ADB, *args], timeout=25, creationflags=FLAGS_NO_WINDOW)


def activity():
    output = adb("shell", "dumpsys", "activity", "activities").decode(errors="replace")
    return next((line for line in output.splitlines() if "topResumedActivity" in line), "")


def require_activity(fragment):
    if fragment not in activity():
        raise RuntimeError(f"Expected foreground activity {fragment}")


def require_start():
    foreground = activity()
    if "PublishVideoActivity" in foreground or "SSZMultipleEditActivity" in foreground or "SSZMediaActivity" in foreground or "SSZBasePreviewActivity" in foreground:
        # If stuck in any sub-activity, cleanly restart Shopee
        adb("shell", "am", "force-stop", "com.shopee.th")
        time.sleep(0.8)
        adb("shell", "monkey", "-p", "com.shopee.th", "-c", "android.intent.category.LAUNCHER", "1")
        time.sleep(3.5)
        tap(0.582, 0.920)
        time.sleep(1.5)
        return None

    if PACKAGE not in foreground:
        # Launch Shopee if not open
        adb("shell", "monkey", "-p", "com.shopee.th", "-c", "android.intent.category.LAUNCHER", "1")
        time.sleep(3.5)
        tap(0.582, 0.920)
        time.sleep(1.5)
        return None

    fg = activity()
    if "ReactActivity" in fg or "ReactTransparentActivity" in fg:
        # Dismiss any open keyboard / comment input via Android nav back
        tap(0.766, 0.977)
        time.sleep(0.5)
        return None

    if "HomeActivity" in fg:
        # On Shopee home page: switch to Live & Video tab (bottom bar 4th icon)
        tap(0.582, 0.920)
        time.sleep(1.5)
        return None

    return None


def nodes():
    remote = f"/data/local/tmp/shopee-prepare-{uuid.uuid4().hex}.xml"
    try:
        for _ in range(4):
            result = adb("shell", "uiautomator", "dump", "--compressed", remote)
            if b"dumped to" in result:
                break
            result = adb("shell", "uiautomator", "dump", remote)
            if b"dumped to" in result:
                break
            time.sleep(0.4)
        else:
            raise RuntimeError("Shopee screen was not readable")
        return list(ET.fromstring(adb("exec-out", "cat", remote)).iter("node"))
    finally:
        adb("shell", "rm", "-f", remote)


def find(items, label, *, prefix=False):
    def matches(value):
        return value.startswith(label) if prefix else value == label

    found = [node for node in items if any(matches(node.get(key, "")) for key in ("text", "content-desc"))]
    if not found:
        raise RuntimeError(f"Missing Shopee control: {label}")
    return found[-1]


def tap(x, y, *options):
    require_activity(PACKAGE)
    if TOUCH_SESSION is not None:
        if options and len(options) == 3 and options[0] == "--swipe-to":
            TOUCH_SESSION.swipe(x, y, float(options[1]), float(options[2]))
        else:
            TOUCH_SESSION.tap(x, y)
        time.sleep(0.35)
        return
    subprocess.run([sys.executable, str(TOUCH), str(x), str(y), *options], check=True, timeout=25, stdout=subprocess.DEVNULL, creationflags=FLAGS_NO_WINDOW)
    time.sleep(0.8)


def tap_node(node):
    if any(node.get(key, "").strip() == "โพสต์" for key in ("text", "content-desc")):
        raise RuntimeError("The review workflow cannot tap the publish button")
    x1, y1, x2, y2 = map(int, re.findall(r"\d+", node.attrib["bounds"]))
    tap((x1 + x2) / 2440, (y1 + y2) / 5424)


def wait_for_control(label, timeout=25):
    deadline = time.monotonic() + timeout
    while True:
        try:
            return find(nodes(), label)
        except RuntimeError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.6)


def clipboard(value):
    if TOUCH_SESSION is not None:
        TOUCH_SESSION.clipboard(value)
        return
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "text.txt"
        path.write_text(value, encoding="utf-8")
        subprocess.run([sys.executable, str(TOUCH), "0", "0", "--clipboard", str(path)], check=True, timeout=25, creationflags=FLAGS_NO_WINDOW)


def review_image(path):
    path.write_bytes(adb("exec-out", "screencap", "-p"))


def _prepare(folder, review, check_only=False):
    notes_file = folder / "product_notes.json"
    if not notes_file.exists():
        notes_file = folder / "notes.json"
    
    product = {}
    if notes_file.exists():
        product = json.loads(notes_file.read_text(encoding="utf-8-sig"))
    elif (folder / "notes.txt").exists():
        lines = (folder / "notes.txt").read_text(encoding="utf-8-sig").splitlines()
        url_line = lines[0].strip() if len(lines) > 0 else ""
        caption_line = lines[1].strip() if len(lines) > 1 else ""
        product = {"title": folder.name, "shopee_url": url_line, "captions": [caption_line]}
    else:
        raise FileNotFoundError(f"ไม่พบไฟล์ product_notes.json หรือ notes.json ในโฟลเดอร์ {folder.name}")

    caption = product.get("captions", [""])[0].strip() if product.get("captions") else ""
    url = product.get("shopee_url", "").strip()
    if not caption or len(caption) > 140:
        raise ValueError("Expected a caption of 1–140 characters")
    
    clean_match = re.search(r"https://shopee\.co\.th/product/\d+/\d+", url)
    if clean_match:
        url = clean_match.group(0)
    else:
        raise ValueError(f"Expected a direct Shopee Thailand product link (https://shopee.co.th/product/SHOP_ID/ITEM_ID), got: {url}")

    videos = list(folder.glob("*.mp4"))
    if not videos:
        raise FileNotFoundError(f"ไม่พบไฟล์วิดีโอ .mp4 ในโฟลเดอร์ {folder.name}")
    sharp = [v for v in videos if "_final_1080_sharp" in v.name]
    video = sharp[0] if sharp else videos[0]
    if check_only:
        print(f"{video}\n{product['title']}\n{url}\n{caption}")
        return
    if "Physical size: 1220x2712" not in adb("shell", "wm", "size").decode():
        raise RuntimeError("This workflow uses the calibrated 1220×2712 phone")
    create = require_start()
    start_activity = activity()

    album = f"SV_{uuid.uuid4().hex[:8]}"
    directory = f"/sdcard/Movies/{album}"
    filename = video.name
    remote = f"{directory}/{filename}"
    adb("shell", "mkdir", "-p", directory)
    adb("push", str(video), remote)
    adb("shell", "am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d", f"file://{remote}")
    for _ in range(8):
        media = adb("shell", "content", "query", "--uri", "content://media/external/video/media",
                    "--projection", "_data").decode(errors="replace")
        indexed_directory = directory.replace("/sdcard/", "/storage/emulated/0/", 1)
        entries = [line.split("_data=", 1)[1] for line in media.splitlines()
                   if f"_data={directory}/" in line or f"_data={indexed_directory}/" in line]
        if entries in ([remote], [f"{indexed_directory}/{filename}"]):
            break
        time.sleep(1)
    else:
        raise RuntimeError("Could not verify the clip in its dedicated album")

    if PACKAGE not in activity():
        raise RuntimeError("Shopee left the starting screen while indexing the clip")
    # Open camera / media activity by tapping create icon (+)
    for attempt in range(5):
        if attempt > 0:
            # Dismiss any keyboard or popup that may have blocked the tap
            tap(0.5, 0.2)
            time.sleep(0.5)
        # Tap create icon (+) at top right (calibrated center 0.930, 0.065)
        tap(0.930, 0.065)
        time.sleep(1.8)
        if "SSZMediaActivity" in activity():
            break
        # If camera didn't open and we are on HomeActivity, re-enter Live & Video
        if "HomeActivity" in activity():
            tap(0.582, 0.920)
            time.sleep(1.2)
    
    # Check if we are on the camera screen (needs tapping 'คลังภาพ') or already in gallery
    try:
        gallery_nodes = nodes()
        has_gallery = any("สามารถเลือกได้สูงสุด" in n.get("text", "") or "tv_media_hint" in n.get("resource-id", "") for n in gallery_nodes)
    except Exception:
        gallery_nodes = []
        has_gallery = False

    if not has_gallery:
        if "SSZMediaActivity" not in activity():
            raise RuntimeError("ไม่สามารถเปิดหน้ากล้อง Shopee ได้ (SSZMediaActivity ไม่ทำงาน - กรุณาตรวจสอบหน้าจอ)")
        try:
            target_node = find(gallery_nodes, "คลังภาพ")
            tap_node(target_node)
        except Exception:
            # Fallback to calibrated tap on 'คลังภาพ' button on camera viewfinder
            tap(0.798, 0.801)
        time.sleep(1.8)
        try:
            gallery_nodes = nodes()
        except Exception:
            gallery_nodes = []

    # Open album dropdown: find tv_pick_title or tap top-center (x=0.50, y=0.063)
    dropdown = next((n for n in gallery_nodes if n.get("resource-id") in ("com.shopee.th:id/tv_pick_title", "com.shopee.th:id/lyt_pick_title")), None)
    if dropdown is not None:
        tap_node(dropdown)
    else:
        tap(0.50, 0.063)
    time.sleep(1.2)

    choose_album(album)
    finish_editor(product, caption, url, review)
    return album, directory


def prepare(folder, review, check_only=False):
    global TOUCH_SESSION
    if check_only:
        return _prepare(folder, review, check_only=True)
    with TouchSession(ADB) as session:
        TOUCH_SESSION = session
        try:
            return _prepare(folder, review, check_only=False)
        finally:
            TOUCH_SESSION = None


def choose_album(album):
    for _ in range(8):
        controls = nodes()
        try:
            target = find(controls, album)
        except RuntimeError:
            tap(0.5, 0.82, "--swipe-to", "0.5", "0.3")
            time.sleep(0.8)
            continue
        tap_node(target)
        break
    else:
        raise RuntimeError(f"Album not found after scrolling: {album}")
    time.sleep(1.2)
    gallery = nodes()
    durations = [node for node in gallery if re.fullmatch(r"\d{2}:\d{2}", node.get("text", ""))]
    if durations:
        tap_node(durations[0])
    else:
        # Tap first clip thumbnail in grid
        tap(0.18, 0.15)
    time.sleep(0.8)
    tap_node(wait_for_control("ถัดไป"))


def finish_editor(product, caption, url, review):
    time.sleep(1.5)
    tap_node(wait_for_control("ถัดไป", timeout=15))
    time.sleep(2.0)
    require_activity("PublishVideoActivity")

    # PublishVideoActivity can animate continuously, so its accessibility dump
    # can fail to settle. These controls use the calibrated screen positions.
    tap(0.49, 0.112)
    time.sleep(0.6)
    clipboard(caption)
    time.sleep(0.5)
    tap(0.50, 0.650)  # Gboard clipboard suggestion
    time.sleep(0.5)
    tap(0.910, 0.059)  # Confirm caption (ตกลง)
    time.sleep(1.0)
    tap(0.78, 0.292)  # Add product
    time.sleep(2.0)
    tap(0.93, 0.056)  # Link importer
    time.sleep(1.5)
    tap(0.40, 0.17)
    time.sleep(0.5)
    clipboard(url)
    time.sleep(0.5)
    tap(0.50, 0.365)  # Paste link
    time.sleep(1.2)
    tap(0.50, 0.365)  # Import
    
    # Wait dynamically for product import results (up to 8 seconds)
    import_ok = False
    for _ in range(8):
        time.sleep(1.0)
        try:
            curr_nodes = nodes()
            if any("นำเข้าไม่สำเร็จ" in (n.get("text") or "") or "ถูกยกเว้น" in (n.get("text") or "") for n in curr_nodes):
                print(f"⚠️ Shopee แจ้งเตือน: ลิงก์สินค้านี้ถูกยกเว้นหรือไม่สามารถนำเข้าได้ ({url})")
                break
            if any("เลือกทั้งหมด" in (n.get("text") or "") or "เพิ่ม" in (n.get("text") or "") for n in curr_nodes):
                if not any("ไม่มีสินค้า" in (n.get("text") or "") for n in curr_nodes):
                    import_ok = True
                    break
        except Exception:
            pass

    if import_ok:
        tap(0.187, 0.880)  # Select all
        time.sleep(1.0)
        tap(0.635, 0.879)  # Add 1
        time.sleep(2.5)
        # If still not returned to PublishVideoActivity, retry tapping Add
        if "PublishVideoActivity" not in activity():
            tap(0.635, 0.879)  # Retry Add
            time.sleep(2.5)
    else:
        # Import failed or excluded: tap back arrow twice to return cleanly
        tap(0.05, 0.05)
        time.sleep(1.0)
        tap(0.05, 0.05)
        time.sleep(1.0)
        raise RuntimeError(f"Shopee ไม่สามารถนำเข้าลิงก์สินค้านี้ได้ (สินค้าถูกยกเว้นหรือไม่ร่วมรายการ Affiliate): {url}")
    require_activity("PublishVideoActivity")
    tap(0.913, 0.496)  # Reuse permission, on by default in a fresh draft -> turn OFF
    time.sleep(0.6)
    tap(0.913, 0.682)  # AI disclosure, off by default in a fresh draft -> turn ON
    time.sleep(0.6)
    review_image(review)
    print(f"Review on phone: {product['title']} | {url}")
    print(f"Expected caption: {caption}")
    print(f"Review screenshot: {review}")


def publish(directory=None):
    require_activity("PublishVideoActivity")
    tap(0.56, 0.907)  # Publish
    time.sleep(7.0)
    fg = activity()
    if "PublishVideoActivity" in fg:
        raise RuntimeError("Shopee is still on the review screen; inspect the phone before retrying")
    if directory:
        try:
            adb("shell", "rm", "-rf", directory)
        except Exception:
            pass
    # If on Profile, return to Live & Video feed
    time.sleep(1.0)
    if "ReactActivity" in fg:
        # Tap back arrow to Live & Video
        tap(0.057, 0.057)
        time.sleep(1.0)
    return fg


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("product_folder", type=Path, nargs="?")
    parser.add_argument("--review", type=Path, default=Path(tempfile.gettempdir()) / "shopee-review.png")
    parser.add_argument("--check-only", action="store_true", help="Validate the product folder without contacting the phone")
    parser.add_argument("--phone-status", action="store_true", help="Check the starting screen without touching it")
    parser.add_argument("--publish", action="store_true", help="Complete publication after preparing the draft")
    args = parser.parse_args()
    try:
        if args.phone_status:
            require_start()
            print("Shopee Live & Video is ready.")
            sys.exit(0)
        if args.product_folder is None:
            parser.error("product_folder is required unless using --phone-status")
        res = prepare(args.product_folder, args.review, args.check_only)
        if args.publish and not args.check_only:
            publish(res[1] if res else None)
            print(f"Published successfully: {args.product_folder.name}")
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError, ET.ParseError) as error:
        parser.exit(1, f"Stopped: {error}\n")
