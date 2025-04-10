import time
import csv
import os
import traceback
import smtplib
from email.mime.text import MIMEText
import os

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException

# Ustawienia konta i SMTP
FACEBOOK_EMAIL = "shopxnorthhub@gmail.com"
FACEBOOK_PASSWORD = "FixPython899489"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "shopxnorthhub@gmail.com"
SMTP_PASS = "FixPython8994"
REPORT_RECIPIENT = "office@liderteam.pl"

def send_email_report(report_text):
    """Wysyła e-mail z raportem na REPORT_RECIPIENT."""
    msg = MIMEText(report_text, _charset="utf-8")
    msg["Subject"] = "Raport z publikacji postów na Facebooku"
    msg["From"] = SMTP_USER
    msg["To"] = REPORT_RECIPIENT
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(msg["From"], [msg["To"]], msg.as_string())
        print("Raport wysłany:", REPORT_RECIPIENT)
    except Exception as e:
        print("Nie udało się wysłać raportu e-mail:", e)

def find_text_area(driver):
    """
    Szuka okna dialogowego tworzenia posta, a wewnątrz niego szuka pola tekstowego,
    wykluczając pola komentarzy (poprzez sprawdzenie placeholdera).
    """
    try:
        dialog = WebDriverWait(driver, 15).until(
            EC.visibility_of_element_located((By.XPATH, "//div[@role='dialog']"))
        )
        text_area = dialog.find_element(
            By.XPATH, ".//div[@role='textbox' and contains(@class, 'notranslate') and not(contains(@aria-placeholder, 'Skomentuj'))]"
        )
        return text_area
    except Exception as e:
        print("Błąd przy wyszukiwaniu pola tekstowego:", e)
        return None

def publish_post_to_facebook(post_text, file_path=None, groups_csv_path="groups.csv"):
    """
    Główna funkcja publikująca post na Facebooku.
    - Inicjalizuje Selenium (przy użyciu środowiska skonfigurowanego na Heroku).
    - Loguje się na Facebooka.
    - Iteruje po grupach (wczytanych z CSV) i publikuje post z przekazaną treścią
      oraz (opcjonalnie) załącza plik (obrazek lub wideo, np. MP4).
    """
    report_lines = []
    success_count = 0
    total_groups = 0

    # Inicjalizujemy Chrome przy użyciu opcji skonfigurowanych do uruchomienia na Heroku
    chrome_options = webdriver.ChromeOptions()
    chrome_options.binary_location = os.environ.get("GOOGLE_CHROME_BIN")
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(
        executable_path=os.environ.get("CHROMEDRIVER_PATH"),
        options=chrome_options
    )

    try:
        # Logowanie do Facebooka
        driver.get("https://www.facebook.com/login")
        email_field = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.ID, "email"))
        )
        email_field.send_keys(FACEBOOK_EMAIL)
        password_field = driver.find_element(By.ID, "pass")
        password_field.send_keys(FACEBOOK_PASSWORD)
        password_field.send_keys(Keys.ENTER)
        time.sleep(10)

        # Wczytanie listy grup z pliku CSV
        groups = []
        if not os.path.exists(groups_csv_path):
            report_lines.append("Brak pliku CSV z grupami!")
            print("Błąd: brak pliku groups.csv")
            return

        with open(groups_csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if row:
                    groups.append(row[0].strip())
        total_groups = len(groups)
        report_lines.append(f"Łącznie grup do publikacji: {total_groups}")

        # Iteracja po grupach
        for group_url in groups:
            print("Przetwarzanie grupy:", group_url)
            report_lines.append(f"Grupa: {group_url}")
            driver.get(group_url)
            time.sleep(10)

            try:
                # A. Kliknięcie "Napisz coś..."
                create_post_button = WebDriverWait(driver, 15).until(
                    EC.element_to_be_clickable((
                        By.XPATH, "//span[contains(text(), 'Napisz coś')]/ancestor::div[@role='button']"
                    ))
                )
                create_post_button.click()
                time.sleep(3)

                # B. Wpisanie treści posta
                text_area = find_text_area(driver)
                if text_area is None:
                    print("Brak pola tekstowego.")
                    report_lines.append("  [ERROR] Brak pola tekstowego.")
                    continue
                text_area.click()
                time.sleep(1)
                text_area.send_keys(post_text)
                time.sleep(2)

                # C. Kliknięcie przycisku "Zdjęcie/film"
                try:
                    photo_button = driver.find_element(
                        By.XPATH, "//div[@role='button'][contains(@aria-label, 'Zdjęcie/film')]"
                    )
                    photo_button.click()
                    time.sleep(3)
                except Exception as e:
                    print("Brak przycisku 'Zdjęcie/film':", e)

                # D. Opcjonalnie: Kliknięcie przycisku "Dodaj zdjęcia/filmy"
                variants = [
                    "//div[@role='button' and contains(text(), 'Dodaj zdjęcia/filmy')]",
                    "//div[@role='button' and contains(text(), 'Dodaj zdjęcia lub filmy')]",
                    "//div[@role='button' and contains(text(), 'Dodaj zdjęcia i filmy')]"
                ]
                for xp in variants:
                    try:
                        el = driver.find_element(By.XPATH, xp)
                        el.click()
                        time.sleep(2)
                        break
                    except:
                        pass

                # E. Załączenie pliku, jeśli został podany i istnieje
                if file_path and os.path.exists(file_path):
                    try:
                        file_inputs = WebDriverWait(driver, 15).until(
                            EC.presence_of_all_elements_located((By.XPATH, "//input[@type='file']"))
                        )
                        if not file_inputs:
                            print("Nie znaleziono input file.")
                            report_lines.append("  [WARN] Brak input[type='file'].")
                        else:
                            file_loaded = False
                            for idx, inp in enumerate(file_inputs):
                                try:
                                    inp.send_keys(file_path)
                                    time.sleep(3)
                                    try:
                                        WebDriverWait(driver, 3).until(
                                            EC.presence_of_element_located((By.XPATH, "//img[contains(@src, 'blob:')]"))
                                        )
                                        file_loaded = True
                                        break
                                    except TimeoutException:
                                        pass
                                except Exception as ex:
                                    print("Błąd przy wysyłaniu pliku:", ex)
                            if not file_loaded:
                                report_lines.append("  [WARN] Plik nie został wgrany.")
                    except Exception as e:
                        print("Błąd: brak input file.")
                        report_lines.append("  [ERROR] Błąd input file.")
                else:
                    if file_path:
                        print("Plik nie istnieje:", file_path)

                # F. Kliknięcie przycisku "Opublikuj"
                try:
                    publish_button = driver.find_element(
                        By.XPATH, "//div[@role='dialog']//div[contains(@aria-label, 'Opublikuj')]"
                    )
                    publish_button.click()
                    time.sleep(25)
                except Exception as e:
                    print("Błąd przy klikaniu 'Opublikuj':", e)
                    report_lines.append("  [ERROR] Nie udało się kliknąć 'Opublikuj'.")

                print("Sukces:", group_url)
                report_lines.append("  [OK] Post opublikowany.")
                success_count += 1

            except Exception as e:
                print("Błąd w grupie", group_url, ":", e)
                traceback.print_exc()
                report_lines.append(f"  [ERROR] Wyjątek: {group_url}: {e}")

            time.sleep(20)

    finally:
        driver.quit()

    # Podsumowanie raportu
    report = "Raport z publikacji:\n" + "\n".join(report_lines)
    report += f"\n\nRazem grup: {total_groups}\nSukces w: {success_count} grupach."
    print(report)

    # Opcjonalnie: wysłanie raportu e-mailem
    try:
        send_email_report(report)
    except Exception as e:
        print("Błąd przy wysyłaniu raportu e-mail:", e)

    return report
