import os
import threading
import time
import uuid
import zipfile
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

app = Flask(__name__)

BASE_DIR = Path(__file__).parent
DOWNLOADS = BASE_DIR / "downloads"
DOWNLOADS.mkdir(exist_ok=True)

jobs = {}


# ======================= STRONA =======================

@app.route("/")
def index():
    return render_template("index.html")


# ======================= API =======================

@app.route("/start", methods=["POST"])
def start():
    data = request.json
    url = data["url"]
    folder = data["folder"]

    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "log": "Rozpoczynam pracę",
        "progress": 0,
        "done": False,
        "zip": None,
        "error": False,
    }

    threading.Thread(
        target=worker,
        args=(job_id, url, folder),
        daemon=True
    ).start()

    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
def status(job_id):
    return jsonify(jobs.get(job_id, {}))


@app.route("/download/<job_id>")
def download(job_id):
    zip_path = jobs[job_id]["zip"]
    return send_file(zip_path, as_attachment=True)


# ======================= LOGIKA =======================

def log_error(message):
    logs.append({
        "type": "error",
        "message": message
    })

def worker(job_id, URL, FOLDER):
    try:
        def set_log(msg, progress=None):
            jobs[job_id]["log"] = msg
            if progress is not None:
                jobs[job_id]["progress"] = progress

        set_log("Uruchamiam Chrome", 5)

        img_dir = DOWNLOADS / FOLDER
        img_dir.mkdir(exist_ok=True)

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")

        driver = webdriver.Chrome(options=options)
        wait = WebDriverWait(driver, 30)

        set_log("Otwieram stronę", 10)
        driver.get(URL)

        # FILTER (jeśli istnieje)
        try:
            set_log("Klikam Filter", 20)
            filter_btn = wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//button[.//text()[contains(., 'Filter')]]")
                )
            )
            filter_btn.click()
            time.sleep(2)
        except:
            pass

        # IMAGES (jeśli istnieje)
        try:
            set_log("Klikam Images", 30)
            images_btn = wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//*[contains(text(),'Images')]")
                )
            )
            driver.execute_script("arguments[0].click();", images_btn)
            time.sleep(2)
        except:
            pass

        set_log("Scrolluję stronę", 40)
        for _ in range(12):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)

        html = driver.page_source
        driver.quit()

        set_log("Analizuję HTML", 55)

        html = re.sub(
            r"https://cdn\.ourdream\.ai/cdn-cgi/image/width=\d+/",
            "",
            html
        )

        soup = BeautifulSoup(html, "html.parser")
        urls = set()

        for img in soup.find_all("img"):
            if img.get("data-src"):
                urls.add(urljoin(URL, img["data-src"]))
            if img.get("src") and not img["src"].startswith("data:"):
                urls.add(urljoin(URL, img["src"]))
            if img.get("srcset"):
                urls.add(urljoin(URL, img["srcset"].split(",")[-1].split()[0]))

        total = len(urls)
        set_log(f"Pobieram obrazy 0/{total}", 65)

        for i, img_url in enumerate(image_urls, 1):
    try:
        r = requests.get(img_url, timeout=20)

        if r.status_code != 200:
            log_error(f"❌ Pominięto obraz {i}: HTTP {r.status_code}")
            continue

        if not r.content or len(r.content) < 1024:
            log_error(f"❌ Pominięto obraz {i}: plik pusty lub za mały")
            continue

        file_path = download_dir / f"img_{i}.jpg"

        with open(file_path, "wb") as f:
            f.write(r.content)

    except Exception as e:
        log_error(f"❌ Pominięto obraz {i}: błąd zapisu")


            ext = img_url.split(".")[-1].split("?")[0]
            if ext not in ("jpg", "jpeg", "png", "webp"):
                ext = "jpg"

            with open(img_dir / f"img_{i}.{ext}", "wb") as f:
                f.write(r.content)

            set_log(f"Pobieram obrazy {i}/{total}", 65 + int(25 * i / total))

        set_log("Tworzę ZIP", 95)
        zip_path = DOWNLOADS / f"{FOLDER}.zip"

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for f in img_dir.iterdir():
                z.write(f, f.name)

        jobs[job_id]["zip"] = str(zip_path)
        jobs[job_id]["done"] = True
        set_log("Zakończono", 100)

    except Exception:
        jobs[job_id]["error"] = True
        jobs[job_id]["log"] = "BŁĄD!"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)


