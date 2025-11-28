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
        self.setup_driver(proxy)
        
    def setup_driver(self, proxy):
        """Setup SeleniumBase driver with proxy and stealth options"""
        try:
            driver_config = {
                'headless': False,  # Keep visible to see what's happening
                'uc': True,  # Undetectable Chrome
                'undetectable': True,  # Anti-detection
            }
            
            # Add proxy if provided
            if proxy:
                driver_config['proxy'] = proxy
                logging.info(f"Using proxy: {proxy.split('@')[-1]}")
            
            self.driver = Driver(**driver_config)
            
            # Additional stealth settings
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            # Set random window size
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
            # Scroll element into view
            self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", element)
            self.human_like_delay(0.5, 1)
            
            # Move to element with slight random offset
            actions = ActionChains(self.driver)
            actions.move_to_element_with_offset(element, random.randint(-2, 2), random.randint(-2, 2))
            actions.pause(random.uniform(0.2, 0.5))
            actions.click()
            actions.perform()
        except:
            # Fallback to simple click
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
                logging.info(f"Telegram message sent")
            else:
                logging.error(f"Failed to send Telegram message")
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
                "Temporarily Blocked",
                "misusing this feature",
                "Community Standards",
                "too fast",
                "blocked",
                "security check"
            ]
            
            page_text = self.driver.page_source
            for indicator in block_indicators:
                if indicator.lower() in page_text.lower():
                    logging.error("Facebook block detected!")
                    return True
            return False
        except:
            return False

    def find_and_click_search_button(self):
        """Find and click the search button using multiple strategies"""
        logging.info("Looking for Search button...")
        
        # Strategy 1: By ID
        search_btn = self.wait_for_element_clickable(By.ID, "did_submit")
        if search_btn:
            logging.info("Found Search button by ID")
            return search_btn
        
        # Strategy 2: By text content
        buttons = self.driver.find_elements(By.TAG_NAME, "button")
        for button in buttons:
            button_text = button.text.strip().lower()
            if "search" in button_text and "cancel" not in button_text:
                logging.info(f"Found Search button by text: {button.text}")
                return button
        
        # Strategy 3: By type submit
        submit_buttons = self.driver.find_elements(By.XPATH, "//button[@type='submit']")
        for button in submit_buttons:
            if button.is_displayed():
                logging.info("Found Search button by type submit")
                return button
        
        # Strategy 4: By form submission
        forms = self.driver.find_elements(By.TAG_NAME, "form")
        for form in forms:
            buttons_in_form = form.find_elements(By.TAG_NAME, "button")
            for button in buttons_in_form:
                if button.is_displayed() and button.is_enabled():
                    logging.info("Found Search button in form")
                    return button
        
        logging.error("Could not find Search button")
        return None

    def process_phone_number(self, phone_number):
        """Process a single phone number through the recovery flow"""
        logging.info(f"Processing: {phone_number}")
        
        try:
            # Navigate to the recovery page
            logging.info("Navigating to Facebook...")
            self.driver.get(CONFIG['base_url'])
            self.human_like_delay(3, 6)
            
            # Check for block
            if self.check_for_block():
                message = f"🚫 Facebook Blocked\n📱 Phone: {phone_number}"
                self.send_telegram_message(message)
                return "blocked"
            
            # Step 1: Find input field and enter phone number
            logging.info("Looking for phone input field...")
            email_input = self.wait_for_element(By.ID, "identify_email")
            
            if not email_input:
                # Try other input fields
                inputs = self.driver.find_elements(By.TAG_NAME, "input")
                for input_field in inputs:
                    input_type = input_field.get_attribute("type")
                    placeholder = input_field.get_attribute("placeholder") or ""
                    if input_type == "text" and any(word in placeholder.lower() for word in ['email', 'mobile', 'phone']):
                        email_input = input_field
                        break
            
            if not email_input:
                logging.error("Could not find phone input field")
                return "error"
            
            # Human-like typing
            email_input.clear()
            self.human_like_delay(1, 2)
            self.human_like_typing(email_input, phone_number)
            logging.info(f"Entered phone number: {phone_number}")
            self.human_like_delay(1, 3)
            
            # Step 2: Find and click Search button
            search_btn = self.find_and_click_search_button()
            if not search_btn:
                return "error"
            
            self.human_like_click(search_btn)
            logging.info("Clicked Search button")
            self.human_like_delay(4, 8)
            
            # Check for block after search
            if self.check_for_block():
                message = f"🚫 Blocked After Search\n📱 Phone: {phone_number}"
                self.send_telegram_message(message)
                return "blocked"
            
            # Step 3: Check what happened after search
            current_url = self.driver.current_url.lower()
            page_text = self.driver.page_source.lower()
            
            # Check for "no results" page
            if "no search results" in page_text or "did not return any results" in page_text:
                message = f"❌ Account Not Found\n📱 Phone: {phone_number}"
                self.send_telegram_message(message)
                logging.info(f"Account not found for {phone_number}")
                return "not_found"
            
            # Check if we're on reset password page
            elif "reset your password" in page_text or "recover/initiate" in current_url:
                logging.info("Account found, on reset password page")
                return self.handle_reset_password(phone_number)
            
            # Check if we're on code entry page
            elif "enter security code" in page_text or "recover/code" in current_url:
                message = f"✅ Code Sent Successfully!\n📱 Phone: {phone_number}"
                self.send_telegram_message(message)
                logging.info(f"Code sent successfully to {phone_number}")
                return "success"
            
            else:
                # Unknown page state
                message = f"❌ Account Not Found\n📱 Phone: {phone_number}"
                self.send_telegram_message(message)
                logging.info(f"Account not found for {phone_number} (unknown page)")
                return "not_found"
                
        except Exception as e:
            logging.error(f"Error processing {phone_number}: {e}")
            message = f"❌ Processing Error\n📱 Phone: {phone_number}\n⚠️ Error: {str(e)}"
            self.send_telegram_message(message)
            return "error"

    def handle_reset_password(self, phone_number):
        """Handle the Reset Your Password page"""
        logging.info("Handling Reset Password page...")
        
        try:
            # Find SMS radio button
            sms_radio = None
            
            # Strategy 1: By value containing 'send_sms'
            sms_radio = self.wait_for_element_clickable(
                By.XPATH, 
                "//input[@type='radio' and contains(@value, 'send_sms')]"
            )
            
            # Strategy 2: By text near radio button
            if not sms_radio:
                sms_labels = self.driver.find_elements(By.XPATH, "//*[contains(text(), 'Send code via SMS')]")
                for label in sms_labels:
                    parent = self.driver.execute_script("return arguments[0].closest('label')", label)
                    if parent:
                        radio = parent.find_element(By.TAG_NAME, "input")
                        if radio.get_attribute("type") == "radio":
                            sms_radio = radio
                            break
            
            if not sms_radio:
                logging.error("SMS radio button not found")
                message = f"❌ Account Not Found\n📱 Phone: {phone_number}"
                self.send_telegram_message(message)
                return "not_found"
            
            # Select SMS option
            if not sms_radio.is_selected():
                self.human_like_click(sms_radio)
                self.human_like_delay(1, 2)
            
            # Find and click Continue button
            continue_btn = None
            
            # Strategy 1: By text
            continue_btn = self.wait_for_element_clickable(
                By.XPATH, 
                "//button[contains(text(), 'Continue')]"
            )
            
            # Strategy 2: By name
            if not continue_btn:
                continue_btn = self.wait_for_element_clickable(By.NAME, "reset_action")
            
            if not continue_btn:
                logging.error("Continue button not found")
                return "error"
                
            self.human_like_click(continue_btn)
            logging.info("Clicked Continue button")
            self.human_like_delay(5, 10)
            
            # Check for block
            if self.check_for_block():
                message = f"🚫 Blocked After Continue\n📱 Phone: {phone_number}"
                self.send_telegram_message(message)
                return "blocked"
            
            # Check if code was sent
            current_url = self.driver.current_url.lower()
            page_text = self.driver.page_source.lower()
            
            if "enter security code" in page_text or "recover/code" in current_url:
                message = f"✅ Code Sent Successfully!\n📱 Phone: {phone_number}"
                self.send_telegram_message(message)
                logging.info(f"Code sent successfully to {phone_number}")
                return "success"
            else:
                message = f"❌ Cannot Send Code\n📱 Phone: {phone_number}"
                self.send_telegram_message(message)
                logging.warning(f"Could not send code to {phone_number}")
                return "error"
                
        except Exception as e:
            logging.error(f"Error in reset password: {e}")
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
        logging.info(f"Sample file created. Please add phone numbers.")
        return

    # Read phone numbers
    with open(CONFIG['phone_numbers_file'], 'r') as f:
        phone_numbers = [line.strip() for line in f if line.strip()]
    
    if not phone_numbers:
        logging.error("No phone numbers found!")
        return

    logging.info(f"Loaded {len(phone_numbers)} phone numbers")
    
    successful = 0
    failed = 0
    blocked = 0
    not_found = 0
    
    try:
        for i, phone_number in enumerate(phone_numbers, 1):
            logging.info(f"Processing {i}/{len(phone_numbers)}: {phone_number}")
            
            # Create new bot instance
            bot = FacebookRecoveryBot(proxy=CONFIG['proxy'])
            
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
                    
                logging.info(f"Progress: {successful}✅ {not_found}❌ {blocked}🚫 {failed}⚠️")
                
            except Exception as e:
                logging.error(f"Error: {e}")
                failed += 1
            finally:
                bot.close()
            
            # Delay between numbers
            if i < len(phone_numbers):
                delay = random.randint(180, 480)  # 3-8 minutes
                logging.info(f"Waiting {delay} seconds...")
                time.sleep(delay)
            
    except KeyboardInterrupt:
        logging.info("Process interrupted")
    
    # Final summary
    logging.info(f"Final: {successful}✅ {not_found}❌ {blocked}🚫 {failed}⚠️")

if __name__ == "__main__":
    main()