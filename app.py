import os
import re
import time
import uuid
import shutil
import threading
from pathlib import Path
from urllib.parse import urljoin

import requests
from flask import Flask, request, jsonify, send_file

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from bs4 import BeautifulSoup

# ================= KONFIG =================

BASE_DIR = Path("/tmp/jobs")
BASE_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
jobs = {}  # job_id -> status

# ================= LOGGING =================

def log(job_id, msg, working=False):
    job = jobs[job_id]

    if working:
        job["dot"] = (job["dot"] + 1) % 4
        dots = "." * job["dot"]

        if job["logs"] and job["logs"][-1].startswith(msg):
            job["logs"][-1] = f"{msg}{dots}"
        else:
            job["logs"].append(f"{msg}{dots}")
    else:
        job["logs"].append(msg)
        job["dot"] = 0


# ================= CORE =================

def run_job(job_id, url, folder_name):
    job = jobs[job_id]

    try:
        job_dir = BASE_DIR / job_id
        img_dir = job_dir / folder_name
        img_dir.mkdir(parents=True, exist_ok=True)

        log(job_id, "Rozpoczynam pracę", working=True)
        time.sleep(1)
        log(job_id, "Rozpoczynam pracę")

        # ===== Selenium =====
        log(job_id, "Uruchamiam Chrome", working=True)

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")

        driver = webdriver.Chrome(options=options)
        wait = WebDriverWait(driver, 30)

        log(job_id, "Uruchamiam Chrome")

        log(job_id, "Otwieram stronę", working=True)
        driver.get(url)
        log(job_id, "Strona otwarta")

        # ===== FILTER (jeśli jest) =====
        try:
            log(job_id, "Szukam Filter", working=True)
            filter_btn = wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//button[.//text()[contains(., 'Filter')]]")
                )
            )
            filter_btn.click()
            time.sleep(2)
            log(job_id, "Kliknięto Filter")
        except:
            log(job_id, "Filter nie znaleziony — pomijam")

        # ===== IMAGES (jeśli jest) =====
        try:
            log(job_id, "Szukam Images", working=True)
            images_btn = wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//*[contains(text(),'Images')]")
                )
            )
            driver.execute_script("arguments[0].click();", images_btn)
            time.sleep(3)
            log(job_id, "Kliknięto Images")
        except:
            log(job_id, "Images nie znalezione — pomijam")

        # ===== SCROLL =====
        log(job_id, "Scrolluję stronę", working=True)
        last_height = 0
        for _ in range(12):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
        log(job_id, "Scroll zakończony")

        html = driver.page_source
        driver.quit()

        # ===== CLEAN HTML =====
        log(job_id, "Czyszczę HTML", working=True)
        html = re.sub(
            r"https://cdn\.ourdream\.ai/cdn-cgi/image/width=\d+/",
            "",
            html
        )
        log(job_id, "HTML oczyszczony")

        # ===== PARSOWANIE =====
        log(job_id, "Parsuję obrazy", working=True)
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

        image_urls = sorted(image_urls)
        log(job_id, f"Znaleziono {len(image_urls)} obrazów")

        # ===== DOWNLOAD =====
        for i, img_url in enumerate(image_urls, 1):
            success = False

            for _ in range(2):
                try:
                    r = requests.get(img_url, timeout=30)
                    if r.status_code != 200:
                        continue
                    if not r.headers.get("Content-Type", "").startswith("image/"):
                        continue
                    if len(r.content) < 5000:
                        continue

                    ext = img_url.split(".")[-1].split("?")[0].lower()
                    if ext not in ("jpg", "jpeg", "png", "webp"):
                        ext = "jpg"

                    with open(img_dir / f"img_{i}.{ext}", "wb") as f:
                        f.write(r.content)

                    success = True
                    break
                except:
                    pass

            if success:
                log(job_id, f"Pobrano {i}/{len(image_urls)}", working=True)
            else:
                log(job_id, f"Pominięto {i}/{len(image_urls)} (błąd)")

        log(job_id, "Pobieranie zakończone")

        # ===== ZIP =====
        log(job_id, "Pakuję ZIP", working=True)
        zip_path = shutil.make_archive(
            str(job_dir / folder_name),
            "zip",
            img_dir
        )
        log(job_id, "ZIP gotowy")

        job["zip"] = zip_path
        job["done"] = True
        log(job_id, "✅ GOTOWE")

    except Exception as e:
        job["error"] = str(e)
        log(job_id, "❌ BŁĄD!")


# ================= API =================

@app.route("/start", methods=["POST"])
def start():
    data = request.json
    job_id = str(uuid.uuid4())

    jobs[job_id] = {
        "logs": [],
        "done": False,
        "error": None,
        "zip": None,
        "dot": 0
    }

    threading.Thread(
        target=run_job,
        args=(job_id, data["url"], data["folder"]),
        daemon=True
    ).start()

    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
def status(job_id):
    return jsonify(jobs.get(job_id, {}))


@app.route("/download/<job_id>")
def download(job_id):
    job = jobs[job_id]
    return send_file(job["zip"], as_attachment=True)


@app.route("/")
def index():
    return "Backend działa"


# ================= START =================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
