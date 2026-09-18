import requests
import re
import json
import time
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urljoin, urlparse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ============================================================
# CONFIG
# ============================================================

SALTO_BASE = "https://www.salto-youth.net"
SALTO_BROWSE = (
    "https://www.salto-youth.net/"
    "tools/european-training-calendar/browse/"
)

OTLAS_BROWSE = (
    "https://www.salto-youth.net/"
    "tools/otlas-partner-finding/projects/"
)

OUTPUT_FILE = "data/salto_courses.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/153.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,nl;q=0.8",
}

# Kleine pauze om de servers niet onnodig zwaar te belasten.
REQUEST_DELAY = 0.35

# Als True: project zonder deadline blijft staan.
# Je kunt dit later op False zetten als je uitsluitend
# projecten met een expliciete toekomstige deadline wilt.
KEEP_WITHOUT_DEADLINE = True


# ============================================================
# SESSION MET RETRIES
# ============================================================

def create_session():
    session = requests.Session()

    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )

    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=10,
        pool_maxsize=10,
    )

    session.mount("https://", adapter)
    session.mount("http://", adapter)

    session.headers.update(HEADERS)

    return session


session = create_session()


# ============================================================
# DATUM FUNCTIES
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


def normalize_text(text):
    if not text:
        return ""

    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def parse_date_string(value):
    """
    Probeert zoveel mogelijk datumformaten van SALTO/OTLAS
    te herkennen.

    Geeft YYYY-MM-DD terug.
    """

    if not value:
        return None

    value = normalize_text(value)

    # ISO
    match = re.search(
        r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b",
        value
    )

    if match:
        try:
            year, month, day = map(int, match.groups())
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # 18 September 2026
    match = re.search(
        r"\b(\d{1,2})\s+"
        r"(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)"
        r"\s+(20\d{2})\b",
        value,
        re.IGNORECASE,
    )

    if match:
        day = int(match.group(1))
        month = MONTHS[match.group(2).lower()]
        year = int(match.group(3))

        try:
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # 18/09/2026
    match = re.search(
        r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b",
        value
    )

    if match:
        day, month, year = map(int, match.groups())

        try:
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # 18-09-2026
    match = re.search(
        r"\b(\d{1,2})-(\d{1,2})-(20\d{2})\b",
        value
    )

    if match:
        day, month, year = map(int, match.groups())

        try:
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return None


def extract_dates(text):
    """
    Haalt zoveel mogelijk datumstrings uit een pagina.
    """

    if not text:
        return []

    patterns = [
        r"\b\d{1,2}\s+"
        r"(?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December)"
        r"\s+20\d{2}\b",

        r"\b\d{1,2}/\d{1,2}/20\d{2}\b",

        r"\b\d{1,2}-\d{1,2}-20\d{2}\b",

        r"\b20\d{2}-\d{1,2}-\d{1,2}\b",
    ]

    results = []

    for pattern in patterns:
        matches = re.findall(
            pattern,
            text,
            flags=re.IGNORECASE
        )

        for match in matches:
            if match not in results:
                results.append(match)

    return results


# ============================================================
# DEADLINE DETECTIE
# ============================================================

DEADLINE_LABELS = [
    "application deadline",
    "deadline for application",
    "application closes",
    "applications close",
    "applications are closed",
    "deadline",
    "partner request deadline",
    "partner request",
    "deadline for this partner request",
    "last day to apply",
    "apply by",
]


def extract_deadline(soup, text):
    """
    Probeert eerst expliciete deadlinevelden te vinden.
    """

    lower_text = text.lower()

    # Zoek in HTML-elementen rond deadline-termen
    for element in soup.find_all(
        ["p", "div", "li", "td", "th", "span", "strong"]
    ):

        element_text = normalize_text(
            element.get_text(" ", strip=True)
        )

        if not element_text:
            continue

        element_lower = element_text.lower()

        if any(label in element_lower for label in DEADLINE_LABELS):

            dates = extract_dates(element_text)

            if dates:
                iso = parse_date_string(dates[0])

                if iso:
                    return dates[0], iso

    # Fallback: zoek deadline en vervolgens een datum
    for label in DEADLINE_LABELS:

        pattern = (
            re.escape(label)
            + r".{0,150}?"
            + r"(\d{1,2}\s+"
              r"(?:January|February|March|April|May|June|July|August|"
              r"September|October|November|December)"
              r"\s+20\d{2}"
              r"|\d{1,2}/\d{1,2}/20\d{2}"
              r"|\d{1,2}-\d{1,2}-20\d{2}"
              r"|20\d{2}-\d{1,2}-\d{1,2})"
        )

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE | re.DOTALL
        )

        if match:
            raw = match.group(1)
            iso = parse_date_string(raw)

            if iso:
                return raw, iso

    return None, None


# ============================================================
# DATUM / PROJECT PERIODE
# ============================================================

def extract_project_dates(text):
    dates = extract_dates(text)

    parsed = []

    for date in dates:
        iso = parse_date_string(date)

        if iso and iso not in parsed:
            parsed.append(iso)

    return parsed


# ============================================================
# NEDERLANDSE ELIGIBILITY
# ============================================================

POSITIVE_PATTERNS = [

    # Direct Nederland
    r"\bnetherlands\b",
    r"\bdutch\b",
    r"\bnederland\b",

    # Programma's
    r"erasmus\+ youth programme countries",
    r"erasmus\+ programme countries",
    r"erasmus\+ program countries",
    r"programme countries",
    r"program countries",

    # EU
    r"eu member states",
    r"eu member state",
    r"european union member states",
    r"all eu countries",

    # Breed
    r"all countries",
    r"all eligible countries",
    r"any country",
    r"participants from all",
    r"open to all",
    r"open for all",

    # Partnerlanden
    r"partner countries",
    r"neighbouring partner countries",
    r"partner countries neighbouring the eu",
]


NEGATIVE_PATTERNS = [

    # Expliciet uitgesloten
    r"excluding netherlands",
    r"excluding dutch participants",
    r"not open to netherlands",
    r"not available for netherlands",
    r"netherlands.*not eligible",
    r"dutch participants.*not eligible",
    r"participants from.*not including.*netherlands",
]


def determine_netherlands_eligibility(text):
    """
    Probeert zo conservatief mogelijk te bepalen of Nederland
    toegestaan is.

    Return:
        True
        False
        None = onbekend
    """

    lower = normalize_text(text).lower()

    # Eerst expliciete uitsluiting controleren.
    for pattern in NEGATIVE_PATTERNS:
        if re.search(pattern, lower):
            return False

    # Daarna expliciete positieve aanwijzingen.
    for pattern in POSITIVE_PATTERNS:
        if re.search(pattern, lower):
            return True

    return None


# ============================================================
# CATEGORIE NORMALISATIE
# ============================================================

CATEGORY_RULES = [

    (
        "youth_exchange",
        [
            "youth exchange",
            "youth exchanges",
            "ka152",
            "ka 152",
        ],
    ),

    (
        "training_course",
        [
            "training course",
            "training courses",
            "ka153",
            "ka 153",
        ],
    ),

    (
        "seminar",
        [
            "seminar",
            "seminars",
        ],
    ),

    (
        "study_visit",
        [
            "study visit",
            "study visits",
        ],
    ),

    (
        "partnership_building",
        [
            "partnership-building activity",
            "partnership building activity",
            "partnership-building",
            "partnership building",
            "pba",
        ],
    ),

    (
        "training_and_networking",
        [
            "training and networking",
            "training & networking",
            "ka153",
        ],
    ),

    (
        "strategic_partnership",
        [
            "strategic partnership",
            "strategic partnerships",
            "ka2",
            "ka 2",
            "ka220",
            "ka 210",
        ],
    ),

    (
        "capacity_building",
        [
            "capacity building",
            "capacity-building",
        ],
    ),

    (
        "transnational_youth_initiative",
        [
            "transnational youth initiative",
            "transnational youth initiatives",
        ],
    ),

    (
        "volunteering",
        [
            "volunteering",
            "volunteer activities",
            "volunteering activities",
            "evs",
            "european solidarity corps",
        ],
    ),

    (
        "meetings_young_people_decision_makers",
        [
            "meetings between young people and decision-makers",
            "young people and decision-makers",
        ],
    ),

    (
        "e_learning",
        [
            "e-learning",
            "elearning",
            "online training",
        ],
    ),

    (
        "conference",
        [
            "conference",
            "symposium",
            "forum",
        ],
    ),

    (
        "other",
        [],
    ),
]


def normalize_category(activity_text, page_text=""):
    combined = (
        normalize_text(activity_text)
        + " "
        + normalize_text(page_text)
    ).lower()

    for category, keywords in CATEGORY_RULES:

        for keyword in keywords:
            if keyword in combined:
                return category

    return "other"


# ============================================================
# PAGINA OPHALEN
# ============================================================

def get_page(url):
    try:

        response = session.get(
            url,
            timeout=30
        )

        if response.status_code != 200:
            print(
                f"HTTP {response.status_code}: {url}"
            )
            return None

        time.sleep(REQUEST_DELAY)

        return response.text

    except requests.RequestException as e:

        print(
            f"Request fout bij {url}: {e}"
        )

        return None


# ============================================================
# SALTO URL DISCOVERY
# ============================================================

def discover_salto_urls():
    """
    Geen max_pages.

    We blijven pagina's proberen totdat:
    - SALTO geen links meer geeft
    - dezelfde pagina opnieuw verschijnt
    """

    print("\n" + "=" * 70)
    print("SALTO URL DISCOVERY")
    print("=" * 70)

    discovered = set()

    page = 1

    previous_signature = None

    while True:

        url = f"{SALTO_BROWSE}?page={page}"

        print(
            f"SALTO browse pagina {page}..."
        )

        html = get_page(url)

        if not html:
            break

        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        page_urls = set()

        for link in soup.find_all("a", href=True):

            href = link.get("href", "")

            full_url = urljoin(
                SALTO_BASE,
                href
            )

            if "/tools/european-training-calendar/" not in full_url:
                continue

            # Alleen individuele activity pages
            if (
                "/training/" in full_url
                or "/goto-training/" in full_url
            ):
                page_urls.add(
                    full_url.split("#")[0]
                )

        if not page_urls:

            print(
                "Geen SALTO-projectlinks meer gevonden."
            )

            break

        signature = tuple(
            sorted(page_urls)
        )

        if signature == previous_signature:

            print(
                "SALTO gaf dezelfde pagina opnieuw. "
                "Discovery gestopt."
            )

            break

        previous_signature = signature

        new_urls = page_urls - discovered

        discovered.update(page_urls)

        print(
            f"  {len(page_urls)} projecten "
            f"gevonden, {len(new_urls)} nieuw."
        )

        if not new_urls:

            print(
                "Geen nieuwe SALTO-projecten meer."
            )

            break

        page += 1

    print(
        f"\nSALTO totaal unieke URL's: "
        f"{len(discovered)}"
    )

    return discovered


# ============================================================
# OTLAS URL DISCOVERY
# ============================================================

def discover_otlas_urls():
    """
    Geen max_pages.

    OTLAS bevat zeer veel projecten.
    We blijven pagination volgen totdat er geen nieuwe
    projectlinks meer gevonden worden.
    """

    print("\n" + "=" * 70)
    print("OTLAS URL DISCOVERY")
    print("=" * 70)

    discovered = set()

    page = 1

    previous_signature = None

    while True:

        url = f"{OTLAS_BROWSE}?page={page}"

        print(
            f"OTLAS browse pagina {page}..."
        )

        html = get_page(url)

        if not html:
            break

        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        page_urls = set()

        for link in soup.find_all("a", href=True):

            href = link.get("href", "")

            full_url = urljoin(
                SALTO_BASE,
                href
            )

            if "/tools/otlas-partner-finding/project/" not in full_url:
                continue

            page_urls.add(
                full_url.split("#")[0]
            )

        if not page_urls:

            print(
                "Geen OTLAS-projectlinks meer gevonden."
            )

            break

        signature = tuple(
            sorted(page_urls)
        )

        if signature == previous_signature:

            print(
                "OTLAS gaf dezelfde pagina opnieuw."
            )

            break

        previous_signature = signature

        new_urls = page_urls - discovered

        discovered.update(page_urls)

        print(
            f"  {len(page_urls)} projecten "
            f"gevonden, {len(new_urls)} nieuw."
        )

        if not new_urls:

            print(
                "Geen nieuwe OTLAS-projecten meer."
            )

            break

        page += 1

    print(
        f"\nOTLAS totaal unieke URL's: "
        f"{len(discovered)}"
    )

    return discovered


# ============================================================
# TITEL
# ============================================================

def extract_title(soup):

    # Eerst H1
    h1 = soup.find("h1")

    if h1:
        title = normalize_text(
            h1.get_text(" ", strip=True)
        )

        if title:
            return title

    # Daarna title tag
    if soup.title:

        title = normalize_text(
            soup.title.get_text(
                " ",
                strip=True
            )
        )

        title = re.sub(
            r"\s*[-|]\s*SALTO.*$",
            "",
            title,
            flags=re.IGNORECASE
        )

        return title.strip()

    return "Onbekend project"


# ============================================================
# SALTO DETAILPAGINA
# ============================================================

def scrape_salto_detail(url):
    html = get_page(url)

    if not html:
        return None

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    text = normalize_text(
        soup.get_text(" ", strip=True)
    )

    title = extract_title(soup)

    # Activity type proberen te vinden
    activity_type = ""

    # Zoek labels rondom bekende SALTO types
    known_types = [
        "Study Visit",
        "Partnership-building Activity",
        "Seminar",
        "Training Course",
        "E-learning",
        "Conference – Symposium - Forum",
        "Conference - Symposium - Forum",
        "Youth Exchange",
        "Training and Networking",
    ]

    lower_text = text.lower()

    for candidate in known_types:

        if candidate.lower() in lower_text:

            activity_type = candidate

            break

    category = normalize_category(
        activity_type,
        text
    )

    deadline, deadline_iso = extract_deadline(
        soup,
        text
    )

    dates = extract_project_dates(text)

    netherlands_eligible = (
        determine_netherlands_eligibility(text)
    )

    # SALTO gebruikt expliciet "This activity is for
    # participants from". Dit is een sterke aanwijzing.
    participant_section = ""

    match = re.search(
        r"This activity is for participants from(.{0,5000})",
        text,
        flags=re.IGNORECASE
    )

    if match:

        participant_section = match.group(1)

        section_eligibility = (
            determine_netherlands_eligibility(
                participant_section
            )
        )

        if section_eligibility is not None:

            netherlands_eligible = (
                section_eligibility
            )

    # Als Nederland niet expliciet genoemd wordt maar
    # de pagina duidelijk een brede programme-country
    # doelgroep heeft, mag hij door.
    if netherlands_eligible is None:

        broad_programme_patterns = [
            "erasmus+ youth programme countries",
            "erasmus+ programme countries",
            "programme countries",
        ]

        if any(
            p in lower_text
            for p in broad_programme_patterns
        ):
            netherlands_eligible = True

    return {
        "title": title,
        "source": "salto",
        "category": category,
        "activity_type": activity_type,
        "dates_found": dates,
        "application_deadline": deadline or "Niet opgegeven",
        "application_deadline_iso": deadline_iso,
        "netherlands_eligible": (
            netherlands_eligible is True
        ),
        "eligibility_status": (
            "eligible"
            if netherlands_eligible is True
            else "not_eligible"
            if netherlands_eligible is False
            else "unknown"
        ),
        "url": url,
    }


# ============================================================
# OTLAS DETAILPAGINA
# ============================================================

def scrape_otlas_detail(url):
    html = get_page(url)

    if not html:
        return None

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    text = normalize_text(
        soup.get_text(" ", strip=True)
    )

    title = extract_title(soup)

    lower_text = text.lower()

    # OTLAS gebruikt verschillende termen.
    activity_type = ""

    otlas_types = [
        "Youth Exchanges",
        "Volunteering Activities",
        "Training and Networking",
        "Transnational Youth Initiatives",
        "Strategic Partnerships",
        "Capacity Building",
        "Meetings between young people and decision-makers",
        "Training course",
        "Training Course",
        "Seminar",
        "Study visit",
        "Study Visit",
        "Partnership-building activity",
        "Partnership Building Activity",
        "E-learning",
    ]

    for candidate in otlas_types:

        if candidate.lower() in lower_text:

            activity_type = candidate

            break

    category = normalize_category(
        activity_type,
        text
    )

    deadline, deadline_iso = extract_deadline(
        soup,
        text
    )

    dates = extract_project_dates(text)

    netherlands_eligible = (
        determine_netherlands_eligibility(
            text
        )
    )

    # OTLAS kan bijvoorbeeld aangeven:
    #
    # "All Erasmus+ Programme countries"
    #
    # Dit moet Nederland toelaten.
    if netherlands_eligible is None:

        broad_patterns = [
            "all erasmus+ programme countries",
            "all programme countries",
            "erasmus+ programme countries",
            "programme countries",
            "all eu countries",
            "all countries",
        ]

        if any(
            p in lower_text
            for p in broad_patterns
        ):
            netherlands_eligible = True

    return {
        "title": title,
        "source": "otlas",
        "category": category,
        "activity_type": activity_type,
        "dates_found": dates,
        "application_deadline": deadline or "Niet opgegeven",
        "application_deadline_iso": deadline_iso,
        "netherlands_eligible": (
            netherlands_eligible is True
        ),
        "eligibility_status": (
            "eligible"
            if netherlands_eligible is True
            else "not_eligible"
            if netherlands_eligible is False
            else "unknown"
        ),
        "url": url,
    }


# ============================================================
# DEADLINE FILTER
# ============================================================

def deadline_is_valid(course):
    """
    Verwijdert projecten waarvan de deadline verstreken is.
    """

    deadline = course.get(
        "application_deadline_iso"
    )

    if not deadline:

        return KEEP_WITHOUT_DEADLINE

    today = datetime.now().strftime(
        "%Y-%m-%d"
    )

    return deadline >= today


# ============================================================
# HOOFDFUNCTIE
# ============================================================

def scrape_all_projects():
    print("\n")
    print("=" * 70)
    print("SALTO + OTLAS COMPLETE SCRAPER")
    print("=" * 70)

    # --------------------------------------------------------
    # 1. URL'S VERZAMELEN
    # --------------------------------------------------------

    salto_urls = discover_salto_urls()

    otlas_urls = discover_otlas_urls()

    print("\n")
    print(
        f"SALTO URL's : {len(salto_urls)}"
    )

    print(
        f"OTLAS URL's : {len(otlas_urls)}"
    )

    # --------------------------------------------------------
    # 2. DETAILPAGINA'S SCRAPEN
    # --------------------------------------------------------

    courses = []

    total = (
        len(salto_urls)
        + len(otlas_urls)
    )

    current = 0

    # --------------------------------------------------------
    # SALTO
    # --------------------------------------------------------

    for url in sorted(salto_urls):

        current += 1

        print(
            f"[{current}/{total}] SALTO: {url}"
        )

        try:

            project = scrape_salto_detail(
                url
            )

            if not project:
                continue

            # Alleen Nederlandse deelnemers
            if not project[
                "netherlands_eligible"
            ]:
                continue

            # Deadline verlopen?
            if not deadline_is_valid(
                project
            ):
                print(
                    "  -> VERLOPEN DEADLINE"
                )
                continue

            courses.append(project)

        except Exception as e:

            print(
                f"  -> fout: {e}"
            )

    # --------------------------------------------------------
    # OTLAS
    # --------------------------------------------------------

    for url in sorted(otlas_urls):

        current += 1

        print(
            f"[{current}/{total}] OTLAS: {url}"
        )

        try:

            project = scrape_otlas_detail(
                url
            )

            if not project:
                continue

            # Nederlandse organisatie moet kunnen deelnemen
            if not project[
                "netherlands_eligible"
            ]:
                continue

            # Deadline verlopen?
            if not deadline_is_valid(
                project
            ):
                print(
                    "  -> VERLOPEN DEADLINE"
                )
                continue

            courses.append(project)

        except Exception as e:

            print(
                f"  -> fout: {e}"
            )

    # --------------------------------------------------------
    # 3. DUBBELE PROJECTEN VERWIJDEREN
    # --------------------------------------------------------

    unique = {}

    for project in courses:

        url = project.get("url")

        if url:
            unique[url] = project

    courses = list(unique.values())

    # --------------------------------------------------------
    # 4. SORTEREN
    # --------------------------------------------------------

    courses.sort(
        key=lambda x: (
            x.get(
                "application_deadline_iso"
            ) or "9999-12-31"
        )
    )

    # --------------------------------------------------------
    # 5. JSON SCHRIJVEN
    # --------------------------------------------------------

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            courses,
            f,
            ensure_ascii=False,
            indent=2
        )

    # --------------------------------------------------------
    # 6. STATISTIEKEN
    # --------------------------------------------------------

    print("\n")
    print("=" * 70)
    print("SCRAPING KLAAR")
    print("=" * 70)

    print(
        f"Totaal Nederlandse projecten: "
        f"{len(courses)}"
    )

    print(
        f"JSON opgeslagen als: "
        f"{OUTPUT_FILE}"
    )

    # Categorieën
    categories = {}

    for course in courses:

        category = course.get(
            "category",
            "other"
        )

        categories[category] = (
            categories.get(category, 0) + 1
        )

    print("\nCategorieën:")

    for category, count in sorted(
        categories.items()
    ):

        print(
            f"  {category}: {count}"
        )

    # Bronnen
    sources = {}

    for course in courses:

        source = course.get(
            "source",
            "unknown"
        )

        sources[source] = (
            sources.get(source, 0) + 1
        )

    print("\nBronnen:")

    for source, count in sources.items():

        print(
            f"  {source}: {count}"
        )

    return courses


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    scrape_all_projects()
