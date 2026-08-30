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


# ============================================================
# 1. TRAINING CALENDAR (Alle types, alleen NL-geschikt)
# ============================================================

def build_training_search_url(offset=0, limit=20):
    """
    Haalt alle soorten activiteiten op (trainingen, seminars, PBA's, study visits)
    waarbij Nederlanders mogen deelnemen.
    """
    now = datetime.now()
    params = [
        ("b_offset", offset),
        ("b_limit", limit),
        ("b_order", "applicationDeadline"),
        ("b_keyword", ""),
        ("b_participating_countries", "country-20"),  # Nederland
        ("b_application_deadline_after_day", now.day),
        ("b_application_deadline_after_month", now.month),
        ("b_application_deadline_after_year", now.year),
        ("b_browse", "1"),
    ]
    return f"{BROWSE_TRAINING_URL}?{urlencode(params)}"


# ============================================================
# 2. OTLAS PARTNER FINDING (Aangepast op de exacte SALTO parameters)
# ============================================================

def build_otlas_search_url(offset=0, limit=10):
    """
    Bouwt de correcte Otlas URL op basis van de exacte site-parameters.
    Gebruikt een lijst van tuples om b_countries[] correct te encoderen.
    """
    now = datetime.now()
    params = [
        ("b_countries[]", "country-20"),             # Nederland
        ("b_inclusion", "0"),
        ("b_partners_needed", "0"),                  # Zet op "1" als je enkel actieve partneroproepen wilt
        ("b_future_deadline", "0"),                  # Zet op "1" als je enkel toekomstige deadlines wilt
        ("b_range_projects", "0"),
        ("b_range_projects_begin_date_day", now.day),
        ("b_range_projects_begin_date_month", now.month),
        ("b_range_projects_begin_date_year", now.year),
        ("b_range_projects_end_date_day", now.day),
        ("b_range_projects_end_date_month", now.month),
        ("b_range_projects_end_date_year", now.year + 5),
        ("b_name", ""),
        ("b_browse", "Search projects"),
        ("b_offset", offset),                         # Gebruik offset i.p.v. page voor paginering
        ("b_limit", limit),                          # Aantal items per pagina (10)
        ("b_order", "created")
    ]
    return f"{BROWSE_OTLAS_URL}?{urlencode(params)}"


def fetch_otlas_exchanges(session):
    print("\n" + "=" * 60)
    print("OTLAS SCRAPING (ALLE ERASMUS+ & ESC PROJECTEN)")
    print("=" * 60)

    otlas_results = []
    seen = set()
    offset = 0
    limit = 10

    while True:
        url = build_otlas_search_url(offset=offset, limit=limit)
        print(f"\n[Otlas Offset {offset}] Ophalen via: {url}")

        response = fetch(session, url)
        if not response:
            break

        soup = BeautifulSoup(response.text, "html.parser")
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
                if not title or title.lower() in ["view", "more", "details"]:
                    title = "Erasmus+ / ESC Project"

                # Detailpagina scrapen voor het exacte type en deadline
                detail_resp = fetch(session, full_url)
                deadline_str = None
                act_type = "Erasmus+ Project"

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

        print(f"  -> {new_count} nieuwe Otlas projecten toegevoegd op deze pagina.")

        # Geen nieuwe projecten meer gevonden op deze pagina = einde van de zoekresultaten
        if new_count == 0:
            break

        offset += limit

    return otlas_results
