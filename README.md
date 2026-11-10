# Shopee Video Auto-Poster Pro (Studio)

ระบบสร้างและโพสต์คลิปวิดีโออัตโนมัติบน Shopee Video เชื่อมต่อผ่าน Android Phone และเว็บแดชบอร์ด

---

## 🚀 วิธีเปิดใช้งานหลังจากลง Windows ใหม่

### 1. ติดตั้ง Python
- ดาวน์โหลดและติดตั้ง **Python 3.10 หรือ 3.11** จาก [python.org](https://www.python.org/)
- **สำคัญมาก:** ตอนติดตั้ง ให้ติ๊กถูกช่อง **"Add python.exe to PATH"**

### 2. รันสคริปต์อัตโนมัติคลิกเดียว
- ดับเบิ้ลคลิกไฟล์ `setup_and_start.bat` ในโฟลเดอร์นี้
- สคริปต์จะติดตั้ง library ที่จำเป็น (`requirements.txt`), สร้าง Shortcut บน Desktop และเปิด Dashboard ที่ [http://localhost:8090](http://localhost:8090)

---

## 📱 การเตรียมมือถือ Android (Xiaomi / เครื่องอื่น)
1. เปิด **Developer Options (สำหรับนักพัฒนาซอฟต์แวร์)** ในมือถือ
2. เปิด **USB Debugging (แก้ไขข้อบกพร่อง USB)**
3. (สำหรับ Xiaomi / Redmi) เปิด **USB Debugging (Security settings / การตั้งค่าความปลอดภัย)**
4. เสียบสาย USB เข้าคอมพิวเตอร์ และกดยอมรับ "Allow USB Debugging" บนหน้าจอมือถือ
5. เปิดแอป Shopee ทิ้งไว้ในหน้า **Live & Video**

---

## 📁 โฟลเดอร์คลิปสินค้า (Queue)
ระบบจะค้นหาโฟลเดอร์คิวตามลำดับ:
1. `D:\shopee-post` (แนะนำเมื่อลง Windows ใหม่ ย้ายมาไว้ที่นี่จะไม่หาย)
2. `Desktop\shopee-post`

