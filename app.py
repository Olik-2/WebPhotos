import os
import time
import re
import threading
import zipfile
from pathlib import Path
from urllib.parse import urljoin

import requests
from flask import Flask, render_template, request, jsonify, send_file

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from bs4 import BeautifulSoup

app = Flask(__name__)

BASE_DIR = Path(__file__).parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)


# =========================
# GLOBALNY STAN JOBA
# =========================
job_state = {
    "status": "idle",
    "logs": [],
    "progress": 0,
    "zip_path": None
}


def add_log(msg):
    job_state["logs"].append(msg)
    print(msg)


# =========================
# SELENIUM WORKER
# =========================
def run_job(url, folder_name):
    try:
        job_state["status"] = "running"
        job_state["logs"].clear()
        job_state["progress"] = 0
        job_state["zip_path"] = None

        add_log("▶ Start Selenium")

        img_dir = DOWNLOAD_DIR / folder_name
        img_dir.mkdir(parents=True, exist_ok=True)

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")

        driver = webdriver.Chrome(options=options)
        wait = WebDriverWait(driver, 30)

        driver.get(url)
        add_log("✔ Strona otwarta")

        # FILTER (opcjonalnie)
        try:
            filter_btn = wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//button[.//text()[contains(., 'Filter')]]")
                )
            )
            filter_btn.click()
            time.sleep(1)
            add_log("✔ Kliknięto Filter")
        except Exception:
            add_log("ℹ️ Brak Filter — pomijam")

        # IMAGES
        try:
            images_btn = wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//*[contains(text(),'Images')]")
                )
            )
            driver.execute_script("arguments[0].click();", images_btn)
            time.sleep(2)
            add_log("✔ Kliknięto Images")
        except Exception:
            add_log("❌ Nie znaleziono Images")
            driver.quit()
            job_state["status"] = "error"
            return

        # SCROLL
        for _ in range(12):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)

        html = driver.page_source
        driver.quit()

        # USUWANIE cdn-cgi
        html = re.sub(
            r"https://cdn\.ourdream\.ai/cdn-cgi/image/width=\d+/",
            "",
            html
        )

        add_log("✔ HTML oczyszczony")

        # PARSOWANIE
        soup = BeautifulSoup(html, "html.parser")
        image_urls = set()

        for img in soup.find_all("img"):
            if img.get("data-src"):
                image_urls.add(urljoin(url, img["data-src"]))

            if img.get("src") and not img["src"].startswith("data:"):
                image_urls.add(urljoin(url, img["src"]))

            if img.get("srcset"):
                try:
                    largest = img["srcset"].split(",")[-1].split()[0]
                    image_urls.add(urljoin(url, largest))
                except Exception:
                    pass

        total = len(image_urls)
        add_log(f"📸 Znaleziono {total} obrazów")

        downloaded = 0

        for idx, img_url in enumerate(sorted(image_urls), 1):
            try:
                r = requests.get(img_url, timeout=20)
                if r.status_code != 200 or not r.content:
                    add_log(f"⚠️ Pominięto obraz {idx} (błąd HTTP)")
                    continue

                ext = img_url.split(".")[-1].split("?")[0].lower()
                if ext not in ("jpg", "jpeg", "png", "webp"):
                    ext = "jpg"

                file_path = img_dir / f"img_{idx}.{ext}"
                with open(file_path, "wb") as f:
                    f.write(r.content)

                if file_path.stat().st_size == 0:
                    add_log(f"⚠️ Pominięto obraz {idx} (pusty plik)")
                    file_path.unlink(missing_ok=True)
                    continue

                downloaded += 1
                job_state["progress"] = int((idx / total) * 100)
                add_log(f"✔ Pobrano {downloaded}/{total}")

            except Exception:
                add_log(f"⚠️ Pominięto obraz {idx} (wyjątek)")
                pass

        # ZIP
        zip_path = DOWNLOAD_DIR / f"{folder_name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file in img_dir.iterdir():
                zipf.write(file, arcname=file.name)

        job_state["zip_path"] = str(zip_path)
        job_state["status"] = "done"
        add_log("✅ Zakończono")

    except Exception as e:
        job_state["status"] = "error"
        add_log(f"❌ BŁĄD: {e}")


# =========================
# ROUTES
# =========================
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/start", methods=["POST"])
def start():
    data = request.json
    url = data.get("url")
    folder = data.get("folder")

    threading.Thread(
        target=run_job,
        args=(url, folder),
        daemon=True
    ).start()

    return jsonify({"ok": True})


@app.route("/status")
def status():
    return jsonify(job_state)


@app.route("/download")
def download():
    if job_state["zip_path"]:
        return send_file(job_state["zip_path"], as_attachment=True)
    return "Brak pliku", 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
