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
            await page.screenshot(path="debug_error_no_azure_button.png")
            await browser.close()
            return []
        
        # ===== KROK 2: Wpisz email Microsoft =====
        print("📧 Wprowadzam email...")
        try:
            await page.wait_for_selector('input[type="email"]', timeout=15000)
            await page.fill('input[type="email"]', AZURE_EMAIL)
            await page.screenshot(path="debug_03_email_filled.png")
            await page.click('input[type="submit"]')
            await page.wait_for_timeout(3000)
            await page.screenshot(path="debug_04_after_email.png")
        except Exception as e:
            print(f"❌ Problem z emailem: {e}")
            await page.screenshot(path="debug_error_email.png")
            await browser.close()
            return []
        
        # ===== KROK 3: Wpisz hasło =====
        print("🔑 Wprowadzam hasło...")
        try:
            await page.wait_for_selector('input[type="password"]', timeout=15000)
            await page.fill('input[type="password"]', AZURE_PASSWORD)
            await page.screenshot(path="debug_05_password_filled.png")
            await page.click('input[type="submit"]')
            await page.wait_for_timeout(5000)
            await page.screenshot(path="debug_06_after_password.png")
        except Exception as e:
            print(f"❌ Problem z hasłem: {e}")
            await page.screenshot(path="debug_error_password.png")
            await browser.close()
            return []
        
        # ===== KROK 4: Obsługa "Stay signed in?" =====
        print("🔄 Sprawdzam 'Stay signed in'...")
        try:
            for selector in ['input[value="No"]', 'input[value="Nie"]', '#idBtn_Back', 'text=No', 'text=Nie']:
                if await page.locator(selector).count() > 0:
                    await page.click(selector)
                    print(f"✅ Kliknięto: {selector}")
                    await page.wait_for_timeout(3000)
                    break
            await page.screenshot(path="debug_07_after_stay_signed.png")
        except Exception as e:
            print(f"⚠️ Brak 'Stay signed in': {e}")
        
        # ===== KROK 5: Czekaj na załadowanie Cambridge =====
        print("⏳ Czekam na załadowanie Cambridge...")
        await page.wait_for_timeout(5000)
        await page.screenshot(path="debug_08_cambridge_loaded.png")
        
        current_url = page.url
        print(f"📍 Aktualny URL: {current_url}")
        
        # Zapisz stronę główną
        html_content = await page.content()
        with open("debug_main_page.html", "w", encoding="utf-8") as f:
            f.write(html_content)
        
        # ===== KROK 6: Kliknij menu "Studia" =====
        print("📚 Klikam menu 'Studia'...")
        try:
            # Znajdź i kliknij "Studia" w menu
            await page.hover('span:has-text("Studia")')
            await page.wait_for_timeout(1000)
            await page.screenshot(path="debug_09_studia_hover.png")
            
            # Kliknij "Harmonogramy moich zajęć"
            print("📅 Klikam 'Harmonogramy moich zajęć'...")
            await page.click('div:has-text("Harmonogramy moich zajęć")')
            await page.wait_for_timeout(5000)
            await page.screenshot(path="debug_10_harmonogram.png")
        except Exception as e:
            print(f"⚠️ Problem z menu Studia: {e}")
            # Alternatywna metoda - bezpośredni link
            try:
                print("🔄 Próbuję alternatywnej metody...")
                # Pobierz link z menu
                link = await page.get_attribute('text=Harmonogramy moich zajęć', 'href')
                if link:
                    await page.goto(link if link.startswith('http') else f"https://student.szkolafilmowa.pl{link}")
                    await page.wait_for_timeout(5000)
            except:
                pass
            await page.screenshot(path="debug_10_error_menu.png")
        
        # Zapisz HTML strony harmonogramu
        html_content = await page.content()
        with open("debug_harmonogram_page.html", "w", encoding="utf-8") as f:
            f.write(html_content)
        
        print("📍 URL harmonogramu: " + page.url)
        await page.screenshot(path="debug_11_harmonogram_loaded.png")
        
        # ===== KROK 7: Pobierz dane z harmonogramu =====
        print("📊 Pobieram dane z harmonogramu...")
        
        events = await page.evaluate('''
            () => {
                const events = [];
                
                // Szukaj wszystkich komórek tabeli z zajęciami
                document.querySelectorAll('table').forEach(table => {
                    table.querySelectorAll('tr').forEach(row => {
                        const text = row.innerText;
                        // Szukaj wierszy z godzinami (format XX:XX)
                        if (text.match(/\\d{1,2}:\\d{2}/)) {
                            events.push({
                                raw: text.trim(),
                                html: row.innerHTML
                            });
                        }
                    });
                });
                
                // Szukaj też divów i spanów z danymi
                document.querySelectorAll('td, div, span').forEach(el => {
                    const text = el.innerText || '';
                    // Szukaj wzorca czasu np. "09:00 - 12:00" lub daty "09.12.2024"
                    if ((text.match(/\\d{1,2}:\\d{2}\\s*[-–]\\s*\\d{1,2}:\\d{2}/) || 
                         text.match(/\\d{1,2}\\.\\d{1,2}\\.\\d{4}/)) && 
                        text.length < 1000 && text.length > 10) {
                        events.push({
                            raw: text.trim(),
                            html: el.innerHTML
                        });
                    }
                });
                
                return events;
            }
        ''')
        
        print(f"📋 Znaleziono {len(events)} potencjalnych wydarzeń")
        
        # Debug - wypisz pierwsze wydarzenia
        for i, event in enumerate(events[:5]):
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
        
        # Data: "15.01.2024" lub "2024-01-15"
        date_match_pl = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', text)
        date_match_iso = re.search(r'(\d{4})-(\d{2})-(\d{2})', text)
        
        if time_match:
            # Wyciągnij datę
            if date_match_pl:
                date_str = f"{date_match_pl.group(3)}-{date_match_pl.group(2).zfill(2)}-{date_match_pl.group(1).zfill(2)}"
            elif date_match_iso:
                date_str = f"{date_match_iso.group(1)}-{date_match_iso.group(2)}-{date_match_iso.group(3)}"
            else:
                # Brak daty - pomiń lub użyj dzisiejszej
                continue
            
            # Wyciągnij tytuł - wszystko co nie jest datą/godziną
            title = text
            # Usuń daty i godziny
            title = re.sub(r'\d{1,2}\.\d{1,2}\.\d{4}', '', title)
            title = re.sub(r'\d{4}-\d{2}-\d{2}', '', title)
            title = re.sub(r'\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2}', '', title)
            title = re.sub(r'\d{1,2}:\d{2}', '', title)
            # Wyczyść
            title = re.sub(r'\s+', ' ', title).strip()
            title = title.strip('-–,. \t\n')
            
            if not title or len(title) < 2:
                title = "Zajęcia"
            
            # Szukaj sali
            room_match = re.search(r'(?:sala|room|s\.|pok\.?)\s*[:\.]?\s*([A-Za-z0-9\-]+)', text, re.IGNORECASE)
            location = room_match.group(1) if room_match else ''
            
            event = {
                'title': title[:150],
                'date': date_str,
                'time_start': f"{time_match.group(1).zfill(2)}:{time_match.group(2)}",
                'time_end': f"{time_match.group(3).zfill(2)}:{time_match.group(4)}",
                'location': location,
                'raw': text[:500]
            }
            
            parsed.append(event)
            print(f"  ✅ Sparsowano: {date_str} {event['time_start']}-{event['time_end']} {title[:50]}")
    
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
            
            event.add('description', f"Źródło: Cambridge\nSzkoła Filmowa")
            
            uid = f"{start_dt.strftime('%Y%m%d%H%M')}-{abs(hash(event_data['title'])) % 100000}@szkolafilmowa"
            event.add('uid', uid)
            
            cal.add_component(event)
            added += 1
            
        except Exception as e:
            print(f"⚠️ Błąd parsowania wydarzenia: {e}")
            continue
    
    with open(OUTPUT_FILE, 'wb') as f:
        f.write(cal.to_ical())
    
    print(f"✅ Zapisano {added} wydarzeń do {OUTPUT_FILE}")
    return added

async def main():
    print("🚀 Start synchronizacji...")
    print(f"📧 Email: {AZURE_EMAIL}")
    print(f"🔑 Hasło: {'*' * len(AZURE_PASSWORD) if AZURE_PASSWORD else 'BRAK!'}")
    
    if not AZURE_EMAIL or not AZURE_PASSWORD:
        print("❌ Brak zmiennych AZURE_EMAIL lub AZURE_PASSWORD!")
        cal = Calendar()
        cal.add('prodid', '-//Plan Zajec//PL')
        cal.add('version', '2.0')
        cal.add('x-wr-calname', 'Plan Zajęć - BŁĄD KONFIGURACJI')
        with open(OUTPUT_FILE, 'wb') as f:
            f.write(cal.to_ical())
        return
    
    raw_events = await login_and_get_schedule()
    parsed_events = parse_events(raw_events)
    
    print(f"📊 Sparsowano {len(parsed_events)} wydarzeń")
    
    if parsed_events:
        create_ics(parsed_events)
    else:
        print("⚠️ Brak wydarzeń - tworzę kalendarz z informacją...")
        cal = Calendar()
        cal.add('prodid', '-//Plan Zajec//PL')
        cal.add('version', '2.0')
        cal.add('x-wr-calname', 'Plan Zajęć - Szkoła Filmowa')
        
        event = Event()
        event.add('summary', '⚠️ Brak zajęć lub problem z synchronizacją')
        tz = pytz.timezone('Europe/Warsaw')
        now = datetime.now(tz)
        event.add('dtstart', now)
        event.add('dtend', now + timedelta(hours=1))
        event.add('description', 'Sprawdź debug-screenshots i debug_harmonogram_page.html w GitHub Actions')
        event.add('uid', f'info-{now.strftime("%Y%m%d")}@szkolafilmowa')
        cal.add_component(event)
        
        with open(OUTPUT_FILE, 'wb') as f:
            f.write(cal.to_ical())

if __name__ == "__main__":
    asyncio.run(main())
