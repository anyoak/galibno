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
import threading
from queue import Queue

# Configuration
CONFIG = {
    'base_url': 'https://web.facebook.com/login/identify/?ctx=recover&from_login_screen=0',
    'phone_numbers_file': 'phone_numbers.txt',
    'telegram_bot_token': 'YOUR_TELEGRAM_BOT_TOKEN',
    'telegram_channel_id': '@YOUR_CHANNEL_NAME',  # or CHANNEL_ID for private channels
    'max_threads': 3,
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
            return None

    def wait_for_element_clickable(self, by, value, timeout=CONFIG['timeout']):
        """Wait for element to be clickable"""
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((by, value))
            )
        except TimeoutException:
            return None

    def detect_current_page(self):
        """Detect which page we're currently on"""
        current_url = self.driver.current_url
        
        # Check for "Find Your Account" page
        if 'login/identify' in current_url:
            try:
                if self.driver.find_element(By.XPATH, "//h2[contains(text(), 'Find Your Account')]"):
                    return "find_account"
            except:
                pass
        
        # Check for "Reset Your Password" page
        if 'recover/initiate' in current_url or 'reset_action' in current_url:
            try:
                if self.driver.find_element(By.XPATH, "//h2[contains(text(), 'Reset Your Password')]"):
                    return "reset_password"
            except:
                pass
        
        # Check for "Enter Security Code" page
        if 'recover/code' in current_url:
            try:
                if self.driver.find_element(By.XPATH, "//h2[contains(text(), 'Enter security code')]"):
                    return "enter_code"
            except:
                pass
        
        # Check for "No search results" page
        try:
            if self.driver.find_element(By.XPATH, "//div[contains(text(), 'No search results')]"):
                return "no_results"
        except:
            pass
        
        return "unknown"

    def process_phone_number(self, phone_number):
        """Process a single phone number through the recovery flow"""
        logging.info(f"Processing phone number: {phone_number}")
        
        try:
            # Navigate to the recovery page
            self.driver.get(CONFIG['base_url'])
            time.sleep(3)
            
            # Step 1: Find Account Page
            page_state = self.detect_current_page()
            if page_state == "find_account":
                # Enter phone number and search
                email_input = self.wait_for_element(By.ID, "identify_email")
                if email_input:
                    email_input.clear()
                    email_input.send_keys(phone_number)
                    
                    search_btn = self.wait_for_element_clickable(By.NAME, "did_submit")
                    if search_btn:
                        search_btn.click()
                        time.sleep(5)
                        
                        # Check result after search
                        page_state = self.detect_current_page()
                        
                        if page_state == "no_results":
                            message = f"❌ Account Not Found\n📱 Phone: {phone_number}\n📅 Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                            self.send_telegram_message(message)
                            logging.info(f"Account not found for {phone_number}")
                            return False
                            
                        elif page_state == "reset_password":
                            # Step 2: Reset Password Page - Select SMS option
                            return self.select_sms_option(phone_number)
                            
                        else:
                            logging.warning(f"Unexpected page state after search: {page_state}")
                            return False
                    
            elif page_state == "reset_password":
                # Directly on reset password page, try to select SMS
                return self.select_sms_option(phone_number)
                
            else:
                logging.warning(f"Unexpected initial page state: {page_state}")
                return False
                
        except Exception as e:
            logging.error(f"Error processing {phone_number}: {e}")
            return False
        
        return False

    def select_sms_option(self, phone_number):
        """Select the SMS option on reset password page"""
        try:
            # Look for SMS radio button
            sms_radio = self.wait_for_element_clickable(
                By.XPATH, 
                "//input[@type='radio' and contains(@value, 'send_sms')]"
            )
            
            if sms_radio:
                # Ensure SMS option is selected
                if not sms_radio.is_selected():
                    sms_radio.click()
                
                # Click Continue button
                continue_btn = self.wait_for_element_clickable(
                    By.XPATH, 
                    "//button[@name='reset_action' and contains(text(), 'Continue')]"
                )
                
                if continue_btn:
                    continue_btn.click()
                    time.sleep(5)
                    
                    # Check if we reached the code entry page
                    page_state = self.detect_current_page()
                    if page_state == "enter_code":
                        message = f"✅ Code Sent Successfully!\n📱 Phone: {phone_number}\n📅 Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                        self.send_telegram_message(message)
                        logging.info(f"Code sent successfully to {phone_number}")
                        return True
                    else:
                        # If we can't reach code entry page, account might not exist or other issue
                        message = f"❌ Cannot Send Code\n📱 Phone: {phone_number}\n⚠️ Status: Cannot select SMS option\n📅 Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                        self.send_telegram_message(message)
                        logging.warning(f"Cannot send code to {phone_number}")
                        return False
            
            else:
                # SMS option not available - account doesn't exist
                message = f"❌ Account Not Found\n📱 Phone: {phone_number}\n📅 Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                self.send_telegram_message(message)
                logging.info(f"Account not found for {phone_number} (no SMS option)")
                return False
                
        except Exception as e:
            logging.error(f"Error selecting SMS option for {phone_number}: {e}")
            message = f"❌ Error Processing\n📱 Phone: {phone_number}\n⚠️ Error: {str(e)}\n📅 Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            self.send_telegram_message(message)
            return False

    def close(self):
        """Close the browser"""
        if self.driver:
            self.driver.quit()

def worker(phone_queue, results_queue):
    """Worker function for multi-threading"""
    bot = FacebookRecoveryBot()
    
    while not phone_queue.empty():
        phone_number = phone_queue.get()
        try:
            success = bot.process_phone_number(phone_number)
            results_queue.put((phone_number, success))
        except Exception as e:
            logging.error(f"Worker error for {phone_number}: {e}")
            results_queue.put((phone_number, False))
        finally:
            phone_queue.task_done()
    
    bot.close()

def main():
    """Main function"""
    # Check if phone numbers file exists
    if not os.path.exists(CONFIG['phone_numbers_file']):
        logging.error(f"Phone numbers file '{CONFIG['phone_numbers_file']}' not found!")
        # Create sample file
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

    # Choose between single-threaded and multi-threaded
    use_threads = input("Use multi-threading? (y/n): ").lower().startswith('y')
    
    if use_threads:
        # Multi-threaded execution
        phone_queue = Queue()
        results_queue = Queue()
        
        # Add phone numbers to queue
        for phone in phone_numbers:
            phone_queue.put(phone)
        
        # Create and start worker threads
        threads = []
        for i in range(min(CONFIG['max_threads'], len(phone_numbers))):
            thread = threading.Thread(target=worker, args=(phone_queue, results_queue))
            thread.daemon = True
            thread.start()
            threads.append(thread)
        
        # Wait for all tasks to complete
        phone_queue.join()
        
        # Collect results
        successful = 0
        failed = 0
        while not results_queue.empty():
            phone, success = results_queue.get()
            if success:
                successful += 1
            else:
                failed += 1
        
        logging.info(f"Multi-threaded processing completed: {successful} successful, {failed} failed")
        
    else:
        # Single-threaded execution
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
                
                # Small delay between requests
                time.sleep(2)
                
        except KeyboardInterrupt:
            logging.info("Process interrupted by user")
        finally:
            bot.close()
        
        logging.info(f"Single-threaded processing completed: {successful} successful, {failed} failed")

if __name__ == "__main__":
    main()