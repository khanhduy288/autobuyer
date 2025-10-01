import json, time, pyautogui, webbrowser

IMG_PATH = "static/images/"

def find_and_click(image_path, confidence=0.8, timeout=10):
    start = time.time()
    while time.time() - start < timeout:
        pos = pyautogui.locateCenterOnScreen(IMG_PATH + image_path, confidence=confidence)
        if pos:
            pyautogui.click(pos)
            time.sleep(1)
            return True
        time.sleep(1)
    return False

def run_from_json(json_file):
    with open(json_file, "r", encoding="utf-8") as f:
        steps = json.load(f)

    for step in steps:
        action = step.get("action")

        if action == "open_url":
            webbrowser.open(step["url"])
            time.sleep(3)

        elif action == "scroll":
            pyautogui.scroll(-step.get("px", 500))
            time.sleep(1)

        elif action == "click_image":
            if not find_and_click(step["image"]):
                return f"❌ Không tìm thấy ảnh {step['image']}"

        elif action == "wait_for_image":
            image = step["image"]
            retry = step.get("retry", 3)
            refresh = step.get("refresh", False)
            px = step.get("px", 500)
            found = False
            for _ in range(retry):
                if find_and_click(image, timeout=5):
                    found = True
                    break
                if refresh:
                    pyautogui.press("f5")
                    time.sleep(3)
                    pyautogui.scroll(-px)
            if not found:
                return f"❌ Không tìm thấy ảnh {image}"

        else:
            print(f"⚠️ Action chưa hỗ trợ: {action}")

    return "✅ Workflow hoàn tất!"
