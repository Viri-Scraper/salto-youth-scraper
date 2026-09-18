import os
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
    """Zet diverse tekstuele datums om naar YYYY-MM-DD voor datumsortering en filtering."""
    if not date_str:
        return None
    try:
        clean_str = date_str.strip()
        for fmt in ("%d %B %Y", "%d %b %Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(clean_str, fmt).strftime("%Y-%m-%d")
            except ValueError:
                pass
    except Exception:
        pass
    return None


def scrape_salto_courses():
    """Schraapt de SALTO European Training Calendar specifiek gefilterd op Nederlandse deelnemers."""
    print("Starten met schrapen van SALTO-aanbod specifiek voor Nederlandse deelnemers...")
    courses = []
    seen_urls = set()
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    base_url = "https://www.salto-youth.net/tools/european-training-calendar/browse/"
    
    page = 1
    while True:
        # target_group='NL' zorgt ervoor dat SALTO alleen projecten toont waar NL deelnemers welkom zijn
        params = {
            "page": page,
            "show_past": "0",
            "target_group": "NL"
        }
        
        try:
            response = requests.get(base_url, headers=HEADERS, params=params, timeout=15)
            if response.status_code != 200:
                print(f"SALTO pagina {page} geeft status code {response.status_code}. Stoppen.")
                break
                
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Alle training/exchange links op de pagina ophalen
            links = soup.find_all("a", href=re.compile(r"/tools/european-training-calendar/(training|goto-training)/"))
            
            page_new_items = 0

            for link in links:
                try:
                    title = link.get_text(strip=True)
                    url = link.get("href", "")
                    
                    if not title or len(title) < 3 or not url:
                        continue
                        
                    full_url = "https://www.salto-youth.net" + url if not url.startswith("http") else url
                    
                    if full_url in seen_urls:
                        continue
                    seen_urls.add(full_url)

                    parent = link.find_parent(["tr", "div", "li"])
                    parent_text = parent.get_text(separator=" ", strip=True) if parent else title
                    row_lower = parent_text.lower()

                    activity_type = "training course"
                    if "youth exchange" in row_lower:
                        activity_type = "youth exchange"
                    elif "study visit" in row_lower:
                        activity_type = "study visit"
                    elif "partnership" in row_lower:
                        activity_type = "partnership building"

                    date_matches = re.findall(r"\d{1,2}\s+[A-Za-z]+\s+\d{4}|\d{1,2}/\d{1,2}/\d{4}", parent_text)
                    deadline = "Niet opgegeven"
                    dates = "Zie website"

                    if len(date_matches) >= 1:
                        deadline = date_matches[0]
                    if len(date_matches) >= 3:
                        dates = f"{date_matches[1]} - {date_matches[2]}"
                    elif len(date_matches) == 2:
                        dates = date_matches[1]

                    deadline_iso = parse_iso_date(deadline)

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
                    page_new_items += 1
                except Exception:
                    continue

            print(f"SALTO Pagina {page}: {page_new_items} nieuwe unieke projecten voor NL verwerkt.")

            if page_new_items == 0:
                print(f"Geen nieuwe projecten meer gevonden op pagina {page}. Schrapen afgerond.")
                break

            page += 1
            time.sleep(0.3)

        except Exception as e:
            print(f"Fout tijdens schrapen van SALTO pagina {page}: {e}")
            break

    print(f"Totaal aantal SALTO projecten voor NL verzameld: {len(courses)}")
    return courses


def scrape_otlas_partner_searches():
    """Schraapt Otlas Partner-finding verzoeken."""
    print("Starten met schrapen van Otlas Partner-finding...")
    partner_searches = []
    seen_urls = set()
    
    url = "https://www.salto-youth.net/tools/otlas-partner-finding/project/"
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            links = soup.find_all("a", href=re.compile(r"/tools/otlas-partner-finding/project/"))
            
            for link in links:
                try:
                    title = link.get_text(strip=True)
                    item_url = link.get("href", "")
                    
                    if not item_url or not title or len(title) < 3:
                        continue
                        
                    full_url = "https://www.salto-youth.net" + item_url if not item_url.startswith("http") else item_url

                    if full_url in seen_urls:
                        continue
                    seen_urls.add(full_url)

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
                except Exception:
                    continue
    except Exception as e:
        print(f"Fout bij ophalen Otlas data: {e}")

    print(f"Totaal aantal Otlas verzoeken verzameld: {len(partner_searches)}")
    return partner_searches


def main():
    salto_data = scrape_salto_courses()
    otlas_data = scrape_otlas_partner_searches()

    combined_data = salto_data + otlas_data
    
    # Gebruik het absolute pad van dit script om gegarandeerd 'data/salto_courses.json' aan te maken
    script_dir = os.path.dirname(os.path.abspath(__file__))
    target_dir = os.path.join(script_dir, "data")
    os.makedirs(target_dir, exist_ok=True)
    
    output_path = os.path.join(target_dir, "salto_courses.json")
    print(f"\n[OPSLAGPAD] Bestand wordt geschreven naar: {output_path}")
    
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(combined_data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
            
        print(f"Succes! In totaal {len(combined_data)} resultaten opgeslagen in '{output_path}'.")
    except Exception as e:
        print(f"Fout bij opslaan van het JSON-bestand: {e}")


if __name__ == "__main__":
    main()
