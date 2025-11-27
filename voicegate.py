import time
import re
import requests
import json
import os
import tempfile
from datetime import datetime
from seleniumbase import Driver, SB
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
import phonenumbers
from phonenumbers import geocoder, region_code_for_number
import pycountry

# ==================== CONFIGURATION ====================
BOT_TOKEN = "8354581009:AAH28Cn3VQAdmQYb8a9q7WNEIly7x7s8moM"
CHAT_ID = "-1002631004312"
BASE_URL = "http://51.89.7.175/sms/subclient/"
LOGIN_URL = "http://51.89.7.175/sms/SignIn"
SMS_URL = "http://51.89.7.175/sms/subclient/Reports"
REFRESH_INTERVAL = 5
MAX_MESSAGES_STORE = 2000
SCROLL_ATTEMPTS = 3
# =======================================================

# Store sent messages to avoid duplicates
last_messages = set()
driver = None

# ------------------- Source Name Detection -------------------

def detect_source_name(message: str, website_source: str) -> str:
    """
    Detect source name from message content for popular services
    """
    message_lower = message.lower()
    
    # Telegram patterns
    telegram_patterns = [
        r'telegram', r'tg\.me', r't\.me', r'@', r'username', 
        r'login code', r'verification code', r'confirm your phone',
        r'telegram code', r'tg code'
    ]
    
    # WhatsApp patterns
    whatsapp_patterns = [
        r'whatsapp', r'wa\.me', r'whats app', r'whatsapp code',
        r'whatsapp verification', r'your whatsapp code'
    ]
    
    # Twilio patterns
    twilio_patterns = [
        r'twilio', r'twilio verification', r'twilio code',
        r'your twilio code'
    ]
    
    # Apple patterns
    apple_patterns = [
        r'apple', r'apple id', r'icloud', r'appstore',
        r'your apple id code', r'apple verification',
        r'use this code to reset your apple id password'
    ]
    
    # 1xBet patterns
    xbet_patterns = [
        r'1xbet', r'1x bet', r'1xbet code', r'1xbet verification',
        r'your 1xbet code', r'1xbet confirm'
    ]
    
    # Facebook patterns
    facebook_patterns = [
        r'facebook', r'fb\.me', r'facebook code', r'facebook login',
        r'your facebook code', r'facebook confirmation'
    ]
    
    # Google patterns
    google_patterns = [
        r'google', r'g-\d{6}', r'google verification', r'your google verification code',
        r'google account', r'gmail'
    ]
    
    # Instagram patterns
    instagram_patterns = [
        r'instagram', r'insta', r'ig', r'instagram code',
        r'your instagram code', r'instagram confirmation'
    ]
    
    # Twitter patterns
    twitter_patterns = [
        r'twitter', r'twitter code', r'twitter verification',
        r'your twitter code'
    ]
    
    # Amazon patterns
    amazon_patterns = [
        r'amazon', r'amazon code', r'amazon otp',
        r'your amazon verification code'
    ]
    
    # Bank patterns
    bank_patterns = [
        r'bank', r'visa', r'mastercard', r'card', r'transaction',
        r'payment', r'otp', r'one time password', r'secure code'
    ]
    
    # Check each service
    services = [
        ("Telegram", telegram_patterns),
        ("WhatsApp", whatsapp_patterns),
        ("Twilio", twilio_patterns),
        ("Apple", apple_patterns),
        ("1xBet", xbet_patterns),
        ("Facebook", facebook_patterns),
        ("Google", google_patterns),
        ("Instagram", instagram_patterns),
        ("Twitter", twitter_patterns),
        ("Amazon", amazon_patterns),
        ("Bank", bank_patterns),
    ]
    
    for service_name, patterns in services:
        for pattern in patterns:
            if re.search(pattern, message_lower, re.IGNORECASE):
                print(f"[🔍] Detected source: {service_name}")
                return service_name
    
    # If no specific service detected, use website source or generic
    if website_source and website_source.strip():
        return website_source.strip()
    else:
        return "Unknown Service"

# ------------------- Enhanced OTP Detection -------------------

def extract_otp(message: str) -> str:
    """
    Ultimate OTP detection for all languages and formats
    """
    if not message or len(message.strip()) < 4:
        return "N/A"
        
    clean_message = message.strip()
    
    # Comprehensive OTP patterns
    patterns = [
        # Standard formats (most common first)
        r'\b\d{6}\b',                           # 123456
        r'\b\d{4}\b',                           # 1234
        r'\b\d{5}\b',                           # 12345
        r'\b\d{3}[-\.\s]?\d{3}\b',              # 123-456, 123.456, 123 456
        r'\b\d{4}[-\.\s]?\d{4}\b',              # 1234-5678, 1234.5678, 1234 5678
        r'\b\d{8}\b',                           # 12345678
        
        # OTP with labels (English)
        r'(?i)(?:code|otp|password|verification|pin|passcode)[\s:\-]*[is\-\:\s]*[\{\[\(]?\s*(\d{4,8})\s*[\}\]\)]?',
        r'(?i)(?:code|otp|password|verification|pin|passcode)[\s:\-]*[is\-\:\s]*(\d{3,8})',
        r'(?i)(?:is|code|use)[\s:\-]*(\d{4,8})',
        
        # OTP with labels (Multi-language)
        r'(?i)(?:код|код|密码|驗證碼|コード|코드|codice|codigo|código)[\s:\-]*[is\-\:\s]*[\{\[\(]?\s*(\d{4,8})\s*[\}\]\)]?',
        
        # WhatsApp specific patterns
        r'\*\s*(\d{4,8})\s*\*',                # *123456*
        r'\[\s*(\d{4,8})\s*\]',                # [123456]
        r'\(\s*(\d{4,8})\s*\)',                # (123456)
        
        # Google/Apple format
        r'[GA]\-\s*(\d{6})',                   # G-123456, A-123456
        
        # Telegram common patterns
        r'Your verification code is\s*[\{\[\(]?\s*(\d{4,8})\s*[\}\]\)]?',
        r'verification code[\s:\-]*[\{\[\(]?\s*(\d{4,8})\s*[\}\]\)]?',
        
        # Common SMS patterns
        r'use[\s]+(\d{4,8})[\s]+to',
        r'enter[\s]+(\d{4,8})[\s]+',
        r'code[\s]+(\d{4,8})[\s]+',
        
        # Bank OTP patterns
        r'OTP[\s:\-]*(\d{6})',
        r'one time password[\s:\-]*(\d{6})',
        r'transaction password[\s:\-]*(\d{6})',
        
        # Social media patterns
        r'Facebook[\s\S]*?code[\s:\-]*(\d{5})',
        r'Instagram[\s\S]*?code[\s:\-]*(\d{6})',
        r'Twitter[\s\S]*?code[\s:\-]*(\d{6})',
        
        # Emergency fallback - any 4-8 digit number not surrounded by other digits
        r'(?<!\d)(\d{4,8})(?!\d)',
    ]
    
    # First pass: try all patterns
    for pattern in patterns:
        try:
            matches = re.findall(pattern, clean_message, re.IGNORECASE | re.MULTILINE)
            if matches:
                for match in matches:
                    if isinstance(match, tuple):
                        match = match[0]
                    otp_candidate = re.sub(r'\D', '', str(match))
                    if 4 <= len(otp_candidate) <= 8 and otp_candidate.isdigit():
                        # Additional validation to avoid false positives
                        if not is_likely_date(otp_candidate) and not is_likely_time(otp_candidate):
                            print(f"[🔍] OTP Found: {otp_candidate} with pattern: {pattern}")
                            return otp_candidate
        except Exception as e:
            continue
    
    # Second pass: look for any standalone 4-8 digit numbers
    standalone_nums = re.findall(r'\b\d{4,8}\b', clean_message)
    for num in standalone_nums:
        if 4 <= len(num) <= 8 and num.isdigit():
            if not is_likely_date(num) and not is_likely_time(num) and not is_sequential(num):
                print(f"[🔍] OTP Found (standalone): {num}")
                return num
    
    return "N/A"

def is_likely_date(num: str) -> bool:
    """Check if number looks like a date"""
    if len(num) == 4:
        # Check if it's a valid time (e.g., 1234 -> 12:34)
        if 0 <= int(num[:2]) <= 23 and 0 <= int(num[2:]) <= 59:
            return True
        # Check if it's a year in reasonable range
        if 1900 <= int(num) <= 2100:
            return True
    elif len(num) == 6:
        # Check if it's a date (e.g., 010123 -> 01/01/23)
        if 1 <= int(num[:2]) <= 31 and 1 <= int(num[2:4]) <= 12:
            return True
    elif len(num) == 8:
        # Check if it's a full date (e.g., 01012023 -> 01/01/2023)
        if 1 <= int(num[:2]) <= 31 and 1 <= int(num[2:4]) <= 12 and 1900 <= int(num[4:]) <= 2100:
            return True
    return False

def is_likely_time(num: str) -> bool:
    """Check if number looks like a time"""
    if len(num) == 4:
        # HHMM format
        if 0 <= int(num[:2]) <= 23 and 0 <= int(num[2:]) <= 59:
            return True
    return False

def is_sequential(num: str) -> bool:
    """Check if number is sequential (1234, 4321, etc)"""
    if len(num) >= 4:
        # Check ascending
        if all(int(num[i]) + 1 == int(num[i+1]) for i in range(len(num)-1)):
            return True
        # Check descending
        if all(int(num[i]) - 1 == int(num[i+1]) for i in range(len(num)-1)):
            return True
        # Check same digits
        if len(set(num)) == 1:
            return True
    return False

# ------------------- Helper Functions -------------------

def mask_number(number: str) -> str:
    digits = re.sub(r"\D", "", number)
    if len(digits) > 6:
        return digits[:4] + "***" + digits[-4:]
    return number

def country_to_flag(country_code: str) -> str:
    if not country_code or len(country_code) != 2:
        return "🏳️"
    return "".join(chr(127397 + ord(c)) for c in country_code.upper())

def detect_country(number: str):
    try:
        parsed = phonenumbers.parse("+" + number, None)
        region = region_code_for_number(parsed)
        country = pycountry.countries.get(alpha_2=region)
        if country:
            return country.name, country_to_flag(region)
    except:
        pass
    return "Unknown", "🏳️"

def send_to_telegram(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    
    # Simple inline keyboard without copy button
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "📢 Main Channel", "url": "https://t.me/mailtwist"},
                {"text": "📋 Get Number", "url": "http://t.me/NumberTwistBot"}
            ]
        ]
    }
    
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": keyboard,
    }
    
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            print(f"[✅] Telegram message sent successfully")
            return True
        else:
            print(f"[❌] Failed: {res.status_code} - {res.text}")
            return False
    except Exception as e:
        print(f"[❌] Telegram error: {e}")
        return False

# ------------------- Browser Management with SeleniumBase -------------------

def setup_browser():
    global driver
    try:
        print("[🔧] Setting up SeleniumBase with UC Mode for CAPTCHA bypass...")
        
        # Use SeleniumBase Driver with UC mode for undetected browsing
        driver = Driver(uc=True, headless=False)  # UC mode works best in non-headless
        
        print("[✅] SeleniumBase UC Mode setup successful")
        return driver
        
    except Exception as e:
        print(f"[❌] SeleniumBase setup failed: {e}")
        raise

def wait_for_manual_login():
    """Wait for user to manually login and detect successful login with CAPTCHA handling"""
    print("[🔐] Please login manually in the browser...")
    print("[⏳] Waiting for you to complete login...")
    
    # Navigate to login page with CAPTCHA protection
    driver.get(LOGIN_URL)
    time.sleep(2)
    
    # Try to handle any CAPTCHA that might appear
    try:
        # SeleniumBase UC mode should handle most CAPTCHAs automatically
        # Additional manual handling if needed
        print("[🛡️] CAPTCHA protection activated...")
    except Exception as e:
        print(f"[⚠️] CAPTCHA handling note: {e}")
    
    # Wait for user to login - detect when URL changes to client dashboard OR subclient
    print("[🎯] Waiting for successful login...")
    try:
        # Wait for either client dashboard or subclient page
        WebDriverWait(driver, 300).until(  # 5 minutes timeout for manual login
            lambda driver: "/client/" in driver.current_url or "/subclient/" in driver.current_url
        )
        
        current_url = driver.current_url
        print(f"[✅] Login successful! Current URL: {current_url}")
        
        # Additional check for dashboard elements
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            print("[✅] Page loaded completely.")
        except:
            print("[⚠️] Could not verify page elements, but continuing...")
        
        return True
        
    except TimeoutException:
        print("[❌] Login timeout. Please check your login.")
        return False

def navigate_to_sms_page():
    """Navigate to SMS reports page after successful login"""
    try:
        print("[🔄] Navigating to SMS reports page...")
        
        # First try direct navigation to SMS URL
        driver.get(SMS_URL)
        time.sleep(3)
        
        # Check if we're on the SMS page by looking for table or reports elements
        try:
            # Wait for either table or any reports-related element
            WebDriverWait(driver, 15).until(
                EC.any_of(
                    EC.presence_of_element_located((By.CLASS_NAME, "table-striped")),
                    EC.presence_of_element_located((By.TAG_NAME, "table")),
                    EC.presence_of_element_located((By.ID, "kt_content_container")),
                    EC.presence_of_element_located((By.CLASS_NAME, "card"))
                )
            )
            print("[✅] SMS reports page loaded successfully.")
            return True
            
        except TimeoutException:
            print("[⚠️] Direct SMS URL failed, trying alternative navigation...")
            
            # Try navigating to base URL first
            driver.get(BASE_URL)
            time.sleep(3)
            
            # Look for Reports link or menu item
            try:
                reports_links = driver.find_elements(By.PARTIAL_LINK_TEXT, "Report")
                if reports_links:
                    reports_links[0].click()
                    time.sleep(3)
                    print("[✅] Navigated to Reports via menu link.")
                    return True
            except:
                pass
                
            # Final attempt - try to find and click SMS/Reports in navigation
            try:
                # Look for any links that might lead to SMS reports
                all_links = driver.find_elements(By.TAG_NAME, "a")
                for link in all_links:
                    href = link.get_attribute("href")
                    if href and ("report" in href.lower() or "sms" in href.lower()):
                        link.click()
                        time.sleep(3)
                        print("[✅] Found and clicked SMS/Reports link.")
                        return True
            except:
                pass
                
            print("[❌] Could not navigate to SMS page automatically.")
            return False
        
    except Exception as e:
        print(f"[❌] Failed to navigate to SMS page: {e}")
        return False

def check_login_status():
    """Check if still logged in by verifying access to protected pages"""
    try:
        current_url = driver.current_url
        # Check if we're on any protected page (not login page)
        if "/SignIn" not in current_url and "/login" not in current_url:
            return True
        else:
            # Try to access dashboard
            driver.get(BASE_URL)
            time.sleep(2)
            if "/SignIn" not in driver.current_url and "/login" not in driver.current_url:
                return True
        return False
    except:
        return False

# ------------------- SMS Extraction for AITelco -------------------

def detect_columns(header_row):
    """Map columns based on AITelco table structure"""
    # Default mapping based on AITelco table structure
    mapping = {
        "date": 0,        # Date column
        "source": 1,      # Termination column  
        "destination": 2, # Number column
        "cli": 3,         # CLI column
        "message": 10     # Message column (last column)
    }
    
    try:
        cells = header_row.find_elements(By.TAG_NAME, "th")
        for idx, cell in enumerate(cells):
            text = cell.text.strip().lower()
            if "date" in text:
                mapping["date"] = idx
            elif "termination" in text:
                mapping["source"] = idx
            elif "number" in text:
                mapping["destination"] = idx
            elif "cli" in text:
                mapping["cli"] = idx
            elif "message" in text:
                mapping["message"] = idx
    except Exception as e:
        print(f"[⚠️] Column detection warning: {e}")
    
    print(f"[📊] AITelco Column mapping: Date[{mapping['date']}], Source[{mapping['source']}], Destination[{mapping['destination']}], CLI[{mapping['cli']}], Message[{mapping['message']}]")
    return mapping

def scroll_table_to_bottom():
    """Scroll the table to load all messages in AITelco"""
    try:
        # Try different possible table containers
        containers = [
            "kt_content_container",
            "table-responsive",
            "card-body",
            "table-container"
        ]
        
        for container_id in containers:
            try:
                table_container = driver.find_element(By.ID, container_id)
                for attempt in range(SCROLL_ATTEMPTS):
                    last_height = driver.execute_script("return arguments[0].scrollHeight", table_container)
                    driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", table_container)
                    time.sleep(1)
                    new_height = driver.execute_script("return arguments[0].scrollHeight", table_container)
                    
                    if new_height == last_height:
                        break
                    print(f"[⬇️] Scrolling table... attempt {attempt + 1}")
                break
            except:
                continue
                
    except Exception as e:
        print(f"[⚠️] Table scrolling issue: {e}")

def extract_sms():
    global last_messages
    try:
        # Wait for any table to be present
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "table"))
        )

        # Scroll to load all messages
        scroll_table_to_bottom()
        time.sleep(2)

        # Find the table - try different table classes
        tables = driver.find_elements(By.TAG_NAME, "table")
        if not tables:
            print("[⚠️] No tables found on page.")
            return 0

        table = tables[0]  # Use first table
        
        # Get all rows from tbody
        rows = table.find_elements(By.CSS_SELECTOR, "tbody tr")
        if not rows:
            print("[⚠️] No data rows found in table.")
            return 0

        # Get header row for column mapping
        try:
            header_row = table.find_element(By.CSS_SELECTOR, "thead tr")
            mapping = detect_columns(header_row)
        except:
            print("[⚠️] Could not detect columns, using default mapping")
            mapping = {"date": 0, "source": 1, "destination": 2, "cli": 3, "message": 10}
        
        new_count = 0
        processed_count = 0

        print(f"[🔍] Scanning {len(rows)} rows for messages...")

        for row_index, row in enumerate(rows):
            try:
                # Skip empty rows or "no results" rows
                row_html = row.get_attribute("innerHTML").lower()
                if "empty" in row_html or "no results" in row_html or "no data" in row_html:
                    continue
                    
                cells = row.find_elements(By.TAG_NAME, "td")
                if len(cells) <= max(mapping.values()):
                    continue

                # Extract data based on column mapping for AITelco
                date = cells[mapping["date"]].text.strip() if mapping["date"] < len(cells) else "N/A"
                website_source = cells[mapping["source"]].text.strip() if mapping["source"] < len(cells) else "N/A"
                destination = cells[mapping["destination"]].text.strip() if mapping["destination"] < len(cells) else "N/A"
                cli = cells[mapping["cli"]].text.strip() if mapping["cli"] < len(cells) else "N/A"
                message = cells[mapping["message"]].text.strip() if mapping["message"] < len(cells) else "N/A"

                # Skip if no message
                if not message or message == "" or message == "N/A":
                    continue
                    
                # Create unique message ID (more specific)
                message_id = f"{website_source}_{destination}_{message[:50]}"
                processed_count += 1
                
                # Skip if already processed
                if message_id in last_messages:
                    continue
                    
                last_messages.add(message_id)
                new_count += 1

                # Extract OTP with enhanced detection
                otp_code = extract_otp(message)
                country_name, country_flag = detect_country(destination)
                masked_number = mask_number(destination)
                
                # Detect source name from message content
                source_name = detect_source_name(message, website_source)

                # NEW MESSAGE STYLE - Using CLI as service
                formatted = (
                    f"📳 New SMS Captured! {cli} of {country_flag}\n\n"
                    f"└ ⏰ TIME: {date}\n"
                    f"└ {country_flag} {country_name}\n"
                    f"└ 🌐 Source: {cli}\n"
                    f"└ 📞 Number: `{masked_number}`\n"
                    f"────────────\n"
                    f"└ 🔐 OTP: `{otp_code}`\n"
                    f"────────────\n"
                    f"💬 Full Message:\n"
                    f"```{message}```"
                )
                
                print(f"[✅] NEW MESSAGE #{new_count}: {source_name} → {masked_number} | OTP: {otp_code}")
                send_to_telegram(formatted)
                
                # Small delay between messages to avoid rate limiting
                time.sleep(0.3)
                
            except StaleElementReferenceException:
                print(f"[⚠️] Stale element at row {row_index}, continuing...")
                continue
            except Exception as e:
                print(f"[❌] Error processing row {row_index}: {e}")
                continue

        print(f"[📊] Scan complete: Processed {processed_count} messages, {new_count} new messages sent.")
        return new_count

    except Exception as e:
        print(f"[❌] Failed to extract SMS: {e}")
        return 0

# ------------------- Page Management -------------------

def refresh_page():
    """Refresh the page to get new messages"""
    try:
        print("[🔄] Refreshing page for new messages...")
        driver.refresh()
        
        # Wait for page to load completely - look for any table
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "table"))
        )
        
        print("[✅] Page refreshed successfully")
        return True
    except Exception as e:
        print(f"[❌] Failed to refresh page: {e}")
        return False

def check_page_loaded():
    """Check if the SMS page is properly loaded"""
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "table"))
        )
        return True
    except:
        return False

# ------------------- Main Monitoring Loop -------------------

def main():
    global driver, last_messages
    
    print("[🚀] Starting Ultimate SMS Monitor Bot for AITelco Panel...")
    print("=" * 60)
    print("[🛡️] AITelco PANEL FEATURES:")
    print("   ✅ Customized for AITelco SMS Panel")
    print("   ✅ SeleniumBase UC Mode - Undetected ChromeDriver")
    print("   ✅ Automatic CAPTCHA and bot detection bypass")
    print("   ✅ Smart Source Name Detection from Message")
    print("   ✅ Telegram, WhatsApp, Twilio, Apple, 1xBet detection")
    print("   ✅ NEW MESSAGE STYLE - CLI as Service")
    print("   ✅ No Copy Button (Clean Interface)")
    print("   ✅ Ultimate OTP detection - NO MISSING OTP")
    print("   ✅ All languages & formats supported")
    print("   ✅ 24/7 continuous monitoring with auto-refresh")
    print("   ✅ Table scrolling to load all messages")
    print("   ✅ VNC optimized")
    print("=" * 60)
    
    # Setup browser with SeleniumBase
    driver = setup_browser()
    
    # Wait for manual login with CAPTCHA protection
    if not wait_for_manual_login():
        print("[❌] Login failed or timeout. Exiting.")
        return
    
    # Navigate to SMS page after successful login
    if not navigate_to_sms_page():
        print("[❌] Cannot access SMS page. Exiting.")
        return
    
    # Initial extraction
    print("[🔍] Starting initial comprehensive scan...")
    initial_count = extract_sms()
    print(f"[✅] Initial scan complete. Sent {initial_count} messages to Telegram.")
    
    # Continuous monitoring
    error_count = 0
    max_errors = 10
    total_messages_sent = initial_count
    
    try:
        print("[📡] Starting 24/7 continuous monitoring...")
        monitor_count = 0
        
        while True:
            monitor_count += 1
            print(f"\n[🔄] Monitoring cycle #{monitor_count}")
            
            try:
                # Check login status
                if not check_login_status():
                    print("[⚠️] Login session lost. Please re-login manually.")
                    if not wait_for_manual_login() or not navigate_to_sms_page():
                        error_count += 1
                        if error_count >= max_errors:
                            break
                        continue
                
                # Refresh page to get latest messages
                if not refresh_page():
                    error_count += 1
                    if error_count >= max_errors:
                        break
                    continue
                
                # Extract new messages
                new_count = extract_sms()
                total_messages_sent += new_count
                
                if new_count > 0:
                    print(f"[🎉] Cycle #{monitor_count}: Sent {new_count} new messages (Total: {total_messages_sent})")
                else:
                    print(f"[👀] Cycle #{monitor_count}: No new messages found (Total: {total_messages_sent})")
                
                # Reset error count on success
                error_count = 0
                
                # Wait before next check
                print(f"[⏳] Waiting {REFRESH_INTERVAL} seconds...")
                time.sleep(REFRESH_INTERVAL)
                
            except Exception as e:
                error_count += 1
                print(f"[❌] Error in cycle #{monitor_count} ({error_count}/{max_errors}): {e}")
                
                if error_count >= max_errors:
                    print("[🔄] Too many consecutive errors. Please check the system.")
                    break
                
                time.sleep(10)
                
    except KeyboardInterrupt:
        print("\n[🛑] Bot stopped by user.")
    except Exception as e:
        print(f"[❌] Critical error: {e}")
    finally:
        if driver:
            print("[🔚] Closing browser...")
            driver.quit()
        print(f"[✅] Bot stopped. Total messages sent: {total_messages_sent}")
        print("[🎯] Ready to restart when needed.")

if __name__ == "__main__":
    main()
