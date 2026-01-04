import os
import re
import time
import zipfile
import uuid
from pathlib import Path
from urllib.parse import urljoin

import requests
from flask import Flask, render_template, request, send_file, jsonify

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from bs4 import BeautifulSoup

app = Flask(__name__)

JOBS = {}  # job_id -> log list


def log(job_id, msg):
    JOBS[job_id].append(msg)
    print(f"[{job_id}] {msg}")


def run_job(job_id, url, folder_name):
    try:
        JOBS[job_id] = []
        log(job_id, "➡ Start Selenium")

        base_dir = Path("/tmp") / job_id
        img_dir = base_dir / folder_name
        img_dir.mkdir(parents=True, exist_ok=True)

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        driver = webdriver.Chrome(options=options)
        wait = WebDriverWait(driver, 30)

        driver.get(url)
        log(job_id, "✔ Strona otwarta")

        # FILTER (jeśli istnieje)
        try:
            filter_btn = wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//button[.//text()[contains(., 'Filter')]]")
                )
            )
            filter_btn.click()
            time.sleep(1)
            log(job_id, "✔ Kliknięto Filter")
        except:
            log(job_id, "ℹ Brak Filter – pominięto")

        # IMAGES
        images_btn = wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//*[contains(text(),'Images')]")
            )
        )
        driver.execute_script("arguments[0].click();", images_btn)
        time.sleep(2)
        log(job_id, "✔ Kliknięto Images")

        # SCROLL
        for _ in range(12):
            driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);"
            )
            time.sleep(2)

        html = driver.page_source
        driver.quit()

        # USUWANIE CDN
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

        log(job_id, f"➡ Znaleziono {len(image_urls)} obrazów")

        downloaded = 0
        for i, img_url in enumerate(sorted(image_urls), 1):
            try:
                r = requests.get(img_url, timeout=20)
                if r.status_code != 200:
                    continue

                ext = img_url.split(".")[-1].split("?")[0].lower()
                if ext not in ("jpg", "jpeg", "png", "webp"):
                    ext = "jpg"

                with open(img_dir / f"img_{i}.{ext}", "wb") as f:
                    f.write(r.content)

                downloaded += 1
                log(job_id, f"Pobrano {downloaded}")
            except:
                pass

        # ZIP
        zip_path = base_dir / "images.zip"
        with zipfile.ZipFile(zip_path, "w") as zipf:
            for file in img_dir.iterdir():
                zipf.write(file, arcname=file.name)

        log(job_id, "✅ GOTOWE")

    except Exception as e:
        log(job_id, f"❌ Błąd: {e}")


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/start", methods=["POST"])
def start():
    url = request.form["url"]
    folder = request.form["folder"]

    job_id = str(uuid.uuid4())
    JOBS[job_id] = []

    from threading import Thread
    Thread(target=run_job, args=(job_id, url, folder), daemon=True).start()

    return jsonify({"job_id": job_id})


@app.route("/logs/<job_id>")
def logs(job_id):
    return jsonify(JOBS.get(job_id, []))


@app.route("/download/<job_id>")
def download(job_id):
    zip_path = Path("/tmp") / job_id / "images.zip"
    return send_file(zip_path, as_attachment=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
