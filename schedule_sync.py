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
            
            # Kliknij Next/Dalej
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
            
            # Kliknij Sign in/Zaloguj
            await page.click('input[type="submit"]')
            await page.wait_for_timeout(5000)
            await page.screenshot(path="debug_06_after_password.png")
        except Exception as e:
            print(f"❌ Problem z hasłem: {e}")
            await page.screenshot(path="debug_error_password.png")
            await browser.close()
            return []
        
        # ===== KROK 4: Obsługa "Stay signed in?" / "Nie wylogowuj mnie" =====
        print("🔄 Sprawdzam 'Stay signed in'...")
        try:
            # Czekaj na ewentualny prompt "Stay signed in?"
            stay_signed_selectors = [
                'input[value="No"]',
                'input[value="Nie"]', 
                '#idBtn_Back',
                'text=No',
                'text=Nie'
            ]
            
            for selector in stay_signed_selectors:
                try:
                    if await page.locator(selector).count() > 0:
                        await page.click(selector)
                        print(f"✅ Kliknięto: {selector}")
                        await page.wait_for_timeout(3000)
                        break
                except:
                    continue
                    
            await page.screenshot(path="debug_07_after_stay_signed.png")
        except Exception as e:
            print(f"⚠️ Brak 'Stay signed in' lub błąd: {e}")
        
        # ===== KROK 5: Czekaj na powrót do Cambridge =====
        print("⏳ Czekam na załadowanie Cambridge...")
        await page.wait_for_timeout(5000)
        await page.screenshot(path="debug_08_cambridge_loaded.png")
        
        # Sprawdź czy jesteśmy zalogowani
        current_url = page.url
        print(f"📍 Aktualny URL: {current_url}")
        
        # ===== KROK 6: Przejdź do planu zajęć =====
        print("📅 Szukam planu zajęć...")
        
        # Zapisz HTML strony głównej po zalogowaniu
        html_content = await page.content()
        with open("debug_main_page.html", "w", encoding="utf-8") as f:
            f.write(html_content)
        
        # Szukaj linku do planu zajęć
        schedule_selectors = [
            'text=Plan zajęć',
            'text=Plan',
            'text=Harmonogram',
            'text=Timetable',
            'text=Schedule',
            'a[href*="plan"]',
            'a[href*="schedule"]',
            'a[href*="harmonogram"]',
            'a[href*="timetable"]'
        ]
        
        for selector in schedule_selectors:
            try:
                if await page.locator(selector).count() > 0:
                    print(f"✅ Znaleziono link do planu: {selector}")
                    await page.click(selector)
                    await page.wait_for_timeout(3000)
                    await page.screenshot(path="debug_09_schedule_page.png")
                    break
            except:
                continue
        
        # ===== KROK 7: Pobierz dane z planu =====
        print("📊 Pobieram dane z planu...")
        await page.wait_for_timeout(3000)
        await page.screenshot(path="debug_10_final.png")
        
        # Zapisz HTML strony z planem
        html_content = await page.content()
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(html_content)
        
        # Pobierz wydarzenia
        events = await page.evaluate('''
            () => {
                const events = [];
                
                // Metoda 1: Szukaj tabel z planem
                document.querySelectorAll('table tr').forEach(row => {
                    const cells = row.querySelectorAll('td');
                    if (cells.length >= 2) {
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
                document.querySelectorAll('[class*="event"], [class*="lesson"], [class*="zajecia"], [class*="schedule"], [class*="plan"]').forEach(el => {
                    if (el.innerText.trim().length > 5) {
                        events.push({
                            raw: el.innerText,
                            html: el.innerHTML
                        });
                    }
                });
                
                // Metoda 3: Szukaj wszystkich komórek z czasem
                document.querySelectorAll('td, div, span').forEach(el => {
                    const text = el.innerText || '';
                    if (text.match(/\\d{1,2}:\\d{2}/) && text.length < 500) {
                        events.push({
                            raw: text,
                            html: el.innerHTML
                        });
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
    seen = set()
    
    for raw in raw_events:
        text = raw.get('raw', '')
        
        # Unikaj duplikatów
        if text in seen:
            continue
        seen.add(text)
        
        # Szukaj wzorców czasu: "09:00 - 10:30" lub "9.00-10.30"
        time_match = re.search(r'(\d{1,2})[:\.](\d{2})\s*[-–]\s*(\d{1,2})[:\.](\d{2})', text)
        
        # Szukaj daty: "2024-01-15" lub "15.01.2024"
        date_match = re.search(r'(\d{4})-(\d{2})-(\d{2})|(\d{1,2})\.(\d{1,2})\.(\d{4})', text)
        
        if time_match:
            # Wyciągnij przedmiot
            lines = text.strip().split('\n')
            title = lines[0] if lines else "Zajęcia"
            
            # Wyczyść tytuł
            title = re.sub(r'\d{1,2}[:\.]\\d{2}.*', '', title).strip()
            if not title or len(title) < 3:
                title = "Zajęcia"
            
            event = {
                'title': title[:100],  # Ogranicz długość
                'time_start': f"{time_match.group(1).zfill(2)}:{time_match.group(2)}",
                'time_end': f"{time_match.group(3).zfill(2)}:{time_match.group(4)}",
                'location': '',
                'raw': text[:500]
            }
            
            if date_match:
                if date_match.group(1):  # Format YYYY-MM-DD
                    event['date'] = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
                else:  # Format DD.MM.YYYY
                    event['date'] = f"{date_match.group(6)}-{date_match.group(5).zfill(2)}-{date_match.group(4).zfill(2)}"
            else:
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
            
            event.add('description', f"Źródło: Cambridge")
            
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
        
        # Dodaj info wydarzenie
        event = Event()
        event.add('summary', '⚠️ Sprawdź konfigurację synchronizacji')
        tz = pytz.timezone('Europe/Warsaw')
        event.add('dtstart', datetime.now(tz))
        event.add('dtend', datetime.now(tz))
        event.add('description', 'Pobierz debug-screenshots z GitHub Actions aby sprawdzić co poszło nie tak.')
        event.add('uid', 'info@szkolafilmowa')
        cal.add_component(event)
        
        with open(OUTPUT_FILE, 'wb') as f:
            f.write(cal.to_ical())

if __name__ == "__main__":
    asyncio.run(main())
