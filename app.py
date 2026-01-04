import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import re
import requests
from pathlib import Path
from urllib.parse import urljoin
import zipfile
import os
import sys

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from bs4 import BeautifulSoup


# ================= POMOCNICZE =================

def open_folder(path: Path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)
        elif sys.platform.startswith("darwin"):
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')
    except Exception:
        pass


# ================= GUI =================

def log(msg):
    log_box.insert(tk.END, msg + "\n")
    log_box.see(tk.END)
    root.update_idletasks()


def start_job():
    url = url_entry.get().strip()
    folder_name = folder_entry.get().strip()

    if not url or not folder_name:
        messagebox.showerror("Błąd", "Podaj URL i nazwę folderu")
        return

    log_box.delete("1.0", tk.END)

    threading.Thread(
        target=run_selenium,
        args=(url, folder_name),
        daemon=True
    ).start()


# ================= LOGIKA =================

def run_selenium(URL, FOLDER_NAME):
    try:
        log("➡ Start Selenium")

        # Folder docelowy
        IMG_DIR = Path.home() / "Downloads" / FOLDER_NAME
        IMG_DIR.mkdir(parents=True, exist_ok=True)

        log(f"📂 Folder docelowy: {IMG_DIR}")

        # Selenium
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-gpu")

        driver = webdriver.Chrome(options=options)
        wait = WebDriverWait(driver, 30)

        driver.get(URL)
        log("✔ Strona otwarta")

        # FILTER (jeśli istnieje)
        try:
            filter_button = wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//button[.//text()[contains(., 'Filter')]]")
                )
            )
            filter_button.click()
            log("✔ Kliknięto Filter")
            time.sleep(1)
        except Exception:
            log("ℹ Brak przycisku Filter — pomijam")

        # IMAGES
        images_element = wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//*[contains(text(),'Images')]")
            )
        )
        driver.execute_script("arguments[0].click();", images_element)
        log("✔ Kliknięto Images")
        time.sleep(2)

        # SCROLL
        log("⬇ Scrollowanie strony")
        for _ in range(12):
            driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);"
            )
            time.sleep(2)

        html = driver.page_source
        driver.quit()

        # ===== USUWANIE cdn-cgi/image/width=... =====
        REMOVE_PATTERN = r"https://cdn\.ourdream\.ai/cdn-cgi/image/width=\d+/"
        html = re.sub(REMOVE_PATTERN, "", html)

        log("✔ HTML oczyszczony")

        # ===== PARSOWANIE =====
        soup = BeautifulSoup(html, "html.parser")

        image_urls = set()

        for img in soup.find_all("img"):
            if img.get("data-src"):
                image_urls.add(urljoin(URL, img["data-src"]))

            if img.get("src") and not img["src"].startswith("data:"):
                image_urls.add(urljoin(URL, img["src"]))

            if img.get("srcset"):
                largest = img["srcset"].split(",")[-1].split()[0]
                image_urls.add(urljoin(URL, largest))

        log(f"➡ Znaleziono {len(image_urls)} obrazów")

        # ===== POBIERANIE =====
        downloaded = 0

        for i, img_url in enumerate(sorted(image_urls), 1):
            try:
                r = requests.get(img_url, timeout=20)
                if r.status_code != 200:
                    continue

                ext = img_url.split(".")[-1].split("?")[0].lower()
                if ext not in ("jpg", "jpeg", "png", "webp"):
                    ext = "jpg"

                name = f"img_{i}.{ext}"
                with open(IMG_DIR / name, "wb") as f:
                    f.write(r.content)

                downloaded += 1
                log(f"✔ Pobrano {downloaded}: {name}")

            except Exception:
                pass

        # ===== ZIP =====
        zip_path = IMG_DIR.with_suffix(".zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file in IMG_DIR.iterdir():
                zipf.write(file, arcname=file.name)

        # ===== KONIEC =====
        log("===================================")
        log(f"✅ GOTOWE")
        log(f"📸 Obrazów: {downloaded}")
        log(f"📂 Folder: {IMG_DIR}")
        log(f"🗜 ZIP: {zip_path}")

        open_folder(IMG_DIR)

        messagebox.showinfo(
            "Gotowe",
            f"Pobrano {downloaded} obrazów.\n\n"
            f"Folder:\n{IMG_DIR}\n\n"
            f"ZIP:\n{zip_path}"
        )

    except Exception as e:
        messagebox.showerror("Błąd krytyczny", str(e))


# ================= OKNO =================

root = tk.Tk()
root.title("Pobieranie strony (Selenium)")
root.geometry("700x500")

frame = ttk.Frame(root, padding=10)
frame.pack(fill="both", expand=True)

ttk.Label(frame, text="Adres strony:").pack(anchor="w")
url_entry = ttk.Entry(frame)
url_entry.pack(fill="x", pady=5)

ttk.Label(frame, text="Nazwa folderu (Downloads):").pack(anchor="w")
folder_entry = ttk.Entry(frame)
folder_entry.pack(fill="x", pady=5)

ttk.Button(frame, text="START", command=start_job).pack(pady=10)

log_box = tk.Text(frame, height=18)
log_box.pack(fill="both", expand=True)

root.mainloop()
