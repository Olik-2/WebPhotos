import os
import re
import time
import threading
import zipfile
from pathlib import Path
from urllib.parse import urljoin

import requests
from flask import Flask, request, jsonify, send_file, render_template
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


app = Flask(__name__)

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

jobs = {}  # job_id -> status/logs/progress


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/start", methods=["POST"])
def start():
    data = request.json
    url = data["url"]
    folder = data["folder"]

    job_id = str(time.time())
    jobs[job_id] = {
        "progress": 0,
        "logs": [],
        "done": False,
        "zip": None
    }

    threading.Thread(
        target=run_job,
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


def log(job_id, msg, progress=None):
    jobs[job_id]["logs"].append(msg)
    if progress is not None:
        jobs[job_id]["progress"] = progress


def run_job(job_id, URL, folder_name):
    try:
        out_dir = DOWNLOAD_DIR / folder_name
        out_dir.mkdir(exist_ok=True)

        log(job_id, "Start Selenium", 5)

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        driver = webdriver.Chrome(options=options)
        wait = WebDriverWait(driver, 30)

        driver.get(URL)
        log(job_id, "Strona otwarta", 15)

        # FILTER (jeśli istnieje)
        try:
            filter_btn = wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//button[.//text()[contains(., 'Filter')]]")
                )
            )
            filter_btn.click()
            log(job_id, "Kliknięto Filter", 25)
            time.sleep(2)
        except:
            log(job_id, "Brak Filter – pomijam", 25)

        # IMAGES
        images_btn = wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//*[contains(text(),'Images')]")
            )
        )
        driver.execute_script("arguments[0].click();", images_btn)
        log(job_id, "Kliknięto Images", 35)
        time.sleep(3)

        # SCROLL
        for i in range(10):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
            log(job_id, f"Scroll {i+1}/10", 35 + i * 2)
            time.sleep(2)

        html = driver.page_source
        driver.quit()

        html = re.sub(
            r"https://cdn\.ourdream\.ai/cdn-cgi/image/width=\d+/",
            "",
            html
        )

        soup = BeautifulSoup(html, "html.parser")
        urls = set()

        for img in soup.find_all("img"):
            for attr in ("data-src", "src"):
                if img.get(attr) and not img[attr].startswith("data:"):
                    urls.add(urljoin(URL, img[attr]))

            if img.get("srcset"):
                urls.add(urljoin(URL, img["srcset"].split(",")[-1].split()[0]))

        log(job_id, f"Znaleziono {len(urls)} obrazów", 60)

        for i, u in enumerate(urls, 1):
            try:
                r = requests.get(u, timeout=20)
                if r.status_code != 200:
                    continue

                name = f"img_{i}.jpg"
                with open(out_dir / name, "wb") as f:
                    f.write(r.content)

                log(job_id, f"Pobrano {i}/{len(urls)}", 60 + int(i / len(urls) * 30))
            except:
                pass

        zip_path = DOWNLOAD_DIR / f"{folder_name}.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            for f in out_dir.iterdir():
                z.write(f, f.name)

        jobs[job_id]["zip"] = str(zip_path)
        jobs[job_id]["done"] = True
        jobs[job_id]["progress"] = 100
        log(job_id, "GOTOWE")

    except Exception as e:
        log(job_id, f"BŁĄD: {e}")
