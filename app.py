import os
import threading
import time
import zipfile
import uuid
import re
import requests
from pathlib import Path
from urllib.parse import urljoin

from flask import Flask, render_template, request, jsonify, send_file

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from bs4 import BeautifulSoup

# ===================== APP =====================

app = Flask(__name__)

BASE_DIR = Path(__file__).parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

# ===================== GLOBAL STATE =====================

state = {
    "running": False,
    "log": "",
    "progress": 0,
    "zip_path": None,
    "error": None,
}

# ===================== HELPERS =====================

def set_log(msg):
    state["log"] = msg

def set_progress(p):
    state["progress"] = p

def fail(msg):
    state["error"] = msg
    state["running"] = False

# ===================== SELENIUM JOB =====================

def run_job(url, folder_name):
    try:
        state["running"] = True
        state["error"] = None
        state["zip_path"] = None
        set_progress(0)

        job_id = str(uuid.uuid4())
        img_dir = DOWNLOAD_DIR / job_id
        img_dir.mkdir(exist_ok=True)

        set_log("Uruchamiam Chrome")
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")

        driver = webdriver.Chrome(options=options)
        wait = WebDriverWait(driver, 30)

        driver.get(url)
        set_log("Strona otwarta")
        time.sleep(2)

        # FILTER (jeśli istnieje)
        try:
            filter_btn = wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//button[.//text()[contains(., 'Filter')]]")
                )
            )
            filter_btn.click()
            set_log("Kliknięto Filter")
            time.sleep(2)
        except Exception:
            set_log("Brak Filter – pomijam")

        # IMAGES (jeśli istnieje)
        try:
            images_btn = wait.until(
                EC.presence_of_element_located(
                    (By.XPATH, "//*[contains(text(),'Images')]")
                )
            )
            driver.execute_script("arguments[0].click();", images_btn)
            set_log("Kliknięto Images")
            time.sleep(2)
        except Exception:
            set_log("Brak Images – pomijam")

        # SCROLL
        set_log("Scrollowanie strony")
        for _ in range(10):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)

        html = driver.page_source
        driver.quit()

        # Oczyszczanie CDN
        html = re.sub(
            r"https://cdn\.ourdream\.ai/cdn-cgi/image/width=\d+/",
            "",
            html
        )

        soup = BeautifulSoup(html, "html.parser")
        image_urls = set()

        for img in soup.find_all("img"):
            if img.get("data-src"):
                image_urls.add(urljoin(url, img["data-src"]))
            if img.get("src") and not img["src"].startswith("data:"):
                image_urls.add(urljoin(url, img["src"]))
            if img.get("srcset"):
                largest = img["srcset"].split(",")[-1].split()[0]
                image_urls.add(urljoin(url, largest))

        total = len(image_urls)
        if total == 0:
            fail("Nie znaleziono obrazów")
            return

        set_log(f"Znaleziono {total} obrazów")
        downloaded = 0

        for idx, img_url in enumerate(sorted(image_urls), 1):
            try:
                r = requests.get(img_url, timeout=20)
                if r.status_code != 200 or len(r.content) < 1024:
                    set_log(f"Pominięto uszkodzony obraz {idx}/{total}")
                    continue

                ext = img_url.split(".")[-1].split("?")[0].lower()
                if ext not in ("jpg", "jpeg", "png", "webp"):
                    ext = "jpg"

                file_path = img_dir / f"img_{idx}.{ext}"
                with open(file_path, "wb") as f:
                    f.write(r.content)

                downloaded += 1
                set_log(f"Pobrano {downloaded}/{total}")
                set_progress(int((idx / total) * 100))

            except Exception:
                set_log(f"Błąd pobierania {idx}/{total}")

        # ZIP
        zip_path = DOWNLOAD_DIR / f"{folder_name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file in img_dir.iterdir():
                zipf.write(file, file.name)

        state["zip_path"] = zip_path.name
        set_log("Zakończono – ZIP gotowy")
        set_progress(100)

    except Exception as e:
        fail(str(e))

    finally:
        state["running"] = False

# ===================== ROUTES =====================

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/start", methods=["POST"])
def start():
    if state["running"]:
        return jsonify({"status": "busy"})

    data = request.json
    url = data.get("url")
    folder = data.get("folder", "images")

    threading.Thread(target=run_job, args=(url, folder), daemon=True).start()
    return jsonify({"status": "started"})

@app.route("/status")
def status():
    return jsonify(state)

@app.route("/download")
def download():
    if not state["zip_path"]:
        return "Brak pliku", 404
    return send_file(
        DOWNLOAD_DIR / state["zip_path"],
        as_attachment=True
    )

# ===================== MAIN =====================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
