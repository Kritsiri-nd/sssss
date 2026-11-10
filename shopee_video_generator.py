import os
import sys
import json
import time
import base64
import wave
import shutil
import random
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

# Set UTF-8
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Paths
BASE_DIR = Path(r"D:\Dev\ComfyUI\tools\shopee_poster")
ASSETS_DIR = BASE_DIR / "assets"
STYLES_DIR = ASSETS_DIR / "styles"
COMFY_ROOT = Path(r"D:\Dev\ComfyUI\ComfyUI-Data\ComfyUI-Installs\ComfyUI\ComfyUI")
COMFY_INPUT = COMFY_ROOT / "input"
COMFY_OUTPUT = COMFY_ROOT / "output"
COMFY_API = "http://127.0.0.1:8188"
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"
FONT_PATH = r"C:\Windows\Fonts\tahomabd.ttf"
if not os.path.exists(FONT_PATH):
    FONT_PATH = r"C:\Windows\Fonts\arialbd.ttf"

def load_env_val(key, default=""):
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return os.environ.get(key, default)

# Keys for Gemini TTS
raw_gemini = load_env_val("GEMINI_KEYS", "")
GEMINI_KEYS = [k.strip() for k in raw_gemini.split(",") if k.strip()]
GEMINI_TTS_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash-lite-tts:generateContent"
QWEN_GATEWAY_URL = "https://gateway.9arm.co/v1/chat/completions"
QWEN_KEY = load_env_val("QWEN_API_KEY", "")

def log(msg, callback=None):
    print(f"[VideoGen] {msg}", flush=True)
    if callback:
        try:
            callback(msg)
        except Exception:
            pass

def comfy_get(endpoint):
    with urllib.request.urlopen(COMFY_API + endpoint, timeout=30) as r:
        return json.load(r)

def comfy_post(endpoint, payload):
    req = urllib.request.Request(
        COMFY_API + endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(e.read().decode('utf-8', 'replace'))

def comfy_free_memory():
    """Unload all models and release system RAM & GPU VRAM in ComfyUI."""
    try:
        req = urllib.request.Request(
            COMFY_API + "/free",
            data=json.dumps({"unload_models": True, "free_memory": True}).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            pass
        time.sleep(2)
    except Exception as e:
        print(f"[VideoGen] Warn: free memory failed ({e})")

def get_media_duration(path):
    cmd = [
        FFPROBE, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json", str(path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(json.loads(res.stdout)["format"]["duration"])

# ==========================================
# CATEGORY & SCENE PLANNING ENGINE (AI-Powered)
# ==========================================
def analyze_product_scene(title, description=""):
    """Dynamically classify product and build tailored scene, action, style ref, and negative prompt."""
    prompt = f"""Analyze this Shopee product for a realistic 9:16 vertical handheld demonstration video:
Product: {title}
Description: {description[:400]}

Choose the BEST category from:
1. tech_desk (mouse, keyboard, speaker, monitor, desk gear) -> style_file: 1793938008397-keyframe.jpg
2. gadget_small (earbuds, cable, charger, powerbank) -> style_file: 1793938094394-keyframe.jpg
3. wearable (watch, smartwatch, band, jewelry) -> style_file: 1793937989122-keyframe.jpg
4. mobile (smartphone, tablet, phone case) -> style_file: 1793937858241-keyframe.jpg
5. apparel_tops (jacket, shirt, t-shirt, hoodie, polo) -> style_file: 1793937821711-keyframe.jpg
6. apparel_bottoms (shorts, pants, trousers, skirt) -> style_file: 1793937844922-keyframe.jpg
7. home_appliance (fan, fridge, stove, kettle, vacuum) -> style_file: 1793937877917-keyframe.jpg
8. tabletop_lifestyle (bag, shoes, cosmetics, food, water bottle, general items) -> style_file: 1793937788265-keyframe.jpg

Return strictly valid JSON:
{{
  "category": "...",
  "style_file": "...",
  "short_name": "Clean English product name (3-5 words)",
  "scene": "1 English sentence describing a plausible home/desk/room setting matching this product with natural daylight",
  "action": "1-2 English sentences describing how 2 natural hands hold/point to this exact product",
  "ref_block": "Comma-separated English names of objects in the style reference that must NOT appear"
}}"""
    try:
        payload = {'model': 'qwen3.8-27b-fp8', 'messages': [{'role': 'user', 'content': prompt}], 'temperature': 0.2}
        headers = {'Authorization': f'Bearer {QWEN_KEY}', 'Content-Type': 'application/json', 'User-Agent': 'curl/7.88.1'}
        req = urllib.request.Request(QWEN_GATEWAY_URL, data=json.dumps(payload).encode('utf-8'), headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = json.loads(r.read().decode('utf-8'))['choices'][0]['message']['content'].strip()
            raw = raw.replace('```json', '').replace('```', '').strip()
            data = json.loads(raw)
            if data.get("style_file") and data.get("scene"):
                return data
    except Exception as e:
        print(f"[VideoGen] AI planning fallback: {e}")

    # Rule-based fallback
    t_lower = title.lower()
    if any(k in t_lower for k in ["เมาส์", "mouse", "คีย์บอร์ด", "keyboard", "ลำโพง", "speaker"]):
        return {
            "category": "tech_desk",
            "style_file": "1793938008397-keyframe.jpg",
            "short_name": title[:30],
            "scene": "a clean wooden computer desk with a softly blurred monitor and keyboard in the background, warm natural sunlight",
            "action": "The left hand steadies the product body while the right index finger gently points to its controls and main features.",
            "ref_block": "keyboard, keycaps, wristband, monitor"
        }
    elif any(k in t_lower for k in ["เสื้อ", "แจ็คเก็ต", "jacket", "shirt", "เชิ้ต", "t-shirt", "เสื้อยืด"]):
        return {
            "category": "apparel_tops",
            "style_file": "1793937821711-keyframe.jpg",
            "short_name": title[:30],
            "scene": "a dark warm-wood wardrobe with soft ambient light, garment hung neatly on a wooden hanger",
            "action": "The left hand steadies the shoulder on the wooden hanger while the right index finger points to the fabric and chest seams.",
            "ref_block": "keyboard, mouse, watch, phone, laptop, desk"
        }
    elif any(k in t_lower for k in ["หูฟัง", "earbuds", "cable", "สายชาร์จ"]):
        return {
            "category": "gadget_small",
            "style_file": "1793938094394-keyframe.jpg",
            "short_name": title[:30],
            "scene": "a warm wooden desk beside a bright window with gentle daylight and natural shadows",
            "action": "The left hand holds the compact product upright while the right index finger points to its key features.",
            "ref_block": "keyboard, shorts, clothes, socks"
        }
    else:
        return {
            "category": "tabletop_lifestyle",
            "style_file": "1793937788265-keyframe.jpg",
            "short_name": title[:30],
            "scene": "a warm clean wooden tabletop beside a window with soft natural lighting and realistic shadows",
            "action": "The left hand steadies the product while the right index finger gently indicates its main feature.",
            "ref_block": "keyboard, mouse, clothes, shorts, socks"
        }

def shorten_script_with_qwen(script, title):
    """Use Qwen 3.8 LLM to condense Thai voiceover to 15-18 words (~7-8 seconds)."""
    try:
        prompt = (
            f"ย่อบทพากย์ภาษาไทยนี้ให้กระชับมาก พูดจบภายใน 7 วินาที (ความยาวไม่เกิน 15-18 คำ) สำหรับคลิปสินค้า 10 วินาที:\n"
            f"สินค้า: {title}\n"
            f"ข้อความเดิม: {script}\n"
            f"ตอบเฉพาะประโยคบทพากย์สั้นๆ เท่านั้น ไม่ต้องใส่เครื่องหมายคำพูด และลงท้ายด้วย ครับ หรือ ค่ะ"
        )
        payload = {
            "model": "qwen3.8-27b-fp8",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3
        }
        headers = {
            "Authorization": f"Bearer {QWEN_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "curl/7.88.1"
        }
        req = urllib.request.Request(QWEN_GATEWAY_URL, data=json.dumps(payload).encode('utf-8'), headers=headers)
        with urllib.request.urlopen(req, timeout=12) as r:
            res = json.loads(r.read().decode('utf-8'))
            short = res['choices'][0]['message']['content'].strip()
            if len(short) > 10:
                return short
    except Exception as e:
        print(f"[VideoGen] shorten_script_with_qwen: {e}")
    return f"{title[:35]} สเปกดี คุ้มค่าน่าใช้ กดสั่งซื้อในตะกร้าได้เลยครับ"

# ==========================================
# STEP 1: QWEN IMAGE PREPROCESSING
# ==========================================
def generate_qwen_image(folder_path, progress_callback=None, force=False):
    folder = Path(folder_path)
    target = folder / "qwen_scene.png"
    if not force and target.exists() and target.stat().st_size > 10000:
        log("Step 1: qwen_scene.png already exists. Skipping.", progress_callback)
        return target

    log("Step 1: Analyzing product category & selecting matching style reference...", progress_callback)
    
    # Read product notes
    notes_file = folder / "product_notes.json"
    title = folder.name
    desc = ""
    if notes_file.exists():
        try:
            data = json.loads(notes_file.read_text(encoding='utf-8'))
            title = data.get("title", title)
            desc = data.get("caption", "")
        except Exception:
            pass

    # AI scene & category analysis
    plan = analyze_product_scene(title, desc)
    (folder / "scene_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    log(f"Category: {plan.get('category')} | Style Ref: {plan.get('style_file')}", progress_callback)

    # Source product images
    images = sorted([f for f in folder.glob("image_*.jpg")])
    if not images:
        images = sorted([f for f in folder.glob("*.jpg")])
    if not images:
        raise FileNotFoundError(f"No product images found in {folder}")

    prod_img = images[0]
    
    # Prepare vertical 9:16 padded product input for Qwen
    log("Step 1: Preparing vertical product composition...", progress_callback)
    source_img = Image.open(prod_img).convert("RGB")
    target_size = (768, 1024)
    box_size = (640, 640)
    bg_pad = ImageOps.fit(source_img, target_size, method=Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(42))
    fg_prod = ImageOps.contain(source_img, box_size, method=Image.Resampling.LANCZOS)
    px = (target_size[0] - fg_prod.width) // 2
    py = (target_size[1] - fg_prod.height) // 2
    pmask = Image.new("L", fg_prod.size, 255).filter(ImageFilter.GaussianBlur(8))
    bg_pad.paste(fg_prod, (px, py), pmask)

    slug = folder.name.replace(" ", "_")[:20]
    name_prod = f"shopee_{slug}_input.png"
    COMFY_INPUT.mkdir(parents=True, exist_ok=True)
    bg_pad.save(COMFY_INPUT / name_prod, format="PNG")

    # Free memory before starting Qwen
    comfy_free_memory()

    wf_path = ASSETS_DIR / "workflow_qwen.json"
    with open(wf_path, encoding='utf-8') as f:
        w = json.load(f)

    # Fast GPU loading
    if '3' in w and 'device' in w['3']['inputs']:
        w['3']['inputs']['device'] = 'default'

    short_name = plan.get("short_name", title[:30])
    scene_text = plan.get("scene", "a clean wooden desk with natural soft daylight")
    action_text = plan.get("action", "The left hand steadies the product while the right index finger points to its main feature.")

    prompt = (
        f"Precisely edit <image1>, which contains the {short_name}. "
        f"Preserve its exact product identity: shape, proportions, materials, colors, logos, buttons, ports, and seams. "
        f"Keep the product centered, sharply focused and clearly visible. "
        f"Recompose it as a casual first-person smartphone product demonstration at home, portrait 9:16. "
        f"Starting composition and hands: {action_text} Exactly two natural hands total, each with a natural wrist and five realistic fingers; bare wrists with no watch, no wristband, no bracelet, no tattoos. "
        f"The background is {scene_text}. "
        f"Replace the studio/advertising background and remove all promotional text, banners, badges, price tags, and watermarks naturally with the clean room scene while preserving the exact product. "
        f"No generated captions, product title, price, CTA, labels, watermark, extra hands, or duplicate items."
    )
    neg = "extra hand, extra arm, extra fingers, duplicate fingers, fused fingers, malformed hands, changed product, wrong color, duplicate item, seller logo, readable text, watermark, caption, UI, collage, infographic, split screen, illustration, CGI, blurry product, wristband, watch, bracelet, text banner, price badge"

    w['5']['inputs'].update(prompt=prompt, negative_prompt=neg, resolution=0, **{'images.image_1': ['20', 0]})
    w['20'] = {'class_type': 'LoadImage', 'inputs': {'image': name_prod}}
    w.pop("21", None)
    w.pop("6", None)

    w['7']['inputs'].update(seed=random.randint(10000000, 99999999), steps=25, latent_image=['5', 2], denoise=1.0)
    w['9']['inputs']['filename_prefix'] = f"shopee_gen/{slug}/qwen_scene"

    res = comfy_post('/prompt', {'prompt': w})
    pid = res['prompt_id']
    log(f"Qwen submitted to ComfyUI (prompt_id={pid}). Generating clean reference image...", progress_callback)

    while True:
        history = comfy_get(f"/history/{pid}").get(pid)
        if history:
            status = history.get('status', {})
            if status.get('status_str') == 'error':
                raise RuntimeError(f"Qwen generation failed: {status}")
            if status.get('completed'):
                saved = []
                for out in history.get('outputs', {}).values():
                    saved += out.get('images', [])
                if not saved:
                    raise RuntimeError("Qwen completed with no image output.")
                src = COMFY_OUTPUT / saved[0].get('subfolder', '') / saved[0]['filename']
                shutil.copy2(src, target)
                log(f"Step 1 Complete: Qwen image saved to {target}", progress_callback)
                return target
        time.sleep(4)

# ==========================================
# STEP 2: GEMINI THAI TTS
# ==========================================
def generate_gemini_tts(folder_path, progress_callback=None, force=False):
    folder = Path(folder_path)
    ready_target = folder / "narration_ready.wav"
    raw_target = folder / "narration_raw.wav"

    if not force and ready_target.exists() and ready_target.stat().st_size > 10000:
        log("Step 2: narration_ready.wav already exists. Skipping.", progress_callback)
        return ready_target

    log("Step 2: Generating Thai voiceover narration via Gemini Flash Lite TTS...", progress_callback)

    notes_file = folder / "product_notes.json"
    script = ""
    title = folder.name
    if notes_file.exists():
        try:
            data = json.loads(notes_file.read_text(encoding='utf-8'))
            script = data.get("script_10s", "")
            title = data.get("title", title)
        except Exception:
            pass

    if not script:
        script = f"{title[:40]} ใช้งานสะดวก คุณภาพดี คุ้มค่าน่าใช้ กดสั่งซื้อในตะกร้าได้เลยครับ"

    # Always ensure script is punchy and fits comfortably in 7.5 - 8.5 seconds
    if len(script) > 60:
        log("Shortening voiceover script with Qwen LLM...", progress_callback)
        script = shorten_script_with_qwen(script, title)
        log(f"Shortened script: {script}", progress_callback)

    voice = "Puck" # Natural warm male voice
    audio_bytes = None
    for k in GEMINI_KEYS:
        url = f"{GEMINI_TTS_URL}?key={k}"
        payload = {
            'contents': [{'parts': [{'text': script}]}],
            'generationConfig': {
                'responseModalities': ['AUDIO'],
                'speechConfig': {
                    'voiceConfig': {'prebuiltVoiceConfig': {'voiceName': voice}}
                }
            }
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode('utf-8'))
                for part in data.get('candidates', [{}])[0].get('content', {}).get('parts', []):
                    if 'inlineData' in part:
                        audio_bytes = base64.b64decode(part['inlineData']['data'])
                        break
            if audio_bytes:
                break
        except Exception as e:
            time.sleep(0.5)
            continue

    if not audio_bytes:
        raise RuntimeError("Failed to generate TTS from all Gemini keys.")

    with wave.open(str(raw_target), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(audio_bytes)

    dur = get_media_duration(raw_target)
    log(f"TTS raw duration: {dur:.2f}s", progress_callback)

    # Normalize audio to fit comfortably in 10s video (target 7.8 - 8.3s)
    if dur > 8.5:
        speed = min(1.35, dur / 8.0)
        cmd = [
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(raw_target),
            "-filter:a", f"atempo={speed:.3f}",
            str(ready_target)
        ]
        subprocess.run(cmd, check=True)
    else:
        shutil.copy2(raw_target, ready_target)

    final_dur = get_media_duration(ready_target)
    log(f"Step 2 Complete: Voiceover ready ({final_dur:.2f}s)", progress_callback)
    return ready_target

# ==========================================
# STEP 3: MINIMAX H3 VIDEO GENERATION
# ==========================================
def generate_h3_video(folder_path, progress_callback=None, force=False):
    folder = Path(folder_path)
    target = folder / "h3_silent_10s.mp4"
    if not force and target.exists() and target.stat().st_size > 100000:
        log("Step 3: h3_silent_10s.mp4 already exists. Skipping.", progress_callback)
        return target

    log("Step 3: Generating 10s handheld video with MiniMax H3 in ComfyUI...", progress_callback)

    qwen_image = folder / "qwen_scene.png"
    if not qwen_image.exists():
        qwen_image = generate_qwen_image(folder_path, progress_callback)

    slug = folder.name.replace(" ", "_")[:20]
    name_start = f"shopee_{slug}_start.png"
    shutil.copy2(qwen_image, COMFY_INPUT / name_start)

    # Free RAM/VRAM from Qwen before loading H3
    log("Step 3: Freeing memory in ComfyUI before loading MiniMax H3...", progress_callback)
    comfy_free_memory()

    wf_path = ASSETS_DIR / "workflow_h3.json"
    with open(wf_path, encoding='utf-8') as f:
        w = json.load(f)

    # Load tailored scene plan for H3
    plan_file = folder / "scene_plan.json"
    plan = {}
    if plan_file.exists():
        try:
            plan = json.loads(plan_file.read_text(encoding='utf-8'))
        except Exception:
            pass

    short_name = plan.get("short_name", folder.name)
    scene_desc = plan.get("scene", "a clean wooden desk with soft natural daylight")
    action_desc = plan.get("action", "The left hand gently steadies the product while the right index finger indicates its main feature.")

    # Model settings
    w['115']['inputs']['aspect_ratio'] = '9:16 (Portrait Widescreen)'
    w['115']['inputs']['megapixels'] = 0.4
    w['133']['inputs']['value'] = 10.0
    w['124']['inputs']['steps'] = 4
    if '128' in w and 'device' in w['128']['inputs']:
        w['128']['inputs']['device'] = 'default'
    w['129']['inputs']['noise_seed'] = random.randint(10000000, 99999999)

    w['400']['inputs']['image'] = name_start
    w['600']['inputs']['image'] = name_start

    h3_prompt = (
        "reference_mapping:\n"
        f"<Picture 1> is the exact {short_name}, the approved Qwen starting frame, and the starting composition. Preserve this same product, scene, lighting, color, and framing. It is the only visual reference; do not add another product.\n"
        "summary:\n"
        "Photorealistic vertical 9:16 handheld smartphone product review, one continuous 10-second silent shot.\n"
        "detailed_description:\n"
        f"Continue smoothly from the starting frame without a cut. Keep the phone camera almost fixed with only a tiny natural handheld drift. Match the warm/cool balance, light direction, contrast, background, shadows, and real-world scale of the starting frame. Keep the product centered, stable, and clear. {scene_desc} {action_desc} Use exactly two natural adult hands; one steadies and one points. At 0-2 seconds hold the opening pose; from 2-5 seconds make the pointing or touching gesture slowly; from 5-7 seconds withdraw slightly and repeat the gesture once; from 7-10 seconds settle back to the starting pose with the product fully visible. Do not freeze between actions; keep subtle natural movement throughout. Maintain the product's exact body shape, color, buttons, seams, ports, logo placement, and proportions. H3 footage stays silent; Thai narration and graphics are added in post.\n"
        "dialogue:\n"
        "None.\n"
        "overall_soundscape:\n"
        "Silent.\n"
        "non_diegetic_music:\n"
        "None.\n"
        "avoidances:\n"
        "No cuts, scene changes, end card, generated text, subtitles, CTA, watermark, extra hands, duplicated fingers, fused fingers, malformed anatomy, product duplication, changed product shape, changed brand marks, drifting product, missing pointer gesture, dramatic zoom, strong camera shake, flicker, or unintended pauses."
    )

    ins = w['137']['inputs']
    for k in list(ins):
        if k.startswith('ref_images.'):
            del ins[k]
    ins['ref_images.ref_image_0'] = ['400', 0]
    ins['prompt'] = h3_prompt

    w['92']['inputs']['filename_prefix'] = f"shopee_gen/{slug}/h3_raw"

    res = comfy_post('/prompt', {'prompt': w})
    pid = res['prompt_id']
    log(f"MiniMax H3 submitted to ComfyUI (prompt_id={pid}). Rendering 10s video...", progress_callback)

    while True:
        history = comfy_get(f"/history/{pid}").get(pid)
        if history:
            status = history.get('status', {})
            if status.get('status_str') == 'error':
                raise RuntimeError(f"H3 video generation failed: {status}")
            if status.get('completed'):
                found = []
                for out in history.get('outputs', {}).values():
                    for vals in out.values():
                        if isinstance(vals, list):
                            for v in vals:
                                if isinstance(v, dict) and str(v.get('filename', '')).lower().endswith('.mp4'):
                                    found.append(v)
                if not found:
                    raise RuntimeError("No H3 mp4 output found in history.")
                src_mp4 = COMFY_OUTPUT / found[0].get('subfolder', '') / found[0]['filename']
                
                # Normalize via ffmpeg to conform to exact 720x1280 24fps 10.0s
                cmd = [
                    FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(src_mp4),
                    "-t", "10", "-an",
                    "-vf", "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,fps=24",
                    "-r", "24",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                    "-movflags", "+faststart",
                    str(target)
                ]
                subprocess.run(cmd, check=True)
                log(f"Step 3 Complete: H3 silent video saved to {target}", progress_callback)
                return target
        time.sleep(8)

# ==========================================
# STEP 4: TITLE OVERLAY & AUDIO MIXING
# ==========================================
def render_final_video(folder_path, progress_callback=None):
    folder = Path(folder_path)
    final_target = folder / "final_10s.mp4"
    log("Step 4: Merging video, title overlay, Thai voiceover, and BGM...", progress_callback)

    h3_video = folder / "h3_silent_10s.mp4"
    if not h3_video.exists():
        h3_video = generate_h3_video(folder_path, progress_callback)

    voice = folder / "narration_ready.wav"
    if not voice.exists():
        voice = generate_gemini_tts(folder_path, progress_callback)

    bgm = ASSETS_DIR / "original_bgm_10s.wav"
    if not bgm.exists():
        raise FileNotFoundError(f"BGM track missing at {bgm}")

    # Build title lines
    notes_file = folder / "product_notes.json"
    title = folder.name
    if notes_file.exists():
        try:
            data = json.loads(notes_file.read_text(encoding='utf-8'))
            title = data.get("title", title)
        except Exception:
            pass

    # Clean short title into 2 lines
    short_title = title.replace("【", "").replace("】", "").replace("[", "").replace("]", "")
    parts = short_title.split()
    if len(parts) >= 4:
        line1 = " ".join(parts[:3])
        line2 = " ".join(parts[3:6])
    elif len(short_title) > 25:
        line1 = short_title[:20]
        line2 = short_title[20:40]
    else:
        line1 = short_title
        line2 = ""

    # Generate overlay image (720x1280)
    overlay_path = folder / "title_buy_now_overlay.png"
    im = Image.new('RGBA', (720, 1280), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    font_title = ImageFont.truetype(FONT_PATH, 34 if line2 else 38)
    y = 65
    for line in [line1, line2]:
        if line:
            d.text((360, y), line, font=font_title, fill=(255, 226, 45, 255),
                   stroke_width=4, stroke_fill=(0, 0, 0, 240), anchor='mt')
            y += 45

    # BUY NOW blue pill button
    x0, y0, x1, y1 = 248, 1154, 472, 1220
    d.rounded_rectangle((x0, y0, x1, y1), radius=31, fill=(38, 83, 219, 246))
    d.ellipse((x0 + 6, y0 + 7, x0 + 57, y0 + 58), fill=(246, 72, 61, 255))
    for x in (x0 + 21, x0 + 32):
        d.line((x + 6, y0 + 19, x, y0 + 32, x + 6, y0 + 45), fill='white', width=4, joint='curve')
    font_cta = ImageFont.truetype(FONT_PATH, 27)
    d.text((x0 + 66, y0 + 33), 'BUY NOW', font=font_cta, fill='white', anchor='lm')
    im.save(overlay_path)

    # Composite video + title overlay
    titled_video = folder / "titled_silent_10s.mp4"
    cmd_title = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(h3_video),
        "-loop", "1", "-i", str(overlay_path),
        "-t", "10",
        "-filter_complex",
        "[0:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,fps=24[base];"
        "[1:v]format=rgba[ov];[base][ov]overlay=0:0:shortest=1,format=yuv420p[v]",
        "-map", "[v]", "-an", "-r", "24",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-movflags", "+faststart",
        str(titled_video)
    ]
    subprocess.run(cmd_title, check=True)

    # Audio filter chain: Voice with subtle room echo + soft BGM
    vd = min(get_media_duration(voice), 8.8)
    fade = min(0.30, max(0.12, vd * 0.08))
    st = max(0.0, vd - fade)

    audio_filter = (
        f"[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"atrim=duration={vd:.4f},highpass=f=120,afftdn=nr=6:nf=-35:tn=1,"
        f"equalizer=f=600:t=q:w=1:g=1.2,equalizer=f=2800:t=q:w=0.9:g=0.8,lowpass=f=7600,"
        f"aecho=0.95:0.70:70|130:0.12|0.06,"
        f"afade=t=out:st={st:.4f}:d={fade:.4f},apad,atrim=duration=10[voice];"
        f"[2:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"atrim=duration=10,volume=0.22,afade=t=out:st=9.35:d=0.65[bg];"
        f"[voice][bg]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.95[a]"
    )

    cmd_final = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(titled_video),
        "-i", str(voice),
        "-i", str(bgm),
        "-filter_complex", audio_filter,
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-t", "10",
        "-movflags", "+faststart",
        str(final_target)
    ]
    subprocess.run(cmd_final, check=True)

    # Cleanup temporary files
    for tmp in [titled_video, overlay_path]:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass

    log(f"Step 4 Complete! Final video ready: {final_target}", progress_callback)
    return final_target

# ==========================================
# MASTER PIPELINE
# ==========================================
def generate_full_video(folder_path, progress_callback=None, force=False):
    log(f"Starting Hand-Shopee full pipeline for: {folder_path}", progress_callback)
    t0 = time.time()
    
    # Step 1: Qwen Image
    generate_qwen_image(folder_path, progress_callback, force=force)
    
    # Step 2: Gemini TTS
    generate_gemini_tts(folder_path, progress_callback, force=force)
    
    # Step 3: MiniMax H3 Video
    generate_h3_video(folder_path, progress_callback, force=force)
    
    # Step 4: Render Final Video
    final_file = render_final_video(folder_path, progress_callback)
    
    elapsed = time.time() - t0
    log(f"All Done! Video created in {elapsed/60:.1f} minutes: {final_file}", progress_callback)
    return str(final_file)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        target_dir = sys.argv[1]
        generate_full_video(target_dir)
    else:
        print("Usage: python shopee_video_generator.py <product_folder_path>")
