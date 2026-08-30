import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup

# ============================================================
# CONFIGURATION
# ============================================================

BASE_URL = "https://www.salto-youth.net"
BROWSE_URL = f"{BASE_URL}/tools/european-training-calendar/browse/"
OUTPUT_FILE = Path("data/salto_courses.json")


# ============================================================
# HTTP SESSION
# ============================================================

def create_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return session


# ============================================================
# HELPERS
# ============================================================

def clean_text(value):
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def fetch(session, url, retries=3):
    for attempt in range(1, retries + 1):
        try:
            response = session.get(url, timeout=30)
            if response.status_code == 200:
                return response
            print(f"  Attempt {attempt}/{retries}: HTTP {response.status_code}")
        except requests.RequestException as exc:
            print(f"  Attempt {attempt}/{retries}: {exc}")

        if attempt < retries:
            time.sleep(2 * attempt)
    return None


def parse_date(value):
    if not value:
        return None
    value = clean_text(value)
    value = re.sub(r"\([^)]*\)", "", value).strip()

    formats = ["%d %B %Y", "%d %b %Y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"]
    for date_format in formats:
        try:
            return datetime.strptime(value, date_format)
        except ValueError:
            continue
    return None


def extract_deadline(soup, text):
    for label in soup.find_all(["dt", "th", "strong", "b"]):
        if "application deadline" in label.get_text().lower():
            parent = label.find_parent(["tr", "dl", "div"])
            if parent:
                full_str = clean_text(parent.get_text())
                match = re.search(r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})", full_str)
                if match:
                    return match.group(1)

    match = re.search(
        r"Application\s+deadline(?:\s*\([^)]*\))?\s*:?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        text,
        re.IGNORECASE,
    )
    if match:
        return clean_text(match.group(1))

    return None


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
# PAGINATED FETCHING (MET B_OFFSET)
# ============================================================

def build_search_url(offset=0, limit=20):
    """Bouwt de exacte SALTO URL op met de juiste parameters voor NL en datum van vandaag."""
    now = datetime.now()

    params = {
        "b_offset": offset,
        "b_limit": limit,
        "b_order": "applicationDeadline",
        "b_keyword": "",
        "b_begin_date_after_day": now.day,
        "b_begin_date_after_month": now.month,
        "b_begin_date_after_year": now.year,
        "b_begin_date_before_day": "",
        "b_begin_date_before_month": "",
        "b_begin_date_before_year": "",
        "b_end_date_after_day": "",
        "b_end_date_after_month": "",
        "b_end_date_after_year": "",
        "b_end_date_before_day": "",
        "b_end_date_before_month": "",
        "b_end_date_before_year": "",
        "b_activity_type": "",
        "b_country": "",
        "b_participating_countries": "country-20",  # Nederland
        "b_application_deadline_after_day": now.day,
        "b_application_deadline_after_month": now.month,
        "b_application_deadline_after_year": now.year,
        "b_application_deadline_before_day": "",
        "b_application_deadline_before_month": "",
        "b_application_deadline_before_year": "",
        "b_browse": "1",
    }

    return f"{BROWSE_URL}?{urlencode(params)}"


def fetch_all_training_links(session):
    all_links = []
    seen = set()
    offset = 0
    limit = 20  # Haal 20 items per pagina op

    while True:
        url = build_search_url(offset=offset, limit=limit)
        print(f"\n[Offset {offset}] Ophalen via: {url}")

        response = fetch(session, url)
        if not response:
            print("  -> Kon pagina niet laden. Stoppen.")
            break

        soup = BeautifulSoup(response.text, "html.parser")
        new_count = 0

        for link in soup.find_all("a", href=True):
            href = link.get("href", "").strip()
            full_url = urljoin(BASE_URL, href)

            if "/tools/european-training-calendar/training/" in full_url:
                if full_url not in seen:
                    title = clean_text(link.get_text(" ", strip=True))
                    if (
                        title
                        and len(title) > 3
                        and title.lower() not in ["read more", "apply now", "details"]
                    ):
                        seen.add(full_url)
                        all_links.append({"title": title, "url": full_url})
                        new_count += 1

        print(f"  -> {new_count} nieuwe trainingen gevonden op deze pagina.")

        # Als er geen nieuwe trainingen meer op de pagina staan, zijn we klaar
        if new_count == 0:
            print("Geen nieuwe resultaten meer gevonden. Bladeren voltooid.")
            break

        offset += limit
        time.sleep(0.5)

    return all_links


# ============================================================
# DETAIL SCRAPING & MAIN LOGIC
# ============================================================

def scrape_detail(session, item):
    response = fetch(session, item["url"])
    if response is None:
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    text = clean_text(soup.get_text(" ", strip=True))

    deadline = extract_deadline(soup, text)
    deadline_date = parse_date(deadline)

    return {
        "title": item["title"],
        "url": item["url"],
        "activity_type": extract_activity_type(text),
        "application_deadline": deadline,
        "application_deadline_iso": (
            deadline_date.strftime("%Y-%m-%d") if deadline_date else None
        ),
        "netherlands_eligible": True,
    }


def scrape():
    print("=" * 60)
    print("SALTO-YOUTH SCRAPER (EXACTE BROWSE STRUCTUUR)")
    print("=" * 60)

    session = create_session()
    links = fetch_all_training_links(session)

    print(f"\n==========================================================")
    print(f"Totaal unieke trainingen verzameld: {len(links)}")
    print(f"==========================================================")

    results = []
    for index, item in enumerate(links, start=1):
        print(f"[{index}/{len(links)}] {item['title']}")
        try:
            data = scrape_detail(session, item)
            if data:
                data["scraped_at"] = datetime.now(timezone.utc).isoformat()
                results.append(data)
                print("  -> Toegevoegd")
        except Exception as exc:
            print(f"  -> Error: {exc}")

        time.sleep(0.3)

    return results


def save_results(results):
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    results.sort(
        key=lambda item: (item["application_deadline_iso"] or "9999-12-31")
    )

    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(results, file, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print(f"Voltooid! {len(results)} trainingen opgeslagen in {OUTPUT_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    results = scrape()
    save_results(results)
