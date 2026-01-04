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
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


app = Flask(__name__)

BASE_DIR = Path(__file__).parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

jobs = {}


def log(job_id, msg, progress=None, working=True):
    dots = ["", ".", "..", "..."]
    if working:
        i = jobs[job_id]["dot"]
        msg = msg + " " + dots[i]
        jobs[job_id]["dot"] = (i + 1) % 4

    jobs[job_id]["logs"].append(msg)
    if progress is not None:
        jobs[job_id]["progress"] = progress
    print(f"[{job_id}] {msg}", flush=True)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/start", methods=["POST"])
def start():
    data = request.json
    job_id = str(time.time())

    jobs[job_id] = {
        "logs": ["Startuję job"],
        "progress": 0,
        "done": False,
        "error": False,
        "zip": None,
        "dot": 0
    }

    threading.Thread(
        target=run_selenium,
        args=(job_id, data["url"], data["folder"]),
        daemon=True
    ).start()

    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
def status(job_id):
    return jsonify(jobs.get(job_id, {}))


@app.route("/download/<job_id>")
def download(job_id):
    return send_file(jobs[job_id]["zip"], as_attachment=True)


def run_selenium(job_id, URL, folder_name):
    try:
        log(job_id, "Wejście do procesu", 2)

        img_dir = DOWNLOAD_DIR / folder_name
        img_dir.mkdir(exist_ok=True)

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")

        service = Service("/usr/bin/chromedriver")

        log(job_id, "Uruchamiam Chrome", 5)
        driver = webdriver.Chrome(service=service, options=options)
        wait = WebDriverWait(driver, 30)

        driver.get(URL)
        log(job_id, "Strona otwarta", 15)

        # FILTER (IF ISTNIEJE)
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
            log(job_id, "Filter pominięty", 25, working=False)

        # IMAGES (IF ISTNIEJE)
        try:
            images_btn = wait.until(
                EC.presence_of_element_located(
                    (By.XPATH, "//*[contains(text(),'Images')]")
                )
            )
            driver.execute_script("arguments[0].click();", images_btn)
            log(job_id, "Kliknięto Images", 35)
            time.sleep(3)
        except:
            log(job_id, "Images pominięty", 35, working=False)

        # SCROLL
        for i in range(12):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            log(job_id, f"Scroll {i+1}/12", 35 + i)
            time.sleep(2)

        html = driver.page_source
        driver.quit()
        log(job_id, "HTML pobrany", 55)

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

        log(job_id, f"Znaleziono {len(urls)} obrazów", 65)

        for i, u in enumerate(sorted(urls), 1):
            try:
                r = requests.get(u, timeout=20)
                if r.status_code != 200:
                    continue
                with open(img_dir / f"img_{i}.jpg", "wb") as f:
                    f.write(r.content)
                log(job_id, f"Pobrano {i}/{len(urls)}", 65 + int(i / len(urls) * 25))
            except:
                pass

        zip_path = DOWNLOAD_DIR / f"{folder_name}.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            for f in img_dir.iterdir():
                z.write(f, f.name)

        jobs[job_id]["zip"] = str(zip_path)
        jobs[job_id]["done"] = True
        jobs[job_id]["progress"] = 100
        log(job_id, "GOTOWE", working=False)

    except Exception as e:
        jobs[job_id]["error"] = True
        log(job_id, "BŁĄD!", working=False)
        log(job_id, str(e), working=False)
