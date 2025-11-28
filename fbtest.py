import os
import time
import logging
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import requests

# Configuration
CONFIG = {
    'base_url': 'https://web.facebook.com/login/identify/?ctx=recover&from_login_screen=0',
    'phone_numbers_file': 'phone_numbers.txt',
    'telegram_bot_token': 'YOUR_TELEGRAM_BOT_TOKEN',
    'telegram_channel_id': '-1003481502962',
    'timeout': 30
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
    def __init__(self):
        self.driver = None
        self.setup_driver()
        
    def setup_driver(self):
        """Setup Chrome driver with appropriate options"""
        chrome_options = Options()
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        
        # Remove headless option for debugging
        # chrome_options.add_argument('--headless')  # Comment this line for debugging
        
        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
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

    def simple_detect_page(self):
        """Simple page detection based on key elements"""
        try:
            # Take screenshot for debugging
            self.driver.save_screenshot('debug_page.png')
            
            # Check for Find Your Account page
            identify_email = self.driver.find_elements(By.ID, "identify_email")
            did_submit = self.driver.find_elements(By.ID, "did_submit")
            
            if identify_email and did_submit:
                logging.info("Detected: Find Your Account page")
                return "find_account"
            
            # Check for Reset Password page
            sms_radio = self.driver.find_elements(By.XPATH, "//input[contains(@value, 'send_sms')]")
            reset_action = self.driver.find_elements(By.NAME, "reset_action")
            
            if sms_radio and reset_action:
                logging.info("Detected: Reset Password page")
                return "reset_password"
            
            # Check for Enter Code page
            recovery_code = self.driver.find_elements(By.ID, "recovery_code_entry")
            if recovery_code:
                logging.info("Detected: Enter Code page")
                return "enter_code"
            
            # Check for No Results
            no_results = self.driver.find_elements(By.XPATH, "//*[contains(text(), 'No search results')]")
            if no_results:
                logging.info("Detected: No Results page")
                return "no_results"
                
            logging.warning("Page detection: Unknown")
            return "unknown"
            
        except Exception as e:
            logging.error(f"Error in page detection: {e}")
            return "unknown"

    def process_phone_number(self, phone_number):
        """Process a single phone number through the recovery flow"""
        logging.info(f"Processing phone number: {phone_number}")
        
        try:
            # Navigate to the recovery page
            logging.info("Navigating to Facebook recovery page...")
            self.driver.get(CONFIG['base_url'])
            time.sleep(5)
            
            # Simple page detection
            page_state = self.simple_detect_page()
            
            if page_state == "find_account":
                return self.handle_find_account(phone_number)
            elif page_state == "reset_password":
                return self.handle_reset_password(phone_number)
            elif page_state == "unknown":
                # Try direct approach
                return self.try_direct_approach(phone_number)
            else:
                logging.warning(f"Unexpected page state: {page_state}")
                return False
                
        except Exception as e:
            logging.error(f"Error processing {phone_number}: {e}")
            message = f"❌ Error Processing\n📱 Phone: {phone_number}\n⚠️ Error: {str(e)}\n📅 Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            self.send_telegram_message(message)
            return False

    def handle_find_account(self, phone_number):
        """Handle the Find Your Account page"""
        logging.info("Handling Find Your Account page...")
        
        # Find and fill the email/phone input
        email_input = self.wait_for_element(By.ID, "identify_email")
        if not email_input:
            logging.error("Could not find identify_email input")
            return False
            
        email_input.clear()
        email_input.send_keys(phone_number)
        logging.info(f"Entered phone number: {phone_number}")
        
        # Find and click the search button
        search_btn = self.wait_for_element_clickable(By.ID, "did_submit")
        if not search_btn:
            logging.error("Could not find did_submit button")
            return False
            
        search_btn.click()
        logging.info("Clicked Search button")
        time.sleep(5)
        
        # Check what happened after search
        new_page_state = self.simple_detect_page()
        
        if new_page_state == "no_results":
            message = f"❌ Account Not Found\n📱 Phone: {phone_number}\n📅 Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            self.send_telegram_message(message)
            logging.info(f"Account not found for {phone_number}")
            return False
            
        elif new_page_state == "reset_password":
            logging.info("Account found, proceeding to reset password page")
            return self.handle_reset_password(phone_number)
            
        else:
            # If we don't know what happened, assume account not found
            message = f"❌ Account Not Found\n📱 Phone: {phone_number}\n📅 Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            self.send_telegram_message(message)
            logging.info(f"Account not found for {phone_number} (unknown state after search)")
            return False

    def handle_reset_password(self, phone_number):
        """Handle the Reset Your Password page"""
        logging.info("Handling Reset Password page...")
        
        try:
            # Find and select SMS radio button
            sms_radio = self.wait_for_element_clickable(
                By.XPATH, 
                "//input[@type='radio' and contains(@value, 'send_sms')]"
            )
            
            if not sms_radio:
                logging.error("SMS radio button not found")
                message = f"❌ Account Not Found\n📱 Phone: {phone_number}\n📅 Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                self.send_telegram_message(message)
                return False
            
            # Select SMS option if not already selected
            if not sms_radio.is_selected():
                sms_radio.click()
                time.sleep(1)
            
            # Click Continue button
            continue_btn = self.wait_for_element_clickable(
                By.XPATH, 
                "//button[@name='reset_action' and contains(text(), 'Continue')]"
            )
            
            if not continue_btn:
                logging.error("Continue button not found")
                return False
                
            continue_btn.click()
            logging.info("Clicked Continue button")
            time.sleep(5)
            
            # Check if we reached the code entry page
            final_page_state = self.simple_detect_page()
            
            if final_page_state == "enter_code":
                message = f"✅ Code Sent Successfully!\n📱 Phone: {phone_number}\n📅 Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                self.send_telegram_message(message)
                logging.info(f"Code sent successfully to {phone_number}")
                return True
            else:
                message = f"❌ Cannot Send Code\n📱 Phone: {phone_number}\n⚠️ Status: Could not send SMS\n📅 Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                self.send_telegram_message(message)
                logging.warning(f"Could not send code to {phone_number}")
                return False
                
        except Exception as e:
            logging.error(f"Error in reset password for {phone_number}: {e}")
            message = f"❌ Error in Reset\n📱 Phone: {phone_number}\n⚠️ Error: {str(e)}\n📅 Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            self.send_telegram_message(message)
            return False

    def try_direct_approach(self, phone_number):
        """Try direct approach when page detection fails"""
        logging.info("Trying direct approach...")
        
        try:
            # Try to find any input field that might be for email/phone
            inputs = self.driver.find_elements(By.TAG_NAME, "input")
            for input_field in inputs:
                input_type = input_field.get_attribute("type")
                input_id = input_field.get_attribute("id")
                input_name = input_field.get_attribute("name")
                input_placeholder = input_field.get_attribute("placeholder")
                
                # Check if this looks like an email/phone input
                if (input_type == "text" and 
                    (input_id and ("email" in input_id.lower() or "phone" in input_id.lower() or "identify" in input_id.lower()) or
                     input_name and ("email" in input_name.lower() or "phone" in input_name.lower()) or
                     input_placeholder and ("email" in input_placeholder.lower() or "mobile" in input_placeholder.lower() or "phone" in input_placeholder.lower()))):
                    
                    input_field.clear()
                    input_field.send_keys(phone_number)
                    logging.info(f"Entered phone number in field: {input_id or input_name}")
                    
                    # Look for submit button
                    buttons = self.driver.find_elements(By.TAG_NAME, "button")
                    for button in buttons:
                        if button.text and ("search" in button.text.lower() or "submit" in button.text.lower() or "continue" in button.text.lower()):
                            button.click()
                            logging.info("Clicked button with text: " + button.text)
                            time.sleep(5)
                            return True
                    
                    break
            
            message = f"❌ Page Not Recognized\n📱 Phone: {phone_number}\n📅 Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            self.send_telegram_message(message)
            return False
            
        except Exception as e:
            logging.error(f"Error in direct approach for {phone_number}: {e}")
            return False

    def close(self):
        """Close the browser"""
        if self.driver:
            self.driver.quit()

def main():
    """Main function"""
    # Check if phone numbers file exists
    if not os.path.exists(CONFIG['phone_numbers_file']):
        logging.error(f"Phone numbers file '{CONFIG['phone_numbers_file']}' not found!")
        with open(CONFIG['phone_numbers_file'], 'w') as f:
            f.write("+1234567890\n+0987654321\n")
        logging.info(f"Sample file '{CONFIG['phone_numbers_file']}' created. Please add phone numbers.")
        return

    # Read phone numbers
    with open(CONFIG['phone_numbers_file'], 'r') as f:
        phone_numbers = [line.strip() for line in f if line.strip()]
    
    if not phone_numbers:
        logging.error("No phone numbers found in the file!")
        return

    logging.info(f"Loaded {len(phone_numbers)} phone numbers")

    # Single-threaded execution for stability
    bot = FacebookRecoveryBot()
    successful = 0
    failed = 0
    
    try:
        for i, phone_number in enumerate(phone_numbers, 1):
            logging.info(f"Processing {i}/{len(phone_numbers)}: {phone_number}")
            
            if bot.process_phone_number(phone_number):
                successful += 1
            else:
                failed += 1
            
            # Delay between requests
            time.sleep(3)
            
    except KeyboardInterrupt:
        logging.info("Process interrupted by user")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
    finally:
        bot.close()
    
    logging.info(f"Processing completed: {successful} successful, {failed} failed")

if __name__ == "__main__":
    main()