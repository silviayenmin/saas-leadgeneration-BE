import re
import requests
from bs4 import BeautifulSoup

def extract_founded_year_from_text(text: str) -> str:
    """
    Search visible page text for indicators of a company starting/founding year.
    Matches cases like: "since 2015", "established 2015", "founded in 2015", "est. 2015", 
    or copyright footers like "(c) 2015-2024" or "© 2015".
    """
    if not text:
        return None
        
    # Standard common patterns for starting/founding year
    patterns = [
        # Match "since 2015", "since. 2015"
        r"(?i)\bsince\b\.?\s*(\d{4})\b",
        # Match "est. 2015", "est 2015", "established 2015", "established in 2015"
        r"(?i)\best\b\.?\s*(\d{4})\b",
        r"(?i)\bestablished\s*(?:in)?\s*(\d{4})\b",
        # Match "founded 2015", "founded in 2015"
        r"(?i)\bfounded\s*(?:in)?\s*(\d{4})\b",
        # Match "started 2015", "started in 2015"
        r"(?i)\bstarted\s*(?:in)?\s*(\d{4})\b",
        # Match copyright range: e.g. "© 2015-2026" or "Copyright 2015"
        r"(?i)(?:copyright|\(c\)|©)\s*(\d{4})(?:\s*-\s*\d{4})?",
    ]
    
    # Normalize extra whitespaces to single spaces
    normalized_text = " ".join(text.split())
    
    for pattern in patterns:
        matches = re.findall(pattern, normalized_text)
        for m in matches:
            try:
                year = int(m)
                # Valid founding year range (between 1800 and current year 2026)
                if 1800 <= year <= 2026:
                    return str(year)
            except ValueError:
                continue
                
    return None

def crawl_website_for_founded_year(url: str) -> str:
    """
    HTTP GET requesting the company homepage, stripping script/style blocks,
    and parsing the text to find a starting/founding year.
    """
    if not url:
        return None
        
    # Normalize the URL
    target_url = url.strip()
    if not target_url.startswith(("http://", "https://")):
        target_url = "http://" + target_url
        
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        # 5 seconds timeout to keep it fast and non-blocking
        resp = requests.get(target_url, headers=headers, timeout=5, verify=False)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Decompose script, style, head, iframe, and noscript blocks to get only raw visible text
            for s in soup(["script", "style", "head", "iframe", "noscript"]):
                s.decompose()
                
            visible_text = soup.get_text(" ")
            year = extract_founded_year_from_text(visible_text)
            if year:
                return year
    except Exception as e:
        print(f"[WebsiteCrawler] Failed to crawl founded year for {url}: {e}")
        
    return None
