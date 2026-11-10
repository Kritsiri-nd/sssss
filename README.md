# 🎬 Shopee Video Auto-Poster Pro Studio

ระบบสร้างและโพสต์คลิปวิดีโอ Shopee Video อัตโนมัติแบบ Full-Stack พร้อม Web Dashboard, ระบบควบคุมมือถือ Android (Scrcpy/ADB), และ AI Video Generation (Qwen + MiniMax H3 + Gemini TTS)

---

## 📋 สิ่งที่ต้องติดตั้งเมื่อลง Windows ใหม่ (จาก 0)

### 1. ติดตั้ง Python
- ดาวน์โหลด **Python 3.10 หรือ 3.11** จาก [python.org](https://www.python.org/downloads/)
- ⚠️ **สำคัญมากที่สุด**: ในหน้าจอแรกของตัวติดตั้ง **ต้องติ๊กถูกช่อง `Add python.exe to PATH`** ก่อนกด Install Now

### 2. ติดตั้ง Git
- ดาวน์โหลด Git จาก [git-scm.com](https://git-scm.com/download/win) ติดตั้งตามค่า Default

### 3. (ทางเลือก) ติดตั้ง ComfyUI (เฉพาะกรณีต้องการ Generate วิดีโอใหม่ด้วย AI)
- หากต้องการใช้ฟังก์ชันสร้างวิดีโออัตโนมัติจากรูปสินค้า ต้องติดตั้ง ComfyUI ที่รันบนพอร์ต `8188` พร้อมโมเดล:
  - Qwen-Image-2.1
  - MiniMax H3 Video Model
- หากใช้โพสต์คลิปอย่างเดียว **ไม่จำเป็นต้องเปิด ComfyUI**

---

## 🚀 ขั้นตอนการเปิดใช้งานครั้งแรกบนเครื่องใหม่ (3 สเต็ปง่ายๆ)

### สเต็ป 1: Clone โปรเจกต์ลงเครื่อง
เปิด CMD หรือ PowerShell ในไดรฟ์ที่คุณต้องการ (เช่น `D:\` หรือ `C:\`) แล้วพิมพ์:
```bash
git clone https://github.com/Kritsiri-nd/sssss.git shopee_poster
cd shopee_poster
```

### สเต็ป 2: สร้างไฟล์คีย์ `.env`
ในโฟลเดอร์โปรเจกต์ จะมีไฟล์แม่แบบชื่อ `.env.example` ให้สร้างไฟล์ใหม่ชื่อ `.env` แล้วใส่คีย์ที่คุณเก็บไว้:
```env
# ไฟล์ .env (ห้ามแชร์ให้ผู้อื่น)
QWEN_API_KEY=sk-xxxxxxx
GEMINI_KEYS=key1,key2,key3
```

### สเต็ป 3: ดับเบิ้ลคลิก `setup_and_start.bat`
- ดับเบิ้ลคลิกไฟล์ **`setup_and_start.bat`**
- สคริปต์จะทำการ:
  1. ติดตั้ง Python Packages ทั้งหมดอัตโนมัติ (`requests`, `Pillow`, `curl_cffi`, `beautifulsoup4`, `pywebview` ฯลฯ)
  2. สร้าง Shortcut **"Shopee Poster Studio"** บนหน้าจอ Desktop ให้ทันที
  3. สตาร์ตเซิร์ฟเวอร์และเปิดเบราว์เซอร์เข้าหน้า Dashboard: **http://localhost:8090** ให้อัตโนมัติ

---

## 📱 การตั้งค่าโทรศัพท์มือถือ Android (Xiaomi / Redmi / Android ทั่วไป)

โปรแกรมใช้ระบบ Scrcpy UHID ในการจำลองการสัมผัสหน้าจอความเร็วสูง จึงต้องเปิดการอนุญาตในมือถือดังนี้:

1. **เปิดโหมดผู้พัฒนา (Developer Options)**:
   - ไปที่ `Settings` (การตั้งค่า) > `About phone` (เกี่ยวกับโทรศัพท์)
   - แตะที่ `OS version` หรือ `Build number` ซ้ำๆ กัน 7 ครั้ง จนขึ้นว่า "คุณเป็นนักพัฒนาซอฟต์แวร์แล้ว"
2. **เปิดการแก้ไขข้อบกพร่อง USB**:
   - ไปที่ `Settings` > `Additional settings` (การตั้งค่าเพิ่มเติม) > `Developer options` (ตัวเลือกสำหรับนักพัฒนา)
   - เปิดสวิตช์ **USB debugging** (แก้ไขข้อบกพร่อง USB)
   - ⚠️ **เฉพาะ Xiaomi / POCO / Redmi (จำเป็นมาก)**: เลื่อนลงมาเปิดสวิตช์ **USB debugging (Security settings)** (แก้ไขข้อบกพร่อง USB - การตั้งค่าความปลอดภัย) เพื่อให้ระบบสั่งแตะหน้าจอและพิมพ์ข้อความได้
3. **เชื่อมต่อสาย USB**:
   - เสียบสาย USB เข้าคอมพิวเตอร์ เลือกโหมด "File Transfer" (ถ่ายโอนไฟล์)
   - เมื่อมีกล่องข้อความถาม "Allow USB debugging?" ให้ติ๊กถูก "Always allow from this computer" แล้วกดยอมรับ
4. **เปิดแอป Shopee**:
   - ล็อกอินบัญชี Shopee ที่ต้องการโพสต์
   - เปิดแอป Shopee ทิ้งไว้ที่หน้า **Live & Video**

---

## 📁 โครงสร้างโฟลเดอร์คิวคลิปสินค้า (Queue Folder)

โปรแกรมจะค้นหาโฟลเดอร์คิวตามลำดับอัตโนมัติ:
1. `D:\shopee-post` (แนะนำที่สุด ข้อมูลไม่ปนกับไดรฟ์ระบบ)
2. `Desktop\shopee-post` (โฟลเดอร์ shopee-post บนหน้าจอ Desktop)

### โครงสร้างไฟล์ในแต่ละสินค้า (เช่น `24_ball_caster`):
```text
shopee-post/
  └── 24_ball_caster/
        ├── video.mp4               <- คลิปวิดีโอที่จะโพสต์ (แนวตั้ง 9:16 ความยาว 10-15 วิ)
        └── product_notes.json      <- ข้อมูลสินค้าและแคปชัน
```

### รูปแบบไฟล์ `product_notes.json`:
```json
{
  "title": "ลูกล้อบอลแบบติด 360 องศา หมุนลื่น ไร้เสียง",
  "shopee_url": "https://shopee.co.th/product/1320886026/44330901920",
  "captions": [
    "ลูกล้อบอลติดใต้กล่อง ช่วยให้เลื่อนย้ายของสะดวกขึ้น #ลูกล้อ #ShopeeVideo"
  ]
}
```
*(หากไม่มี `product_notes.json` สามารถใช้ `notes.txt` โดยบรรทัดแรกใส่ URL Shopee และบรรทัดที่สองใส่แคปชันได้)*

---

## 🌟 ฟีเจอร์เด่นของระบบ

- **Web Dashboard สวยงามใช้งานง่าย**: ดูคิวงาน, ความคืบหน้า (Progress bar), สถานะแบตเตอรี่มือถือ และสถานะความพร้อมของจอแบบ Real-time
- **หน้าจอมือถือสด & สั่งงานได้**: ดูภาพจอมือถือสดๆ จากเว็บแดชบอร์ด คลิกสั่งงาน หรือเปิดหน้าต่าง Scrcpy 60 FPS แยกได้ทันที
- **ตัวเลือกตั้งหน่วงเวลา (Posting Delay)**: เลือกเว้นช่วงระหว่างคลิปได้: ทันที (0 นาที), 1 นาที, 5 นาที, 10 นาที, 15 นาที, 30 นาที
- **Bulletproof Screen Recovery**: ระบบตรวจจับหน้าจออัจฉริยะ ป้องกันการกดโดนแป้นพิมพ์ และหากเกิดข้อผิดพลาดจะรีเซ็ตและรีสตาร์ต Shopee กลับมาหน้า Live & Video ให้อัตโนมัติ ไม่ทำให้คลิปอื่นในคิวเสียตาม
- **Excluded Product Safety**: ตรวจจับสินค้าที่ Shopee ไม่อนุญาตให้แนบตะกร้า (Excluded Affiliate Link) และแจ้งเตือนอย่างชัดเจน ไม่ค้างจอ
- **Shopee Link Importer**: วางลิงก์สินค้า Shopee บนหน้าเว็บ เพื่อดึงข้อมูลรูปภาพ HD และให้ AI เขียนแคปชันสร้างโฟลเดอร์พร้อมลงคิวได้ทันที
