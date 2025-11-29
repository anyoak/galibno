import os
import time
import random
import logging
from seleniumbase import Driver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import requests

# Configuration
CONFIG = {
    'base_url': 'https://web.facebook.com/login/identify/?ctx=recover&from_login_screen=0',
    'phone_numbers_file': 'phone_numbers.txt',
    'telegram_bot_token': 'YOUR_TELEGRAM_BOT_TOKEN',
    'telegram_channel_id': '-1003481502962',
    'timeout': 30,
    'proxy': 'aagrflash:aagrflash@as.75ce620de1d51edc.abcproxy.vip:4950'
}

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('facebook_recovery.log'),
        logging.StreamHandler()
    ]
)

class FacebookRecoveryBot:
    def __init__(self, proxy=None):
        self.driver = None
        self.proxy = proxy
        self.setup_driver()
        
    def setup_driver(self):
        """Setup SeleniumBase driver with proxy and stealth options"""
        try:
            driver_config = {
                'headless': False,
                'uc': True,
                'undetectable': True,
            }
            
            # Add proxy without authentication popup
            if self.proxy:
                driver_config['proxy'] = self.proxy
                logging.info(f"Using proxy: {self.proxy.split('@')[-1]}")
            
            self.driver = Driver(**driver_config)
            
            # Additional stealth settings
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            self.driver.set_window_size(random.randint(1200, 1400), random.randint(800, 1000))
            
            logging.info("Driver setup completed")
            
        except Exception as e:
            logging.error(f"Error setting up driver: {e}")
            raise
        
    def human_like_delay(self, min_seconds=2, max_seconds=5):
        """Random delay to mimic human behavior"""
        delay = random.uniform(min_seconds, max_seconds)
        time.sleep(delay)
        
    def human_like_typing(self, element, text):
        """Type like a human with random delays"""
        for char in text:
            element.send_keys(char)
            time.sleep(random.uniform(0.1, 0.3))
            
    def human_like_click(self, element):
        """Click like a human with mouse movements"""
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", element)
            self.human_like_delay(0.5, 1)
            
            actions = ActionChains(self.driver)
            actions.move_to_element_with_offset(element, random.randint(-2, 2), random.randint(-2, 2))
            actions.pause(random.uniform(0.2, 0.5))
            actions.click()
            actions.perform()
        except:
            element.click()
        
    def send_telegram_message(self, message):
        """Send message to Telegram channel"""
        try:
            url = f"https://api.telegram.org/bot{CONFIG['telegram_bot_token']}/sendMessage"
            payload = {
                'chat_id': CONFIG['telegram_channel_id'],
                'text': message,
                'parse_mode': 'HTML'
            }
            response = requests.post(url, data=payload, timeout=10)
            if response.status_code == 200:
                logging.info(f"Telegram message sent: {message}")
            else:
                logging.error(f"Failed to send Telegram message: {response.text}")
        except Exception as e:
            logging.error(f"Error sending Telegram message: {e}")

    def wait_for_element(self, by, value, timeout=CONFIG['timeout']):
        """Wait for element to be present"""
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, value))
            )
        except TimeoutException:
            logging.error(f"Element not found: {by} = {value}")
            return None

    def wait_for_element_clickable(self, by, value, timeout=CONFIG['timeout']):
        """Wait for element to be clickable"""
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((by, value))
            )
        except TimeoutException:
            logging.error(f"Element not clickable: {by} = {value}")
            return None

    def detect_page_state(self):
        """Detect specific page states based on text content and elements"""
        try:
            page_text = self.driver.page_source.lower()
            current_url = self.driver.current_url.lower()
            
            # Check for "No Search Results"
            if "no search results" in page_text or "your search did not return any results" in page_text:
                logging.info("Detected: No Search Results page")
                return "no_results"
            
            # Check for "We'll send you a code to your mobile number"
            if "we'll send you a code to your mobile number" in page_text or "we can send a login code to" in page_text:
                logging.info("Detected: Account Found - Code Send Page")
                return "account_found"
            
            # Check for "Enter Security Code"
            if "enter security code" in page_text:
                logging.info("Detected: Enter Security Code page")
                return "enter_code"
            
            # Check for "Try another way"
            if "try another way" in page_text:
                logging.info("Detected: Try Another Way page")
                return "try_another_way"
            
            # Check for Reset Password page with SMS options
            reset_password_elements = [
                "reset your password",
                "how do you want to receive the code",
                "send code via sms"
            ]
            
            if any(text in page_text for text in reset_password_elements):
                sms_radio = self.driver.find_elements(By.XPATH, "//input[contains(@value, 'send_sms')]")
                if sms_radio:
                    logging.info("Detected: Reset Password Method Selection page")
                    return "reset_method"
            
            # Check for Find Your Account page
            if "find your account" in page_text and self.driver.find_elements(By.ID, "identify_email"):
                logging.info("Detected: Find Your Account page")
                return "find_account"
            
            # Check for block
            block_indicators = ["temporarily blocked", "misusing this feature", "community standards", "too fast"]
            for indicator in block_indicators:
                if indicator in page_text:
                    logging.error("Facebook block detected!")
                    return "blocked"
            
            logging.warning(f"Unknown page state. URL: {current_url}")
            return "unknown"
            
        except Exception as e:
            logging.error(f"Error in page detection: {e}")
            return "unknown"

    def process_phone_number(self, phone_number):
        """Process a single phone number through the recovery flow"""
        logging.info(f"🔍 Processing: {phone_number}")
        
        try:
            # Navigate to the recovery page
            logging.info("🌐 Navigating to Facebook recovery page...")
            self.driver.get(CONFIG['base_url'])
            self.human_like_delay(3, 5)
            
            # Detect initial page state
            page_state = self.detect_page_state()
            
            if page_state == "blocked":
                message = f"🚫 Facebook Blocked\n📱 Phone: {phone_number}"
                self.send_telegram_message(message)
                return "blocked"
            
            if page_state != "find_account":
                logging.warning(f"Unexpected initial page: {page_state}")
                # Try to reload
                self.driver.get(CONFIG['base_url'])
                self.human_like_delay(2, 4)
                page_state = self.detect_page_state()
            
            # Step 1: Enter phone number and search
            if page_state == "find_account":
                email_input = self.wait_for_element(By.ID, "identify_email")
                if not email_input:
                    logging.error("❌ Could not find phone input field")
                    return "error"
                
                email_input.clear()
                self.human_like_delay(1, 2)
                self.human_like_typing(email_input, phone_number)
                logging.info(f"📝 Entered phone number: {phone_number}")
                self.human_like_delay(1, 2)
                
                # Click Search button
                search_btn = self.wait_for_element_clickable(By.ID, "did_submit")
                if search_btn:
                    self.human_like_click(search_btn)
                    logging.info("🔍 Clicked Search button")
                    self.human_like_delay(4, 6)
                else:
                    logging.error("❌ Search button not found")
                    return "error"
            else:
                logging.error(f"❌ Not on Find Account page. Current: {page_state}")
                return "error"
            
            # Step 2: Check search results
            page_state = self.detect_page_state()
            logging.info(f"📄 Page after search: {page_state}")
            
            if page_state == "no_results":
                message = f"❌ Account Not Found\n📱 Phone: {phone_number}\n⏰ Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                self.send_telegram_message(message)
                logging.info(f"❌ No account found for {phone_number}")
                return "not_found"
            
            elif page_state == "account_found":
                message = f"✅ Account Found!\n📱 Phone: {phone_number}\n⏰ Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                self.send_telegram_message(message)
                logging.info(f"✅ Account found for {phone_number}")
                return self.handle_account_found_page(phone_number)
            
            elif page_state == "reset_method":
                message = f"✅ Account Found!\n📱 Phone: {phone_number}\n⏰ Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                self.send_telegram_message(message)
                logging.info(f"✅ Account found for {phone_number}")
                return self.handle_reset_password_page(phone_number)
            
            elif page_state == "blocked":
                message = f"🚫 Blocked After Search\n📱 Phone: {phone_number}"
                self.send_telegram_message(message)
                return "blocked"
            
            else:
                logging.warning(f"Unexpected page after search: {page_state}")
                message = f"❌ Account Not Found\n📱 Phone: {phone_number}\n⏰ Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                self.send_telegram_message(message)
                return "not_found"
                
        except Exception as e:
            logging.error(f"❌ Error processing {phone_number}: {e}")
            message = f"❌ Processing Error\n📱 Phone: {phone_number}\n⚠️ Error: {str(e)}"
            self.send_telegram_message(message)
            return "error"

    def handle_account_found_page(self, phone_number):
        """Handle the account found page - click Continue"""
        logging.info("🔄 Handling Account Found page...")
        
        try:
            # Find and click Continue button
            continue_btn = self.wait_for_element_clickable(
                By.XPATH, 
                "//button[contains(text(), 'Continue')]"
            )
            
            if not continue_btn:
                # Try alternative selectors
                continue_btn = self.wait_for_element_clickable(By.XPATH, "//input[@type='submit']")
                continue_btn = self.wait_for_element_clickable(By.XPATH, "//button[@type='submit']")
            
            if not continue_btn:
                logging.error("❌ Continue button not found")
                return "error"
                
            self.human_like_click(continue_btn)
            logging.info("➡️ Clicked Continue button")
            self.human_like_delay(5, 8)
            
            # Check result after continue
            page_state = self.detect_page_state()
            logging.info(f"📄 Page after continue: {page_state}")
            
            if page_state == "enter_code":
                message = f"✅ OTP Send Success!\n📱 Phone: {phone_number}\n⏰ Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                self.send_telegram_message(message)
                logging.info(f"✅ OTP sent successfully to {phone_number}")
                return "success"
            
            elif page_state == "try_another_way":
                logging.info("🔄 Trying another way...")
                return self.handle_try_another_way(phone_number)
            
            elif page_state == "blocked":
                message = f"🚫 Blocked After Continue\n📱 Phone: {phone_number}"
                self.send_telegram_message(message)
                return "blocked"
            
            else:
                message = f"❌ Cannot Send OTP\n📱 Phone: {phone_number}\n⚠️ Status: {page_state}"
                self.send_telegram_message(message)
                logging.warning(f"❌ Could not send OTP to {phone_number}")
                return "error"
                
        except Exception as e:
            logging.error(f"❌ Error in account found page: {e}")
            message = f"❌ Continue Error\n📱 Phone: {phone_number}\n⚠️ Error: {str(e)}"
            self.send_telegram_message(message)
            return "error"

    def handle_try_another_way(self, phone_number):
        """Handle Try Another Way page - click it and select SMS"""
        logging.info("🔄 Handling Try Another Way page...")
        
        try:
            # Click Try Another Way button
            try_another_btn = self.wait_for_element_clickable(
                By.XPATH, 
                "//a[contains(text(), 'Try another way')]"
            )
            
            if not try_another_btn:
                try_another_btn = self.wait_for_element_clickable(
                    By.XPATH, 
                    "//button[contains(text(), 'Try another way')]"
                )
            
            if try_another_btn:
                self.human_like_click(try_another_btn)
                logging.info("🔄 Clicked Try Another Way")
                self.human_like_delay(3, 5)
            
            # Now select Send via SMS option
            sms_option = self.wait_for_element_clickable(
                By.XPATH, 
                "//*[contains(text(), 'Send via SMS')]"
            )
            
            if not sms_option:
                # Try radio button
                sms_option = self.wait_for_element_clickable(
                    By.XPATH, 
                    "//input[contains(@value, 'sms') or contains(@value, 'send_sms')]"
                )
            
            if sms_option:
                self.human_like_click(sms_option)
                logging.info("📱 Selected Send via SMS")
                self.human_like_delay(1, 2)
            
            # Click Continue
            continue_btn = self.wait_for_element_clickable(
                By.XPATH, 
                "//button[contains(text(), 'Continue')]"
            )
            
            if continue_btn:
                self.human_like_click(continue_btn)
                logging.info("➡️ Clicked Continue after SMS selection")
                self.human_like_delay(5, 8)
                
                # Check if OTP was sent
                page_state = self.detect_page_state()
                if page_state == "enter_code":
                    message = f"✅ OTP Send Success!\n📱 Phone: {phone_number}\n⏰ Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                    self.send_telegram_message(message)
                    logging.info(f"✅ OTP sent successfully to {phone_number}")
                    return "success"
                else:
                    message = f"❌ Cannot Send OTP via SMS\n📱 Phone: {phone_number}\n⚠️ Status: {page_state}"
                    self.send_telegram_message(message)
                    return "error"
            else:
                logging.error("❌ Continue button not found in Try Another Way")
                return "error"
                
        except Exception as e:
            logging.error(f"❌ Error in Try Another Way: {e}")
            message = f"❌ Try Another Way Error\n📱 Phone: {phone_number}\n⚠️ Error: {str(e)}"
            self.send_telegram_message(message)
            return "error"

    def handle_reset_password_page(self, phone_number):
        """Handle the Reset Your Password page"""
        logging.info("🔄 Handling Reset Password page...")
        
        try:
            # Check if SMS is already selected
            sms_radio = self.wait_for_element(By.XPATH, "//input[contains(@value, 'send_sms')]")
            if not sms_radio:
                logging.error("❌ SMS radio button not found")
                return "error"
            
            # Select SMS if not selected
            if not sms_radio.is_selected():
                self.human_like_click(sms_radio)
                self.human_like_delay(1, 2)
                logging.info("✅ Selected SMS option")
            
            # Click Continue
            continue_btn = self.wait_for_element_clickable(By.XPATH, "//button[@name='reset_action']")
            
            if not continue_btn:
                continue_btn = self.wait_for_element_clickable(By.XPATH, "//button[contains(text(), 'Continue')]")
            
            if continue_btn:
                self.human_like_click(continue_btn)
                logging.info("➡️ Clicked Continue button")
                self.human_like_delay(5, 8)
                
                page_state = self.detect_page_state()
                if page_state == "enter_code":
                    message = f"✅ OTP Send Success!\n📱 Phone: {phone_number}\n⏰ Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                    self.send_telegram_message(message)
                    logging.info(f"✅ OTP sent successfully to {phone_number}")
                    return "success"
                else:
                    message = f"❌ Cannot Send OTP\n📱 Phone: {phone_number}\n⚠️ Status: {page_state}"
                    self.send_telegram_message(message)
                    return "error"
            else:
                logging.error("❌ Continue button not found")
                return "error"
                
        except Exception as e:
            logging.error(f"❌ Error in reset password: {e}")
            message = f"❌ Reset Error\n📱 Phone: {phone_number}\n⚠️ Error: {str(e)}"
            self.send_telegram_message(message)
            return "error"

    def close(self):
        """Close the browser"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass

def main():
    """Main function"""
    # Check if phone numbers file exists
    if not os.path.exists(CONFIG['phone_numbers_file']):
        logging.error(f"Phone numbers file not found!")
        with open(CONFIG['phone_numbers_file'], 'w') as f:
            f.write("+1234567890\n+0987654321\n")
        logging.info(f"Sample file created: {CONFIG['phone_numbers_file']}")
        return

    # Read phone numbers
    with open(CONFIG['phone_numbers_file'], 'r') as f:
        phone_numbers = [line.strip() for line in f if line.strip()]
    
    if not phone_numbers:
        logging.error("No phone numbers found!")
        return

    logging.info(f"📱 Loaded {len(phone_numbers)} phone numbers")
    
    # Create bot instance with proxy
    bot = FacebookRecoveryBot(proxy=CONFIG['proxy'])
    
    successful = 0
    not_found = 0
    blocked = 0
    errors = 0
    
    try:
        for i, phone_number in enumerate(phone_numbers, 1):
            logging.info(f"🔨 Processing {i}/{len(phone_numbers)}: {phone_number}")
            
            result = bot.process_phone_number(phone_number)
            
            if result == "success":
                successful += 1
            elif result == "not_found":
                not_found += 1
            elif result == "blocked":
                blocked += 1
            else:
                errors += 1
            
            # Log current progress
            logging.info(f"📊 Progress: {successful}✅ {not_found}❌ {blocked}🚫 {errors}⚠️")
            
            # Wait 5 seconds before next number (same tab)
            if i < len(phone_numbers):
                logging.info("⏳ Waiting 5 seconds for next number...")
                time.sleep(5)
                
                # Refresh the page for next number (same URL)
                logging.info("🔄 Refreshing page for next number...")
                bot.driver.get(CONFIG['base_url'])
                bot.human_like_delay(2, 3)
            
    except KeyboardInterrupt:
        logging.info("🛑 Process interrupted by user")
    except Exception as e:
        logging.error(f"💥 Unexpected error: {e}")
    finally:
        bot.close()
    
    # Final summary
    final_message = f"""
📊 Facebook Recovery Bot - Final Report
✅ OTP Sent Success: {successful}
❌ Account Not Found: {not_found}
🚫 Blocked: {blocked}
⚠️ Errors: {errors}
📱 Total Processed: {len(phone_numbers)}
⏰ Completed: {time.strftime('%Y-%m-%d %H:%M:%S')}
    """
    logging.info(final_message)
    
    # Send final report to Telegram
    try:
        bot_temp = FacebookRecoveryBot(proxy=CONFIG['proxy'])
        bot_temp.send_telegram_message(final_message)
        bot_temp.close()
    except Exception as e:
        logging.error(f"Error sending final Telegram message: {e}")

if __name__ == "__main__":
    main()