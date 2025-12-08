import asyncio
from playwright.async_api import async_playwright
from icalendar import Calendar, Event
from datetime import datetime
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
        
        # Zrzut ekranu do debugowania
        await page.screenshot(path="debug_01_start.png")
        
        # Szukaj przycisku logowania Azure
        print("🔐 Szukam przycisku logowania...")
        
        # Próbuj różne selektory dla przycisku logowania
        login_selectors = [
            'text=Zaloguj',
            'text=Login',
            'text=Azure',
            'text=Microsoft',
            'a[href*="azure"]',
            'a[href*="login"]',
            'button:has-text("Zaloguj")',
            '.login-button',
            '#login'
        ]
        
        for selector in login_selectors:
            try:
                if await page.locator(selector).count() > 0:
                    print(f"✅ Znaleziono: {selector}")
                    await page.click(selector)
                    break
            except:
                continue
        
        await page.wait_for_timeout(3000)
        await page.screenshot(path="debug_02_after_login_click.png")
        
        # Logowanie Azure AD
        print("📧 Wprowadzam email...")
        try:
            await page.wait_for_selector('input[type="email"]', timeout=10000)
            await page.fill('input[type="email"]', AZURE_EMAIL)
            await page.click('input[type="submit"]')
            await page.wait_for_timeout(2000)
        except Exception as e:
            print(f"⚠️ Problem z emailem: {e}")
            await page.screenshot(path="debug_error_email.png")
        
        print("🔑 Wprowadzam hasło...")
        try:
            await page.wait_for_selector('input[type="password"]', timeout=10000)
            await page.fill('input[type="password"]', AZURE_PASSWORD)
            await page.click('input[type="submit"]')
            await page.wait_for_timeout(3000)
        except Exception as e:
            print(f"⚠️ Problem z hasłem: {e}")
            await page.screenshot(path="debug_error_password.png")
        
        # Obsługa "Stay signed in?"
        try:
            stay_signed = page.locator('text=Stay signed in')
            if await stay_signed.count() > 0:
                await page.click('text=No')
                await page.wait_for_timeout(2000)
        except:
            pass
        
        await page.screenshot(path="debug_03_after_login.png")
        print("✅ Zalogowano, pobieram plan zajęć...")
        
        # Poczekaj na załadowanie strony z planem
        await page.wait_for_timeout(5000)
        await page.screenshot(path="debug_04_schedule_page.png")
        
        # Pobierz HTML do analizy
        html_content = await page.content()
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(html_content)
        
        # Próba pobrania wydarzeń - DOSTOSUJ SELEKTORY!
        events = await page.evaluate('''
            () => {
                const events = [];
                
                // Metoda 1: Szukaj tabel z planem
                document.querySelectorAll('table tr').forEach(row => {
                    const cells = row.querySelectorAll('td');
                    if (cells.length >= 3) {
                        const text = row.innerText;
                        if (text.match(/\\d{1,2}[:\\.\\-]\\d{2}/)) {
                            events.push({
                                raw: row.innerText,
                                html: row.innerHTML
                            });
                        }
                    }
                });
                
                // Metoda 2: Szukaj divów z wydarzeniami
                document.querySelectorAll('[class*="event"], [class*="lesson"], [class*="zajecia"], [class*="schedule"]').forEach(el => {
                    events.push({
                        raw: el.innerText,
                        html: el.innerHTML
                    });
                });
                
                // Metoda 3: Szukaj elementów z czasem
                document.querySelectorAll('*').forEach(el => {
                    if (el.children.length === 0) {
                        const text = el.innerText || '';
                        if (text.match(/\\d{1,2}:\\d{2}\\s*-\\s*\\d{1,2}:\\d{2}/)) {
                            const parent = el.closest('tr, div, li');
                            if (parent) {
                                events.push({
                                    raw: parent.innerText,
                                    html: parent.innerHTML
                                });
                            }
                        }
                    }
                });
                
                return events;
            }
        ''')
        
        print(f"📋 Znaleziono {len(events)} potencjalnych wydarzeń")
        
        await browser.close()
        return events

def parse_events(raw_events):
    """Parsuj surowe dane na strukturyzowane wydarzenia"""
    parsed = []
    
    for raw in raw_events:
        text = raw.get('raw', '')
        
        # Szukaj wzorców czasu: "09:00 - 10:30" lub "9.00-10.30"
        time_match = re.search(r'(\d{1,2})[:\.](\d{2})\s*[-–]\s*(\d{1,2})[:\.](\d{2})', text)
        
        # Szukaj daty: "2024-01-15" lub "15.01.2024" lub "15 stycznia"
        date_match = re.search(r'(\d{4})-(\d{2})-(\d{2})|(\d{1,2})\.(\d{1,2})\.(\d{4})', text)
        
        if time_match:
            # Wyciągnij przedmiot (pierwsza linia lub tekst przed godziną)
            lines = text.strip().split('\n')
            title = lines[0] if lines else "Zajęcia"
            
            # Wyczyść tytuł
            title = re.sub(r'\d{1,2}[:\.]\\d{2}.*', '', title).strip()
            if not title:
                title = "Zajęcia"
            
            event = {
                'title': title,
                'time_start': f"{time_match.group(1).zfill(2)}:{time_match.group(2)}",
                'time_end': f"{time_match.group(3).zfill(2)}:{time_match.group(4)}",
                'location': '',
                'raw': text
            }
            
            if date_match:
                if date_match.group(1):  # Format YYYY-MM-DD
                    event['date'] = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
                else:  # Format DD.MM.YYYY
                    event['date'] = f"{date_match.group(6)}-{date_match.group(5).zfill(2)}-{date_match.group(4).zfill(2)}"
            else:
                # Użyj dzisiejszej daty jako fallback
                event['date'] = datetime.now().strftime('%Y-%m-%d')
            
            # Szukaj sali
            room_match = re.search(r'sala?\s*[:\.]?\s*(\w+\d*)|room\s*[:\.]?\s*(\w+)', text, re.IGNORECASE)
            if room_match:
                event['location'] = room_match.group(1) or room_match.group(2)
            
            parsed.append(event)
    
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
            
            event.add('description', f"Źródło: Cambridge\n\nDane surowe:\n{event_data.get('raw', '')[:500]}")
            
            uid = f"{start_dt.strftime('%Y%m%d%H%M')}-{hash(event_data['title']) % 10000}@szkolafilmowa"
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
    
    if not AZURE_EMAIL or not AZURE_PASSWORD:
        print("❌ Brak zmiennych AZURE_EMAIL lub AZURE_PASSWORD!")
        # Utwórz pusty kalendarz
        cal = Calendar()
        cal.add('prodid', '-//Plan Zajec//PL')
        cal.add('version', '2.0')
        cal.add('x-wr-calname', 'Plan Zajęć - Błąd konfiguracji')
        with open(OUTPUT_FILE, 'wb') as f:
            f.write(cal.to_ical())
        return
    
    raw_events = await login_and_get_schedule()
    parsed_events = parse_events(raw_events)
    
    print(f"📊 Sparsowano {len(parsed_events)} wydarzeń")
    
    if parsed_events:
        create_ics(parsed_events)
    else:
        print("⚠️ Brak wydarzeń do zapisania, tworzę pusty kalendarz...")
        cal = Calendar()
        cal.add('prodid', '-//Plan Zajec//PL')
        cal.add('version', '2.0')
        cal.add('x-wr-calname', 'Plan Zajęć - Szkoła Filmowa')
        
        # Dodaj testowe wydarzenie
        event = Event()
        event.add('summary', '⚠️ Synchronizacja wymaga dostosowania')
        event.add('dtstart', datetime.now(pytz.timezone('Europe/Warsaw')))
        event.add('dtend', datetime.now(pytz.timezone('Europe/Warsaw')))
        event.add('description', 'Sprawdź logi GitHub Actions i dostosuj selektory')
        event.add('uid', 'test@szkolafilmowa')
        cal.add_component(event)
        
        with open(OUTPUT_FILE, 'wb') as f:
            f.write(cal.to_ical())

if __name__ == "__main__":
    asyncio.run(main())
