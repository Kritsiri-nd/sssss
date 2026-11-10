"""Shopee Product Auto-Importer & Qwen AI Script Generator.
Fetches product details & HD images from Shopee URLs and generates captions/scripts using Qwen 3.8.
"""
import os
import re
import json
import time
import urllib.request
import urllib.parse
from pathlib import Path
from curl_cffi import requests
from bs4 import BeautifulSoup

def load_env_val(key, default=""):
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return os.environ.get(key, default)

QWEN_GATEWAY_URL = "https://gateway.9arm.co/v1/chat/completions"
QWEN_API_KEY = load_env_val("QWEN_API_KEY", "")
QWEN_MODEL = "qwen3.8-27b-fp8"
if Path(r"D:\shopee-post").exists():
    DEFAULT_QUEUE_DIR = Path(r"D:\shopee-post")
elif (Path.home() / "OneDrive" / "Desktop" / "shopee-post").exists():
    DEFAULT_QUEUE_DIR = Path.home() / "OneDrive" / "Desktop" / "shopee-post"
elif (Path.home() / "Desktop" / "shopee-post").exists():
    DEFAULT_QUEUE_DIR = Path.home() / "Desktop" / "shopee-post"
else:
    DEFAULT_QUEUE_DIR = Path(r"D:\shopee-post")


def resolve_shopee_url(url: str) -> str:
    """Resolve short links (s.shopee.co.th) or universal links to full Shopee product URL."""
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url

    # Follow redirects if it's a short link or redirect link
    try:
        session = requests.Session(impersonate="chrome120")
        res = session.get(url, allow_redirects=True, timeout=12)
        return res.url
    except Exception:
        return url


def sanitize_filename(name: str, max_length: int = 40) -> str:
    """Sanitize string into a valid folder/file slug."""
    clean = re.sub(r'[\\/*?:"<>|]', '', name)
    clean = re.sub(r'[\s_]+', '_', clean).strip('_')
    # If mostly English/alphanumeric, keep lower
    if len(clean) > max_length:
        clean = clean[:max_length].rstrip('_')
    return clean or "shopee_product"


def extract_shopee_metadata(url: str):
    """Fetch product page and extract title, description, price, and gallery images."""
    canonical_url = resolve_shopee_url(url)
    session = requests.Session(impersonate="chrome120")
    headers = {
        "Referer": "https://shopee.co.th/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    }
    res = session.get(canonical_url, headers=headers, timeout=18)
    if res.status_code != 200:
        raise RuntimeError(f"Shopee returned HTTP {res.status_code}")

    soup = BeautifulSoup(res.text, "html.parser")

    # 1. Title
    title = ""
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title.get("content").strip()
    elif soup.title and soup.title.string:
        title = soup.title.string.strip()

    title = re.sub(r'\s*\|\s*Shopee\s*Thailand.*$', '', title, flags=re.IGNORECASE).strip()

    # If title is missing (e.g. mobile SPA redirect from short link), retry with desktop /product/{shop_id}/{item_id} URL
    if not title:
        m = re.search(r'/(\d{6,15})/(\d{6,15})', canonical_url) or re.search(r'i\.(\d{6,15})\.(\d{6,15})', canonical_url)
        if m:
            shop_id, item_id = m.groups()
            desktop_url = f"https://shopee.co.th/product/{shop_id}/{item_id}"
            res2 = session.get(desktop_url, headers=headers, timeout=18)
            if res2.status_code == 200:
                res = res2
                canonical_url = desktop_url
                soup = BeautifulSoup(res.text, "html.parser")
                og_title = soup.find("meta", property="og:title")
                if og_title and og_title.get("content"):
                    title = og_title.get("content").strip()
                elif soup.title and soup.title.string:
                    title = soup.title.string.strip()
                title = re.sub(r'\s*\|\s*Shopee\s*Thailand.*$', '', title, flags=re.IGNORECASE).strip()

    # 2. Description
    desc = ""
    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        desc = og_desc.get("content").strip()

    # 3. Images from HTML (down-th.img.susercontent.com)
    # Shopee stores high-res images on susercontent
    raw_imgs = re.findall(r'(https://down-th\.img\.susercontent\.com/file/[a-zA-Z0-9_-]+)', res.text)
    images = []
    seen = set()
    for img_url in raw_imgs:
        if img_url not in seen:
            seen.add(img_url)
            images.append(img_url)

    if not title:
        raise ValueError("ไม่สามารถอ่านชื่อสินค้าจากลิงก์ Shopee นี้ได้ (อาจเป็นลิงก์เสียหรือสินค้าถูกระงับ)")

    return {
        "canonical_url": canonical_url,
        "title": title,
        "description": desc,
        "images": images
    }


def call_qwen_ai(title: str, description: str) -> dict:
    """Call Qwen 3.8 to generate video caption, voiceover script, and clean slug."""
    system_prompt = (
        "คุณคือ AI ผู้เชี่ยวชาญการทำ Shopee Video และ Affiliate Marketing สำหรับตลาดไทย\n"
        "หน้าที่ของคุณคือเขียนสคริปต์พากย์เสียงและแคปชันสำหรับคลิปวิดีโอ 10-15 วินาที\n"
        "ตอบกลับในรูปแบบ JSON เท่านั้น (ห้ามใส่ markdown ```json หรือคำนำหน้าใดๆ)\n"
        "โครงสร้าง JSON ที่ต้องการ:\n"
        "{\n"
        "  \"caption\": \"แคปชันสั้นน่าดึงดูด 1-2 ประโยค ชวนซื้อ ลงท้ายด้วย #ShopeeVideo #ShopeeTH #ของดีบอกต่อ (ความยาวไม่เกิน 140 ตัวอักษร)\",\n"
        "  \"script_10s\": \"บทพากย์เสียงภาษาไทยสั้นๆ 10-15 วินาที (3-4 ประโยค) เริ่มด้วยเปิดจุดเด่น จุดเด่นสเปก และชวนกดตะกร้า\",\n"
        "  \"slug\": \"ชื่อย่อสินค้าภาษาอังกฤษ 3-5 คำ คั่นด้วยขีดล่าง เช่น lucky_flame_gas_stove\"\n"
        "}"
    )

    user_prompt = f"ชื่อสินค้า: {title}\n\nรายละเอียดสินค้า:\n{description[:1200]}"

    data = {
        "model": QWEN_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.7
    }

    req = urllib.request.Request(
        QWEN_GATEWAY_URL,
        data=json.dumps(data).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {QWEN_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "curl/7.88.1"
        }
    )

    with urllib.request.urlopen(req, timeout=30) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        raw_content = res["choices"][0]["message"]["content"].strip()
        
        # Clean potential markdown fence
        raw_content = re.sub(r'^```json\s*', '', raw_content)
        raw_content = re.sub(r'\s*```$', '', raw_content)
        
        try:
            parsed = json.loads(raw_content)
            return parsed
        except Exception:
            # Fallback regex extraction if Qwen returned extra text
            m_cap = re.search(r'"caption":\s*"([^"]+)"', raw_content)
            m_scr = re.search(r'"script_10s":\s*"([^"]+)"', raw_content)
            m_slug = re.search(r'"slug":\s*"([^"]+)"', raw_content)
            return {
                "caption": m_cap.group(1) if m_cap else f"{title} ซื้อได้แล้ววันนี้ที่ Shopee! #ShopeeVideo #ShopeeTH",
                "script_10s": m_scr.group(1) if m_scr else f"แนะนำ {title} ใช้งานดีและสะดวกมาก ใครมองหาอยู่กดสั่งในตะกร้าได้เลยครับ",
                "slug": m_slug.group(1) if m_slug else sanitize_filename(title)
            }


def get_next_queue_index(queue_dir: Path) -> int:
    """Find next numeric index prefix for new product folders."""
    existing_dirs = [d.name for d in queue_dir.iterdir() if d.is_dir() and not d.name.startswith(("_", "."))]
    highest = 0
    for d in existing_dirs:
        m = re.match(r'^(\d+)_', d)
        if m:
            val = int(m.group(1))
            if val > highest:
                highest = val
    return highest + 1


def import_shopee_product(shopee_url: str, max_images: int = 5, queue_dir: Path = DEFAULT_QUEUE_DIR) -> dict:
    """End-to-end import: Scrape Shopee -> Call Qwen -> Download HD Images -> Save folder & JSON."""
    queue_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Scrape Shopee
    meta = extract_shopee_metadata(shopee_url)
    title = meta["title"]
    description = meta["description"]
    canonical_url = meta["canonical_url"]
    images = meta["images"]

    # 2. Call Qwen AI
    ai_result = call_qwen_ai(title, description)
    caption = ai_result.get("caption", f"{title} #ShopeeVideo #ShopeeTH")
    script_10s = ai_result.get("script_10s", "")
    slug = sanitize_filename(ai_result.get("slug", title))

    # 3. Determine Folder Name
    next_idx = get_next_queue_index(queue_dir)
    folder_name = f"{next_idx:02d}_{slug}"
    target_folder = queue_dir / folder_name
    target_folder.mkdir(parents=True, exist_ok=True)

    # 4. Download HD Images
    downloaded_images = []
    session = requests.Session(impersonate="chrome120")
    headers = {"Referer": "https://shopee.co.th/"}
    
    for idx, img_url in enumerate(images[:max_images], 1):
        try:
            r = session.get(img_url, headers=headers, timeout=15)
            if r.status_code == 200 and len(r.content) > 1000:
                file_name = f"image_{idx:02d}.jpg"
                file_path = target_folder / file_name
                file_path.write_bytes(r.content)
                downloaded_images.append(file_name)
        except Exception as e:
            print(f"Failed to download image {img_url}: {e}")

    # 5. Save product_notes.json & notes.txt
    product_notes = {
        "title": title,
        "shopee_url": canonical_url,
        "original_url": shopee_url,
        "captions": [caption],
        "script_10s": script_10s,
        "images": downloaded_images,
        "folder_name": folder_name,
        "imported_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }

    notes_json_path = target_folder / "product_notes.json"
    notes_json_path.write_text(json.dumps(product_notes, indent=2, ensure_ascii=False), encoding="utf-8")

    # Fallback notes.txt
    notes_txt_path = target_folder / "notes.txt"
    notes_txt_path.write_text(f"{canonical_url}\n{caption}\n", encoding="utf-8")

    return {
        "success": True,
        "folder_name": folder_name,
        "index": next_idx,
        "title": title,
        "caption": caption,
        "script_10s": script_10s,
        "images_count": len(downloaded_images),
        "folder_path": str(target_folder)
    }


if __name__ == "__main__":
    import sys
    test_url = sys.argv[1] if len(sys.argv) > 1 else "https://shopee.co.th/product/39109149/2022932374"
    print(f"Testing import for: {test_url}")
    res = import_shopee_product(test_url, max_images=3)
    print("Result:", json.dumps(res, indent=2, ensure_ascii=False))

