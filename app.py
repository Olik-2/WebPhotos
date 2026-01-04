import os
import time
import threading
import signal

from flask import Flask, render_template, request, Response
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import requests
from urllib.parse import urljoin

app = Flask(__name__)
logs = []


def log(msg):
    print(msg)
    logs.append(msg)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/logs")
def stream_logs():
    def event_stream():
        last = 0
        while True:
            if len(logs) > last:
                yield logs[last] + "\n"
                last += 1
            time.sleep(0.5)
    return Response(event_stream(), mimetype="text/plain")


@app.route("/start", methods=["POST"])
def start():
    url = request.form["url"]
    folder = request.form["folder"]
    threading.Thread(target=run_job, args=(url, folder), daemon=True).start()
    return "OK"


def run_job(URL, folder_name):
    try:
        log("➡ Start")

        os.makedirs("downloads", exist_ok=True)
        target_dir = os.path.join("downloads", folder_name)
        os.makedirs(target_dir, exist_ok=True)

        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        driver = webdriver.Chrome(options=options)
        wait = WebDriverWait(driver, 30)

        log("🌐 Otwieram stronę")
        driver.get(URL)
        time.sleep(3)

        # FILTER (opcjonalnie)
        try:
            log("🔘 Szukam Filter")
            filter_btn = wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//button[contains(.,'Filter')]")
                )
            )
            filter_btn.click()
            time.sleep(2)
        except:
            log("ℹ Filter nie znaleziony")

        # IMAGES
        log("🖼 Klikam Images")
        images_btn = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//*[contains(text(),'Images')]")
            )
        )
        driver.execute_script("arguments[0].click();", images_btn)
        time.sleep(5)

        log("⬇ Scroll")
        for _ in range(10):
            driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight)"
            )
            time.sleep(2)

        html = driver.page_source
        driver.quit()

        log("✂ Usuwam linię CDN")
        html = "\n".join(
            line for line in html.splitlines()
            if "https://cdn.ourdream.ai/cdn-cgi/image/width=30/" not in line
        )

        soup = BeautifulSoup(html, "html.parser")
        images = set()

        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src")
            if src and not src.startswith("data:"):
                images.add(urljoin(URL, src))

        log(f"🔎 Znaleziono {len(images)} obrazów")

        for i, img_url in enumerate(images, 1):
            try:
                r = requests.get(img_url, timeout=20)
                if r.status_code == 200:
                    with open(
                        os.path.join(target_dir, f"img_{i}.jpg"), "wb"
                    ) as f:
                        f.write(r.content)
                    log(f"✔ Pobrano {i}")
            except:
                pass

        log("✅ GOTOWE — zamykanie serwera")
        time.sleep(2)
        os.kill(os.getpid(), signal.SIGTERM)

    except Exception as e:
        log(f"❌ Błąd: {e}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
