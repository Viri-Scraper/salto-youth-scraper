# ============================================================
# 1. TRAINING CALENDAR (Alle types, alleen NL-geschikt)
# ============================================================

def build_training_search_url(offset=0, limit=20):
    """
    Haalt álle soorten activiteiten op (trainingen, seminars, PBA's, study visits)
    waarbij Nederlanders mogen deelnemen.
    """
    now = datetime.now()
    params = {
        "b_offset": offset,
        "b_limit": limit,
        "b_order": "applicationDeadline",
        "b_keyword": "",
        "b_participating_countries": "country-20",  # Nederland blijft behouden
        "b_application_deadline_after_day": now.day,
        "b_application_deadline_after_month": now.month,
        "b_application_deadline_after_year": now.year,
        "b_browse": "1",
    }
    return f"{BROWSE_TRAINING_URL}?{urlencode(params)}"


# ============================================================
# 2. OTLAS PARTNER FINDING (Alle Erasmus+ & ESC projecten voor NL)
# ============================================================

def build_otlas_search_url(page=1):
    """
    Zoekt in Otlas naar álle projecten (KA1, KA2, ESC) voor Nederland 
    zonder te beperken tot enkel 'Youth Exchange'.
    """
    params = {
        "country": "NL",  # Nederland blijft behouden
        "page": page
        # 'q' is verwijderd zodat ALLE projecttypes binnenkomen
    }
    return f"{BROWSE_OTLAS_URL}?{urlencode(params)}"


def fetch_otlas_exchanges(session):
    print("\n" + "=" * 60)
    print("OTLAS SCRAPING (ALLE ERASMUS+ & ESC PROJECTEN)")
    print("=" * 60)

    otlas_results = []
    seen = set()
    page = 1

    while True:  # Blijf doorgaan totdat er geen pagina's meer zijn
        url = build_otlas_search_url(page=page)
        print(f"\n[Otlas Pagina {page}] Ophalen via: {url}")

        response = fetch(session, url)
        if not response:
            break

        soup = BeautifulSoup(response.text, "html.parser")
        links = soup.find_all("a", href=re.compile(r"/tools/otlas-partner-finding/project/\d+"))
        
        if not links:
            print("  -> Geen Otlas projecten meer gevonden.")
            break

        new_count = 0
        for link in links:
            href = link.get("href", "").strip()
            full_url = urljoin(BASE_URL, href)

            if full_url not in seen:
                seen.add(full_url)
                title = clean_text(link.get_text(" ", strip=True))
                if not title or title.lower() in ["view", "more", "details"]:
                    title = "Erasmus+ / ESC Project"

                # Detailpagina scrapen voor het exacte type en deadline
                detail_resp = fetch(session, full_url)
                deadline_str = None
                act_type = "Erasmus+ Project"

                if detail_resp:
                    dt_soup = BeautifulSoup(detail_resp.text, "html.parser")
                    dt_text = clean_text(dt_soup.get_text(" ", strip=True))
                    deadline_str = extract_deadline(dt_soup, dt_text)
                    act_type = extract_activity_type(dt_text)

                deadline_date = parse_date(deadline_str)

                otlas_results.append({
                    "title": title,
                    "url": full_url,
                    "activity_type": act_type,
                    "application_deadline": deadline_str,
                    "application_deadline_iso": (
                        deadline_date.strftime("%Y-%m-%d") if deadline_date else None
                    ),
                    "netherlands_eligible": True,
                    "scraped_at": datetime.now(timezone.utc).isoformat()
                })
                new_count += 1
                time.sleep(0.3)

        print(f"  -> {new_count} nieuwe Otlas projecten toegevoegd op deze pagina.")
        
        # Als er geen NIEUWE projecten meer op de pagina stonden, zijn we aan het einde
        if new_count == 0:
            break

        page += 1

    return otlas_results
