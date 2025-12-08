import asyncio
from playwright.async_api import async_playwright
from icalendar import Calendar, Event
from datetime import datetime, timedelta
import pytz
import os
import re

# Konfiguracja
CAMBRIDGE_URL = "https://student.szkolafilmowa.pl/palio/html.run?_Instance=cambridge"
AZURE_EMAIL = os.environ.get("AZURE_EMAIL")
AZURE_PASSWORD = os.environ.get("AZURE_PASSWORD")
OUTPUT_FILE = "plan_zajec.ics"

async def login_and_get_schedule():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        print("🌐 Otwieram stronę Cambridge...")
        await page.goto(CAMBRIDGE_URL)
        await page.wait_for_timeout(3000)
        await page.screenshot(path="debug_01_start.png")
        
        # ===== KROK 1: Kliknij "Zaloguj przez Azure" =====
        print("🔐 Klikam 'Zaloguj przez Azure'...")
        try:
            await page.click('input[value="Zaloguj przez Azure"]')
            await page.wait_for_timeout(3000)
        except Exception as e:
            print(f"❌ Nie znaleziono przycisku Azure: {e}")
            await browser.close()
            return []
        
        # ===== KROK 2: Wpisz email Microsoft =====
        print("📧 Wprowadzam email...")
        try:
            await page.wait_for_selector('input[type="email"]', timeout=15000)
            await page.fill('input[type="email"]', AZURE_EMAIL)
            await page.click('input[type="submit"]')
            await page.wait_for_timeout(3000)
        except Exception as e:
            print(f"❌ Problem z emailem: {e}")
            await browser.close()
            return []
        
        # ===== KROK 3: Wpisz hasło =====
        print("🔑 Wprowadzam hasło...")
        try:
            await page.wait_for_selector('input[type="password"]', timeout=15000)
            await page.fill('input[type="password"]', AZURE_PASSWORD)
            await page.click('input[type="submit"]')
            await page.wait_for_timeout(5000)
        except Exception as e:
            print(f"❌ Problem z hasłem: {e}")
            await browser.close()
            return []
        
        # ===== KROK 4: Obsługa "Stay signed in?" =====
        print("🔄 Sprawdzam 'Stay signed in'...")
        try:
            for selector in ['input[value="No"]', 'input[value="Nie"]', '#idBtn_Back']:
                if await page.locator(selector).count() > 0:
                    await page.click(selector)
                    await page.wait_for_timeout(3000)
                    break
        except:
            pass
        
        # ===== KROK 5: Czekaj na Cambridge =====
        print("⏳ Czekam na załadowanie Cambridge...")
        await page.wait_for_timeout(5000)
        await page.screenshot(path="debug_05_cambridge.png")
        
        # ===== KROK 6: Przejdź do harmonogramu moich zajęć =====
        print("📅 Przechodzę do harmonogramu...")
        
        # Pobierz link z menu JavaScript
        harmonogram_url = await page.evaluate('''
            () => {
                const html = document.documentElement.innerHTML;
                const match = html.match(/(\\/palio\\/html\\.run\\?[^"']*_PageID=191[^"']*)/);
                if (match) {
                    return match[1].replace(/&amp;/g, '&');
                }
                return null;
            }
        ''')
        
        if harmonogram_url:
            full_url = f"https://student.szkolafilmowa.pl{harmonogram_url}"
            print(f"🌐 Przechodzę do: {full_url}")
            await page.goto(full_url)
            await page.wait_for_timeout(3000)
        
        await page.screenshot(path="debug_06_harmonogram_list.png")
        
        # ===== KROK 7: Kliknij na numer albumu (pierwszy link w tabeli) =====
        print("📋 Szukam numeru albumu...")
        
        # Znajdź pierwszy link w tabeli z klasą "sort"
        album_link = await page.evaluate('''
            () => {
                // Szukaj linków w tabeli sort
                const table = document.querySelector('table.sort');
                if (table) {
                    const link = table.querySelector('tbody a.link');
                    if (link) {
                        return link.getAttribute('href');
                    }
                }
                
                // Alternatywnie szukaj linku z _RowID
                const links = document.querySelectorAll('a[href*="_RowID"]');
                if (links.length > 0) {
                    return links[0].getAttribute('href');
                }
                
                return null;
            }
        ''')
        
        if album_link:
            full_url = album_link if album_link.startswith('http') else f"https://student.szkolafilmowa.pl{album_link}"
            print(f"🎓 Klikam album: {full_url}")
            await page.goto(full_url)
            await page.wait_for_timeout(5000)
        else:
            print("⚠️ Nie znaleziono linku do albumu")
        
        await page.screenshot(path="debug_07_album_page.png")
        
        # Zapisz HTML
        html_content = await page.content()
        with open("debug_album_page.html", "w", encoding="utf-8") as f:
            f.write(html_content)
        
        print(f"📍 Aktualny URL: {page.url}")
        
        # ===== KROK 8: Sprawdź czy trzeba wybrać tydzień =====
        # Może być lista tygodni do wyboru
        
        week_links = await page.evaluate('''
            () => {
                const links = [];
                document.querySelectorAll('a').forEach(a => {
                    const href = a.getAttribute('href') || '';
                    const text = a.innerText || '';
                    // Szukaj linków z datami tygodni
                    if (text.match(/\\d{2}\\.\\d{2}\\.\\d{4}/) || text.match(/tydzień/i) || href.includes('Week')) {
                        links.push({
                            href: href,
                            text: text.trim().substring(0, 100)
                        });
                    }
                });
                return links;
            }
        ''')
        
        print(f"📅 Znaleziono {len(week_links)} linków do tygodni")
        for wl in week_links[:5]:
            print(f"  - {wl['text'][:50]}")
        
        # Jeśli są linki do tygodni, kliknij pierwszy (aktualny tydzień)
        if week_links:
            first_week = week_links[0]
            if first_week['href']:
                week_url = first_week['href'] if first_week['href'].startswith('http') else f"https://student.szkolafilmowa.pl{first_week['href']}"
                print(f"📅 Klikam tydzień: {first_week['text'][:30]}")
                await page.goto(week_url)
                await page.wait_for_timeout(3000)
                await page.screenshot(path="debug_08_week.png")
        
        # ===== KROK 9: Pobierz dane z harmonogramu =====
        print("📊 Pobieram dane z harmonogramu...")
        
        # Zapisz finalny HTML
        html_content = await page.content()
        with open("debug_harmonogram_page.html", "w", encoding="utf-8") as f:
            f.write(html_content)
        
        await page.screenshot(path="debug_09_final.png")
        
        events = await page.evaluate('''
            () => {
                const events = [];
                
                // Szukaj wszystkich tabel
                document.querySelectorAll('table').forEach(table => {
                    table.querySelectorAll('tr').forEach(row => {
                        const text = row.innerText || '';
                        // Szukaj wierszy z godzinami (format HH:MM)
                        if (text.match(/\\d{1,2}:\\d{2}/)) {
                            events.push({
                                raw: text.trim().substring(0, 1000),
                                html: row.innerHTML.substring(0, 2000)
                            });
                        }
                    });
                });
                
                // Szukaj komórek z danymi zajęć
                document.querySelectorAll('td').forEach(td => {
                    const text = td.innerText || '';
                    // Szukaj komórek z czasem i datą
                    if (text.match(/\\d{1,2}:\\d{2}/) && text.length > 10 && text.length < 1000) {
                        events.push({
                            raw: text.trim(),
                            html: td.innerHTML.substring(0, 1000)
                        });
                    }
                });
                
                // Szukaj divów z zajęciami
                document.querySelectorAll('div').forEach(div => {
                    const text = div.innerText || '';
                    if (text.match(/\\d{1,2}:\\d{2}\\s*[-–]\\s*\\d{1,2}:\\d{2}/) && 
                        text.length > 15 && text.length < 1000) {
                        events.push({
                            raw: text.trim(),
                            html: div.innerHTML.substring(0, 1000)
                        });
                    }
                });
                
                return events;
            }
        ''')
        
        print(f"📋 Znaleziono {len(events)} potencjalnych wydarzeń")
        
        # Debug - wypisz pierwsze wydarzenia
        for i, event in enumerate(events[:10]):
            print(f"  Event {i+1}: {event.get('raw', '')[:100]}...")
        
        await browser.close()
        return events

def parse_events(raw_events):
    """Parsuj surowe dane na strukturyzowane wydarzenia"""
    parsed = []
    seen = set()
    
    for raw in raw_events:
        text = raw.get('raw', '')
        
        # Unikaj duplikatów
        text_hash = hash(text)
        if text_hash in seen:
            continue
        seen.add(text_hash)
        
        # Szukaj wzorców
        # Czas: "09:00 - 10:30" lub "9:00-10:30"
        time_match = re.search(r'(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})', text)
        
        # Data: "15.01.2024" lub "15.12.2024"
        date_match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', text)
        
        if time_match and date_match:
            # Wyciągnij datę
            day = date_match.group(1).zfill(2)
            month = date_match.group(2).zfill(2)
            year = date_match.group(3)
            date_str = f"{year}-{month}-{day}"
            
            # Wyciągnij tytuł - usuń daty i godziny
            title = text
            title = re.sub(r'\d{1,2}\.\d{1,2}\.\d{4}', '', title)
            title = re.sub(r'\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2}', '', title)
            title = re.sub(r'\d{1,2}:\d{2}', '', title)
            title = re.sub(r'\s+', ' ', title).strip()
            title = title.strip('-–,. \t\n')
            
            if not title or len(title) < 2:
                title = "Zajęcia"
            
            # Szukaj sali
            room_match = re.search(r'(?:sala|room|s\.|pok\.?|lab|studio|aula)\s*[:\.]?\s*([A-Za-z0-9\-/]+)', text, re.IGNORECASE)
            location = room_match.group(1) if room_match else ''
            
            event = {
                'title': title[:150],
                'date': date_str,
                'time_start': f"{time_match.group(1).zfill(2)}:{time_match.group(2)}",
                'time_end': f"{time_match.group(3).zfill(2)}:{time_match.group(4)}",
                'location': location,
                'raw': text[:300]
            }
            
            parsed.append(event)
            print(f"  ✅ {date_str} {event['time_start']}-{event['time_end']} {title[:40]}")
    
    return parsed

def create_ics(events):
    """Utwórz plik ICS z wydarzeniami"""
    cal = Calendar()
    cal.add('prodid', '-//Plan Zajec Szkola Filmowa//PL')
    cal.add('version', '2.0')
    cal.add('calscale', 'GREGORIAN')
    cal.add('method', 'PUBLISH')
    cal.add('x-wr-calname', 'Plan Zajęć - Szkoła Filmowa')
    cal.add('x-wr-timezone', 'Europe/Warsaw')
    
    tz = pytz.timezone('Europe/Warsaw')
    added = 0
    
    for event_data in events:
        try:
            event = Event()
            event.add('summary', event_data['title'])
            
            date_str = event_data['date']
            start_time = event_data['time_start']
            end_time = event_data['time_end']
            
            start_dt = datetime.strptime(f"{date_str} {start_time}", "%Y-%m-%d %H:%M")
            end_dt = datetime.strptime(f"{date_str} {end_time}", "%Y-%m-%d %H:%M")
            
            event.add('dtstart', tz.localize(start_dt))
            event.add('dtend', tz.localize(end_dt))
            
            if event_data.get('location'):
                event.add('location', event_data['location'])
            
            event.add('description', 'Źródło: Cambridge - Szkoła Filmowa')
            
            uid = f"{start_dt.strftime('%Y%m%d%H%M')}-{abs(hash(event_data['title'])) % 100000}@szkolafilmowa"
            event.add('uid', uid)
            
            cal.add_component(event)
            added += 1
            
        except Exception as e:
            print(f"⚠️ Błąd: {e}")
            continue
    
    with open(OUTPUT_FILE, 'wb') as f:
        f.write(cal.to_ical())
    
    print(f"✅ Zapisano {added} wydarzeń do {OUTPUT_FILE}")
    return added

async def main():
    print("🚀 Start synchronizacji...")
    print(f"📧 Email: {AZURE_EMAIL}")
    print(f"🔑 Hasło ustawione: {'TAK' if AZURE_PASSWORD else 'NIE!'}")
    
    if not AZURE_EMAIL or not AZURE_PASSWORD:
        print("❌ Brak AZURE_EMAIL lub AZURE_PASSWORD!")
        cal = Calendar()
        cal.add('prodid', '-//Plan Zajec//PL')
        cal.add('version', '2.0')
        cal.add('x-wr-calname', 'BŁĄD - brak konfiguracji')
        with open(OUTPUT_FILE, 'wb') as f:
            f.write(cal.to_ical())
        return
    
    raw_events = await login_and_get_schedule()
    parsed_events = parse_events(raw_events)
    
    print(f"📊 Sparsowano {len(parsed_events)} wydarzeń")
    
    if parsed_events:
        create_ics(parsed_events)
    else:
        print("⚠️ Brak wydarzeń - sprawdź debug_harmonogram_page.html")
        cal = Calendar()
        cal.add('prodid', '-//Plan Zajec//PL')
        cal.add('version', '2.0')
        cal.add('x-wr-calname', 'Plan Zajęć - Szkoła Filmowa')
        
        event = Event()
        event.add('summary', '⚠️ Sprawdź konfigurację - brak zajęć')
        tz = pytz.timezone('Europe/Warsaw')
        now = datetime.now(tz)
        event.add('dtstart', now)
        event.add('dtend', now + timedelta(hours=1))
        event.add('description', 'Pobierz pliki debug z GitHub Actions aby sprawdzić problem.')
        event.add('uid', f'info-{now.strftime("%Y%m%d%H%M")}@szkolafilmowa')
        cal.add_component(event)
        
        with open(OUTPUT_FILE, 'wb') as f:
            f.write(cal.to_ical())

if __name__ == "__main__":
    asyncio.run(main())
