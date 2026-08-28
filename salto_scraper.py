import os
import json
import re
import time
from datetime import datetime
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.salto-youth.net"
CALENDAR_URL = f"{BASE_URL}/tools/european-training-calendar/browse/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9,nl;q=0.8"
}

def parse_deadline(date_str):
    if not date_str:
        return None
    clean_str = re.sub(r'(?i)application deadline:?', '', date_str).strip()
    formats = ["%d %B %Y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"]
    for fmt in formats:
        try:
            return datetime.strptime(clean_str, fmt)
        except ValueError:
            continue
    return None

def fetch_details_from_page(course_url):
    """Haalt veilig details op zonder het script te laten crashen bij een netwerkfout."""
    details = {"deadline": None, "extra_text": ""}
    try:
        # Pauzeer heel even om rate-limiting te voorkomen
        time.sleep(0.5)
        res = requests.get(course_url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            text = soup.get_text(" ", strip=True)
            details["extra_text"] = text

            match = re.search(r"Application deadline:\s*([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})", text, re.IGNORECASE)
            if match:
                details["deadline"] = match.group(1).strip()
    except Exception as e:
        print(f"Waarschuwing: Kon details niet ophalen voor {course_url} ({e})")
    return details

def categorize_activity(title, content_text):
    combined = f"{title} {content_text}".lower()

    if "youth exchange" in combined or "jongerenuitwisseling" in combined:
        return "Jongerenuitwisseling (Youth Exchange)"
    elif "pba" in combined or "partnership building" in combined:
        return "Partnership Building Activity (PBA)"
    elif "training course" in combined or "training" in combined:
        return "Training Course"
    elif "seminar" in combined or "conference" in combined:
        return "Seminar / Conference"
    elif "study visit" in combined or "contact making" in combined:
        return "Study Visit / Contact Making"
    elif "youth worker" in combined or "mobility" in combined:
        return "Youth Worker Mobility"
    else:
        return "Erasmus+ Project"

def scrape_salto():
    print("Starten met ophalen en categoriseren van SALTO-Youth projecten...")
    
    params = {
        "target_group_country": "Netherlands",
        "status": "open"
    }

    try:
        response = requests.get(CALENDAR_URL, headers=HEADERS, params=params, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"Fout bij ophalen van SALTO-overzicht: {e}")
        # Retoneer een lege lijst i.p.v. het script te laten crashen
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    valid_courses = []
    today = datetime.now()

    links = soup.find_all("a", href=re.compile(r"/tools/european-training-calendar/training/"))
    seen_urls = set()

    for link in links:
        try:
            course_url = BASE_URL + link["href"] if link["href"].startswith("/") else link["href"]
            
            if course_url in seen_urls:
                continue
            seen_urls.add(course_url)

            title = link.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            parent_text = link.parent.parent.get_text(" ", strip=True) if link.parent else ""
            
            page_details = fetch_details_from_page(course_url)
            
            match = re.search(r"([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})", parent_text)
            deadline_str = page_details["deadline"] or (match.group(1) if match else None)
            deadline_dt = parse_deadline(deadline_str) if deadline_str else None

            # Controle op verstreken deadline
            if deadline_dt and deadline_dt < today:
                print(f"Overslaan (Deadline verstreken): {title} ({deadline_str})")
                continue

            category = categorize_activity(title, page_details["extra_text"])

            valid_courses.append({
                "id": course_url.split("/")[-2] if "/" in course_url else course_url,
                "title": title,
                "category": category,
                "deadline": deadline_str if deadline_str else "Zolang aanmelding open staat",
                "deadline_iso": deadline_dt.strftime("%Y-%m-%d") if deadline_dt else None,
                "url": course_url,
                "target_country": "Netherlands",
                "scraped_at": today.strftime("%Y-%m-%d %H:%M:%S")
            })
        except Exception as err:
            print(f"Foutje bij verwerken item, sla over: {err}")
            continue

    print(f"\nTotaal {len(valid_courses)} actuele projecten gecategoriseerd en opgeslagen.")
    return valid_courses

def save_json(data, filename="salto_courses.json"):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Bestand opgeslagen: {filename}")

if __name__ == "__main__":
    courses = scrape_salto()
    save_json(courses)
