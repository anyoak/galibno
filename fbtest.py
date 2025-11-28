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
    'telegram_bot_token': '8301109365:AAEyEPV0qT2V1ecI8vQK3i69wgV1taKQOck',
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
        self.setup_driver(proxy)
        
    def setup_driver(self, proxy):
        """Setup SeleniumBase driver with proxy and stealth options"""
        try:
            driver_config = {
                'headless': False,  # Set to True for headless
                'uc': True,  # Undetectable Chrome
                'undetectable': True,  # Anti-detection
                'disable_gpu': False,
                'user_data_dir': None,
                'disable_dev_shm_usage': True,
                'no_sandbox': True,
            }
            
            # Add proxy if provided
            if proxy:
                driver_config['proxy'] = proxy
                logging.info(f"Using proxy: {proxy.split('@')[-1]}")
            
            self.driver = Driver(**driver_config)
            
            # Additional stealth settings
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            self.driver.execute_script("Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]})")
            self.driver.execute_script("Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']})")
            
            # Set window size to look more human
            self.driver.set_window_size(random.randint(1200, 1400), random.randint(800, 1000))
            
            logging.info("Driver setup completed with stealth mode")
            
        except Exception as e:
            logging.error(f"Error setting up driver: {e}")
            raise
        
    def human_like_delay(self, min_seconds=2, max_seconds=5):
        """Random delay to mimic human behavior"""
        delay = random.uniform(min_seconds, max_seconds)
        logging.debug(f"Human delay: {delay:.2f} seconds")
        time.sleep(delay)
        
    def human_like_typing(self, element, text):
        """Type like a human with random delays"""
        for char in text:
            element.send_keys(char)
            time.sleep(random.uniform(0.08, 0.2))  # Random typing speed
            
    def human_like_click(self, element):
        """Click like a human with mouse movements"""
        actions = ActionChains(self.driver)
        # Move to element with slight offset
        actions.move_to_element_with_offset(element, random.randint(-5, 5), random.randint(-5, 5))
        actions.pause(random.uniform(0.1, 0.3))
        actions.click()
        actions.perform()
        
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

    def check_for_block(self):
        """Check if Facebook has blocked us"""
        try:
            block_indicators = [
                "//*[contains(text(), 'Temporarily Blocked')]",
                "//*[contains(text(), 'misusing this feature')]",
                "//*[contains(text(), 'Community Standards')]",
                "//*[contains(text(), 'too fast')]",
                "//*[contains(text(), 'blocked')]",
                "//*[contains(text(), 'security check')]"
            ]
            
            for indicator in block_indicators:
                if self.driver.find_elements(By.XPATH, indicator):
                    logging.error("Facebook has temporarily blocked the request!")
                    return True
                    
            # Check for CAPTCHA
            captcha_indicators = [
                "//*[contains(text(), 'captcha')]",
                "//*[contains(text(), 'security check')]",
                "//img[contains(@src, 'captcha')]"
            ]
            
            for indicator in captcha_indicators:
                if self.driver.find_elements(By.XPATH, indicator):
                    logging.error("CAPTCHA detected!")
                    return True
                    
            return False
        except:
            return False

    def detect_current_page(self):
        """Detect current Facebook page state"""
        try:
            # Check for block first
            if self.check_for_block():
                return "blocked"
            
            # Check URL patterns
            current_url = self.driver.current_url.lower()
            
            if 'login/identify' in current_url:
                # Verify it's the find account page
                if self.driver.find_elements(By.ID, "identify_email"):
                    logging.info("Detected: Find Your Account page")
                    return "find_account"
                    
            elif 'recover/initiate' in current_url:
                # Verify it's the reset password page
                if self.driver.find_elements(By.XPATH, "//input[contains(@value, 'send_sms')]"):
                    logging.info("Detected: Reset Password page")
                    return "reset_password"
                    
            elif 'recover/code' in current_url:
                # Verify it's the enter code page
                if self.driver.find_elements(By.ID, "recovery_code_entry"):
                    logging.info("Detected: Enter Code page")
                    return "enter_code"
            
            # Check for no results
            no_results_texts = [
                "no search results",
                "did not return any results",
                "no account found"
            ]
            
            page_text = self.driver.page_source.lower()
            for text in no_results_texts:
                if text in page_text:
                    logging.info("Detected: No Results")
                    return "no_results"
            
            # Element-based detection as fallback
            if self.driver.find_elements(By.ID, "identify_email"):
                return "find_account"
            elif self.driver.find_elements(By.XPATH, "//input[contains(@value, 'send_sms')]"):
                return "reset_password"
            elif self.driver.find_elements(By.ID, "recovery_code_entry"):
                return "enter_code"
                
            logging.warning("Page state: Unknown")
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
            self.human_like_delay(3, 6)
            
            # Check for block
            if self.check_for_block():
                message = f"🚫 Facebook Blocked\n📱 Phone: {phone_number}\n⏰ Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                self.send_telegram_message(message)
                return "blocked"
            
            # Detect current page
            page_state = self.detect_current_page()
            logging.info(f"📄 Current page: {page_state}")
            
            if page_state == "find_account":
                return self.handle_find_account(phone_number)
            elif page_state == "reset_password":
                return self.handle_reset_password(phone_number)
            elif page_state == "blocked":
                message = f"🚫 Blocked on Entry\n📱 Phone: {phone_number}\n⏰ Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                self.send_telegram_message(message)
                return "blocked"
            else:
                logging.error(f"❓ Unknown page state: {page_state}")
                return "error"
                
        except Exception as e:
            logging.error(f"❌ Error processing {phone_number}: {e}")
            message = f"❌ Processing Error\n📱 Phone: {phone_number}\n⚠️ Error: {str(e)[:100]}\n⏰ Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            self.send_telegram_message(message)
            return "error"

    def handle_find_account(self, phone_number):
        """Handle the Find Your Account page"""
        logging.info("👤 Handling Find Your Account page...")
        
        # Find and fill the email/phone input
        email_input = self.wait_for_element(By.ID, "identify_email")
        if not email_input:
            logging.error("❌ Could not find identify_email input")
            return "error"
            
        email_input.clear()
        self.human_like_typing(email_input, phone_number)
        logging.info(f"📝 Entered phone number: {phone_number}")
        
        self.human_like_delay(1, 3)
        
        # Find and click the SEARCH button (not cancel)
        search_btn = self.wait_for_element_clickable(By.ID, "did_submit")
        if not search_btn:
            logging.error("❌ Could not find Search button")
            return "error"
            
        self.human_like_click(search_btn)
        logging.info("🔍 Clicked Search button")
        self.human_like_delay(4, 8)
        
        # Check for block after search
        if self.check_for_block():
            message = f"🚫 Blocked After Search\n📱 Phone: {phone_number}\n⏰ Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            self.send_telegram_message(message)
            return "blocked"
        
        # Check what happened after search
        new_page_state = self.detect_current_page()
        logging.info(f"📄 Page after search: {new_page_state}")
        
        if new_page_state == "no_results":
            message = f"❌ Account Not Found\n📱 Phone: {phone_number}\n⏰ Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            self.send_telegram_message(message)
            logging.info(f"❌ Account not found for {phone_number}")
            return "not_found"
            
        elif new_page_state == "reset_password":
            logging.info("✅ Account found, proceeding to reset password")
            return self.handle_reset_password(phone_number)
            
        else:
            message = f"❌ Account Not Found\n📱 Phone: {phone_number}\n⏰ Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            self.send_telegram_message(message)
            logging.info(f"❌ Account not found for {phone_number} (unknown state)")
            return "not_found"

    def handle_reset_password(self, phone_number):
        """Handle the Reset Your Password page"""
        logging.info("🔄 Handling Reset Password page...")
        
        try:
            # Find and select SMS radio button
            sms_radio = self.wait_for_element_clickable(
                By.XPATH, 
                "//input[@type='radio' and contains(@value, 'send_sms')]"
            )
            
            if not sms_radio:
                logging.error("❌ SMS radio button not found")
                message = f"❌ Account Not Found\n📱 Phone: {phone_number}\n⏰ Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                self.send_telegram_message(message)
                return "not_found"
            
            # Select SMS option if not already selected
            if not sms_radio.is_selected():
                self.human_like_click(sms_radio)
                self.human_like_delay(1, 2)
            
            # Click Continue button
            continue_btn = self.wait_for_element_clickable(
                By.XPATH, 
                "//button[@name='reset_action' and contains(text(), 'Continue')]"
            )
            
            if not continue_btn:
                logging.error("❌ Continue button not found")
                return "error"
                
            self.human_like_click(continue_btn)
            logging.info("➡️ Clicked Continue button")
            self.human_like_delay(5, 10)
            
            # Check for block after continue
            if self.check_for_block():
                message = f"🚫 Blocked After Continue\n📱 Phone: {phone_number}\n⏰ Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                self.send_telegram_message(message)
                return "blocked"
            
            # Check if we reached the code entry page
            final_page_state = self.detect_current_page()
            logging.info(f"📄 Final page state: {final_page_state}")
            
            if final_page_state == "enter_code":
                message = f"✅ Code Sent Successfully!\n📱 Phone: {phone_number}\n⏰ Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                self.send_telegram_message(message)
                logging.info(f"✅ Code sent successfully to {phone_number}")
                return "success"
            else:
                message = f"❌ Cannot Send Code\n📱 Phone: {phone_number}\n⚠️ Could not send SMS\n⏰ Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                self.send_telegram_message(message)
                logging.warning(f"❌ Could not send code to {phone_number}")
                return "error"
                
        except Exception as e:
            logging.error(f"❌ Error in reset password for {phone_number}: {e}")
            message = f"❌ Reset Error\n📱 Phone: {phone_number}\n⚠️ Error: {str(e)[:100]}\n⏰ Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            self.send_telegram_message(message)
            return "error"

    def close(self):
        """Close the browser"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass

def load_proxies():
    """Load proxies from file or use single proxy"""
    if os.path.exists('proxies.txt'):
        with open('proxies.txt', 'r') as f:
            proxies = [line.strip() for line in f if line.strip()]
        logging.info(f"Loaded {len(proxies)} proxies from file")
        return proxies
    else:
        # Use single proxy from config
        return [CONFIG['proxy']]

def main():
    """Main function"""
    # Check if phone numbers file exists
    if not os.path.exists(CONFIG['phone_numbers_file']):
        logging.error(f"Phone numbers file '{CONFIG['phone_numbers_file']}' not found!")
        with open(CONFIG['phone_numbers_file'], 'w') as f:
            f.write("+1234567890\n+0987654321\n")
        logging.info(f"Sample file created. Please add phone numbers to {CONFIG['phone_numbers_file']}")
        return

    # Read phone numbers
    with open(CONFIG['phone_numbers_file'], 'r') as f:
        phone_numbers = [line.strip() for line in f if line.strip()]
    
    if not phone_numbers:
        logging.error("No phone numbers found in the file!")
        return

    logging.info(f"📱 Loaded {len(phone_numbers)} phone numbers")
    
    # Load proxies
    proxies = load_proxies()
    
    successful = 0
    failed = 0
    blocked = 0
    not_found = 0
    
    try:
        for i, phone_number in enumerate(phone_numbers, 1):
            logging.info(f"🔨 Processing {i}/{len(phone_numbers)}: {phone_number}")
            
            # Rotate proxies if available
            proxy = random.choice(proxies) if proxies else None
            
            # Create new bot instance for each number
            bot = FacebookRecoveryBot(proxy=proxy)
            
            try:
                result = bot.process_phone_number(phone_number)
                
                if result == "success":
                    successful += 1
                elif result == "not_found":
                    not_found += 1
                elif result == "blocked":
                    blocked += 1
                else:
                    failed += 1
                    
                # Log summary
                logging.info(f"📊 Progress: {successful}✅ {not_found}❌ {blocked}🚫 {failed}⚠️")
                
            except Exception as e:
                logging.error(f"❌ Error processing {phone_number}: {e}")
                failed += 1
            finally:
                bot.close()
            
            # Long random delay between numbers (3-8 minutes)
            if i < len(phone_numbers):
                delay = random.randint(180, 480)  # 3-8 minutes
                logging.info(f"⏳ Waiting {delay} seconds before next number...")
                time.sleep(delay)
            
    except KeyboardInterrupt:
        logging.info("🛑 Process interrupted by user")
    except Exception as e:
        logging.error(f"💥 Unexpected error: {e}")
    
    # Final summary
    logging.info(f"🎯 Final Results: {successful}✅ {not_found}❌ {blocked}🚫 {failed}⚠️")
    
    # Send final report to Telegram
    final_message = f"""
📊 Facebook Recovery Bot - Final Report
✅ Success: {successful}
❌ Not Found: {not_found} 
🚫 Blocked: {blocked}
⚠️ Errors: {failed}
📱 Total: {len(phone_numbers)}
⏰ Completed: {time.strftime('%Y-%m-%d %H:%M:%S')}
    """
    try:
        bot_temp = FacebookRecoveryBot()
        bot_temp.send_telegram_message(final_message)
        bot_temp.close()
    except:
        pass

if __name__ == "__main__":
    main()
