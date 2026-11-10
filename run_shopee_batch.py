import sys
import time
from pathlib import Path
import subprocess
import json
import argparse

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

QUEUE_DIR = Path(r"D:\Dev\ComfyUI\ugc_runpod_womenswear_20_2026-11-05\shopee_post_queue_2026-11-06")
PREPARE_SCRIPT = Path(r"D:\Dev\ComfyUI\tools\shopee_prepare.py")
TOUCH = Path(r"D:\Dev\ComfyUI\tools\shopee_touch.py")
REVIEW_DIR = Path(r"C:\Users\krits\.gemini\antigravity\brain\08d6ea2b-be9b-4ffc-9fa4-a765dae735ce\reviews")
REVIEW_DIR.mkdir(parents=True, exist_ok=True)
PYTHON = sys.executable

ALL_ITEMS = [
    "g97_gray_straight_trousers",        # 1 - DONE
    "jennie_black_short_pants",          # 2 - DONE
    "fancy_belle_black_skort",           # 3 - DONE
    "ap_stores_cream_cartoon_pajamas",   # 4
    "ghaohes_dark_denim_shorts",         # 5
    "striped_puff_sleeve_blouse",        # 6
    "kals_mira_brown_tank_top",          # 7
    "paloy_blue_poppy_jeans",            # 8
    "olive_brown_soft_long_sleeve",      # 9
    "yy_black_knit_turtleneck",          # 10
    "sanukthai_cotton_pajama_set",       # 11
    "beming_knit_cardigan",              # 12
    "belin_star_high_waist_jeans",       # 13
    "minilab_wide_leg_trousers",         # 14
    "paradise_denim_mini_skirt",         # 15
    "suda_sada_denim_shorts",            # 16
    "happy_tee_womens_polo",             # 17
    "amma_wide_leg_pants",               # 18
    "haas_v_neck_long_sleeve_shirt",     # 19
    "spinnyhouse_ribbed_collared_top",   # 20
]

PROGRESS_FILE = Path(r"D:\Dev\ComfyUI\tools\batch_progress.json")

def load_progress():
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "completed": [
            "g97_gray_straight_trousers",
            "jennie_black_short_pants",
            "fancy_belle_black_skort"
        ],
        "failed": {}
    }

def save_progress(data):
    PROGRESS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def reset_to_live_and_video():
    for attempt in range(6):
        try:
            res = subprocess.run([PYTHON, str(PREPARE_SCRIPT), "--phone-status"],
                                 capture_output=True, text=True, timeout=12, encoding="utf-8")
            if "Shopee Live & Video is ready" in res.stdout:
                return True
        except Exception:
            pass
        try:
            # Tap discard if exit confirmation dialog is up
            subprocess.run([PYTHON, str(TOUCH), "0.50", "0.870"], timeout=10, capture_output=True)
            time.sleep(1.0)
            # Tap back arrow
            subprocess.run([PYTHON, str(TOUCH), "0.057", "0.057"], timeout=10, capture_output=True)
            time.sleep(1.2)
        except Exception:
            pass
    return False

def post_item(item_name, index):
    folder = QUEUE_DIR / item_name
    review_path = REVIEW_DIR / f"{index:02d}_{item_name}.png"
    print(f"\n=======================================================", flush=True)
    print(f"[{index}/20] Processing {item_name}...", flush=True)
    print(f"=======================================================", flush=True)
    
    reset_to_live_and_video()
    
    cmd = [
        PYTHON,
        str(PREPARE_SCRIPT),
        str(folder),
        "--publish",
        "--review",
        str(review_path)
    ]
    
    for attempt in range(1, 3):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=180)
            if proc.returncode == 0:
                print(f"[SUCCESS] [{index}/20] {item_name} published successfully!", flush=True)
                return True
            else:
                print(f"[RETRY {attempt}/2] Error: {proc.stderr.strip()}", flush=True)
                reset_to_live_and_video()
                time.sleep(2.0)
        except Exception as e:
            print(f"[RETRY {attempt}/2] Exception: {e}", flush=True)
            reset_to_live_and_video()
            time.sleep(2.0)
            
    return False

def run_range(start_idx, end_idx):
    progress = load_progress()
    for i in range(start_idx, end_idx + 1):
        item = ALL_ITEMS[i - 1]
        if item in progress["completed"]:
            print(f"[{i}/20] {item} already completed. Skipping.", flush=True)
            continue
        success = post_item(item, i)
        if success:
            progress["completed"].append(item)
            save_progress(progress)
        else:
            progress["failed"][item] = "Failed after retry"
            save_progress(progress)
        time.sleep(3.0)
    print(f"\nBatch range [{start_idx} to {end_idx}] finished. Total completed: {len(progress['completed'])}/20", flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=4)
    parser.add_argument("--end", type=int, default=20)
    args = parser.parse_args()
    run_range(args.start, args.end)
