def scrape_salto_courses():
    """Schraapt ALLE pagina's van SALTO European Training Calendar zonder paginalimiet."""
    print("Starten met schrapen van SALTO-Youth (alle pagina's)...")
    courses = []
    seen_urls = set()
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    base_url = "https://www.salto-youth.net/tools/european-training-calendar/browse/"
    
    page = 1
    while True:
        params = {"page": page}
        
        try:
            response = requests.get(base_url, headers=HEADERS, params=params, timeout=10)
            if response.status_code != 200:
                print(f"SALTO pagina {page} geeft status code {response.status_code}. Stoppen.")
                break
                
            soup = BeautifulSoup(response.text, "html.parser")
            links = soup.find_all("a", href=re.compile(r"/tools/european-training-calendar/training/"))
            
            page_new_items = 0

            for link in links:
                url = link.get("href", "")
                title = link.get_text(strip=True)
                
                if not url or not title or len(title) < 3:
                    continue

                full_url = "https://www.salto-youth.net" + url if not url.startswith("http") else url
                
                if full_url in seen_urls:
                    continue
                
                seen_urls.add(full_url)
                page_new_items += 1

                parent = link.find_parent(["tr", "div", "li"])
                parent_text = parent.get_text(separator=" ", strip=True) if parent else ""
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

            print(f"SALTO Pagina {page}: {page_new_items} nieuwe projecten gevonden.")

            # Als er geen nieuwe unieke items meer zijn gevonden, is het einde van de lijst bereikt
            if page_new_items == 0:
                print(f"Geen nieuwe items meer op pagina {page}. Alle pagina's doorgezocht.")
                break

            page += 1
            time.sleep(0.5)

        except Exception as e:
            print(f"Fout tijdens schrapen van SALTO pagina {page}: {e}")
            break

    print(f"Totaal aantal SALTO projecten verzameld: {len(courses)}")
    return courses
