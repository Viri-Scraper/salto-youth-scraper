import json
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, urljoin
import requests
from bs4 import BeautifulSoup

# Base URL's
BASE_URL = "https://www.salto-youth.net"
BROWSE_TRAINING_URL = f"{BASE_URL}/tools/european-training-calendar/browse/"
BROWSE_OTLAS_URL = f"{BASE_URL}/tools/otlas-partner-finding/projects/"

# General Headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


# ============================================================
# HELPER FUNCTIES
# ============================================================

def fetch(session, url, retries=3):
    """Haalt een URL op met automatische retry en foutafhandeling."""
    for attempt in range(retries):
        try:
            response = session.get(url, headers=HEADERS, timeout=15)
            if response.status_code == 200:
                return response
        except requests.RequestException as e:
            print(f"  [Fout] Poging {attempt + 1} mislukt voor {url}: {e}")
            time.sleep(1)
    return None


def clean_text(text):
    """Schoont overtollige witruimtes en 'nbsp' karakters op."""
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_date(date_str):
    """Probeert diverse datumformaten om te zetten naar een datetime object."""
    if not date_str:
        return None

    date_str = date_str.strip().lower()
    
    # Vervang Nederlandse maandnamen door Engelse voor eenduidige parsing
    nl_to_en = {
        "januari": "january", "februari": "february", "maart": "march",
        "april": "april", "mei": "may", "juni": "june",
        "juli": "july", "augustus": "august", "september": "september",
        "oktober": "october", "november": "november", "december": "december"
    }
    for nl, en in nl_to_en.items():
        date_str = date_str.replace(nl, en)

    formats = [
        "%d %B %Y",       # 12 October 2026
        "%d %b %Y",        # 12 Oct 2026
        "%Y-%m-%d",        # 2026-10-12
        "%d/%m/%Y",        # 12/10/2026
        "%d.%m.%Y",        # 12.10.2026
        "%d-%m-%Y",        # 12-10-2026
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            pass
    return None


def extract_deadline(soup, text):
    """
    Zoekt intensief naar verstopte deadlines op detailpagina's (Otlas & Training).
    Geavanceerde zoeklogica met bredere trefwoorden en regex.
    """
    # 1. Specifieke Otlas & SALTO HTML velden en labels
    patterns = [
        r"(?:application deadline|deadline|partners needed by|partners found by|apply before|expiry date|valid until)\s*[:\-\=]?\s*(\d{1,2}[\/\.\-\s]+(?:[A-Za-z]+|\d{1,2})[\/\.\-\s]+\d{2,4})",
        r"(?:deadline|apply by)\s*[:\-\=]?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
    ]

    # Zoek via bekende HTML structuren (bijv. <th>/<td> paren, dt/dd lijsten of meta tags)
    for element in soup.find_all(['tr', 'div', 'p', 'li', 'td', 'dt']):
        el_text = clean_text(element.get_text(" ", strip=True))
        for pattern in patterns:
            match = re.search(pattern, el_text, re.IGNORECASE)
            if match:
                raw_match = match.group(1).strip()
                # Valideer of het een echte datum is
                if parse_date(raw_match):
                    return raw_match

    # 2. Brede regex-fallback op de gehele paginatekst
    months_regex = r"(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec|januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december)"
    
    # Zoekt naar patronen als "Deadline: 15 October 2026" of "until 20/11/2026"
    fallback_matches = re.findall(
        rf"(?:deadline|apply|before|until|expires|partners?)\b.*?(\d{{1,2}}\s+{months_regex}\s+\d{{4}}|\d{{1,2}}[\/\.\-]\d{{1,2}}[\/\.\-]\d{{4}})",
        text,
        re.IGNORECASE
    )

    for candidate in fallback_matches:
        if parse_date(candidate):
            return candidate

    return None


def extract_activity_type(soup, full_text):
    """Bepaalt het type activiteit op basis van HTML-elementen of trefwoorden."""
    extracted_raw = ""
    type_selectors = [".project-type", ".activity-type", ".badge", ".tags", "span[class*='type']"]
    for selector in type_selectors:
        for el in soup.select(selector):
            extracted_raw += " " + el.get_text(" ", strip=True)

    type_label = soup.find(text=re.compile(r"Type of event|Event type|Activity type|Type of activity|Project type", re.IGNORECASE))
    if type_label and type_label.parent:
        extracted_raw += " " + type_label.parent.get_text(" ", strip=True)
    
    search_text = (extracted_raw + " " + full_text).lower()

    if "youth exchange" in search_text or "jongerenuitwisseling" in search_text:
        return "Jongerenuitwisseling"
    elif "e-learning" in search_text or "online course" in search_text or "webinar" in search_text or "mooc" in search_text:
        return "E-learning"
    elif "study visit" in search_text or "studiebezoek" in search_text:
        return "Studiebezoek"
    elif "partnership" in search_text or "pba" in search_text or "partnerschap" in search_text:
        return "Partnerschapsbijeenkomst"
    elif "seminar" in search_text:
        return "Seminar"
    elif "conference" in search_text or "conferentie" in search_text:
        return "Conferentie"
    elif "networking" in search_text or "network" in search_text or "netwerk" in search_text:
        return "Netwerkevenement"
    elif "training" in search_text or "course" in search_text:
        return "Training"
    elif "esc" in search_text or "solidarity corps" in search_text or "volunteering" in search_text or "vrijwilligerswerk" in search_text:
        return "European Solidarity Corps"
    
    return "Overig"


# ============================================================
# 1. TRAINING CALENDAR SCRAPER
# ============================================================

def build_training_search_url(offset=0, limit=20):
    params = [
        ("b_offset", offset),
        ("b_limit", limit),
        ("b_order", "applicationDeadline"),
        ("b_keyword", ""),
        ("b_participating_countries", "country-20"),
        ("b_browse", "1"),
    ]
    return f"{BROWSE_TRAINING_URL}?{urlencode(params)}"


def fetch_training_calendar(session):
    print("\n" + "=" * 60)
    print("SALTO TRAINING CALENDAR SCRAPING")
    print("=" * 60)

    results = []
    seen = set()
    offset = 0
    limit = 20

    while True:
        url = build_training_search_url(offset=offset, limit=limit)
        print(f"[Training Offset {offset}] Ophalen via: {url}")

        response = fetch(session, url)
        if not response:
            break

        soup = BeautifulSoup(response.text, "html.parser")
        links = soup.find_all("a", href=re.compile(r"/tools/european-training-calendar/training/[^/]+/\d+"))

        if not links:
            print("  -> Geen trainingen meer gevonden op deze pagina.")
            break

        added_on_page = 0
        for link in links:
            href = link.get("href", "").strip()
            full_url = urljoin(BASE_URL, href)

            if full_url in seen:
                continue
            seen.add(full_url)

            title = clean_text(link.get_text(" ", strip=True))
            if not title or title.lower() in ["view", "more", "details"]:
                continue

            detail_resp = fetch(session, full_url)
            deadline_str = None
            act_type = "Overig"

            if detail_resp:
                dt_soup = BeautifulSoup(detail_resp.text, "html.parser")
                dt_text = clean_text(dt_soup.get_text(" ", strip=True))
                deadline_str = extract_deadline(dt_soup, dt_text)
                act_type = extract_activity_type(dt_soup, dt_text)

            deadline_date = parse_date(deadline_str)
            deadline_iso = deadline_date.strftime("%Y-%m-%d") if deadline_date else None

            results.append({
                "title": title,
                "url": full_url,
                "source": "Training Calendar",
                "activity_type": act_type,
                "application_deadline": deadline_str or "Niet vermeld",
                "application_deadline_iso": deadline_iso,
                "netherlands_eligible": True,
                "scraped_at": datetime.now(timezone.utc).isoformat()
            })
            added_on_page += 1
            time.sleep(0.1)

        print(f"  -> {added_on_page} nieuwe trainingen verwerkt op deze pagina.")
        
        if len(links) < limit:
            break

        offset += limit

    return results


# ============================================================
# 2. OTLAS PARTNER FINDING SCRAPER
# ============================================================

def build_otlas_search_url(offset=0, limit=10):
    base_params = (
        "b_browse=Search+projects"
        "&b_countries%5B%5D=country-20"
        "&b_inclusion=0"
        "&b_partners_needed=0"
        "&b_future_deadline=0"
        "&b_range_projects=0"
        "&b_name="
        f"&b_offset={offset}"
        f"&b_limit={limit}"
        "&b_order=created"
    )
    return f"{BROWSE_OTLAS_URL}?{base_params}"


def fetch_otlas_exchanges(session):
    print("\n" + "=" * 60)
    print("OTLAS SCRAPING")
    print("=" * 60)

    otlas_results = []
    seen = set()
    offset = 0
    limit = 10

    while True:
        url = build_otlas_search_url(offset=offset, limit=limit)
        print(f"[Otlas Offset {offset}] Ophalen via: {url}")

        response = fetch(session, url)
        if not response:
            break

        soup = BeautifulSoup(response.text, "html.parser")
        links = soup.find_all("a", href=re.compile(r"/tools/otlas-partner-finding/project/"))

        if not links:
            print("  -> Geen Otlas projecten meer gevonden op deze pagina.")
            break

        added_on_page = 0
        for link in links:
            href = link.get("href", "").strip()
            full_url = urljoin(BASE_URL, href)

            if full_url in seen:
                continue
            seen.add(full_url)

            title = clean_text(link.get_text(" ", strip=True))
            if not title or title.lower() in ["view", "more", "details", "read more"]:
                container = link.find_parent(["tr", "div", "li"])
                if container:
                    heading = container.find(["h2", "h3", "h4", "strong", "a"])
                    if heading:
                        title = clean_text(heading.get_text(" ", strip=True))
                if not title or title.lower() in ["view", "more", "details"]:
                    title = "Otlas Partner Project"

            detail_resp = fetch(session, full_url)
            deadline_str = None
            act_type = "Overig"

            if detail_resp:
                dt_soup = BeautifulSoup(detail_resp.text, "html.parser")
                dt_text = clean_text(dt_soup.get_text(" ", strip=True))
                
                deadline_str = extract_deadline(dt_soup, dt_text)
                act_type = extract_activity_type(dt_soup, dt_text)

            deadline_date = parse_date(deadline_str)
            deadline_iso = deadline_date.strftime("%Y-%m-%d") if deadline_date else None

            otlas_results.append({
                "title": title,
                "url": full_url,
                "source": "Otlas",
                "activity_type": act_type,
                "application_deadline": deadline_str or "Doorlopend / Niet vermeld",
                "application_deadline_iso": deadline_iso,
                "netherlands_eligible": True,
                "scraped_at": datetime.now(timezone.utc).isoformat()
            })
            added_on_page += 1
            time.sleep(0.1)

        print(f"  -> {added_on_page} nieuwe Otlas projecten verwerkt op deze pagina.")

        if len(links) < limit:
            break

        offset += limit

    return otlas_results


# ============================================================
# MAIN EXECUTION
# ============================================================

def main():
    session = requests.Session()

    training_data = fetch_training_calendar(session)
    otlas_data = fetch_otlas_exchanges(session)

    raw_projects = training_data + otlas_data
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # FILTER: Verwijder verlopen projecten
    active_projects = []
    expired_count = 0

    for project in raw_projects:
        iso_deadline = project.get("application_deadline_iso")
        # Behoud het project als er géén ISO-datum is OF als de datum vandaag/in de toekomst ligt
        if not iso_deadline or iso_deadline >= today_iso:
            active_projects.append(project)
        else:
            expired_count += 1

    print("\n" + "=" * 60)
    print("SCRAPING EN FILTERING VOLTOOID:")
    print(f" - Totaal opgehaald     : {len(raw_projects)} items")
    print(f" - Verlopen (verwijderd): {expired_count} items")
    print(f" - Totaal actief behouden: {len(active_projects)} items")
    print("=" * 60)

    # Schrijf direct naar data/salto_courses.json
    output_dir = "data"
    output_filename = os.path.join(output_dir, "salto_courses.json")

    os.makedirs(output_dir, exist_ok=True)
    
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(active_projects, f, ensure_ascii=False, indent=2)

    print(f"\nResultaten succesvol overschreven in '{output_filename}'")


if __name__ == "__main__":
    main()
