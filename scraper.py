import json
import re
import time
from datetime import datetime
import requests
from bs4 import BeautifulSoup

# Headers om te voorkomen dat SALTO de scraper blokkeert
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def parse_iso_date(date_str):
    """Probeert een datumstring veilig om te zetten naar YYYY-MM-DD voor filtering."""
    if not date_str:
        return None
    
    # Probeer bekende datumpatronen van SALTO te matchen (bijv. "15 October 2026" of "15/10/2026")
    try:
        # Verwijder eventuele extra tekst
        clean_str = date_str.strip()
        
        # Voorbeeldconversie voor indelingen zoals "15 October 2026"
        for fmt in ("%d %B %Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(clean_str, fmt).strftime("%Y-%m-%d")
            except ValueError:
                pass
    except Exception:
        pass
    
    return None


def scrape_salto_courses():
    """Schraapt SALTO-Youth European Training Calendar inclusief alle pagina's."""
    print("Starten met schrapen van SALTO-Youth...")
    courses = []
    page = 1
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # Basis URL voor het zoeken (gehouden op minimale parameters om uitsluiting te voorkomen)
    base_url = "https://www.salto-youth.net/tools/european-training-calendar/browse/"
    
    while True:
        # Parameter 'page' zorgt dat we ALLE resultaten ophalen
        params = {
            "page": page
        }
        
        try:
            response = requests.get(base_url, headers=HEADERS, params=params, timeout=15)
            if response.status_code != 200:
                print(f"SALTO pagina {page} gaf statuscode {response.status_code}. Stoppen met pagineren.")
                break
                
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Zoek alle cursus-containers op de pagina
            # Opmerking: Pas eventueel de HTML elementen/classes aan op basis van de exacte SALTO DOM-structuur
            items = soup.find_all("div", class_=re.compile("training-item|calendar-item|list-item"))
            
            # Als er geen items op deze pagina staan, zijn we bij het einde van de zoekresultaten
            if not items:
                print(f"Geen resultaten meer gevonden op SALTO pagina {page}. Paginering voltooid.")
                break
                
            print(f"SALTO Pagina {page}: {len(items)} items gevonden. Verwerken...")
            
            for item in items:
                try:
                    # Titel en URL
                    title_elem = item.find("a", class_=re.compile("title|heading")) or item.find("h3") or item.find("a")
                    if not title_elem:
                        continue
                        
                    title = title_elem.get_text(strip=True)
                    url = title_elem.get("href", "")
                    if url and not url.startswith("http"):
                        url = "https://www.salto-youth.net" + url
                        
                    # Activity type
                    type_elem = item.find(class_=re.compile("type|category"))
                    activity_type = type_elem.get_text(strip=True).lower() if type_elem else "training course"
                    
                    # Datums
                    dates_elem = item.find(class_=re.compile("date|period"))
                    dates = dates_elem.get_text(strip=True) if dates_elem else "Niet opgegeven"
                    
                    # Deadline
                    deadline_elem = item.find(class_=re.compile("deadline"))
                    deadline = deadline_elem.get_text(strip=True) if deadline_elem else "Niet opgegeven"
                    deadline_iso = parse_iso_date(deadline)
                    
                    # Veilige filtering: sla alleen over als de deadline ECHT in het verleden ligt
                    if deadline_iso and deadline_iso < today_str:
                        continue
                        
                    courses.append({
                        "title": title,
                        "source": "salto",  # Koppelbron voor website-filter
                        "activity_type": activity_type,
                        "dates": dates,
                        "application_deadline": deadline,
                        "application_deadline_iso": deadline_iso,
                        "url": url
                    })
                except Exception as e:
                    print(f"Fout bij verwerken van een SALTO item op pagina {page}: {e}")
                    continue
            
            page += 1
            time.sleep(1)  # Nette pauze om SALTO server niet te overbelasten
            
        except Exception as e:
            print(f"Fout bij ophalen SALTO pagina {page}: {e}")
            break
            
    print(f"Totaal aantal geldige SALTO projecten opgehaald: {len(courses)}")
    return courses


def scrape_otlas_partner_searches():
    """Schraapt Otlas Partner-finding verzoeken."""
    print("Starten met schrapen van Otlas Partner-finding...")
    partner_searches = []
    
    # Basis structuur voor Otlas partner zoekopdrachten
    url = "https://www.salto-youth.net/tools/otlas-partner-finding/project/"
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            items = soup.find_all("div", class_=re.compile("project-item|otlas-item|list-item"))
            
            for item in items:
                try:
                    title_elem = item.find("a")
                    if not title_elem:
                        continue
                        
                    title = title_elem.get_text(strip=True)
                    item_url = title_elem.get("href", "")
                    if item_url and not item_url.startswith("http"):
                        item_url = "https://www.salto-youth.net" + item_url
                        
                    dates_elem = item.find(class_=re.compile("date"))
                    dates = dates_elem.get_text(strip=True) if dates_elem else "Zie projectomschrijving"
                    
                    partner_searches.append({
                        "title": title,
                        "source": "otlas",  # Koppelbron voor website-filter
                        "activity_type": "partner finding",
                        "dates": dates,
                        "application_deadline": "N.v.t.",
                        "application_deadline_iso": None,
                        "url": item_url
                    })
                except Exception as e:
                    continue
    except Exception as e:
        print(f"Fout bij ophalen Otlas data: {e}")
        
    print(f"Totaal aantal Otlas verzoeken opgehaald: {len(partner_searches)}")
    return partner_searches


def main():
    # 1. Schraap data van beide bronnen
    salto_data = scrape_salto_courses()
    otlas_data = scrape_otlas_partner_searches()
    
    # 2. Voeg de lijsten samen
    combined_data = salto_data + otlas_data
    
    # 3. Sla op in de JSON map voor GitHub Actions / Website
    output_path = "data/salto_courses.json"
    
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(combined_data, f, ensure_ascii=False, indent=2)
        print(f"Succesvol {len(combined_data)} items opgeslagen in '{output_path}'!")
    except Exception as e:
        print(f"Fout bij opslaan van JSON-bestand: {e}")

if __name__ == "__main__":
    main()
