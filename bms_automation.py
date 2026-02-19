from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
import time
import os

# --- Constants ---
# [USER TODO] Need to set these values
BMS_URL = "https://bms.breezm.com"
# Default profile directory in the current folder for portability
AUTOMATION_PROFILE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "chrome_profile"))

def open_bms_popup(customer_name, order_no, username, password):
    """
    1. BMS Access & Login (Idempotent)
    2. Search Customer Name
    3. Click specific Order Number card
    """
    if not username or not password:
        print("Username or Password not provided.")
        return False

    try:
        opts = Options()
        opts.add_experimental_option("detach", True) # Keep browser open
        opts.add_argument(f"--user-data-dir={AUTOMATION_PROFILE_DIR}")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--window-size=1600,950")
        opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        
        service = Service(ChromeDriverManager().install())
        drv = webdriver.Chrome(service=service, options=opts)

        # 1. BMS Access
        drv.get(BMS_URL)
        time.sleep(1)

        # 2. Login Check
        def _is_search_ready():
            try:
                WebDriverWait(drv, 3).until(EC.presence_of_element_located((By.CSS_SELECTOR,"input[placeholder*='이름 2글자']")))
                return True
            except: return False

        if not _is_search_ready():
            try:
                # Login Form
                uid = WebDriverWait(drv, 5).until(EC.presence_of_element_located((By.CSS_SELECTOR,"input[type='text'], input[type='email']")))
                pwd = WebDriverWait(drv, 5).until(EC.presence_of_element_located((By.CSS_SELECTOR,"input[type='password']")))
                
                # Input Credentials
                uid.clear(); uid.send_keys(username)
                pwd.clear(); pwd.send_keys(password); pwd.send_keys(Keys.RETURN)
                
                # Wait for search box
                WebDriverWait(drv, 10).until(lambda d: _is_search_ready())
            except Exception as e:
                print("Login error (or already logged in):", e)

        # 3. Search Customer Name
        try:
            inp = WebDriverWait(drv, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR,"input[placeholder*='이름 2글자']")))
            ActionChains(drv).move_to_element(inp).click()\
                .key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL)\
                .send_keys(Keys.BACK_SPACE).send_keys(customer_name).pause(0.5)\
                .send_keys(Keys.RETURN).perform()
            
            # Wait for results
            time.sleep(1.5)
            
            # 4. Find & Click Order Card
            # XPath to find button ancestor of element containing the order number
            xp = f"//p[contains(normalize-space(.),'주문번호') and contains(normalize-space(.), '{order_no}')]/ancestor::*[@role='button'][1]"
            btn = WebDriverWait(drv, 10).until(EC.presence_of_element_located((By.XPATH, xp)))
            
            # Scroll & Click
            drv.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            time.sleep(0.5)
            
            try: btn.click()
            except: drv.execute_script("arguments[0].click();", btn)
            
            return True
            
        except Exception as e:
            print(f"Search/Click failed: {e}")
            return False

    except Exception as e:
        print(f"Browser error: {e}")
        return False
