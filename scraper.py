#!/usr/bin/env python3

"""
SALTO + OTLAS Erasmus+ Youth scraper
====================================

Bronnen:
- SALTO European Training Calendar
- SALTO OTLAS Partner Finding

Output:
- data/salto_courses.json

Belangrijk:
- Nederlandse deelname/partnergeschiktheid wordt expliciet gecontroleerd.
- Verlopen deadlines worden verwijderd.
- OTLAS-projecten zonder deadline worden alleen behouden wanneer
  het project nog loopt of in de toekomst plaatsvindt.
- Geen vaste paginalimiet.
- Pagination gebeurt via b_limit + b_offset.
- Bescherming tegen oneindige loops.
"""

from __future__ import annotations

import json
import os
import re
import time
import hashlib
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qsl, urlencode, urlunparse

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURATIE
# ============================================================

BASE_URL = "https://www.salto-youth.net"

SALTO_BROWSE_URL = (
    "https://www.salto-youth.net/tools/european-training-calendar/browse/"
)

OTLAS_BROWSE_URL = (
    "https://www.salto-youth.net/tools/otlas-partner-finding/projects/"
)

OUTPUT_FILE = Path("data/salto_courses.json")

# Aantal resultaten per overzichtspagina.
# SALTO/OTLAS gebruiken momenteel 10 als standaard.
PAGE_SIZE = 10

# Kleine pauze om de website niet onnodig zwaar te belasten.
REQUEST_DELAY = 0.35

# Extra timeout voor individuele HTTP requests.
REQUEST_TIMEOUT = 30

# User-Agent zodat de website weet dat dit een normale scraper/client is.
USER_AGENT = (
    "Wikkel-Erasmus-Scraper/1.0 "
    "(SALTO/OTLAS opportunity aggregation)"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
}

# OTLAS-projecten zonder partnerdeadline mogen worden meegenomen,
# maar alleen wanneer het project zelf nog actief/toekomstig is.
KEEP_OTLAS_WITHOUT_DEADLINE = True


# ============================================================
# SESSION
# ============================================================

session = requests.Session()
session.headers.update(HEADERS)


# ============================================================
# CONSTANTEN
# ============================================================

TODAY = date.today()


# SALTO activity types
SALTO_CATEGORY_MAP = {
    "study visit": "study_visit",
    "partnership-building activity": "partnership_building",
    "partnership building activity": "partnership_building",
    "seminar": "seminar",
    "training course": "training_course",
    "e-learning": "e_learning",
    "conference – symposium - forum": "conference",
    "conference - symposium - forum": "conference",
    "conference": "conference",
}


# OTLAS gebruikt momenteel deze activiteitstypes.
OTLAS_CATEGORY_MAP = {
    "youth exchanges": "youth_exchange",
    "volunteering activities": "volunteering",
    "volunteering activities (formerly evs)": "volunteering",
    "training and networking": "training_and_networking",
    "transnational youth initiatives": "transnational_youth_initiative",
    "strategic partnerships": "strategic_partnership",
    "capacity building": "capacity_building",
    "meetings between young people and decision-makers": "decision_makers",
}


# ============================================================
# HTTP
# ============================================================

def fetch(url: str, retries: int = 3) -> requests.Response | None:
    """
    Download een pagina met retries.

    Geeft None terug wanneer alle pogingen mislukken.
    """

    for attempt in range(1, retries + 1):
        try:
            response = session.get(
                url,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code == 200:
                time.sleep(REQUEST_DELAY)
                return response

            # Rate limiting
            if response.status_code == 429:
                wait = 5 * attempt
                print(
                    f"  HTTP 429 ontvangen. "
                    f"Wachten {wait}s..."
                )
                time.sleep(wait)
                continue

            print(
                f"  HTTP {response.status_code}: {url}"
            )

        except requests.RequestException as exc:
            print(
                f"  Request fout "
                f"(poging {attempt}/{retries}): {exc}"
            )

            if attempt < retries:
                time.sleep(2 * attempt)

    return None


# ============================================================
# URL HELPERS
# ============================================================

def make_offset_url(
    base_url: str,
    offset: int,
    order: str,
) -> str:
    """
    Bouwt een SALTO/OTLAS URL met b_limit + b_offset.
    """

    parsed = urlparse(base_url)

    params = dict(parse_qsl(parsed.query))

    params["b_limit"] = str(PAGE_SIZE)
    params["b_offset"] = str(offset)
    params["b_order"] = order

    new_query = urlencode(params)

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment,
        )
    )


def normalize_url(url: str) -> str:
    """
    Normaliseert URL's zodat dezelfde pagina niet meerdere keren
    wordt opgeslagen.
    """

    if not url:
        return ""

    url = urljoin(BASE_URL, url)

    parsed = urlparse(url)

    # Fragment verwijderen
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path.rstrip("/"),
            "",
            parsed.query,
            "",
        )
    )


# ============================================================
# TEKST HELPERS
# ============================================================

def clean_text(value: str | None) -> str:
    """
    Maakt whitespace netjes.
    """

    if not value:
        return ""

    return re.sub(r"\s+", " ", value).strip()


def soup_text(soup: BeautifulSoup) -> str:
    """
    Volledige tekst van een pagina.
    """

    return clean_text(soup.get_text(" ", strip=True))


def normalize_for_match(value: str) -> str:
    """
    Normaliseert tekst voor betrouwbare vergelijkingen.
    """

    value = value.lower()

    value = (
        value
        .replace("–", "-")
        .replace("—", "-")
        .replace("’", "'")
    )

    value = re.sub(r"\s+", " ", value)

    return value.strip()


# ============================================================
# DATUM HELPERS
# ============================================================

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def parse_iso_date(value: str) -> date | None:
    """
    Parse YYYY-MM-DD.
    """

    if not value:
        return None

    match = re.search(
        r"\b(20\d{2})-(\d{2})-(\d{2})\b",
        value,
    )

    if not match:
        return None

    try:
        return date(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
        )
    except ValueError:
        return None


def parse_english_date(value: str) -> date | None:
    """
    Parse bijvoorbeeld:
    18 September 2026
    September 18, 2026
    """

    if not value:
        return None

    text = clean_text(value).lower()

    # 18 September 2026
    match = re.search(
        r"\b(\d{1,2})\s+"
        r"(january|february|march|april|may|june|july|"
        r"august|september|october|november|december)"
        r"\s+(20\d{2})\b",
        text,
    )

    if match:
        day = int(match.group(1))
        month = MONTHS[match.group(2)]
        year = int(match.group(3))

        try:
            return date(year, month, day)
        except ValueError:
            return None

    # September 18, 2026
    match = re.search(
        r"\b"
        r"(january|february|march|april|may|june|july|"
        r"august|september|october|november|december)"
        r"\s+(\d{1,2}),?\s+(20\d{2})\b",
        text,
    )

    if match:
        month = MONTHS[match.group(1)]
        day = int(match.group(2))
        year = int(match.group(3))

        try:
            return date(year, month, day)
        except ValueError:
            return None

    return None


def extract_iso_dates(text: str) -> list[str]:
    """
    Haalt alle ISO-datums uit tekst.
    """

    return sorted(
        set(
            re.findall(
                r"\b20\d{2}-\d{2}-\d{2}\b",
                text or "",
            )
        )
    )


def latest_date_from_strings(values: list[str]) -> date | None:
    """
    Zoek de laatste parsebare datum.
    """

    parsed = []

    for value in values:
        d = parse_iso_date(value)

        if d:
            parsed.append(d)

    if not parsed:
        return None

    return max(parsed)


# ============================================================
# TITEL
# ============================================================

def extract_title(soup: BeautifulSoup) -> str:
    """
    Haalt de titel uit H1.
    """

    h1 = soup.find("h1")

    if h1:
        title = clean_text(h1.get_text(" ", strip=True))

        if title:
            return title

    # Fallback
    if soup.title:
        title = clean_text(soup.title.get_text(" ", strip=True))

        title = re.sub(
            r"\s*\|\s*SALTO.*$",
            "",
            title,
            flags=re.I,
        )

        return title

    return ""


# ============================================================
# LINK DETECTIE
# ============================================================

def is_salto_detail_url(url: str) -> bool:
    """
    Controleert of een URL naar een SALTO training/detailpagina gaat.
    """

    path = urlparse(url).path.lower()

    return (
        "/tools/european-training-calendar/training/" in path
        or "/tools/european-training-calendar/goto-training/" in path
    )


def is_otlas_detail_url(url: str) -> bool:
    """
    Controleert of een URL naar een OTLAS project gaat.
    """

    path = urlparse(url).path.lower()

    return "/tools/otlas-partner-finding/project/" in path


def extract_detail_links(
    soup: BeautifulSoup,
    source: str,
) -> list[str]:

    links = []

    for a in soup.find_all("a", href=True):
        href = normalize_url(a.get("href"))

        if not href:
            continue

        if source == "salto":
            valid = is_salto_detail_url(href)
        else:
            valid = is_otlas_detail_url(href)

        if valid:
            links.append(href)

    return list(dict.fromkeys(links))


# ============================================================
# ELIGIBILITY
# ============================================================

def contains_netherlands(text: str) -> bool:
    """
    Expliciete Nederlandse deelname.
    """

    normalized = normalize_for_match(text)

    return (
        "netherlands" in normalized
        or "the netherlands" in normalized
    )


def contains_programme_country_group(text: str) -> bool:
    """
    Controleert alleen expliciete SALTO/Erasmus+
    programme-country formuleringen.

    We nemen NIET zomaar ieder voorkomen van
    'partner countries' als bewijs.
    """

    normalized = normalize_for_match(text)

    patterns = [
        "erasmus+ youth programme countries",
        "erasmus: youth in action programme countries",
        "erasmus+ programme countries",
    ]

    return any(
        pattern in normalized
        for pattern in patterns
    )


def determine_eligibility(
    eligibility_text: str,
) -> tuple[bool, str]:

    text = clean_text(eligibility_text)

    if contains_netherlands(text):
        return True, "netherlands_explicitly_listed"

    if contains_programme_country_group(text):
        return True, "erasmus_programme_countries"

    return False, "netherlands_not_found"


# ============================================================
# SALTO ELIGIBILITY
# ============================================================

def extract_salto_eligibility(soup: BeautifulSoup) -> str:
    """
    SALTO heeft momenteel tekst zoals:

    This activity is for participants from

    Netherlands, Germany, ...

    We halen alleen het relevante gedeelte op.
    """

    text = soup_text(soup)

    marker = re.search(
        r"This activity is for participants from",
        text,
        flags=re.I,
    )

    if not marker:
        # Sommige detailpagina's gebruiken:
        # "This Training Course is for ... from"
        marker = re.search(
            r"This .*? is\s+for .*? from",
            text,
            flags=re.I,
        )

    if not marker:
        return ""

    start = marker.end()

    remainder = text[start:]

    stop_patterns = [
        r"Application deadline",
        r"Date of selection",
        r"Please note",
        r"More information",
        r"Contact",
        r"Apply now",
        r"Training overview",
    ]

    end_positions = []

    for pattern in stop_patterns:
        match = re.search(
            pattern,
            remainder,
            flags=re.I,
        )

        if match:
            end_positions.append(match.start())

    if end_positions:
        remainder = remainder[:min(end_positions)]

    return clean_text(remainder)


# ============================================================
# SALTO DEADLINE
# ============================================================

def extract_salto_deadline(
    soup: BeautifulSoup,
) -> tuple[str, str]:
    """
    Haalt de application deadline uit de SALTO-pagina.
    """

    text = soup_text(soup)

    # Primaire huidige formulering:
    # Application deadline (24h UTC): 18 September 2026
    pattern = re.search(
        r"Application deadline"
        r"(?:\s*\([^)]*\))?"
        r"\s*[:\-]?\s*"
        r"(\d{1,2}\s+"
        r"(?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December)"
        r"\s+20\d{2})",
        text,
        flags=re.I,
    )

    if pattern:
        raw = clean_text(pattern.group(1))
        parsed = parse_english_date(raw)

        if parsed:
            return raw, parsed.isoformat()

    # Fallback voor varianten
    marker = re.search(
        r"Application deadline",
        text,
        flags=re.I,
    )

    if marker:
        section = text[marker.start():marker.start() + 250]

        parsed = parse_english_date(section)

        if parsed:
            return parsed.strftime("%d %B %Y"), parsed.isoformat()

        iso = parse_iso_date(section)

        if iso:
            return iso.isoformat(), iso.isoformat()

    return "", ""


# ============================================================
# SALTO CATEGORY
# ============================================================

def extract_salto_activity_type(
    soup: BeautifulSoup,
) -> str:
    """
    Probeert eerst het type uit de detailpagina te halen.
    """

    text = soup_text(soup)

    # Langste/meer specifieke eerst
    candidates = sorted(
        SALTO_CATEGORY_MAP.keys(),
        key=len,
        reverse=True,
    )

    normalized = normalize_for_match(text)

    for candidate in candidates:
        if candidate in normalized:
            return candidate

    return "Other"


def normalize_salto_category(
    activity_type: str,
) -> str:

    normalized = normalize_for_match(activity_type)

    return SALTO_CATEGORY_MAP.get(
        normalized,
        "other",
    )


# ============================================================
# SALTO DATA
# ============================================================

def scrape_salto_detail(url: str) -> dict | None:
    """
    Verwerk één SALTO detailpagina.
    """

    response = fetch(url)

    if not response:
        return None

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    title = extract_title(soup)

    if not title:
        return None

    eligibility_text = extract_salto_eligibility(soup)

    eligible, reason = determine_eligibility(
        eligibility_text
    )

    if not eligible:
        return None

    activity_type = extract_salto_activity_type(soup)

    category = normalize_salto_category(
        activity_type
    )

    deadline, deadline_iso = extract_salto_deadline(
        soup
    )

    # Verlopen deadline verwijderen
    if deadline_iso:
        parsed_deadline = parse_iso_date(deadline_iso)

        if parsed_deadline and parsed_deadline < TODAY:
            return None

    # Datums uit de detailpagina.
    # Alleen informatief; de deadline wordt apart opgeslagen.
    all_text = soup_text(soup)

    dates_found = extract_iso_dates(all_text)

    # Nederlandse / Engelse datums op detailpagina kunnen
    # ook in andere vorm staan. We bewaren ISO indien gevonden.
    dates_found = sorted(set(dates_found))

    return {
        "title": title,
        "source": "salto",
        "category": category,
        "categories": [category],
        "activity_type": activity_type,
        "dates_found": dates_found,
        "application_deadline": deadline,
        "application_deadline_iso": deadline_iso,
        "netherlands_eligible": True,
        "eligibility_reason": reason,
        "eligibility_type": "participant",
        "url": url,
    }


# ============================================================
# SALTO SCRAPER
# ============================================================

def scrape_salto_courses() -> list[dict]:
    """
    Doorzoekt alle SALTO ETC-pagina's.

    Geen vaste paginalimiet.

    Stopvoorwaarden:
    - pagina bevat geen nieuwe detail-URL's
    - dezelfde URL-signatuur komt opnieuw voor
    """

    print()
    print("=" * 70)
    print("SALTO EUROPEAN TRAINING CALENDAR")
    print("=" * 70)

    results = []

    seen_detail_urls = set()
    seen_page_signatures = set()

    offset = 0
    page_number = 1

    while True:

        url = make_offset_url(
            SALTO_BROWSE_URL,
            offset,
            "applicationDeadline",
        )

        print(
            f"\nSALTO pagina {page_number} "
            f"(offset={offset})"
        )

        response = fetch(url)

        if not response:
            print("  Pagina kon niet worden geladen.")
            break

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        detail_urls = extract_detail_links(
            soup,
            "salto",
        )

        new_urls = [
            item
            for item in detail_urls
            if item not in seen_detail_urls
        ]

        print(
            f"  Detail-links gevonden: "
            f"{len(detail_urls)}"
        )

        print(
            f"  Nieuwe links: "
            f"{len(new_urls)}"
        )

        if not new_urls:
            print(
                "  Geen nieuwe SALTO-resultaten meer."
            )
            break

        # Bescherming tegen een pagina die steeds dezelfde
        # resultaten teruggeeft.
        signature = hashlib.sha256(
            "|".join(sorted(new_urls)).encode("utf-8")
        ).hexdigest()

        if signature in seen_page_signatures:
            print(
                "  Herhaalde pagina gedetecteerd. "
                "SALTO wordt gestopt."
            )
            break

        seen_page_signatures.add(signature)

        for detail_url in new_urls:
            seen_detail_urls.add(detail_url)

            print(
                f"    -> {detail_url}"
            )

            try:
                item = scrape_salto_detail(
                    detail_url
                )

                if item:
                    results.append(item)

            except Exception as exc:
                print(
                    f"       FOUT: {exc}"
                )

        offset += PAGE_SIZE
        page_number += 1

    print()
    print(
        f"SALTO: {len(results)} "
        f"bruikbare Nederlandse resultaten."
    )

    return results


# ============================================================
# OTLAS LIST DATE EXTRACTION
# ============================================================

def extract_otlas_list_dates(
    soup: BeautifulSoup,
) -> tuple[date | None, date | None, date | None]:
    """
    Probeert op de OTLAS-overzichtspagina:

    - partner deadline
    - project start
    - project einde

    te vinden.

    OTLAS gebruikt op de huidige pagina ISO-datums.
    """

    text = soup_text(soup)

    deadline = None
    start = None
    end = None

    # We zoeken eerst expliciet rond de labels.

    deadline_match = re.search(
        r"Deadline for this partner request:"
        r"\s*(20\d{2}-\d{2}-\d{2})",
        text,
        flags=re.I,
    )

    if deadline_match:
        deadline = parse_iso_date(
            deadline_match.group(1)
        )

    project_match = re.search(
        r"This project takes place:"
        r"\s*from\s*"
        r"(20\d{2}(?:-\d{2})?(?:-\d{2})?)"
        r"\s*till\s*"
        r"(20\d{2}(?:-\d{2})?(?:-\d{2})?)",
        text,
        flags=re.I,
    )

    if project_match:

        start_raw = project_match.group(1)
        end_raw = project_match.group(2)

        # Alleen volledige ISO datum betrouwbaar parsen.
        start = parse_iso_date(start_raw)
        end = parse_iso_date(end_raw)

    return deadline, start, end


# ============================================================
# OTLAS CATEGORY EXTRACTION
# ============================================================

def extract_otlas_categories(
    soup: BeautifulSoup,
) -> tuple[list[str], str]:
    """
    Haalt categorieën uit het specifieke:

    This project relates to:

    gedeelte.

    Hierdoor worden woorden elders op de pagina niet
    ten onrechte als categorie gezien.
    """

    text = soup_text(soup)

    marker = re.search(
        r"This project relates to:",
        text,
        flags=re.I,
    )

    if not marker:
        return ["other"], "Other"

    remainder = text[marker.end():]

    stop_patterns = [
        r"and is focusing on:",
        r"This project can include",
        r"Short URL to this project:",
        r"Please login",
    ]

    end_positions = []

    for pattern in stop_patterns:
        match = re.search(
            pattern,
            remainder,
            flags=re.I,
        )

        if match:
            end_positions.append(match.start())

    if end_positions:
        remainder = remainder[:min(end_positions)]

    relevant_text = normalize_for_match(
        remainder
    )

    categories = []
    labels = []

    # Langste labels eerst.
    for label, category in sorted(
        OTLAS_CATEGORY_MAP.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):

        if label in relevant_text:
            if category not in categories:
                categories.append(category)

                # Mooie originele label
                labels.append(
                    label.title()
                )

    if not categories:
        return ["other"], "Other"

    return categories, ", ".join(labels)


# ============================================================
# OTLAS ELIGIBILITY
# ============================================================

def extract_otlas_eligibility(
    soup: BeautifulSoup,
) -> str:
    """
    Haalt alleen het gedeelte rondom:

    We're looking for:

    ... from Netherlands, Germany, ...

    """

    text = soup_text(soup)

    marker = re.search(
        r"We['’]re looking for:",
        text,
        flags=re.I,
    )

    if not marker:
        return ""

    remainder = text[marker.end():]

    # Zoek het eerste "from ..."
    from_match = re.search(
        r"\bfrom\s+(.+?)(?="
        r"\s+Deadline for this partner request:"
        r"|\s+Please login"
        r"|\s+Project overview"
        r")",
        remainder,
        flags=re.I,
    )

    if from_match:
        return clean_text(
            from_match.group(1)
        )

    # Sommige projecten hebben geen deadline.
    from_match = re.search(
        r"\bfrom\s+(.+?)(?="
        r"\s+Please login"
        r"|\s+Project overview"
        r")",
        remainder,
        flags=re.I,
    )

    if from_match:
        return clean_text(
            from_match.group(1)
        )

    return ""


# ============================================================
# OTLAS DEADLINE
# ============================================================

def extract_otlas_deadline(
    soup: BeautifulSoup,
) -> tuple[str, str]:
    """
    Extracteert:

    Deadline for this partner request:
    2026-10-16
    """

    text = soup_text(soup)

    match = re.search(
        r"Deadline for this partner request:"
        r"\s*(20\d{2}-\d{2}-\d{2})",
        text,
        flags=re.I,
    )

    if not match:
        return "", ""

    raw = match.group(1)

    parsed = parse_iso_date(raw)

    if not parsed:
        return "", ""

    return raw, parsed.isoformat()


# ============================================================
# OTLAS DETAIL
# ============================================================

def scrape_otlas_detail(
    url: str,
) -> dict | None:

    response = fetch(url)

    if not response:
        return None

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    title = extract_title(soup)

    if not title:
        return None

    eligibility_text = extract_otlas_eligibility(
        soup
    )

    eligible, reason = determine_eligibility(
        eligibility_text
    )

    if not eligible:
        return None

    categories, activity_type = (
        extract_otlas_categories(soup)
    )

    deadline, deadline_iso = (
        extract_otlas_deadline(soup)
    )

    # Verlopen deadline = verwijderen
    if deadline_iso:
        parsed_deadline = parse_iso_date(
            deadline_iso
        )

        if parsed_deadline and parsed_deadline < TODAY:
            return None

    # Projectdatums
    project_text = soup_text(soup)

    iso_dates = extract_iso_dates(
        project_text
    )

    # Als er geen deadline is:
    # alleen behouden als het project zelf nog loopt/toekomstig is.
    if not deadline_iso:

        if not KEEP_OTLAS_WITHOUT_DEADLINE:
            return None

        # Zoek projectperiode.
        project_match = re.search(
            r"taking place\s+from\s+"
            r"(20\d{2}(?:-\d{2})?(?:-\d{2})?)"
            r"\s+till\s+"
            r"(20\d{2}(?:-\d{2})?(?:-\d{2})?)",
            project_text,
            flags=re.I,
        )

        if project_match:

            end_raw = project_match.group(2)

            end_date = parse_iso_date(
                end_raw
            )

            if end_date and end_date < TODAY:
                return None

    return {
        "title": title,
        "source": "otlas",
        "category": categories[0],
        "categories": categories,
        "activity_type": activity_type,
        "dates_found": iso_dates,
        "application_deadline": deadline,
        "application_deadline_iso": deadline_iso,
        "netherlands_eligible": True,
        "eligibility_reason": reason,
        "eligibility_type": "organisation_partner",
        "url": url,
    }


# ============================================================
# OTLAS LIST PAGE FILTERING
# ============================================================

def get_otlas_candidate_links(
    soup: BeautifulSoup,
) -> list[str]:
    """
    Haalt OTLAS detail-links uit een overzichtspagina.

    We openen niet automatisch ieder oud project.
    """

    return extract_detail_links(
        soup,
        "otlas",
    )


def page_contains_relevant_otlas_projects(
    soup: BeautifulSoup,
) -> bool:
    """
    Controleert of de pagina überhaupt nog
    potentiële actieve projecten bevat.

    We gebruiken dit niet als enige filter;
    detailpagina's blijven de definitieve bron.
    """

    text = soup_text(soup)

    if "Deadline for this partner request:" in text:
        return True

    if "This project takes place:" in text:
        return True

    return False


# ============================================================
# OTLAS SCRAPER
# ============================================================

def scrape_otlas_projects() -> list[dict]:
    """
    Doorzoekt OTLAS.

    Belangrijk optimalisatieprincipe:

    OTLAS bevat momenteel meer dan 11.000 projecten.
    De database bevat ook veel oude/verlopen projecten.

    Daarom:
    1. overzichtspagina's doorlopen;
    2. detail-links verzamelen;
    3. alleen actieve/potentieel relevante projecten openen;
    4. op detailpagina Nederlandse partnergeschiktheid bevestigen.
    """

    print()
    print("=" * 70)
    print("OTLAS PARTNER FINDING")
    print("=" * 70)

    results = []

    seen_detail_urls = set()
    seen_page_signatures = set()

    offset = 0
    page_number = 1

    while True:

        url = make_offset_url(
            OTLAS_BROWSE_URL,
            offset,
            "lastmod",
        )

        print(
            f"\nOTLAS pagina {page_number} "
            f"(offset={offset})"
        )

        response = fetch(url)

        if not response:
            print(
                "  Pagina kon niet worden geladen."
            )
            break

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        if not page_contains_relevant_otlas_projects(
            soup
        ):
            print(
                "  Geen relevante OTLAS-resultaten "
                "meer op deze pagina."
            )
            break

        detail_urls = get_otlas_candidate_links(
            soup
        )

        new_urls = [
            item
            for item in detail_urls
            if item not in seen_detail_urls
        ]

        print(
            f"  Detail-links gevonden: "
            f"{len(detail_urls)}"
        )

        print(
            f"  Nieuwe links: "
            f"{len(new_urls)}"
        )

        if not new_urls:
            print(
                "  Geen nieuwe OTLAS-resultaten meer."
            )
            break

        signature = hashlib.sha256(
            "|".join(sorted(new_urls)).encode("utf-8")
        ).hexdigest()

        if signature in seen_page_signatures:
            print(
                "  Herhaalde pagina gedetecteerd. "
                "OTLAS wordt gestopt."
            )
            break

        seen_page_signatures.add(signature)

        for detail_url in new_urls:

            seen_detail_urls.add(
                detail_url
            )

            print(
                f"    -> {detail_url}"
            )

            try:

                item = scrape_otlas_detail(
                    detail_url
                )

                if item:
                    results.append(item)

            except Exception as exc:
                print(
                    f"       FOUT: {exc}"
                )

        offset += PAGE_SIZE
        page_number += 1

    print()
    print(
        f"OTLAS: {len(results)} "
        f"bruikbare Nederlandse partner-resultaten."
    )

    return results


# ============================================================
# DEDUPLICATIE
# ============================================================

def deduplicate_results(
    items: list[dict],
) -> list[dict]:
    """
    Verwijdert dubbele resultaten op URL.
    """

    seen = set()
    output = []

    for item in items:

        url = normalize_url(
            item.get("url", "")
        )

        if not url:
            continue

        if url in seen:
            continue

        seen.add(url)

        item["url"] = url

        output.append(item)

    return output


# ============================================================
# EXTRA VALIDATIE
# ============================================================

def validate_item(item: dict) -> bool:
    """
    Controleert of een JSON-item minimaal
    de noodzakelijke structuur heeft.
    """

    required_fields = [
        "title",
        "source",
        "category",
        "categories",
        "activity_type",
        "netherlands_eligible",
        "eligibility_type",
        "url",
    ]

    for field in required_fields:

        if field not in item:
            return False

    if not item["title"]:
        return False

    if item["source"] not in {
        "salto",
        "otlas",
    }:
        return False

    if item["netherlands_eligible"] is not True:
        return False

    if not isinstance(
        item["categories"],
        list,
    ):
        return False

    return True


def validate_results(
    items: list[dict],
) -> list[dict]:

    valid = []

    for item in items:

        if validate_item(item):
            valid.append(item)

    return valid


# ============================================================
# SORTERING
# ============================================================

def sort_results(
    items: list[dict],
) -> list[dict]:
    """
    Sorteert eerst op deadline.
    Items zonder deadline komen daarna.
    """

    def sort_key(item):

        deadline = item.get(
            "application_deadline_iso"
        )

        if deadline:
            return (
                0,
                deadline,
                item.get("title", "").lower(),
            )

        return (
            1,
            "9999-99-99",
            item.get("title", "").lower(),
        )

    return sorted(
        items,
        key=sort_key,
    )


# ============================================================
# JSON SCHRIJVEN
# ============================================================

def write_json(
    items: list[dict],
) -> None:
    """
    Schrijft atomisch naar data/salto_courses.json.

    Eerst wordt een tijdelijk bestand geschreven.
    Daarna wordt het bestaande bestand vervangen.

    Daardoor blijft het oude JSON-bestand behouden wanneer
    het schrijven mislukt.
    """

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_file = OUTPUT_FILE.with_suffix(
        ".tmp"
    )

    with temporary_file.open(
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            items,
            file,
            ensure_ascii=False,
            indent=2,
        )

        file.write("\n")

    os.replace(
        temporary_file,
        OUTPUT_FILE,
    )


# ============================================================
# STATISTIEKEN
# ============================================================

def print_statistics(
    items: list[dict],
) -> None:

    salto = [
        item
        for item in items
        if item["source"] == "salto"
    ]

    otlas = [
        item
        for item in items
        if item["source"] == "otlas"
    ]

    print()
    print("=" * 70)
    print("RESULTAAT")
    print("=" * 70)

    print(
        f"Totaal: {len(items)}"
    )

    print(
        f"SALTO:  {len(salto)}"
    )

    print(
        f"OTLAS:  {len(otlas)}"
    )

    print()
    print("Categorieën:")

    counts = {}

    for item in items:

        for category in item.get(
            "categories",
            [],
        ):

            counts[category] = (
                counts.get(category, 0) + 1
            )

    for category, count in sorted(
        counts.items()
    ):
        print(
            f"  {category}: {count}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    started = datetime.now()

    print()
    print("=" * 70)
    print("WIKKEL ERASMUS+ SCRAPER")
    print("=" * 70)

    print(
        f"Datum: {TODAY.isoformat()}"
    )

    print(
        f"Output: {OUTPUT_FILE}"
    )

    print()

    # --------------------------------------------------------
    # SALTO
    # --------------------------------------------------------

    try:
        salto_results = scrape_salto_courses()

    except Exception as exc:

        print(
            "\nFATALE SALTO-FOUT:"
        )
        print(exc)

        salto_results = []

    # --------------------------------------------------------
    # OTLAS
    # --------------------------------------------------------

    try:
        otlas_results = scrape_otlas_projects()

    except Exception as exc:

        print(
            "\nFATALE OTLAS-FOUT:"
        )
        print(exc)

        otlas_results = []

    # --------------------------------------------------------
    # COMBINEREN
    # --------------------------------------------------------

    combined = (
        salto_results
        + otlas_results
    )

    combined = deduplicate_results(
        combined
    )

    combined = validate_results(
        combined
    )

    combined = sort_results(
        combined
    )

    # --------------------------------------------------------
    # VEILIGHEID
    # --------------------------------------------------------

    # Als beide bronnen niets opleveren, overschrijven we
    # NIET je bestaande JSON.
    if not combined:

        print()
        print(
            "WAARSCHUWING:"
        )

        print(
            "De scraper heeft 0 geldige resultaten "
            "opgeleverd."
        )

        print(
            "Het bestaande JSON-bestand wordt "
            "NIET overschreven."
        )

        return

    # --------------------------------------------------------
    # JSON
    # --------------------------------------------------------

    write_json(
        combined
    )

    # --------------------------------------------------------
    # STATISTIEKEN
    # --------------------------------------------------------

    print_statistics(
        combined
    )

    elapsed = (
        datetime.now()
        - started
    )

    print()
    print("=" * 70)

    print(
        f"Klaar in: {elapsed}"
    )

    print(
        f"JSON opgeslagen als: "
        f"{OUTPUT_FILE}"
    )

    print("=" * 70)


if __name__ == "__main__":
    main()
