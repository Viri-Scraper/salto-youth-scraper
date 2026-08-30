import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURATION
# ============================================================

BASE_URL = "https://www.salto-youth.net"
# Gefilterd op de SALTO-server op deelnemers uit Nederland (ID 177)
CALENDAR_URL = f"{BASE_URL}/tools/european-training-calendar/browse/?b_participating_countries%5B%5D=177"
OUTPUT_FILE = Path("data/salto_courses.json")


# ============================================================
# HTTP SESSION
# ============================================================

def create_session():
    session = requests.Session()

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"{BASE_URL}/",
    })

    return session


# ============================================================
# HELPERS
# ============================================================

def clean_text(value):
    """Maak tekst schoon en verwijder dubbele whitespace."""
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def fetch(session, url, retries=3):
    """Haal een URL op met eenvoudige retry-logica."""
    for attempt in range(1, retries + 1):
        try:
            response = session.get(
                url,
                timeout=30,
                allow_redirects=True,
            )

            print(
                f"GET {response.url} "
                f"[HTTP {response.status_code}]"
            )

            if response.status_code == 200:
                return response

            print(
                f"Attempt {attempt}/{retries}: "
                f"HTTP {response.status_code}"
            )

        except requests.RequestException as exc:
            print(
                f"Attempt {attempt}/{retries}: "
                f"{type(exc).__name__}: {exc}"
            )

        if attempt < retries:
            time.sleep(2 * attempt)

    return None


# ============================================================
# DATE PARSING
# ============================================================

def parse_date(value):
    """Probeer een datumstring om te zetten naar datetime."""
    if not value:
        return None

    value = clean_text(value)
    # Verwijder eventuele haakjes/tijdsaanduidingen (bijv. 23:59 CET)
    value = re.sub(r"\([^)]*\)", "", value).strip()

    formats = [
        "%d %B %Y",
        "%d %b %Y",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y-%m-%d",
    ]

    for date_format in formats:
        try:
            return datetime.strptime(value, date_format)
        except ValueError:
            continue

    return None


def extract_deadline(soup, text):
    """Zoek de application deadline in de pagina via selectors en regex fallback."""
    # Method 1: HTML-structuur van SALTO
    for label in soup.find_all(["dt", "th", "strong", "b"]):
        if "application deadline" in label.get_text().lower():
            parent = label.find_parent(["tr", "dl", "div"])
            if parent:
                full_str = clean_text(parent.get_text())
                match = re.search(r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})", full_str)
                if match:
                    return match.group(1)

    # Method 2: Regex fallback
    patterns = [
        r"Application\s+deadline(?:\s*\([^)]*\))?\s*:?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        r"Deadline\s*:\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return clean_text(match.group(1))

    return None


def extract_dates(text):
    """Zoek activiteitdatums."""
    pattern = r"\b(\d{1,2}(?:-\d{1,2})?\s+[A-Za-z]+\s+\d{4})\b"
    matches = re.findall(pattern, text, re.IGNORECASE)
    return matches[:5]


# ============================================================
# ACTIVITY TYPE
# ============================================================

def extract_activity_type(text):
    patterns = [
        ("Training Course", r"\bTraining Course\b"),
        ("Partnership-building Activity", r"\bPartnership[- ]building Activity\b"),
        ("Study Visit", r"\bStudy Visit\b"),
        ("Youth Exchange", r"\bYouth Exchange\b"),
        ("Seminar", r"\bSeminar\b"),
        ("Conference", r"\bConference\b"),
        ("E-learning", r"\bE-learning\b"),
    ]

    for name, pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return name

    return "Other"


# ============================================================
# TRAINING LINKS & PAGINATION
# ============================================================

def extract_training_links(soup, seen):
    results = []

    for link in soup.find_all("a", href=True):
        href = link.get("href", "").strip()
        if not href:
            continue

        url = urljoin(BASE_URL, href)

        if "/tools/european-training-calendar/training/" not in url:
            continue

        if url in seen:
            continue

        title = clean_text(link.get_text(" ", strip=True))
        if not title or len(title) < 3:
            continue

        seen.add(url)
        results.append({
            "title": title,
            "url": url,
        })

    return results


def fetch_all_training_links(session):
    """Loop door ALLE pagina's van de SALTO kalender voor Nederland."""
    all_links = []
    seen = set()
    page = 1

    while True:
        separator = "&" if "?" in CALENDAR_URL else "?"
        page_url = f"{CALENDAR_URL}{separator}page={page}"

        print(f"\nPagina {page} ophalen: {page_url}")

        response = fetch(session, page_url)
        if response is None:
            print(f"Kon pagina {page} niet ophalen. Stoppen.")
            break

        soup = BeautifulSoup(response.text, "html.parser")
        new_links = extract_training_links(soup, seen)

        if not new_links:
            print(f"Geen nieuwe trainingen meer gevonden op pagina {page}. Paginering afgerond.")
            break

        print(f"Pagina {page}: {len(new_links)} nieuwe trainingen gevonden.")
        all_links.extend(new_links)

        page += 1
        time.sleep(0.5)

    return all_links


# ============================================================
# DETAIL PAGE
# ============================================================

def scrape_detail(session, item):
    response = fetch(session, item["url"])
    if response is None:
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    text = clean_text(soup.get_text(" ", strip=True))

    deadline = extract_deadline(soup, text)
    deadline_date = parse_date(deadline)
    dates = extract_dates(text)

    return {
        "title": item["title"],
        "url": item["url"],
        "activity_type": extract_activity_type(text),
        "dates_found": dates,
        "application_deadline": deadline,
        "application_deadline_iso": (
            deadline_date.strftime("%Y-%m-%d")
            if deadline_date
            else None
        ),
        "netherlands_eligible": True,  # Zeker gesteld door SALTO zoekfilter
    }


# ============================================================
# MAIN SCRAPER
# ============================================================

def scrape():
    print("=" * 60)
    print("SALTO-YOUTH SCRAPER (ALLE RESULTATEN VOOR NL)")
    print("=" * 60)

    session = create_session()

    print("\nAlle overzichtspagina's doorlopen voor Nederland...")
    links = fetch_all_training_links(session)

    print(f"\nTotaal unieke trainingen gevonden: {len(links)}")

    if not links:
        raise RuntimeError("Geen training links gevonden.")

    results = []

    print("\nDetails ophalen en opslaan...")

    for index, item in enumerate(links, start=1):
        print(f"\n[{index}/{len(links)}] {item['title']}")

        try:
            data = scrape_detail(session, item)

            if data is None:
                print("  -> ophalen mislukt")
                continue

            data["scraped_at"] = datetime.now(timezone.utc).isoformat()
            
            # Voeg ALLES direct toe zonder te filteren
            results.append(data)
            print("  -> TOEGEVOEGD")

        except Exception as exc:
            print(f"  -> ERROR: {type(exc).__name__}: {exc}")

        time.sleep(0.4)

    return results


# ============================================================
# SAVE JSON
# ============================================================

def save_results(results):
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Sorteer op deadline als die bekend is, anders achteraan
    results.sort(
        key=lambda item: (
            item["application_deadline_iso"] or "9999-12-31"
        )
    )

    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(results, file, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print(f"{len(results)} trainingen opgeslagen in JSON.")
    print(f"Bestand: {OUTPUT_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    results = scrape()
    save_results(results)
