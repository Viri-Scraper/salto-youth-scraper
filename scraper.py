import json
import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.salto-youth.net"
CALENDAR_URL = "https://www.salto-youth.net/tools/european-training-calendar/browse/"


def create_session():
    session = requests.Session()

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9,nl;q=0.8",
        "Referer": BASE_URL + "/",
    })

    return session


def get_page(session, url, params=None):
    print(f"\nGET {url}")

    try:
        response = session.get(
            url,
            params=params,
            timeout=20,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        print(f"REQUEST ERROR: {exc}")
        return None

    print(f"HTTP: {response.status_code}")
    print(f"Final URL: {response.url}")
    print(f"Content-Type: {response.headers.get('content-type')}")
    print(f"Response length: {len(response.text)} bytes")

    if response.status_code != 200:
        print(response.text[:500])
        return None

    return response


def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_date(value):
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

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass

    return None


def extract_deadline(text):
    """
    Zoek bijvoorbeeld:

    Application deadline (24h UTC):
    30 August 2026
    """

    pattern = (
        r"Application\s+deadline"
        r"(?:\s*\([^)]*\))?"
        r"\s*:?\s*"
        r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})"
    )

    match = re.search(pattern, text, re.IGNORECASE)

    if not match:
        return None

    return clean_text(match.group(1))


def extract_country_eligibility(text):
    """
    SALTO toont vaak tekst zoals:

    This activity is for participants from
    ...
    Netherlands
    ...
    """

    lower = text.lower()

    # Expliciet Nederland gevonden.
    if "netherlands" in lower:
        return True

    # Deze groepen bevatten Nederland volgens SALTO.
    if "erasmus+ youth programme countries" in lower:
        return True

    return False


def categorize(title, text):
    combined = f"{title} {text}".lower()

    if "youth exchange" in combined:
        return "Youth Exchange"

    if "partnership-building activity" in combined:
        return "Partnership Building Activity (PBA)"

    if "training course" in combined:
        return "Training Course"

    if "seminar" in combined:
        return "Seminar"

    if "conference" in combined:
        return "Conference"

    if "study visit" in combined:
        return "Study Visit"

    if "e-learning" in combined:
        return "E-learning"

    return "Other"


def extract_training_links(soup):
    """
    Zoek alle links naar SALTO training detailpagina's.

    We gebruiken urljoin() zodat zowel relatieve als absolute
    URLs correct worden verwerkt.
    """

    results = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = link["href"].strip()

        absolute_url = urljoin(BASE_URL, href)

        if "/tools/european-training-calendar/training/" not in absolute_url:
            continue

        if absolute_url in seen:
            continue

        seen.add(absolute_url)

        title = clean_text(link.get_text(" ", strip=True))

        if not title:
            continue

        results.append({
            "title": title,
            "url": absolute_url,
        })

    return results


def scrape_training_page(session, item):
    response = get_page(session, item["url"])

    if response is None:
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    text = clean_text(soup.get_text(" ", strip=True))

    deadline = extract_deadline(text)
    deadline_date = parse_date(deadline)

    eligible = extract_country_eligibility(text)

    return {
        "title": item["title"],
        "url": item["url"],
        "category": categorize(item["title"], text),
        "deadline": deadline,
        "deadline_iso": (
            deadline_date.strftime("%Y-%m-%d")
            if deadline_date
            else None
        ),
        "netherlands_eligible": eligible,
        "scraped_at": datetime.now().isoformat(timespec="seconds"),
    }


def scrape_salto():
    session = create_session()

    print("=" * 60)
    print("SALTO-YOUTH SCRAPER")
    print("=" * 60)

    # Eerst bewust GEEN filters.
    #
    # Dit is belangrijk:
    # we willen eerst bewijzen dat de basispagina werkt.
    response = get_page(session, CALENDAR_URL)

    if response is None:
        print("\nKON DE SALTO-PAGINA NIET OPHALEN.")
        return []

    soup = BeautifulSoup(response.text, "html.parser")

    print("\nHTML geladen.")
    print(f"Page title: {clean_text(soup.title.get_text()) if soup.title else 'UNKNOWN'}")

    links = extract_training_links(soup)

    print(f"\nTraining links gevonden: {len(links)}")

    if not links:
        print("\nGEEN TRAINING LINKS GEVONDEN.")
        print("De eerste 2000 tekens van de HTML:")
        print(response.text[:2000])

        # HTML opslaan zodat we exact kunnen inspecteren wat SALTO terugstuurt.
        with open("debug_salto.html", "w", encoding="utf-8") as file:
            file.write(response.text)

        print("\nHTML opgeslagen als: debug_salto.html")
        return []

    print("\nEerste gevonden trainingen:")

    for item in links[:10]:
        print(f"- {item['title']}")
        print(f"  {item['url']}")

    results = []

    today = datetime.now().replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    print("\nDetails ophalen...\n")

    for index, item in enumerate(links, start=1):

        print(f"[{index}/{len(links)}] {item['title']}")

        try:
            data = scrape_training_page(session, item)

            if not data:
                continue

            if not data["netherlands_eligible"]:
                print("  -> Niet voor Nederland")
                continue

            if data["deadline_iso"]:
                deadline_date = datetime.strptime(
                    data["deadline_iso"],
                    "%Y-%m-%d",
                )

                if deadline_date < today:
                    print("  -> Deadline verstreken")
                    continue

            print("  -> TOEGEVOEGD")

            results.append(data)

        except Exception as exc:
            print(f"  -> FOUT: {type(exc).__name__}: {exc}")

    return results


def save_json(data):
    filename = "salto_courses.json"

    with open(filename, "w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print(f"\nOpgeslagen: {filename}")
    print(f"Aantal resultaten: {len(data)}")


if __name__ == "__main__":
    try:
        courses = scrape_salto()
        save_json(courses)

    except KeyboardInterrupt:
        print("\nGestopt door gebruiker.")

    except Exception as exc:
        print("\nKRIITIEKE FOUT")
        print(f"{type(exc).__name__}: {exc}")

        raise
