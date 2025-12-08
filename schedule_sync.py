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
            await page.screenshot(path="debug_02_azure_login.png")
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
        await page.screenshot(path="debug_05_cambridge_loaded.png")
        
        # Zapisz stronę główną
        html_content = await page.content()
        with open("debug_main_page.html", "w", encoding="utf-8") as f:
            f.write(html_content)
        
        # ===== KROK 6: Pobierz URL do harmonogramu z JavaScript =====
        print("📅 Szukam linku do harmonogramu...")
        
        harmonogram_url = await page.evaluate('''
            () => {
                // Szukaj w menu JavaScript
                const scripts = document.querySelectorAll('script');
                for (const script of scripts) {
                    const text = script.innerText || script.textContent;
                    // Szukaj linku do "Harmonogramy moich zajęć" (PageID=191)
                    const match = text.match(/Harmonogramy moich zajęć.*?(\\/palio\\/html\\.run\\?[^"]+_PageID=191[^"]+)/);
                    if (match) {
                        return match[1].replace(/&amp;/g, '&');
                    }
                }
                
                // Alternatywnie szukaj w ukrytych divach menu
                const menuItems = document.querySelectorAll('.jsdomenuitem, [id^="menuItem"]');
                for (const item of menuItems) {
                    if (item.innerText.includes('Harmonogramy moich zajęć')) {
                        // Pobierz onclick lub href
                        const onclick = item.getAttribute('onclick');
                        if (onclick) {
                            const match = onclick.match(/location.*?['"]([^'"]+)['"]/);
                            if (match) return match[1];
                        }
                    }
                }
                
                return null;
            }
        ''')
        
        print(f"📍 Znaleziony URL harmonogramu: {harmonogram_url}")
        
        # Jeśli nie znaleziono, spróbuj przez menu hover
        if not harmonogram_url:
            print("🔄 Próbuję przez menu rozwijane...")
            try:
                # Hover na "Studia"
                await page.hover('#menuBarItem3')
                await page.wait_for_timeout(1000)
                await page.screenshot(path="debug_06_menu_hover.png")
                
                # Kliknij "Harmonogramy moich zajęć"
                await page.click('#menuItem9')
                await page.wait_for_timeout(5000)
                await page.screenshot(path="debug_07_harmonogram.png")
            except Exception as e:
                print(f"⚠️ Problem z menu: {e}")
                
                # Ostatnia próba - szukaj w HTML linków
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
        
        # Jeśli mamy URL, przejdź do niego
        if harmonogram_url:
            full_url = harmonogram_url if harmonogram_url.startswith('http') else f"https://student.szkolafilmowa.pl{harmonogram_url}"
            print(f"🌐 Przechodzę do: {full_url}")
            await page.goto(full_url)
            await page.wait_for_timeout(5000)
        
        await page.screenshot(path="debug_08_harmonogram_page.png")
        
        # Zapisz HTML harmonogramu
        html_content = await page.content()
        with open("debug_harmonogram_page.html", "w", encoding="utf-8") as f:
            f.write(html_content)
        
        print(f"📍 Aktualny URL: {page.url}")
        
        # ===== KROK 7: Sprawdź czy trzeba wybrać tydzień =====
        # Czasami trzeba wybrać zakres dat
        
        # Pobierz wszystkie linki do tygodni jeśli są
        week_links = await page.evaluate('''
            () => {
                const links = [];
                document.querySelectorAll('a').forEach(a => {
                    const href = a.getAttribute('href') || '';
                    const text = a.innerText || '';
                    // Szukaj linków z datami lub "tydzień"
                    if (href.includes('PageID=191') || text.match(/\\d{2}\\.\\d{2}\\.\\d{4}/)) {
                        links.push({
                            href: href,
                            text: text.trim()
                        });
                    }
                });
                return links;
            }
        ''')
        
        print(f"📋 Znaleziono {len(week_links)} linków do tygodni")
        
        # ===== KROK 8: Pobierz dane z harmonogramu =====
        print("📊 Pobieram dane z harmonogramu...")
        
        events = await page.evaluate('''
            () => {
                const events = [];
                
                // Szukaj tabel z zajęciami
                document.querySelectorAll('table').forEach(table => {
                    table.querySelectorAll('tr').forEach(row => {
                        const text = row.innerText;
                        // Szukaj wierszy z godzinami
                        if (text.match(/\\d{1,2}:\\d{2}/)) {
                            events.push({
                                raw: text.trim().substring(0, 500),
                                html: row.innerHTML.substring(0, 1000)
                            });
                        }
                    });
                });
                
                // Szukaj komórek z czasem
                document.querySelectorAll('td').forEach(td => {
                    const text = td.innerText || '';
                    if (text.match(/\\d{1,2}:\\d{2}\\s*[-–]\\s*\\d{1,2}:\\d{2}/) && text.length > 10 && text.length < 500) {
                        events.push({
                            raw: text.trim(),
                            html: td.innerHTML.substring(0, 500)
                        });
                    }
                });
                
                // Szukaj divów z zajęciami (czasem plan jest w divach)
                document.querySelectorAll('div, span').forEach(el => {
                    const text = el.innerText || '';
                    if (text.match(/\\d{1,2}:\\d{2}\\s*[-–]\\s*\\d{1,2}:\\d{2}/) && 
                        text.match(/\\d{1,2}\\.\\d{1,2}\\.\\d{4}/) &&
                        text.length > 20 && text.length < 500) {
                        events.push({
                            raw: text.trim(),
                            html: el.innerHTML.substring(0, 500)
                        });
                    }
                });
                
                return events;
            }
        ''')
        
        print(f"📋 Znaleziono {len(events)} potencjalnych wydarzeń")
        
        # Debug - wypisz pierwsze wydarzenia
        for i, event in enumerate(events[:10]):
            print(f"  Event {i+1}: {event.get('raw', '')[:80]}...")
        
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
        # Czas: "09:00 - 10:30"
        time_match = re.search(r'(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})', text)
        
        # Data: "15.01.2024" lub "15.12.2024"
        date_match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', text)
        
        if time_match and date_match:
            # Wyciągnij datę
            day = date_match.group(1).zfill(2)
            month = date_match.group(2).zfill(2)
            year = date_match.group(3)
            date_str = f"{year}-{month}-{day}"
            
            # Wyciągnij tytuł
            title = text
            title = re.sub(r'\d{1,2}\.\d{1,2}\.\d{4}', '', title)
            title = re.sub(r'\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2}', '', title)
            title = re.sub(r'\d{1,2}:\d{2}', '', title)
            title = re.sub(r'\s+', ' ', title).strip()
            title = title.strip('-–,. \t\n')
            
            if not title or len(title) < 2:
                title = "Zajęcia"
            
            # Szukaj sali
            room_match = re.search(r'(?:sala|room|s\.|pok\.?|lab|studio)\s*[:\.]?\s*([A-Za-z0-9\-]+)', text, re.IGNORECASE)
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
            
            event.add('description', f"Źródło: Cambridge")
            
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
        event.add('description', 'Pobierz debug_harmonogram_page.html z GitHub Actions')
        event.add('uid', f'info-{now.strftime("%Y%m%d%H%M")}@szkolafilmowa')
        cal.add_component(event)
        
        with open(OUTPUT_FILE, 'wb') as f:
            f.write(cal.to_ical())

if __name__ == "__main__":
    asyncio.run(main())
