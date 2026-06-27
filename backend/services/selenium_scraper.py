import logging
import re
import time
import asyncio
from typing import Dict, Any, Optional
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

logger = logging.getLogger(__name__)

def run_selenium_scrape(url: str) -> Optional[Dict[str, Any]]:
    """Synchronous core Selenium scraper execution."""
    driver = None
    try:
        logger.info("Initializing Selenium headless browser for URL: %s", url)
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(20)
        
        driver.get(url)
        time.sleep(2)  # Allow dynamic JavaScript elements to render
        
        # 1. Extract Product Title
        title = ""
        title_selectors = [
            (By.ID, "productTitle"), # Amazon
            (By.CLASS_NAME, "B_NuCI"), # Flipkart legacy
            (By.CLASS_NAME, "VU-ZEg"), # Flipkart new
            (By.CLASS_NAME, "pdp-title"), # Croma
            (By.TAG_NAME, "h1") # Generic fallback
        ]
        for by, sel in title_selectors:
            try:
                elem = driver.find_element(by, sel)
                if elem and elem.text.strip():
                    title = elem.text.strip()
                    break
            except Exception:
                continue
        
        if not title:
            title = driver.title
            
        if title:
            # Clean generic page suffixes
            title = re.sub(r'\s*\|\s*Amazon\.in.*', '', title, flags=re.IGNORECASE)
            title = re.sub(r'buy\s+.*\s+online\s+.*', '', title, flags=re.IGNORECASE)
            title = title.strip()

        # 2. Extract Price
        price = None
        price_selectors = [
            (By.CLASS_NAME, "a-price-whole"), # Amazon
            (By.CLASS_NAME, "Nx9Btz"), # Flipkart new
            (By.CLASS_NAME, "_30jeq3"), # Flipkart legacy
            (By.CLASS_NAME, "pdp-cp-price"), # Croma
            (By.ID, "pdp-price") # Croma
        ]
        for by, sel in price_selectors:
            try:
                elem = driver.find_element(by, sel)
                if elem and elem.text.strip():
                    txt = elem.text.strip()
                    digits = "".join(re.findall(r'\d', txt))
                    if digits:
                        price = float(digits)
                        break
            except Exception:
                continue
                
        # Heuristic fallback if price selectors didn't match
        if price is None:
            body_text = ""
            try:
                body_text = driver.find_element(By.TAG_NAME, "body").text
            except Exception:
                pass
            price_matches = re.findall(r'(?:₹|Rs\.?)\s*([\d,]+)', body_text)
            for val in price_matches:
                digits = val.replace(",", "")
                if digits.isdigit():
                    price = float(digits)
                    break

        # 3. Extract Specifications
        specifications = {}
        
        # Table-based Technical specs (Amazon/Croma/Flipkart tech tables)
        try:
            tables = driver.find_elements(By.XPATH, "//table[contains(@class, 'prodDetails') or contains(@class, 'techSpecs') or contains(@id, 'technicalSpecifications_section_1')]")
            for table in tables:
                rows = table.find_elements(By.TAG_NAME, "tr")
                for row in rows:
                    try:
                        th = row.find_element(By.TAG_NAME, "th")
                        td = row.find_element(By.TAG_NAME, "td")
                        if th and td:
                            specifications[th.text.strip()] = td.text.strip()
                    except Exception:
                        pass
        except Exception:
            pass
            
        if not specifications:
            try:
                rows = driver.find_elements(By.XPATH, "//tr[contains(@class, '_1sdu8O') or contains(@class, 'WryVHM') or contains(@class, 'cp-specification-row')]")
                for row in rows:
                    try:
                        cells = row.find_elements(By.TAG_NAME, "td")
                        if len(cells) >= 2:
                            specifications[cells[0].text.strip()] = cells[1].text.strip()
                    except Exception:
                        pass
            except Exception:
                pass

        if not specifications:
            try:
                elements = driver.find_elements(By.XPATH, "//*[contains(@class, 'spec-key') or contains(@class, 'spec-label')]")
                for key_elem in elements:
                    try:
                        val_elem = key_elem.find_element(By.XPATH, "./following-sibling::*")
                        if key_elem and val_elem:
                            specifications[key_elem.text.strip()] = val_elem.text.strip()
                    except Exception:
                        pass
            except Exception:
                pass

        logger.info("Successfully scraped product using Selenium. Name: %s, Price: %s, Specs count: %d", title, price, len(specifications))
        return {
            "name": title if title else None,
            "price": price,
            "specifications": specifications if specifications else {}
        }
    except Exception as e:
        logger.error("Selenium scraping failed for %s: %s", url, e)
        return None
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

async def scrape_with_selenium_async(url: str) -> Optional[Dict[str, Any]]:
    """Runs Selenium scraping asynchronously in a background thread."""
    return await asyncio.to_thread(run_selenium_scrape, url)
