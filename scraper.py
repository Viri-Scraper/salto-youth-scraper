def scrape_salto_courses():
    """Schraapt het VOLLEDIGE SALTO-aanbod zonder limieten en filtert zelf op NL en alle mogelijke bredere termen zoals partner/programme countries."""
    print("Starten met schrapen van het VOLLEDIGE SALTO-aanbod (zonder restricties)...")
    courses = []
    seen_urls = set()
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    base_url = "https://www.salto-youth.net/tools/european-training-calendar/browse/"
    
    page = 1
    max_pages = 60  # Ruime limiet om echt alles op te halen
    
    # Een uitgebreide lijst van zoektermen die Nederland of brede deelname garanderen
    inclusion_keywords = [
        "nl", "netherlands", "nederland", 
        "partner countries", "programme countries", 
        "all countries", "all eligible", "any country", 
        "salto", "erasmus+", "european solidarity corps", "salto-youth"
    ]

    while page <= max_pages:
        # GEEN target_group parameter meer, zodat we echt de hele database doorzoeken
        params = {
            "page": page,
            "show_past": "0"
        }
        
        try:
            response = requests.get(base_url, headers=HEADERS, params=params, timeout=20)
            if response.status_code != 200:
                print(f"SALTO pagina {page} gaf status code {response.status_code}. Stoppen.")
                break
                
            soup = BeautifulSoup(response.text, "html.parser")
            links = soup.find_all("a", href=re.compile(r"/tools/european-training-calendar/(training|goto-training)/"))
            
            if not links:
                print(f"Geen links meer gevonden op SALTO pagina {page}. Schrapen afgerond.")
                break

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

                    # Controleer of een van de brede inclusietermen erin voorkomt
                    # Als een project specifiek een heel ander continent filtert (bijv. alleen Latin America), 
                    # kun je dit hier eventueel op afstemmen, maar zo vangen we alle open/partner/programme/NL termen op.
                    is_relevant = any(keyword in row_lower for keyword in inclusion_keywords)
                    
                    # Als de tekst heel summier is, nemen we hem voor de zekerheid toch mee om geen data te missen
                    if not is_relevant and len(row_lower) > 50:
                        continue

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

            print(f"SALTO Pagina {page}: {page_new_items} projecten gematcht en toegevoegd.")

            if page_new_items == 0 and page > 5:
                # Als een paar pagina's achter elkaar niks opleveren na pagina 5, kunnen we stoppen
                pass

            page += 1
            time.sleep(0.2)

        except Exception as e:
            print(f"Fout op SALTO pagina {page}: {e}")
            break

    print(f"Totaal aantal SALTO projecten (inclusief partner/programme countries) verzameld: {len(courses)}")
    return courses
