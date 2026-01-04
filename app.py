import os
import time
import re
import threading
import zipfile
import uuid
from pathlib import Path
from urllib.parse import urljoin

import requests
from flask import Flask, request, jsonify, send_file
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup

# ================= APP =================

app = Flask(__name__)

BASE_DIR = Path("/tmp/jobs")
BASE_DIR.mkdir(exist_ok=True)

jobs = {}

# ================= LOGGING =================

DOTS = ["", ".", "..", "..."]

def log(job_id, msg, working=False):
    job = jobs[job_id]
    if working:
        job["dot"] = (job["dot"] + 1) % 4
        msg = msg + " " + DOTS[job["dot"]]
    job["logs"].append(msg)

# ================= SELENIUM HELPERS =================

def click_if_exists(driver, xpath, job_id, label, timeout=20):
    log(job_id, f"Szukam {label}", working=True)
    end = time.time() + timeout

    while time.time() < end:
        try:
            els = driver.find_elements(By.XPATH, xpath)
            if els:
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});", els[0]
                )
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", els[0])
                log(job_id, f"{label} kliknięty")
                return True
        except Exception:
            pass

        log(job_id, f"Szukam {label}", working=True)
        time.sleep(1)

    log(job_id, f"{label} pominięty")
    return False

# ================= JOB =================

def run_job(job_id, url, folder_name):
    try:
        job = jobs[job_id]
        log(job_id, "Startuję Selenium")

        job_dir = BASE_DIR / job_id
        img_dir = job_dir / folder_name
        img_dir.mkdir(parents=True, exist_ok=True)

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        driver = webdriver.Chrome(options=options)
        driver.get(url)
        log(job_id, "Strona otwarta")

        # FILTER → IMAGES
        click_if_exists(driver, "//button[.//text()[contains(., 'Filter')]]", job_id, "Filter")
        time.sleep(2)
        click_if_exists(driver, "//*[contains(text(),'Images')]", job_id, "Images")
        time.sleep(3)

        # SCROLL
        for i in range(12):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            log(job_id, f"Scroll {i+1}/12", working=True)
            time.sleep(2)

        log(job_id, "Scroll zakończony")

        html = driver.page_source
        driver.quit()

        # CLEAN HTML
        html = re.sub(
            r"https://cdn\.ourdream\.ai/cdn-cgi/image/width=\d+/",
            "",
            html,
        )
        log(job_id, "HTML oczyszczony")

        soup = BeautifulSoup(html, "html.parser")

        image_urls = set()
        for img in soup.find_all("img"):
            for attr in ("data-src", "src"):
                if img.get(attr) and not img[attr].startswith("data:"):
                    image_urls.add(urljoin(url, img[attr]))
            if img.get("srcset"):
                largest = img["srcset"].split(",")[-1].split()[0]
                image_urls.add(urljoin(url, largest))

        log(job_id, f"Znaleziono {len(image_urls)} obrazów")

        # DOWNLOAD
        for i, img_url in enumerate(sorted(image_urls), 1):
            try:
                r = requests.get(img_url, timeout=20)
                if r.status_code != 200:
                    continue
                ext = img_url.split(".")[-1].split("?")[0]
                if ext not in ("jpg", "jpeg", "png", "webp"):
                    ext = "jpg"
                with open(img_dir / f"img_{i}.{ext}", "wb") as f:
                    f.write(r.content)
                log(job_id, f"Pobrano {i}", working=True)
            except Exception:
                pass

        # ZIP
        zip_path = job_dir / f"{folder_name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file in img_dir.iterdir():
                zipf.write(file, arcname=file.name)

        job["zip"] = str(zip_path)
        job["done"] = True
        log(job_id, "✅ GOTOWE")

    except Exception as e:
        jobs[job_id]["error"] = True
        jobs[job_id]["done"] = True
        log(job_id, "❌ BŁĄD!")
        log(job_id, str(e))

# ================= ROUTES =================

@app.route("/start", methods=["POST"])
def start():
    data = request.json
    job_id = str(uuid.uuid4())

    jobs[job_id] = {
        "logs": [],
        "done": False,
        "error": False,
        "zip": None,
        "dot": 0,
    }

    threading.Thread(
        target=run_job,
        args=(job_id, data["url"], data["folder"]),
        daemon=True,
    ).start()

    return jsonify({"job_id": job_id})

@app.route("/status/<job_id>")
def status(job_id):
    return jsonify(jobs.get(job_id, {}))

@app.route("/download/<job_id>")
def download(job_id):
    job = jobs.get(job_id)
    if not job or not job["zip"]:
        return "Brak pliku", 404
    return send_file(job["zip"], as_attachment=True)

# ================= RUN =================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
