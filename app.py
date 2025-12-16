import json
import time
import pyautogui
import webbrowser
import os
import shutil
import random
import cv2
import numpy as np
import requests
from PIL import ImageGrab
import pytesseract
from datetime import datetime
from flask import Flask, request, jsonify, render_template, redirect
import unicodedata
from difflib import SequenceMatcher
import re

app = Flask(__name__)

IMG_PATH = "static/images/"
WORKFLOW_FILE = "workflow.json"
# đường dẫn tới tesseract.exe (phải đúng)
pytesseract.pytesseract.tesseract_cmd = r"C:\projectdev\project3m\autobuyer\tessat\tesseract.exe"

# trỏ tới folder tessdata chứa eng.traineddata, vie.traineddata
os.environ["TESSDATA_PREFIX"] = r"D:\project8m\autobuyer\tessat\tessdata"
# đảm bảo thư mục ảnh tồn tại
os.makedirs(IMG_PATH, exist_ok=True)
# ================== SYSTEM PHRASES ==================
SYSTEM_PHRASES = [
    "tin nhan",
    "cuoc goi",
    "goi video",
    "goi thoai",
    "sticker",
    "dang tam dung",
    "khong gui",
    "he thong",
    "tai khoan",
    "chuyen khoan",
    "zalo",
    "mini app",
]


# ================== UTILS ==================
def strip_accents(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.lower()


def normalize_text(text: str) -> str:
    text = text.strip()

    replacements = {
        "Nguyén": "Nguyễn",
        "Nguyễn": "Nguyễn",
        "Thé": "Thế",
        "Hién": "Hiện",
        "Huyén": "Huyền",
        "Thuy": "Thủy",
        "Tran": "Trần",
        "Hoang": "Hoàng",
        "Le": "Lê",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)

    text = re.sub(r'^[^A-Za-zÀ-ỹ]+|[^A-Za-zÀ-ỹ0-9]+$', '', text)
    text = unicodedata.normalize("NFC", text)
    return text


def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()


# ================== FILTER LOGIC ==================
def is_system_line(line: str) -> bool:
    lower = strip_accents(line)
    return any(p in lower for p in SYSTEM_PHRASES)

def starts_with_uppercase(line: str) -> bool:
    for ch in line:
        if ch.isalpha():
            return ch.isupper()
    return False


def is_message_like(line: str) -> bool:
    lower = strip_accents(line)

    if len(line) <= 5:
        return True

    message_patterns = [
        "vâng", "ạ", "ok", "oki", "nhé", "rồi", "đi",
        "xem", "check", "cảm ơn", "cam on", "chào",
        "mình", "bạn", "anh", "chị", "em",
        "chưa", "đang", "vừa", "mai", "nay",
        "xin", "gửi", "apply", "cv"
    ]

    if any(p in lower for p in message_patterns):
        return True

    if re.search(r'\b(gui|xem|vao|lam|noi|bao|hoi)\b', lower):
        return True

    return False


def is_chat_title(line: str) -> bool:
    if not line:
        return False

    # system / thông báo
    if is_system_line(line):
        return False

    # không viết hoa chữ cái đầu → tin nhắn
    if not starts_with_uppercase(line):
        return False

    # mention / ký hiệu đầu dòng
    if line.startswith(("@", "#", "©", "™", "&", "+", ")")):
        return False

    # link
    if "http://" in line or "https://" in line:
        return False

    # có dấu : → tin nhắn
    if ":" in line:
        return False

    # rác
    if re.match(r'^[\W\d]+$', line):
        return False

    # hội thoại
    if is_message_like(line):
        return False

    # độ dài hợp lý
    if not (4 <= len(line) <= 45):
        return False

    return True



def merge_similar(names, threshold=0.85):
    merged = []

    for name in names:
        key = strip_accents(name)
        found = False

        for i, exist in enumerate(merged):
            exist_key = strip_accents(exist)
            if similar(key, exist_key) >= threshold:
                if len(name) > len(exist):
                    merged[i] = name
                found = True
                break

        if not found:
            merged.append(name)

    return merged


# ================== OCR ==================
def ocr_region(region, lang="vie+eng"):
    x, y, w, h = map(int, region)
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h))

    img = img.convert("L")  # grayscale
    img = img.resize((w*2, h*2))  # phóng to
    # tăng độ tương phản
    from PIL import ImageEnhance, ImageFilter
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(2.0)
    # lọc noise nhẹ
    img = img.filter(ImageFilter.MedianFilter(size=3))
    # threshold để bỏ background nhẹ
    img = img.point(lambda p: 0 if p < 180 else 255)

    return pytesseract.image_to_string(
        img,
        lang=lang,
        config="--psm 6"
    )

def ocr_region_dual(region, lang="vie+eng"):
    x, y, w, h = map(int, region)

    h1 = int(h * 0.5)
    h2 = int(h * 0.7)

    text1 = ocr_region([x, y, w, h1], lang)
    text2 = ocr_region([x, y + int(h * 0.15), w, h2], lang)

    return text1 + "\n" + text2


# ================== BACKUP ==================
def backup_workflow():
    if os.path.exists(WORKFLOW_FILE):
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        shutil.copy(WORKFLOW_FILE, WORKFLOW_FILE + f".bak.{ts}")


# ================== MAIN ==================
def ocr_chat_list(step):
    chat_list_region = step["chat_list_region"]
    scroll_px = step.get("scroll_px", 400)
    max_scrolls = step.get("max_scrolls", 30)
    output_json = step.get("output_json", "static/all_chats.json")

    os.makedirs(os.path.dirname(output_json), exist_ok=True)

    all_chat_names = []
    no_new_round = 0

    x, y, w, h = chat_list_region
    cx = x + w // 2
    cy = y + h // 2

    for _ in range(max_scrolls):
        text = ocr_region_dual(chat_list_region)
        lines = [normalize_text(l) for l in text.splitlines() if l.strip()]

        before = set(all_chat_names)

        for line in lines:
            line = line.strip()

            # ❌ quá ngắn
            if len(strip_accents(line)) < 3:
                continue

            # ❌ OCR rác: AAA, !!!, :::, …
            if len(set(strip_accents(line))) <= 2:
                continue

            # ❌ CHỈ loại nếu ký tự ĐẦU TIÊN viết thường
            if line[0].islower():
                continue

            # 🔥 CẮT ĐUÔI RÁC: số / ký hiệu / chữ lẻ
            # VD: "Count Kèr 4" -> "Count Kèr"
            line = re.sub(r'[\s#\-\._]*[A-Z0-9]{1,3}$', '', line).strip()

            # ❌ các câu preview tin nhắn (bắt đầu)
            if any(
                strip_accents(line).startswith(k) for k in [
                    "dang ", "da ", "vua ", "chua ",
                    "xin ", "chao ", "ok ", "oki ",
                    "uh ", "u ", "ha ", "a "
                ]
            ):
                continue

            # 🔥 loại câu giống suy nghĩ / tin nhắn
            if any(
                strip_accents(line).startswith(k) for k in [
                    "mk ", "minh ", "gia dinh ", "hien ",
                    "ket ", "tim ", "nham", "ta xua"
                ]
            ):
                continue

            # 🔥 preview có dấu câu
            if any(c in line for c in ["!", "?", ".", ","]):
                continue

            # 🔥 quá dài → giống tin nhắn
            if len(line.split()) > 5:
                continue

            # 🔥 auto reply / hệ thống / QC
            lowered = strip_accents(line)
            if any(k in lowered for k in [
                "hien", "dang", "chua", "vui long",
                "cam on", "nhan duoc", "tu van",
                "tong dai", "he thong", "khach hang"
            ]):
                continue

            # 🔥 OCR noise: quá nhiều từ ngắn
            words = line.split()
            if len(words) >= 3:
                short_words = sum(1 for w in words if len(w) <= 2)
                if short_words >= 2:
                    continue

            # 🔥 OCR noise: viết hoa quá nhiều
            letters = [c for c in line if c.isalpha()]
            if letters:
                upper_ratio = sum(c.isupper() for c in letters) / len(letters)
                if upper_ratio > 0.7:
                    continue

            # ❌ lọc hệ thống / link / message (logic cũ của bạn)
            if not is_chat_title(line):
                continue

            all_chat_names.append(line)

        # loại trùng + gộp gần giống
        all_chat_names = list(dict.fromkeys(all_chat_names))
        all_chat_names = merge_similar(all_chat_names)

        if set(all_chat_names) == before:
            no_new_round += 1
        else:
            no_new_round = 0

        if no_new_round >= 3:
            print("🛑 Không có chat mới → STOP")
            break

        pyautogui.moveTo(cx, cy)
        pyautogui.scroll(-scroll_px)
        time.sleep(0.4)

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(all_chat_names, f, ensure_ascii=False, indent=2)

    print(f"✅ OCR DONE: {len(all_chat_names)} chats")
    
def ocr_all_chats_from_list(step):
    import os, json, time, re
    import pyautogui

    input_json = step.get("input_json", "static/all_chats.json")
    search_image = step.get("search_image", "static/images/search_zalo.png")
    chat_content_region = step["chat_content_region"]  # [x,y,w,h]
    scroll_px = step.get("scroll_px", 450)
    max_scrolls = step.get("max_scrolls", 50)
    output_dir = step.get("output_dir", "static/chats")

    os.makedirs(output_dir, exist_ok=True)

    if not os.path.exists(input_json):
        print("❌ Không tìm thấy all_chats.json")
        return

    with open(input_json, "r", encoding="utf-8") as f:
        chat_names = json.load(f)

    x, y, w, h = chat_content_region
    cx = x + w // 2
    cy = y + h // 2

    def clean_line(line):
        line = line.strip()
        
        # loại emoji
        line = re.sub("[\U00010000-\U0010ffff]", "", line)
        
        # loại URL
        if re.search(r'https?://', line):
            return None
        # loại dòng toàn ký tự đặc biệt/số
        if re.fullmatch(r'[\W\d_]+', line):
            return None
        # loại dòng quá ngắn
        if len(line) < 5:
            return None
        # loại từ khóa rác OCR
        if any(word in line.lower() for word in [
            "sticker", "dang tam dung", "he thong", "success", "process", "sandbox", "browser"
        ]):
            return None
        # loại ngày, giờ, phút, gid
        if re.search(r'\d{1,2}[:h giờ]|gid|phút|ngày|/|\\', line):
            return None
        # chỉ giữ chữ và số, bỏ ký tự lạ
        if not re.search(r'[a-zA-Z0-9]', line):
            return None
        
        return line

    for idx, chat_name in enumerate(chat_names, 1):
        print(f"\n📨 [{idx}/{len(chat_names)}] OCR CHAT: {chat_name}")

        # 1️⃣ click icon search
        if not find_and_click(search_image, confidence=0.85, timeout=8):
            print("❌ Không click được search → skip")
            continue
        time.sleep(0.8)

        # 2️⃣ nhập tên chat
        query = strip_accents(chat_name)
        query = re.sub(r'[^A-Za-z0-9 ]+', '', query)
        query = re.sub(r'\s+', ' ', query).strip()

        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.05)
        pyautogui.press("backspace")
        time.sleep(0.05)
        pyautogui.write(query, interval=0.04)
        time.sleep(1)

        # 3️⃣ click kết quả đầu
        pyautogui.press("enter")
        time.sleep(1.2)

        # 🔹 click giữa chat để hủy focus latest message
        pyautogui.moveTo(cx, cy)
        pyautogui.click()
        time.sleep(0.3)

        # 4️⃣ OCR nội dung chat (scroll ngược lên lấy tin cũ)
        chat_text_lines = []
        no_new_text = 0
        stop_threshold = 10

        for _ in range(max_scrolls):
            text = ocr_region(chat_content_region).strip()
            lines = [l.strip() for l in text.splitlines() if l.strip()]

            # --- CLEAN LINES ---
            cleaned_lines = []
            for line in lines:
                cl = clean_line(line)
                if cl and cl not in chat_text_lines:
                    cleaned_lines.append(cl)

            if not cleaned_lines:
                no_new_text += 1
            else:
                chat_text_lines.extend(cleaned_lines)
                no_new_text = 0

            if no_new_text >= stop_threshold:
                break

            # scroll ngược lên để lấy tin nhắn cũ
            pyautogui.moveTo(cx, cy)
            pyautogui.scroll(scroll_px)
            time.sleep(0.5)

        # 5️⃣ lưu file
        chat_text = "\n".join(chat_text_lines)
        safe_name = re.sub(r'[\\/:*?"<>|]', "_", chat_name)
        out_file = os.path.join(output_dir, f"{safe_name}.json")

        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "chat_name": chat_name,
                    "content": chat_text.strip()
                },
                f,
                ensure_ascii=False,
                indent=2
            )

        print(f"✅ Saved: {out_file}")
        time.sleep(1)




def find_image_pos(image_path, confidence=0.9, timeout=5):
    """Tìm ảnh và trả về tọa độ tâm (x,y), None nếu không tìm thấy"""
    full = os.path.join(IMG_PATH, image_path)
    if not os.path.exists(full):
        print(f"❌ Không tìm thấy file ảnh {full}")
        return None

    start = time.time()
    while time.time() - start < timeout:
        screenshot = pyautogui.screenshot()
        screenshot = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

        template = cv2.imread(full, cv2.IMREAD_COLOR)
        if template is None:
            return None

        h, w = template.shape[:2]
        res = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)

        if max_val >= confidence:
            center_x = max_loc[0] + w // 2
            center_y = max_loc[1] + h // 2
            return (center_x, center_y)
        time.sleep(0.3)
    return None


def find_and_click(image_path, confidence=0.87, timeout=10):
    """Tìm ảnh bằng OpenCV và click"""
    full = os.path.join(IMG_PATH, image_path)
    if not os.path.exists(full):
        print(f"❌ Không tìm thấy file ảnh {full}")
        return False

    start = time.time()
    while time.time() - start < timeout:
        # chụp màn hình
        screenshot = pyautogui.screenshot()
        screenshot = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

        template = cv2.imread(full, cv2.IMREAD_COLOR)
        if template is None:
            print(f"❌ Không đọc được ảnh template {full}")
            return False

        h, w = template.shape[:2]

        res = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)

        if max_val >= confidence:
            center_x = max_loc[0] + w // 2
            center_y = max_loc[1] + h // 2
            pyautogui.click(center_x, center_y)
            print(f"✅ OpenCV Click {image_path} tại ({center_x},{center_y}), match={max_val:.2f}")
            time.sleep(1)
            return True
        else:
            print(f"⚠️ Chưa thấy {image_path}, độ khớp={max_val:.2f}, retry...")
            time.sleep(0.5)
    return False


def run_from_json(json_file):
    """Chạy workflow từ file JSON. Hỗ trợ wait_and_click_image, restart_after, loop_to."""
    with open(json_file, "r", encoding="utf-8") as f:
        steps = json.load(f)

    i = 0
    while i < len(steps):
        step = steps[i]
        action = step.get("action")
        print(f"[RUN] Action: {action} -> {step}")

        if action == "open_url":
            url = step.get("url")
            if url:
                webbrowser.open(url)
                print(f"🌐 Open URL: {url}")
            time.sleep(1)
            i += 1

        elif action == "scroll":
            base_px = step.get("px", 500)
            px = random.randint(base_px - 20, base_px + 20)  # random ±20 quanh px

            screen_w, screen_h = pyautogui.size()
            target_x, target_y = screen_w // 2 + random.randint(-30, 30), screen_h // 2 + random.randint(-20, 20)
            human_move_to(target_x, target_y)
            pyautogui.moveRel(
                random.uniform(-8, 8),
                random.uniform(-6, 6),
                duration=random.uniform(0.06, 0.18)
            )
            pyautogui.scroll(-px)
            print(f"🖱 Human-like scroll xuống {px}px (gốc {base_px}) từ ({target_x}, {target_y})")
            time.sleep(random.uniform(0.8, 1.6))
            i += 1

            
        elif action == "hotkey":
            keys = step.get("keys", [])
            if keys:
                pyautogui.hotkey(*keys)
                print(f"👉 Nhấn tổ hợp phím: {' + '.join(keys)}")
            else:
                print("⚠️ Không có phím nào để nhấn trong action hotkey")
            i += 1   # để sang bước tiếp theo

        elif action == "wait_and_click_image":
            image = step.get("image")
            retry_interval = step.get("retry_interval", 2)
            timeout_single = step.get("timeout_single", 2)
            threshold = step.get("threshold", 0.87)  # mặc định 0.87 nếu không truyền

            print(f"🔄 Chờ và click {image} (threshold={threshold})...")

            fail_count = 0  # đếm số lần thất bại liên tiếp
            while True:
                pos = find_image_pos(image, confidence=threshold, timeout=timeout_single)
                if pos:
                    x, y = pos
                    print(f"✅ Tìm thấy {image} tại ({x}, {y}) → di chuyển & click nhẹ")

                    # di chuyển mượt giống người
                    cx, cy = pyautogui.position()
                    pyautogui.moveTo(
                        cx + random.uniform(-10, 10),
                        cy + random.uniform(-10, 10),
                        duration=random.uniform(0.15, 0.35)
                    )
                    pyautogui.moveTo(
                        x + random.uniform(-3, 3),
                        y + random.uniform(-3, 3),
                        duration=random.uniform(0.25, 0.45)
                    )
                    pyautogui.click()
                    print(f"👆 Click xong {image}")
                    break  # ra khỏi while nếu đã click thành công

                else:
                    fail_count += 1
                    print(f"⚠️ Không thấy {image} (fail={fail_count}), thử lại sau {retry_interval}s...")
                    time.sleep(retry_interval)

                    # nếu fail 2 lần thì F5 và reset về đầu workflow
                    if fail_count >= 2:
                        print("🔄 Không thấy ảnh 2 lần => F5 lại trang và restart workflow...")
                        pyautogui.press("f5")
                        time.sleep(5)  # đợi trang load lại
                        i = 0  # reset về đầu workflow
                        break  # thoát vòng while, workflow sẽ restart sau khi i += 1

            i += 1



        elif action == "click_image":
            image = step.get("image")
            threshold = step.get("threshold", 0.96)  # mặc định 0.96
            print(f"🔘 Click image {image} (threshold={threshold})")
            if not find_and_click(image, timeout=10, confidence=threshold):
                return f"❌ Không tìm thấy ảnh {image}"
            i += 1

        elif action == "click_pos":
            x, y = step.get("x"), step.get("y")
            pyautogui.click(x, y)
            print(f"🖱 Click tọa độ ({x}, {y})")
            time.sleep(1)
            i += 1

        elif action == "click_offset":
            image = step.get("image")
            offset_x = step.get("x", 0)
            offset_y = step.get("y", 0)
            if image:
                pos = find_image_pos(image, timeout=5)
                if pos:
                    x, y = pos
                    pyautogui.click(x + offset_x, y + offset_y)
                    print(f"🖱 Click offset ({offset_x},{offset_y}) từ {image} tại ({x+offset_x},{y+offset_y})")
                else:
                    return f"❌ Không tìm thấy ảnh {image}"
            else:
                screen_w, screen_h = pyautogui.size()
                center_x, center_y = screen_w // 2, screen_h // 2
                pyautogui.click(center_x + offset_x, center_y + offset_y)
                print(f"🖱 Click offset từ center màn hình ({center_x+offset_x},{center_y+offset_y})")
            time.sleep(1)
            i += 1

        elif action == "input_text":
            text = step.get("text", "")
            print(f"⌨️ Nhập text: {text}")
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.5)
            pyautogui.press("delete")
            time.sleep(0.5)
            pyautogui.typewrite(text)
            time.sleep(0.8)
            i += 1

        elif action == "sleep":
            seconds = step.get("seconds", 3)
            print(f"⏳ Sleep {seconds}s...")
            time.sleep(seconds)
            i += 1

        elif action == "restart_after":
            seconds = step.get("seconds", 900)
            restart_url = step.get("url")
            print(f"⏳ Chờ {seconds}s trước khi restart workflow...")
            time.sleep(seconds)
            if restart_url:
                print(f"🔄 Mở lại URL trên tab hiện tại: {restart_url}")
                if not find_and_click("url.png", timeout=5):
                    pyautogui.click(200, 50)  # fallback
                time.sleep(0.5)
                pyautogui.hotkey("ctrl", "a")
                pyautogui.typewrite(restart_url)
                pyautogui.press("enter")
            i += 1

        elif action == "ocr_chat_list":
            ocr_chat_list(step)
            i += 1

        elif action == "ocr_all_chats_from_list":
            ocr_all_chats_from_list(step)
            i += 1


        elif action == "keep_product":
            print("👉 Đang giữ sản phẩm...")

            # danh sách ảnh cần click lần lượt
            product_images = [
                "huydon.png",
                "lydohuy1.png",
                "xacnhanhuy.png",
                "xacnhanhuy2.png",
                "themlaivaogio.png",
                "backlaigiohang.png",
                "mualai.png",
                "paypay1.png",
                "lendonlai.png"
            ]

            for img in product_images:
                print(f"👉 Đang xử lý {img}...")
                while True:
                    try:
                        location = pyautogui.locateCenterOnScreen(
                            os.path.join(IMG_PATH, img), confidence=0.96
                        )
                        if location:
                            pyautogui.click(location)
                            print(f"✅ Click vào {img} thành công")
                            time.sleep(3)
                            break  # thoát vòng lặp, sang ảnh tiếp theo
                        else:
                            print(f"⚠️ Chưa thấy {img}, retry sau 2s...")
                            time.sleep(2)
                    except Exception as e:
                        print(f"❌ Lỗi khi click {img}: {e}")
                        time.sleep(2)

            # ✅ sau khi xong hết danh sách ảnh, tăng i
            i += 1

        elif action == "loop_to":
            target = step.get("index", 0)
            print(f"🔁 Quay lại bước {target}")
            i = target  # nhảy lại bước mong muốn

        else:
            print(f"⚠️ Action chưa hỗ trợ: {action}")
            i += 1

    return "✅ Workflow hoàn tất!"


@app.route("/")
def index():
    current_url = ""
    current_quantity = 1  # mặc định số lượng = 1

    if os.path.exists(WORKFLOW_FILE):
        try:
            with open(WORKFLOW_FILE, "r", encoding="utf-8") as f:
                steps = json.load(f)
            for step in steps:
                if step.get("action") == "restart_after":
                    current_url = step.get("url", "")
                if step.get("action") == "input_text":
                    # ép thành int an toàn
                    try:
                        current_quantity = int(step.get("text", 1))
                    except:
                        current_quantity = 1
        except Exception as e:
            print("⚠️ Lỗi đọc workflow.json:", e)

    return render_template(
        "index.html",
        current_url=current_url,
        current_quantity=current_quantity,
        ma_sp_exists=os.path.exists(os.path.join(IMG_PATH, "ma_sp.png")),
        loai_sp_exists=os.path.exists(os.path.join(IMG_PATH, "loai_sp.png"))
    )

@app.route("/save", methods=["POST"])
def save_workflow():
    url = request.form.get("url")
    so_luong = request.form.get("so_luong")  # số lượng nhập từ form
    file_ma = request.files.get("ma_sp")
    file_loai = request.files.get("loai_sp")

    # lưu ảnh nếu có upload
    if file_ma:
        file_ma.save(os.path.join(IMG_PATH, "ma_sp.png"))
    if file_loai:
        file_loai.save(os.path.join(IMG_PATH, "loai_sp.png"))

    # ép số lượng thành int, default 1
    try:
        so_luong = str(max(1, int(so_luong)))
    except:
        so_luong = "1"

    # đọc workflow.json
    if not os.path.exists(WORKFLOW_FILE):
        return "❌ workflow.json chưa tồn tại", 400
    with open(WORKFLOW_FILE, "r", encoding="utf-8") as f:
        workflow = json.load(f)

    # cập nhật step restart_after.url
    for step in workflow:
        if step.get("action") == "restart_after":
            step["url"] = url

    # cập nhật step input_text.text
    updated = False
    for step in workflow:
        if step.get("action") == "input_text":
            step["text"] = so_luong
            updated = True
            break

    # nếu không có input_text thì thêm vào trước restart_after
    if not updated:
        for idx, step in enumerate(workflow):
            if step.get("action") == "restart_after":
                workflow.insert(idx, {"action": "input_text", "text": so_luong})
                break

    # ghi lại file
    with open(WORKFLOW_FILE, "w", encoding="utf-8") as f:
        json.dump(workflow, f, ensure_ascii=False, indent=2)

    return redirect("/")


@app.route("/start", methods=["POST"])
def start():
    if not os.path.exists(WORKFLOW_FILE):
        return jsonify({"result": "❌ workflow.json chưa có"}), 400
    result = run_from_json(WORKFLOW_FILE)
    return jsonify({"result": result})


if __name__ == "__main__":
    app.run(port=5000)
