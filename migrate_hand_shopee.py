"""Migrate hand_shopee into shopee-post folder.
Organizes each product into standard structure with video and product_notes.json.
"""
import json
import shutil
from pathlib import Path

SRC_DIR = Path(r"D:\Dev\ComfyUI\hand_shopee_19_10s_2026-11-07")
DEST_DIR = Path(r"C:\Users\krits\OneDrive\Desktop\shopee-post")
DEST_DIR.mkdir(parents=True, exist_ok=True)

manifest_file = SRC_DIR / "manifest.json"
plan_file = SRC_DIR / "scene_plan.json"

manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
plan = json.loads(plan_file.read_text(encoding="utf-8")) if plan_file.exists() else []
plan_map = {item.get("slug"): item for item in plan}

print(f"Scanning {len(manifest)} items from manifest...")

migrated_count = 0
for m in manifest:
    seq = m.get("sequence", 0)
    slug = m.get("slug", "")
    title = m.get("listing_title") or m.get("title") or slug
    url = m.get("shopee_url", "")
    
    # Narration / Caption
    plan_item = plan_map.get(slug, {})
    narration = plan_item.get("narration", "").strip()
    category = m.get("category", "").strip()
    
    # Compose clean caption with hashtags
    hashtag_parts = ["#ShopeeVideo", "#ShopeeTH"]
    if category:
        clean_cat = category.replace(" ", "").replace("-", "")
        hashtag_parts.insert(0, f"#{clean_cat}")
    hashtags = " ".join(hashtag_parts)
    
    if narration:
        caption = f"{narration} {hashtags}".strip()
    else:
        caption = f"{title} {hashtags}".strip()
        
    if len(caption) > 138:
        caption = caption[:135] + "..."

    # Find source product folder
    p_matches = list((SRC_DIR / "products").glob(f"{seq:02d}_{slug}*"))
    if not p_matches:
        p_matches = list((SRC_DIR / "products").glob(f"*{slug}*"))
    
    if not p_matches:
        print(f"[{seq:02d}] ⚠️ Folder not found for slug: {slug}")
        continue
        
    p_dir = p_matches[0]
    video_src = p_dir / "renders" / "final_10s.mp4"
    if not video_src.exists():
        # Look for any mp4 in renders or root
        mp4s = list((p_dir / "renders").glob("*.mp4")) or list(p_dir.glob("*.mp4"))
        if mp4s:
            video_src = mp4s[0]
        else:
            print(f"[{seq:02d}] ⚠️ No mp4 video found in {p_dir.name}")
            continue

    # Clean target folder name: e.g. "01_fantech_whg04"
    target_folder_name = f"{seq:02d}_{slug}"
    target_dir = DEST_DIR / target_folder_name
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # Copy video
    target_video = target_dir / f"{slug}_final_10s.mp4"
    shutil.copy2(video_src, target_video)
    
    # Write product_notes.json
    notes_data = {
        "title": title,
        "shopee_url": url,
        "captions": [caption]
    }
    notes_path = target_dir / "product_notes.json"
    notes_path.write_text(json.dumps(notes_data, indent=2, ensure_ascii=False), encoding="utf-8")
    
    migrated_count += 1
    print(f"[{seq:02d}] ✅ Migrated -> {target_folder_name} (Video: {video_src.name}, Title: {title[:30]}...)")

print(f"\n🎉 Successfully migrated {migrated_count} products into {DEST_DIR}!")
