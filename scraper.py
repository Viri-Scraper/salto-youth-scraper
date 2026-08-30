import json
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

    date_str = date_str.strip()
    formats = [
        "%d %B %Y",      # 12 October 2026
        "%d %b %Y",       # 12 Oct 2026
        "%Y-%m-%d",       # 2026-10-12
        "%d/%m/%Y",       # 12/10/2026
        "%d.%m.%Y",       # 12.10.2026
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            pass
    return None


def extract_deadline(soup, text):
    """Zoekt naar een aanmelddeadline in de detailpagina."""
    label = soup.find(text=re.compile(r"Application deadline|Deadline", re.IGNORECASE))
    if label and label.parent:
        parent_text = label.parent.get_text(" ", strip=True)
        match = re.search(r"(?:Application deadline|Deadline)\s*:\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})", parent_text, re.IGNORECASE)
        if match:
            return match.group(1)

    match = re.search(r"(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})", text, re.IGNORECASE)
    if match:
        return match.group(1)

    return None


def extract_activity_type(soup, full_text):
    """
    Bepaalt het type activiteit op basis van specifieke HTML-elementen 
    of regex-zoekwoorden over de tekst.
    """
    extracted_raw = ""
    
    # Zoek in bekende Otlas & SALTO HTML containers
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
    now = datetime.now()
    params = [
        ("b_offset", offset),
        ("b_limit", limit),
        ("b_order", "applicationDeadline"),
        ("b_keyword", ""),
        ("b_participating_countries", "country-20"),
        ("b_application_deadline_after_day", now.day),
        ("b_application_deadline_after_month", now.month),
        ("b_application_deadline_after_year", now.year),
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
        print(f"\n[Training Offset {offset}] Ophalen via: {url}")

        response = fetch(session, url)
        if not response:
            break

        soup = BeautifulSoup(response.text, "html.parser")
        links = soup.find_all("a", href=re.compile(r"/tools/european-training-calendar/training/[^/]+/\d+"))

        if not links:
            print("  -> Geen trainingen meer gevonden.")
            break

        new_count = 0
        for link in links:
            href = link.get("href", "").strip()
            full_url = urljoin(BASE_URL, href)

            if full_url not in seen:
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

                results.append({
                    "title": title,
                    "url": full_url,
                    "source": "Training Calendar",
                    "activity_type": act_type,
                    "application_deadline": deadline_str,
                    "application_deadline_iso": (
                        deadline_date.strftime("%Y-%m-%d") if deadline_date else None
                    ),
                    "netherlands_eligible": True,
                    "scraped_at": datetime.now(timezone.utc).isoformat()
                })
                new_count += 1
                time.sleep(0.2)

        print(f"  -> {new_count} nieuwe activiteiten toegevoegd.")

        if new_count == 0:
            break

        offset += limit

    return results


# ============================================================
# 2. OTLAS PARTNER FINDING SCRAPER (GECORRIGEERDE URL & LOGICA)
# ============================================================

def build_otlas_search_url(offset=0, limit=10):
    """
    Gebruikt de exacte URL-structuur van de Otlas zoekopdracht, 
    zonder de restrictieve datum-parameters die resultaten blokkeren.
    """
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
    print("OTLAS SCRAPING (HERSTELD EN GEOPTIMALISEERD)")
    print("=" * 60)

    otlas_results = []
    seen = set()
    offset = 0
    limit = 10
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    while True:
        url = build_otlas_search_url(offset=offset, limit=limit)
        print(f"\n[Otlas Offset {offset}] Ophalen via: {url}")

        response = fetch(session, url)
        if not response:
            break

        soup = BeautifulSoup(response.text, "html.parser")
        
        # Otlas projectlinks herkennen
        links = soup.find_all("a", href=re.compile(r"/tools/otlas-partner-finding/project/\d+"))

        if not links:
            print("  -> Geen Otlas projecten meer gevonden.")
            break

        new_count = 0
        for link in links:
            href = link.get("href", "").strip()
            full_url = urljoin(BASE_URL, href)

            if full_url not in seen:
                seen.add(full_url)
                
                title = clean_text(link.get_text(" ", strip=True))
                
                # Als de link zelf alleen 'View' of 'Details' zegt, pak de titel uit de rij/container
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

                # Sla projecten alleen over als de deadline hard in het verleden ligt
                if deadline_iso and deadline_iso < today_iso:
                    continue

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
                new_count += 1
                time.sleep(0.2)

        print(f"  -> {new_count} actieve Otlas projecten verwerkt.")

        # Veiligheidsstop als er op een pagina niks nieuws meer bij kwam
        if new_count == 0:
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

    all_projects = training_data + otlas_data

    print("\n" + "=" * 60)
    print(f"SCRAPING VOLTOOID:")
    print(f" - Training Calendar : {len(training_data)} items")
    print(f" - Otlas Partnering  : {len(otlas_data)} items")
    print(f" - Totaal actief     : {len(all_projects)} items")
    print("=" * 60)

    output_filename = "salto_projects.json"
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(all_projects, f, ensure_ascii=False, indent=2)

    print(f"\nResultaten succesvol opgeslagen in '{output_filename}'")


if __name__ == "__main__":
    main()
