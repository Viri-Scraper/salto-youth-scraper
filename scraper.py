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
BROWSE_TRAINING_URL = f"{BASE_URL}/tools/european-training-calendar/browse/"
BROWSE_OTLAS_URL = f"{BASE_URL}/tools/otlas-partner-finding/projects/"
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
            print(f"   Attempt {attempt}/{retries}: HTTP {response.status_code}")
        except requests.RequestException as exc:
            print(f"   Attempt {attempt}/{retries}: {exc}")

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
        if "application deadline" in label.get_text().lower() or "deadline" in label.get_text().lower():
            parent = label.find_parent(["tr", "dl", "div", "p"])
            if parent:
                full_str = clean_text(parent.get_text())
                match = re.search(r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})", full_str)
                if match:
                    return match.group(1)

    match = re.search(
        r"deadline(?:\s*\([^)]*\))?\s*:?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        text,
        re.IGNORECASE,
    )
    if match:
        return clean_text(match.group(1))

    return None


def extract_activity_type(text):
    patterns = [
        ("Youth Exchange", r"\bYouth[- ]Exchange\b|\bYouth Mobility\b|\bKA105\b|\bKA151\b|\bKA152\b"),
        ("Training Course", r"\bTraining Course\b|\bTraining\b"),
        ("Partnership-building Activity", r"\bPartnership[- ]building Activity\b|\bPBA\b"),
        ("Study Visit", r"\bStudy Visit\b"),
        ("Seminar", r"\bSeminar\b"),
        ("Conference", r"\bConference\b"),
        ("E-learning", r"\bE-learning\b"),
    ]
    for name, pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return name
    return "Youth Exchange"  # Default fallback voor Otlas projecten


# ============================================================
# 1. TRAINING CALENDAR SCRAPING
# ============================================================

def build_training_search_url(offset=0, limit=20):
    now = datetime.now()
    params = {
        "b_offset": offset,
        "b_limit": limit,
        "b_order": "applicationDeadline",
        "b_keyword": "",
        "b_begin_date_after_day": now.day,
        "b_begin_date_after_month": now.month,
        "b_begin_date_after_year": now.year,
        "b_participating_countries": "country-20",  # Nederland
        "b_application_deadline_after_day": now.day,
        "b_application_deadline_after_month": now.month,
        "b_application_deadline_after_year": now.year,
        "b_browse": "1",
    }
    return f"{BROWSE_TRAINING_URL}?{urlencode(params)}"


def fetch_all_training_links(session):
    all_links = []
    seen = set()
    offset = 0
    limit = 20

    while True:
        url = build_training_search_url(offset=offset, limit=limit)
        print(f"\n[Training Calendar Offset {offset}] Ophalen via: {url}")

        response = fetch(session, url)
        if not response:
            break

        soup = BeautifulSoup(response.text, "html.parser")
        new_count = 0

        for link in soup.find_all("a", href=True):
            href = link.get("href", "").strip()
            full_url = urljoin(BASE_URL, href)

            if "/tools/european-training-calendar/training/" in full_url:
                if full_url not in seen:
                    title = clean_text(link.get_text(" ", strip=True))
                    if title and len(title) > 3 and title.lower() not in ["read more", "apply now", "details"]:
                        seen.add(full_url)
                        all_links.append({"title": title, "url": full_url})
                        new_count += 1

        print(f"  -> {new_count} nieuwe trainingen gevonden.")
        if new_count == 0:
            break

        offset += limit
        time.sleep(0.5)

    return all_links


# ============================================================
# 2. OTLAS PARTNER FINDING (YOUTH EXCHANGES)
# ============================================================

def build_otlas_search_url(page=1):
    params = {
        "q": "Youth Exchange",
        "action": "ka1",
        "country": "NL",
        "page": page
    }
    return f"{BROWSE_OTLAS_URL}?{urlencode(params)}"


def fetch_otlas_exchanges(session):
    print("\n" + "=" * 60)
    print("OTLAS SCRAPING (YOUTH EXCHANGES)")
    print("=" * 60)

    otlas_results = []
    seen = set()
    page = 1

    while page <= 5:  # Maximaal 5 pagina's Otlas doorzoeken
        url = build_otlas_search_url(page=page)
        print(f"\n[Otlas Pagina {page}] Ophalen via: {url}")

        response = fetch(session, url)
        if not response:
            break

        soup = BeautifulSoup(response.text, "html.parser")
        project_cards = soup.find_all(["div", "article"], class_=re.compile(r"project|item|card", re.I))

        # Indien geen specifieke cards gevonden, zoek op alle links in de Otlas projecten map
        links = soup.find_all("a", href=re.compile(r"/tools/otlas-partner-finding/project/\d+"))
        
        if not links:
            print("  -> Geen Otlas projecten meer gevonden op deze pagina.")
            break

        new_count = 0
        for link in links:
            href = link.get("href", "").strip()
            full_url = urljoin(BASE_URL, href)

            if full_url not in seen:
                seen.add(full_url)
                title = clean_text(link.get_text(" ", strip=True))
                if not title or title.lower() in ["view", "more", "details"]:
                    title = "Youth Exchange Project"

                # Detailpagina scrapen voor type en deadline
                detail_resp = fetch(session, full_url)
                deadline_str = None
                act_type = "Youth Exchange"

                if detail_resp:
                    dt_soup = BeautifulSoup(detail_resp.text, "html.parser")
                    dt_text = clean_text(dt_soup.get_text(" ", strip=True))
                    deadline_str = extract_deadline(dt_soup, dt_text)
                    act_type = extract_activity_type(dt_text)

                deadline_date = parse_date(deadline_str)

                otlas_results.append({
                    "title": title,
                    "url": full_url,
                    "activity_type": act_type,
                    "application_deadline": deadline_str,
                    "application_deadline_iso": (
                        deadline_date.strftime("%Y-%m-%d") if deadline_date else None
                    ),
                    "netherlands_eligible": True,
                    "scraped_at": datetime.now(timezone.utc).isoformat()
                })
                new_count += 1
                time.sleep(0.3)

        print(f"  -> {new_count} Otlas projecten toegevoegd.")
        if new_count == 0:
            break

        page += 1

    return otlas_results


# ============================================================
# MAIN SCRAPE LOGIC
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
    print("SALTO-YOUTH & OTLAS COMBINED SCRAPER")
    print("=" * 60)

    session = create_session()

    # 1. Training Calendar
    links = fetch_all_training_links(session)
    results = []

    print(f"\n==========================================================")
    print(f"Verwerken van {len(links)} Training Calendar links...")
    print(f"==========================================================")

    for index, item in enumerate(links, start=1):
        print(f"[{index}/{len(links)}] {item['title']}")
        try:
            data = scrape_detail(session, item)
            if data:
                data["scraped_at"] = datetime.now(timezone.utc).isoformat()
                results.append(data)
        except Exception as exc:
            print(f"  -> Error: {exc}")
        time.sleep(0.3)

    # 2. Otlas Youth Exchanges
    otlas_items = fetch_otlas_exchanges(session)
    results.extend(otlas_items)

    return results


def save_results(results):
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Ontdubbelen op basis van URL
    unique_results = {}
    for item in results:
        unique_results[item["url"]] = item

    final_list = list(unique_results.values())
    final_list.sort(
        key=lambda item: (item["application_deadline_iso"] or "9999-12-31")
    )

    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(final_list, file, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print(f"Voltooid! Totaal {len(final_list)} items opgeslagen in {OUTPUT_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    results = scrape()
    save_results(results)
