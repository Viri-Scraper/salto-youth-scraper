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
    """Zet tekstuele datums om naar YYYY-MM-DD voor datumsortering en filtering."""
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
    """Schraapt SALTO European Training Calendar."""
    print("Starten met schrapen van SALTO-Youth...")
    courses = []
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    base_url = "https://www.salto-youth.net/tools/european-training-calendar/browse/"
    
    page = 1
    while True:
        params = {
            "page": page,
            "target_group": "NL"
        }
        
        try:
            response = requests.get(base_url, headers=HEADERS, params=params, timeout=15)
            if response.status_code != 200:
                print(f"SALTO pagina {page} geeft status code {response.status_code}. Stoppen.")
                break
                
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Zoek ruime elementen (containers/rijen)
            items = soup.find_all("div", class_=re.compile("training-item|calendar-item|list-item|item")) or soup.find_all("tr")
            
            if not items:
                print(f"Geen items meer gevonden op pagina {page}.")
                break
                
            page_items_count = 0

            for item in items:
                try:
                    title_elem = item.find("a", class_=re.compile("title|heading")) or item.find("h3") or item.find("a")
                    if not title_elem:
                        continue
                        
                    title = title_elem.get_text(strip=True)
                    url = title_elem.get("href", "")
                    
                    if not title or len(title) < 3 or not url:
                        continue
                        
                    full_url = "https://www.salto-youth.net" + url if not url.startswith("http") else url
                    
                    item_text = item.get_text(separator=" ", strip=True)
                    row_lower = item_text.lower()

                    activity_type = "training course"
                    if "youth exchange" in row_lower:
                        activity_type = "youth exchange"
                    elif "study visit" in row_lower:
                        activity_type = "study visit"
                    elif "partnership" in row_lower:
                        activity_type = "partnership building"

                    date_matches = re.findall(r"\d{1,2}\s+[A-Za-z]+\s+\d{4}|\d{1,2}/\d{1,2}/\d{4}", item_text)
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
                    page_items_count += 1
                except Exception as e:
                    # Zorg dat één kapot item het script niet laat crashen
                    continue

            print(f"SALTO Pagina {page}: {page_items_count} projecten verwerkt.")

            if page_items_count == 0:
                break

            page += 1
            time.sleep(0.5)

        except Exception as e:
            print(f"Fout tijdens schrapen van SALTO pagina {page}: {e}")
            break

    print(f"Totaal aantal SALTO projecten verzameld: {len(courses)}")
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
            items = soup.find_all("div", class_=re.compile("project-item|otlas-item|list-item|item")) or soup.find_all("tr")
            
            for item in items:
                try:
                    title_elem = item.find("a")
                    if not title_elem:
                        continue
                        
                    title = title_elem.get_text(strip=True)
                    item_url = title_elem.get("href", "")
                    
                    if not item_url or not title or len(title) < 5:
                        continue
                        
                    full_url = "https://www.salto-youth.net" + item_url if not item_url.startswith("http") else item_url

                    item_text = item.get_text(separator=" ", strip=True)
                    date_match = re.search(r"\d{1,2}\s+[A-Za-z]+\s+\d{4}|\b[A-Za-z]+\s+\d{4}\b", item_text)
                    dates = date_match.group(0) if date_match else "Zie projectomschrijving"

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
    
    # 1. Zorg dat de map 'data/' altijd bestaat (voorkomt FileNotFoundError / exit code 1)
    os.makedirs("data", exist_ok=True)
    output_path = os.path.join("data", "salto_courses.json")
    
    # 2. Sla het bestand op
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(combined_data, f, ensure_ascii=False, indent=2)
        print(f"\nSucces! In totaal {len(combined_data)} resultaten opgeslagen in '{output_path}'.")
    except Exception as e:
        print(f"Fout bij opslaan van het JSON-bestand: {e}")
        exit(1)

if __name__ == "__main__":
    main()
