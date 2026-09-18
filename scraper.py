import json
import re
import time
from datetime import datetime
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9"
}

def parse_iso_date(date_str):
    """Zet een datum om naar YYYY-MM-DD voor datumsortering en filtering."""
    if not date_str:
        return None
    try:
        clean_str = date_str.strip()
        for fmt in ("%d %B %Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d %b %Y"):
            try:
                return datetime.strptime(clean_str, fmt).strftime("%Y-%m-%d")
            except ValueError:
                pass
    except Exception:
        pass
    return None


def scrape_salto_courses():
    """Schraapt SALTO European Training Calendar specifiek voor Nederlandse deelnemers."""
    print("Starten met schrapen van SALTO-Youth (alleen toegankelijk voor NL)...")
    courses = []
    page = 1
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    base_url = "https://www.salto-youth.net/tools/european-training-calendar/browse/"
    
    while True:
        # Filter expliciet op Nederland als doelgroep/land van herkomst
        params = {
            "page": page,
            "target_group": "NL"
        }
        
        try:
            response = requests.get(base_url, headers=HEADERS, params=params, timeout=15)
            if response.status_code != 200:
                print(f"SALTO pagina {page} gaf statuscode {response.status_code}. Stoppen met pagineren.")
                break
                
            soup = BeautifulSoup(response.text, "html.parser")
            rows = soup.find_all("tr") or soup.find_all("div", class_=re.compile("item|row|card", re.I))
            
            page_items_found = 0

            for row in rows:
                link = row.find("a", href=re.compile(r"/tools/european-training-calendar/training/"))
                if not link:
                    continue

                url = link.get("href", "")
                title = link.get_text(strip=True)
                
                if not title or len(title) < 3:
                    continue

                page_items_found += 1
                full_url = "https://www.salto-youth.net" + url if not url.startswith("http") else url
                row_text = row.get_text(separator=" ", strip=True)

                # Type activiteit bepalen
                activity_type = "training course"
                row_lower = row_text.lower()
                if "youth exchange" in row_lower:
                    activity_type = "youth exchange"
                elif "study visit" in row_lower:
                    activity_type = "study visit"
                elif "partnership" in row_lower:
                    activity_type = "partnership building"

                # Datums en deadlines achterhalen
                date_matches = re.findall(r"\d{1,2}\s+[A-Za-z]+\s+\d{4}|\d{1,2}/\d{1,2}/\d{4}", row_text)
                deadline = "Niet opgegeven"
                dates = "Zie website"

                if len(date_matches) >= 1:
                    deadline = date_matches[0]
                if len(date_matches) >= 3:
                    dates = f"{date_matches[1]} - {date_matches[2]}"
                elif len(date_matches) == 2:
                    dates = date_matches[1]

                deadline_iso = parse_iso_date(deadline)

                # Sla verlopen projecten automatisch over
                if deadline_iso and deadline_iso < today_str:
                    continue

                courses.append({
                    "title": title,
                    "source": "salto",
                    "activity_type": activity_type,
                    "dates": dates,
                    "application_deadline": deadline,
                    "application_deadline_iso": deadline_iso,
                    "url": full_url
                })

            print(f"SALTO Pagina {page}: {page_items_found} NL-projecten verwerkt.")

            if page_items_found == 0:
                print(f"Einde van resultaten bereikt op pagina {page}.")
                break

            page += 1
            time.sleep(1) # Nette pauze tegen overbelasting server

        except Exception as e:
            print(f"Fout tijdens schrapen van SALTO pagina {page}: {e}")
            break

    print(f"Totaal aantal SALTO projecten voor NL verzameld: {len(courses)}")
    return courses


def scrape_otlas_partner_searches():
    """Schraapt Otlas Partner-finding verzoeken."""
    print("Starten met schrapen van Otlas Partner-finding...")
    partner_searches = []
    
    url = "https://www.salto-youth.net/tools/otlas-partner-finding/project/"
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            links = soup.find_all("a", href=re.compile(r"/tools/otlas-partner-finding/project/"))
            
            processed_urls = set()
            for link in links:
                item_url = link.get("href", "")
                title = link.get_text(strip=True)

                if not item_url or item_url in processed_urls or not title or len(title) < 5:
                    continue

                processed_urls.add(item_url)
                full_url = "https://www.salto-youth.net" + item_url if not item_url.startswith("http") else item_url

                parent = link.find_parent(["tr", "div", "li"])
                dates = "Zie projectomschrijving"
                
                if parent:
                    parent_text = parent.get_text(separator=" ", strip=True)
                    date_match = re.search(r"\d{1,2}\s+[A-Za-z]+\s+\d{4}|\b[A-Za-z]+\s+\d{4}\b", parent_text)
                    if date_match:
                        dates = date_match.group(0)

                partner_searches.append({
                    "title": title,
                    "source": "otlas",
                    "activity_type": "partner finding",
                    "dates": dates,
                    "application_deadline": "Zie Otlas",
                    "application_deadline_iso": None,
                    "url": full_url
                })
    except Exception as e:
        print(f"Fout bij ophalen Otlas data: {e}")

    print(f"Totaal aantal Otlas verzoeken verzameld: {len(partner_searches)}")
    return partner_searches


def main():
    salto_data = scrape_salto_courses()
    otlas_data = scrape_otlas_partner_searches()

    combined_data = salto_data + otlas_data
    output_path = "data/salto_courses.json"
    
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(combined_data, f, ensure_ascii=False, indent=2)
        print(f"\nSucces! In totaal {len(combined_data)} resultaten opgeslagen in '{output_path}'.")
    except Exception as e:
        print(f"Fout bij opslaan van het JSON-bestand: {e}")

if __name__ == "__main__":
    main()
