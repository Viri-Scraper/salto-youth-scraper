import os
import json
import re
from datetime import datetime
import requests
from bs4 import BeautifulSoup

# Basishurls voor SALTO-Youth Training Calendar
BASE_URL = "https://www.salto-youth.net"
CALENDAR_URL = f"{BASE_URL}/tools/european-training-calendar/browse/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
}

def parse_date(date_str):
    """Probeert een tekstdatum (bijv. '15 October 2026') om te zetten naar een datetime object."""
    if not date_str:
        return None
    
    # Verwijder extra spaties en bekende woorden
    clean_str = date_str.replace("Application deadline:", "").strip()
    
    # Verschillende datumnotaties die SALTO gebruikt
    date_formats = ["%d %B %Y", "%d-%m-%Y", "%Y-%m-%d"]
    
    for fmt in date_formats:
        try:
            return datetime.strptime(clean_str, fmt)
        except ValueError:
            continue
    return None

def scrape_salto_calendar():
    print("Starten met scrapen van SALTO-Youth (Erasmus+ uitwisselingen en trainingen)...")
    
    # Zoekparameters specifiek voor aanbod open voor Nederlanders
    params = {
        "target_group_country": "Netherlands",
        "status": "open"
    }
    
    try:
        response = requests.get(CALENDAR_URL, headers=HEADERS, params=params, timeout=20)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Fout bij het ophalen van SALTO-Youth: {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    valid_courses = []
    today = datetime.now()

    # Zoek naar cursus-elementen op de pagina
    event_items = soup.select(".training-listing-item, .eventItem, article, table.calendarList tr")
    if not event_items:
        event_items = soup.find_all("a", href=re.compile(r"/tools/european-training-calendar/training/"))

    for item in event_items:
        try:
            if item.name == "a":
                link_elem = item
                parent = item.parent
            else:
                link_elem = item.find("a", href=re.compile(r"/tools/european-training-calendar/training/"))
                parent = item

            if not link_elem or not link_elem.get("href"):
                continue

            course_url = BASE_URL + link_elem["href"] if link_elem["href"].startswith("/") else link_elem["href"]
            course_id = re.search(r"/training/(\d+)", course_url)
            course_id_str = course_id.group(1) if course_id else course_url

            title = link_elem.get_text(strip=True)
            text_content = parent.get_text(" ", strip=True)

            # Bepaal het type Erasmus+ activiteit (Youth Exchange, Training Course, etc.)
            activity_type = "Erasmus+ Project"
            if "Youth Exchange" in text_content or "Jongerenuitwisseling" in text_content:
                activity_type = "Youth Exchange"
            elif "Training Course" in text_content:
                activity_type = "Training Course"
            elif "Seminar" in text_content:
                activity_type = "Seminar"

            # Haal de aanmelddeadline op
            deadline_match = re.search(r"Application deadline:\s*([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})", text_content, re.IGNORECASE)
            deadline_raw = deadline_match.group(1) if deadline_match else None
            
            # Converteren naar datum-object voor de deadline-check
            deadline_dt = parse_date(deadline_raw) if deadline_raw else None

            # -----------------------------------------------------------------
            # AUTOMATISCHE VERWIJDERING/FILTERING
            # Als de deadline bekend is en AL IS VERSTREKEN, slaan we hem over!
            # -----------------------------------------------------------------
            if deadline_dt and deadline_dt < today:
                print(f"Overslaan (deadline verstreken): {title} ({deadline_raw})")
                continue

            course_data = {
                "id": course_id_str,
                "title": title,
                "type": activity_type,
                "deadline": deadline_raw if deadline_raw else "Zie SALTO pagina",
                "deadline_iso": deadline_dt.strftime("%Y-%m-%d") if deadline_dt else None,
                "url": course_url,
                "target_country": "Netherlands",
                "scraped_at": today.strftime("%Y-%m-%d %H:%M:%S")
            }
            
            valid_courses.append(course_data)

        except Exception as err:
            print(f"Fout bij verwerken van een item: {err}")
            continue

    print(f"\nTotaal {len(valid_courses)} actuele Erasmus+ projecten gevonden voor Nederland.")
    return valid_courses

def save_to_json(courses, filename="salto_courses.json"):
    """Slaat het opgeschoonde JSON-bestand op in de huidige map op de server."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(script_dir, filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(courses, f, ensure_ascii=False, indent=2)
    print(f"Actueel overzicht opgeslagen in: {filepath}")

if __name__ == "__main__":
    actueel_aanbod = scrape_salto_calendar()
    save_to_json(actueel_aanbod)