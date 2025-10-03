import json
import time
import pyautogui
import webbrowser
import os
import shutil
import cv2
import numpy as np
import requests
from datetime import datetime
from flask import Flask, request, jsonify, render_template, redirect

app = Flask(__name__)

IMG_PATH = "static/images/"
WORKFLOW_FILE = "workflow.json"

# đảm bảo thư mục ảnh tồn tại
os.makedirs(IMG_PATH, exist_ok=True)
TOKEN = "8399603454:AAFYyIAFPiV8REr-2uYwsEzJax0YgSX1frU"
CHAT_ID = -4948414512  # ID group "Thông báo đơn hàng"

def send_telegram_message(text):
    """Gửi tin nhắn về Telegram group"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    try:
        res = requests.post(url, json=payload, timeout=5)
        print("📩 Gửi Telegram:", res.json())
    except Exception as e:
        print("⚠️ Lỗi gửi Telegram:", e)

def backup_workflow():
    """Tạo bản sao lưu workflow trước khi ghi đè"""
    if os.path.exists(WORKFLOW_FILE):
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        bak_name = WORKFLOW_FILE + f".bak.{ts}"
        shutil.copy(WORKFLOW_FILE, bak_name)
        print(f"🔖 Backup workflow -> {bak_name}")


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
            px = step.get("px", 500)
            screen_w, screen_h = pyautogui.size()
            pyautogui.moveTo(screen_w // 2, screen_h // 2)
            pyautogui.scroll(-px)
            print(f"🖱 Scroll xuống {px}px")
            time.sleep(1)
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
            threshold = step.get("threshold", 0.96)  # mặc định 0.96 nếu không truyền

            print(f"🔄 Chờ và click {image} (threshold={threshold})...")

            fail_count = 0  # đếm số lần thất bại liên tiếp
            while True:
                if find_and_click(image, timeout=timeout_single, confidence=threshold):
                    print(f"✅ Đã click được {image}")
                    break
                else:
                    fail_count += 1
                    print(f"⚠️ Không thấy {image} (fail={fail_count}), retry sau {retry_interval}s...")
                    time.sleep(retry_interval)

                    # nếu fail 2 lần thì F5 và reset i = 1
                    if fail_count >= 2:
                        print("🔄 Không thấy ảnh 2 lần => F5 lại trang và restart workflow...")
                        pyautogui.press("f5")
                        time.sleep(5)  # đợi trang load
                        i = 0  # reset về đầu workflow (vì cuối loop có i += 1, nên i=0 -> sẽ thành 1)
                        break

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
            send_telegram_message("✅ Đơn hàng đã được giữ thành công!")


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
