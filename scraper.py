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
CALENDAR_URL = f"{BASE_URL}/tools/european-training-calendar/browse/"
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

    formats = [
        "%d %B %Y",
        "%d %b %Y",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y-%m-%d",
    ]

    for date_format in formats:

        try:
            return datetime.strptime(
                value,
                date_format,
            )

        except ValueError:
            continue

    return None


def extract_deadline(text):
    """Zoek de application deadline in de pagina."""

    patterns = [

        (
            r"Application\s+deadline"
            r"(?:\s*\([^)]*\))?"
            r"\s*:?\s*"
            r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})"
        ),

        (
            r"Deadline\s*:\s*"
            r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})"
        ),
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if match:
            return clean_text(
                match.group(1)
            )

    return None


def extract_dates(text):
    """
    Zoek activiteitdatums.

    Voorbeelden:

    15-22 October 2026
    10 September 2026
    """

    pattern = (
        r"\b"
        r"(\d{1,2}"
        r"(?:-\d{1,2})?"
        r"\s+[A-Za-z]+\s+\d{4})"
        r"\b"
    )

    matches = re.findall(
        pattern,
        text,
        re.IGNORECASE,
    )

    return matches[:5]


# ============================================================
# ACTIVITY TYPE
# ============================================================

def extract_activity_type(text):

    patterns = [

        (
            "Training Course",
            r"\bTraining Course\b",
        ),

        (
            "Partnership-building Activity",
            r"\bPartnership[- ]building Activity\b",
        ),

        (
            "Study Visit",
            r"\bStudy Visit\b",
        ),

        (
            "Youth Exchange",
            r"\bYouth Exchange\b",
        ),

        (
            "Seminar",
            r"\bSeminar\b",
        ),

        (
            "Conference",
            r"\bConference\b",
        ),

        (
            "E-learning",
            r"\bE-learning\b",
        ),
    ]

    for name, pattern in patterns:

        if re.search(
            pattern,
            text,
            re.IGNORECASE,
        ):
            return name

    return "Other"


# ============================================================
# NETHERLANDS ELIGIBILITY
# ============================================================

def is_netherlands_eligible(text):
    """
    Controleer of deelnemers uit Nederland
    kunnen deelnemen.

    Nederland kan expliciet worden genoemd of
    onderdeel zijn van Erasmus+ Youth Programme countries.
    """

    lower = text.lower()

    if "netherlands" in lower:
        return True

    if "erasmus+ youth programme countries" in lower:
        return True

    return False


# ============================================================
# TRAINING LINKS
# ============================================================

def extract_training_links(soup):

    results = []
    seen = set()

    for link in soup.find_all(
        "a",
        href=True,
    ):

        href = link.get(
            "href",
            "",
        ).strip()

        if not href:
            continue

        url = urljoin(
            BASE_URL,
            href,
        )

        if (
            "/tools/european-training-calendar/"
            "training/"
            not in url
        ):
            continue

        if url in seen:
            continue

        title = clean_text(
            link.get_text(
                " ",
                strip=True,
            )
        )

        if not title:
            continue

        seen.add(url)

        results.append({
            "title": title,
            "url": url,
        })

    return results


# ============================================================
# DETAIL PAGE
# ============================================================

def scrape_detail(session, item):

    response = fetch(
        session,
        item["url"],
    )

    if response is None:
        return None

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    text = clean_text(
        soup.get_text(
            " ",
            strip=True,
        )
    )

    deadline = extract_deadline(text)

    deadline_date = parse_date(
        deadline
    )

    dates = extract_dates(text)

    return {
        "title": item["title"],
        "url": item["url"],
        "activity_type": extract_activity_type(text),
        "dates_found": dates,
        "application_deadline": deadline,
        "application_deadline_iso": (
            deadline_date.strftime(
                "%Y-%m-%d"
            )
            if deadline_date
            else None
        ),
        "netherlands_eligible": (
            is_netherlands_eligible(text)
        ),
    }


# ============================================================
# MAIN SCRAPER
# ============================================================

def scrape():

    print("=" * 60)
    print("SALTO-YOUTH SCRAPER")
    print("=" * 60)

    session = create_session()

    print("\nOverzichtspagina ophalen...")

    response = fetch(
        session,
        CALENDAR_URL,
    )

    if response is None:

        raise RuntimeError(
            "SALTO calendar kon niet worden opgehaald."
        )

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    # --------------------------------------------------------
    # PAGE TITLE
    # --------------------------------------------------------

    if soup.title:
        page_title = clean_text(
            soup.title.get_text()
        )
    else:
        page_title = "UNKNOWN"

    print(
        f"Page title: {page_title}"
    )

    # --------------------------------------------------------
    # FIND TRAINING LINKS
    # --------------------------------------------------------

    links = extract_training_links(
        soup
    )

    print(
        f"Training links gevonden: "
        f"{len(links)}"
    )

    if not links:

        Path(
            "debug_salto.html"
        ).write_text(
            response.text,
            encoding="utf-8",
        )

        raise RuntimeError(
            "Geen training links gevonden. "
            "debug_salto.html is opgeslagen."
        )

    print("\nEerste trainingen:")

    for item in links[:10]:

        print(
            f"- {item['title']}"
        )

        print(
            f"  {item['url']}"
        )

    # --------------------------------------------------------
    # PROCESS TRAININGS
    # --------------------------------------------------------

    today = datetime.now(
        timezone.utc
    ).date()

    results = []

    print(
        "\nDetails ophalen..."
    )

    for index, item in enumerate(
        links,
        start=1,
    ):

        print(
            f"\n[{index}/{len(links)}] "
            f"{item['title']}"
        )

        try:

            data = scrape_detail(
                session,
                item,
            )

            if data is None:

                print(
                    "  -> ophalen mislukt"
                )

                continue

            # -----------------------------------------------
            # NETHERLANDS FILTER
            # -----------------------------------------------

            if not data[
                "netherlands_eligible"
            ]:

                print(
                    "  -> niet beschikbaar "
                    "voor Nederland"
                )

                continue

            # -----------------------------------------------
            # DEADLINE FILTER
            # -----------------------------------------------

            deadline_iso = data[
                "application_deadline_iso"
            ]

            if deadline_iso:

                deadline = datetime.strptime(
                    deadline_iso,
                    "%Y-%m-%d",
                ).date()

                if deadline < today:

                    print(
                        "  -> deadline verstreken"
                    )

                    continue

            # -----------------------------------------------
            # SAVE RESULT
            # -----------------------------------------------

            data["scraped_at"] = (
                datetime.now(
                    timezone.utc
                ).isoformat()
            )

            results.append(
                data
            )

            print(
                "  -> TOEGEVOEGD"
            )

        except Exception as exc:

            print(
                "  -> ERROR: "
                f"{type(exc).__name__}: "
                f"{exc}"
            )

        # Kleine pauze tussen requests.
        time.sleep(0.5)

    return results


# ============================================================
# SAVE JSON
# ============================================================

def save_results(results):

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    results.sort(
        key=lambda item: (
            item[
                "application_deadline_iso"
            ]
            or "9999-12-31"
        )
    )

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            results,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print("\n" + "=" * 60)

    print(
        f"{len(results)} trainingen opgeslagen."
    )

    print(
        f"Bestand: {OUTPUT_FILE}"
    )

    print("=" * 60)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    results = scrape()

    save_results(
        results
    )
