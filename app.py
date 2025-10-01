import json
import time
import pyautogui
import webbrowser
import os
import shutil
from datetime import datetime
from flask import Flask, request, jsonify, render_template, redirect

app = Flask(__name__)

IMG_PATH = "static/images/"
WORKFLOW_FILE = "workflow.json"

# đảm bảo thư mục ảnh tồn tại
os.makedirs(IMG_PATH, exist_ok=True)


def backup_workflow():
    """Tạo bản sao lưu workflow trước khi ghi đè"""
    if os.path.exists(WORKFLOW_FILE):
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        bak_name = WORKFLOW_FILE + f".bak.{ts}"
        shutil.copy(WORKFLOW_FILE, bak_name)
        print(f"🔖 Backup workflow -> {bak_name}")


def find_and_click(image_path, confidence=0.9, timeout=10):
    """Tìm ảnh trên màn hình và click (timeout tính bằng giây)"""
    full = os.path.join(IMG_PATH, image_path)
    start = time.time()
    while time.time() - start < timeout:
        try:
            pos = pyautogui.locateCenterOnScreen(full, confidence=confidence)
            if pos:
                pyautogui.click(pos)
                print(f"✅ Click vào {image_path} tại {pos}")
                time.sleep(1)
                return True
        except Exception as e:
            # pyautogui.ImageNotFoundException được bắt ở đây
            pass
        time.sleep(0.5)
    return False


def run_from_json(json_file):
    """Chạy workflow từ file JSON. Hỗ trợ wait_and_click_image và restart_after."""
    with open(json_file, "r", encoding="utf-8") as f:
        steps = json.load(f)

    for step in steps:
        action = step.get("action")
        print(f"[RUN] Action: {action} -> {step}")

        if action == "open_url":
            url = step.get("url")
            if url:
                webbrowser.open(url)
                print(f"🌐 Open URL: {url}")
            time.sleep(1)

        elif action == "scroll":
            px = step.get("px", 500)
            screen_w, screen_h = pyautogui.size()
            pyautogui.moveTo(screen_w // 2, screen_h // 2)
            pyautogui.scroll(-px)
            print(f"🖱 Scroll xuống {px}px")
            time.sleep(1)

        elif action == "wait_and_click_image":
            image = step.get("image")
            retry_interval = step.get("retry_interval", 2)
            timeout_single = step.get("timeout_single", 2)
            print(f"🔄 Chờ và click {image} mỗi {retry_interval}s (timeout mỗi lần {timeout_single}s)...")
            while True:
                if find_and_click(image, timeout=timeout_single):
                    print(f"✅ Đã click được {image}")
                    break
                print(f"⚠️ Không thấy {image}, retry sau {retry_interval}s...")
                time.sleep(retry_interval)

        elif action == "click_image":
            image = step.get("image")
            print(f"🔘 Click image {image}")
            if not find_and_click(image, timeout=10):
                return f"❌ Không tìm thấy ảnh {image}"

        elif action == "click_pos":
            x, y = step.get("x"), step.get("y")
            pyautogui.click(x, y)
            print(f"🖱 Click tọa độ ({x}, {y})")
            time.sleep(1)

        elif action == "click_offset":
            image = step.get("image")
            offset_x = step.get("x", 0)
            offset_y = step.get("y", 0)
            if image:
                pos = pyautogui.locateCenterOnScreen(os.path.join(IMG_PATH, image), confidence=0.8)
                if pos:
                    x, y = pos
                    pyautogui.click(x + offset_x, y + offset_y)
                    print(f"🖱 Click offset ({offset_x},{offset_y}) từ {image} tại ({x+offset_x},{y+offset_y})")
                else:
                    return f"❌ Không tìm thấy ảnh {image} để click offset"
            else:
                screen_w, screen_h = pyautogui.size()
                center_x, center_y = screen_w // 2, screen_h // 2
                pyautogui.click(center_x + offset_x, center_y + offset_y)
                print(f"🖱 Click offset ({offset_x},{offset_y}) từ center màn hình tại ({center_x+offset_x},{center_y+offset_y})")
            time.sleep(1)

        elif action == "input_text":
            text = step.get("text", "")
            print(f"⌨️ Nhập text: {text}")
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.2)
            pyautogui.press("delete")
            time.sleep(0.2)
            pyautogui.typewrite(text)
            time.sleep(0.5)

        elif action == "sleep":
            seconds = step.get("seconds", 3)
            print(f"⏳ Sleep {seconds}s...")
            time.sleep(seconds)

        elif action == "restart_after":
            seconds = step.get("seconds", 900)
            restart_url = step.get("url")
            print(f"⏳ Chờ {seconds}s trước khi restart workflow...")
            time.sleep(seconds)
            if restart_url:
                print(f"🔄 Mở lại URL: {restart_url}")
                webbrowser.open(restart_url)
            # nếu bạn muốn loop lại workflow, có thể gọi run_from_json(json_file) ở đây
            # nhưng hiện tại chỉ mở lại URL và tiếp tục chạy các bước tiếp theo

        else:
            print(f"⚠️ Action chưa hỗ trợ: {action}")

    return "✅ Workflow hoàn tất!"


@app.route("/")
def index():
    current_url = ""
    if os.path.exists(WORKFLOW_FILE):
        try:
            with open(WORKFLOW_FILE, "r", encoding="utf-8") as f:
                steps = json.load(f)
            for step in steps:
                if step.get("action") == "open_url":
                    current_url = step.get("url", "")
                    break
        except Exception as e:
            print("⚠️ Lỗi đọc workflow.json:", e)

    return render_template(
        "index.html",
        current_url=current_url,
        ma_sp_exists=os.path.exists(os.path.join(IMG_PATH, "ma_sp.png")),
        loai_sp_exists=os.path.exists(os.path.join(IMG_PATH, "loai_sp.png"))
    )


@app.route("/save", methods=["POST"])
def save_workflow():
    url = request.form.get("url")
    file_ma = request.files.get("ma_sp")
    file_loai = request.files.get("loai_sp")

    # Lưu ảnh mới nếu upload
    if file_ma:
        file_ma.save(os.path.join(IMG_PATH, "ma_sp.png"))
    if file_loai:
        file_loai.save(os.path.join(IMG_PATH, "loai_sp.png"))

    # Cập nhật URL trong step restart_after
    if os.path.exists(WORKFLOW_FILE):
        with open(WORKFLOW_FILE, "r", encoding="utf-8") as f:
            workflow = json.load(f)
    else:
        return "❌ workflow.json chưa tồn tại, hãy tạo trước", 400

    updated = False
    for step in workflow:
        if step.get("action") == "restart_after":
            step["url"] = url
            updated = True
            break

    if not updated:
        return "❌ Không tìm thấy step restart_after trong workflow.json", 400

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
