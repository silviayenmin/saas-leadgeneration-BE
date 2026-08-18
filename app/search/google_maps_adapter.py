import os
import sys

# Reconfigure stdout and stderr to safely handle encoding errors on Windows
try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import re
import time
import random
from urllib.parse import urljoin
from bs4 import BeautifulSoup

class GoogleMapsAdapter:
    def __init__(self):
        self.platform_name = "google_maps"

    def search(self, keyword: str, timeframe: str = "qdr:m3", match_type: str = "partial", location: str = None, industry: str = None, api_key: str = None, limit: int = 10, exclude_urls: set = None, exclude_names: set = None) -> list:
        # Build search query
        query_parts = [keyword]
        if location and location.strip():
            query_parts.append(f"in {location.strip()}")
        query = " ".join(query_parts)

        print(f"[GoogleMapsAdapter] Running Playwright Maps scraper for query: {query}")
        
        raw_leads = self.scrape_playwright(keyword, location, max_results=limit, exclude_urls=exclude_urls, exclude_names=exclude_names)
        
        results = []
        for lead in raw_leads:
            emails = []
            linkedin = None
            owner_name = None
            summary = None
            web_contacts = []
            founded_year = None
            if lead.get("website"):
                print(f"[GoogleMapsAdapter] Crawling website for business '{lead.get('name')}': {lead.get('website')}")
                try:
                    crawl_res = self.crawl_business_website_optimized(lead["website"], lead["name"])
                    emails = crawl_res["emails"]
                    linkedin = crawl_res["socials"]["linkedin"]
                    owner_name = crawl_res["owner_name"]
                    summary = crawl_res["summary"]
                    web_contacts = crawl_res["contacts"]
                    founded_year = crawl_res["founded_year"]
                    
                    if owner_name:
                        print(f"      -> Extracted Owner/CEO: {owner_name}")
                    if web_contacts:
                        print(f"      -> Extracted contacts list: {web_contacts}")
                    if summary:
                        print(f"      -> Extracted Summary: {summary[:60]}...")
                    if founded_year:
                        print(f"      -> Extracted Founded Year: {founded_year}")
                    if emails:
                        print(f"      -> Emails found: {list(emails)}")
                    else:
                        print("      -> No emails found on website.")
                except Exception as crawl_err:
                    print(f"[GoogleMapsAdapter] Web crawler error for {lead['website']}: {crawl_err}")
            contact_info = emails[0] if emails else None
            
            title = f"{lead['name']} - {lead['category'] or 'Business'} in {location or 'Target Area'}"
            snippet = f"Address: {lead['address']}. Phone: {lead['phone'] or 'None'}. Rating: {lead['rating']} ({lead['reviews']} reviews). Website: {lead['website'] or 'None'}."
            
            result = {
                "title": title,
                "snippet": snippet,
                "link": lead["mapsUrl"] or f"https://www.google.com/maps/search/{keyword}+{location}".replace(" ", "+"),
                "meta_business_name": lead["name"],
                "meta_address": lead["address"],
                "meta_website": lead["website"],
                "meta_contact_info": contact_info,
                "meta_linkedin": linkedin,
                "meta_owner_name": owner_name,
                "meta_description": summary,
                "meta_contacts": web_contacts,
                "meta_founded_year": founded_year or "",
                "phone": lead["phone"],
                "rating": lead["rating"],
                "reviews": lead["reviews"]
            }
            results.append(result)
            
        return results

    def crawl_business_website_optimized(self, url: str, company_name: str) -> dict:
        """
        Crawls the business website once, downloading the homepage and at most 3 candidate pages,
        and extracts emails, socials, owner name, contacts list, summary, and founded year in memory.
        """
        result = {
            "emails": [],
            "socials": {"linkedin": None, "facebook": None, "twitter": None},
            "owner_name": None,
            "contacts": [],
            "summary": None,
            "founded_year": None
        }
        
        if not url:
            return result
            
        # Normalize the URL
        target_url = url.strip()
        if not target_url.startswith(("http://", "https://")):
            target_url = "http://" + target_url
            
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        # 1. Fetch homepage
        homepage_html = ""
        try:
            resp = requests.get(target_url, headers=headers, timeout=6.0, allow_redirects=True, verify=False)
            if resp.status_code == 200:
                homepage_html = resp.text
        except Exception as e:
            print(f"[GoogleMapsAdapter Optimized Crawl] Failed to fetch homepage {target_url}: {e}")
            return result
            
        if not homepage_html:
            return result
            
        homepage_soup = BeautifulSoup(homepage_html, "html.parser")
        
        # 2. Extract emails from homepage
        emails_found = set()
        self.extract_emails_from_text(homepage_html, emails_found)
        
        # 3. Extract socials from homepage
        for a in homepage_soup.find_all("a", href=True):
            href = a["href"].strip().lower()
            if "linkedin.com/company/" in href or "linkedin.com/in/" in href:
                result["socials"]["linkedin"] = a["href"].strip()
            elif "facebook.com/" in href:
                result["socials"]["facebook"] = a["href"].strip()
            elif "twitter.com/" in href or "x.com/" in href:
                result["socials"]["twitter"] = a["href"].strip()
                
        # 4. Extract owner name from homepage
        owner_name = self.extract_owner_name_from_html(homepage_html, company_name)
        
        # 5. Extract contacts list from homepage
        contacts = []
        seen_names = set()
        self.extract_contacts_from_html(homepage_html, company_name, contacts, seen_names)
        
        # 6. Extract summary from homepage
        summary = self.extract_website_summary(homepage_html)
        
        # 7. Extract founded year from homepage
        homepage_soup_founded = BeautifulSoup(homepage_html, "html.parser")
        for s in homepage_soup_founded(["script", "style", "head", "iframe", "noscript"]):
            s.decompose()
        visible_text = homepage_soup_founded.get_text(" ")
        from app.search.website_crawler import extract_founded_year_from_text
        founded_year = extract_founded_year_from_text(visible_text)
        
        # 8. Find candidate contact/about/team links to crawl
        candidate_links = []
        for a in homepage_soup.find_all("a", href=True):
            href = a["href"].strip()
            text = a.get_text().lower()
            if any(x in href.lower() or x in text for x in ["contact", "about", "support", "info", "help", "team", "leadership", "people", "staff", "management"]):
                full_url = urljoin(target_url, href)
                if self.get_domain(target_url) == self.get_domain(full_url):
                    if full_url not in candidate_links and full_url != target_url:
                        candidate_links.append(full_url)
                        
        # 9. Crawl up to 3 candidate pages and extract additional info
        for link in candidate_links[:3]:
            try:
                c_resp = requests.get(link, headers=headers, timeout=4.0, verify=False)
                if c_resp.status_code == 200:
                    c_html = c_resp.text
                    
                    # Extract emails
                    self.extract_emails_from_text(c_html, emails_found)
                    
                    # Extract owner name (if not found on homepage)
                    if not owner_name:
                        owner_name = self.extract_owner_name_from_html(c_html, company_name)
                        
                    # Extract contacts
                    if len(contacts) < 5:
                        self.extract_contacts_from_html(c_html, company_name, contacts, seen_names)
            except Exception:
                pass
                
        # Filter emails
        filtered_emails = []
        for email in emails_found:
            email_lower = email.lower()
            if not any(email_lower.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"]):
                filtered_emails.append(email)
                
        if contacts and not owner_name:
            owner_name = contacts[0]["name"]
            
        result["emails"] = filtered_emails
        result["owner_name"] = owner_name
        result["contacts"] = contacts
        result["summary"] = summary
        result["founded_year"] = founded_year
        
        return result

    def scrape_playwright(self, business_type: str, location: str, max_results: int = 15, exclude_urls: set = None, exclude_names: set = None) -> list:
        import concurrent.futures
        
        def run_in_thread():
            from playwright.sync_api import sync_playwright
            
            print(f"[GoogleMapsAdapter] Running Playwright scraper fallback for '{business_type}' in '{location}'")
            leads = []
            
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True, args=["--disable-gpu", "--no-sandbox"])
                    ctx = browser.new_context(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        viewport={"width": 1280, "height": 800}
                    )
                    page = ctx.new_page()
                    
                    # 1. Navigate to Maps search
                    loc_clean = location.strip() if location else ""
                    query = f"{business_type} in {loc_clean}".strip().replace(" ", "+")
                    page.goto(f"https://www.google.com/maps/search/{query}", timeout=60000)
                    time.sleep(3.0) # Wait for page load
                    
                    scrollable_selector = 'div[role="feed"]'
                    
                    # Accept consent banners if present
                    try:
                        btn = page.locator('button:has-text("Accept all"), button:has-text("Reject all")').first
                        if btn.is_visible(timeout=3000):
                            btn.click()
                            time.sleep(1.5)
                    except Exception:
                        pass
                    
                    # 2. Wait for result list or direct page redirect
                    place_urls = []
                    try:
                        page.wait_for_selector(scrollable_selector, timeout=15000)
                        print("[GoogleMapsAdapter] Found search results sidebar.")
                    except Exception:
                        print("[GoogleMapsAdapter] Could not find scrollable feed container. Checking if direct listing page loaded.")
                        if "/maps/place/" in page.url:
                            print("[GoogleMapsAdapter] Redirected directly to place page.")
                            place_urls = [page.url]
                        else:
                            print("[GoogleMapsAdapter] No results container found and not redirected. Search query might have returned 0 results.")
                            browser.close()
                            return []
                    
                    # 3. Collect place URLs in exact rank order as we scroll
                    if place_urls != [page.url]:
                        scroll_attempts = 0
                        max_scroll_attempts = 60
                        last_height = 0
                        no_change_count = 0
                        
                        exclude_urls_clean = {u.strip() for u in (exclude_urls or set())}
                        exclude_names_clean = {n.lower().strip() for n in (exclude_names or set())}
                        
                        while len(place_urls) < max_results and scroll_attempts < max_scroll_attempts:
                            feed_el = page.query_selector(scrollable_selector)
                            place_elements = feed_el.query_selector_all('a[href*="/maps/place/"]') if feed_el else page.query_selector_all('a[href*="/maps/place/"]')
                            
                            for el in place_elements:
                                href = el.get_attribute("href")
                                card_name = el.get_attribute("aria-label") or ""
                                if card_name:
                                    card_name = card_name.replace(" · Website", "").replace(" · Directions", "").strip()
                                    
                                if not href and not card_name:
                                    continue
                                    
                                is_duplicate = False
                                if href and href.strip() in exclude_urls_clean:
                                    is_duplicate = True
                                if card_name and card_name.lower().strip() in exclude_names_clean:
                                    is_duplicate = True
                                    
                                if is_duplicate:
                                    continue
                                    
                                if href and href not in place_urls:
                                    place_urls.append(href)
                                    if len(place_urls) >= max_results:
                                        break
                            
                            print(f"[GoogleMapsAdapter] Collected {len(place_urls)} unique place links on scroll attempt {scroll_attempts+1}/{max_scroll_attempts}")
                            
                            if len(place_urls) >= max_results:
                                break
                                
                            # Scroll down the sidebar
                            page.evaluate(
                                f"""
                                const feed = document.querySelector('{scrollable_selector}');
                                if (feed) {{
                                    feed.scrollTo(0, feed.scrollHeight);
                                }}
                                """
                            )
                            try:
                                feed_el = page.query_selector(scrollable_selector)
                                if feed_el:
                                    feed_el.hover()
                                    page.mouse.wheel(0, 1500)
                                    feed_el.press("PageDown")
                                    time.sleep(0.5)
                                    feed_el.press("PageDown")
                            except Exception:
                                pass
                                
                            time.sleep(2.0)
                            
                            new_height = page.evaluate(f"document.querySelector('{scrollable_selector}').scrollHeight")
                            if new_height == last_height:
                                no_change_count += 1
                                if no_change_count > 1:
                                    page.evaluate(
                                        f"""
                                        const feed = document.querySelector('{scrollable_selector}');
                                        if (feed) {{
                                            feed.scrollTo(0, feed.scrollHeight - 500);
                                            setTimeout(() => {{ feed.scrollTo(0, feed.scrollHeight); }}, 100);
                                        }}
                                        """
                                    )
                                if no_change_count >= 6:
                                    print("[GoogleMapsAdapter] Reached the end of the Google Maps feed.")
                                    break
                            else:
                                no_change_count = 0
                                
                            last_height = new_height
                            scroll_attempts += 1
                    
                    extract_js = r"""
                    () => {
                        const nameEl = document.querySelector('h1.DUwDvf');
                        const name = nameEl ? nameEl.textContent.trim() : '';

                        let rating = '';
                        let reviews = '';
                        const ratingContainer = document.querySelector('div.F7nice');
                        if (ratingContainer) {
                            const spans = Array.from(ratingContainer.querySelectorAll('span'));
                            for (const span of spans) {
                                const txt = span.textContent.trim();
                                if (/^[1-5]\.[0-9]$/.test(txt)) {
                                    rating = txt;
                                } else if (txt.includes('(') && txt.includes(')')) {
                                    const cleanStr = txt.replace(/[()]/g, '').trim();
                                    const parts = cleanStr.split(/\s+/);
                                    if (parts.length > 0 && /^\d+[\d,.]*[km]?$/i.test(parts[0])) {
                                        reviews = parts[0];
                                    }
                                } else if (/^\d+[\d,]*$/.test(txt)) {
                                    reviews = txt.trim();
                                }
                            }
                        }

                        let category = '';
                        const categoryBtn = document.querySelector('button[class*="D7m2Ci"]');
                        if (categoryBtn) {
                            category = categoryBtn.textContent.trim();
                        } else {
                            const olocBtn = document.querySelector('button[data-item-id="oloc"]');
                            if (olocBtn) category = olocBtn.textContent.trim();
                        }

                        let address = '';
                        let phone = '';
                        let website = '';

                        const addressBtn = document.querySelector('button[data-item-id="address"]');
                        if (addressBtn) {
                            address = addressBtn.textContent.trim();
                        }
                        const phoneBtn = document.querySelector('button[data-item-id^="phone:tel:"]');
                        if (phoneBtn) {
                            phone = phoneBtn.textContent.trim();
                        }
                        const websiteLink = document.querySelector('a[data-item-id="authority"]');
                        if (websiteLink) {
                            website = websiteLink.href;
                        } else {
                            const websiteBtn = document.querySelector('button[data-item-id="authority"]');
                            if (websiteBtn) website = websiteBtn.textContent.trim();
                        }

                        // Fallbacks
                        const allButtons = Array.from(document.querySelectorAll('button'));
                        if (!address) {
                            for (const btn of allButtons) {
                                const img = btn.querySelector('img');
                                if (img && img.src.includes('map_pin')) {
                                    address = btn.textContent.trim();
                                    break;
                                }
                            }
                        }
                        if (!phone) {
                            const phoneRegex = /^(\+?\d{1,4}[- ]?)?\d{3,5}[- ]?\d{3,5}[- ]?\d{2,6}$/;
                            for (const btn of allButtons) {
                                const txt = btn.textContent.trim();
                                if (phoneRegex.test(txt) && txt.replace(/[- ]/g, '').length >= 8) {
                                    phone = txt;
                                    break;
                                }
                            }
                        }

                        return { name, category, address, phone, rating, reviews, website };
                    }
                    """

                    # 4. Hybrid Details Fetch: Try extracting directly from sidebar cards first,
                    # and only visit individual detail pages if phone/website is missing.
                    if place_urls == [page.url]:
                        # Direct redirect to single place page
                        try:
                            page.wait_for_selector('h1.DUwDvf', timeout=10000)
                            time.sleep(2.0)
                            lead_data = page.evaluate(extract_js)
                            lead_data["mapsUrl"] = page.url
                            leads.append(lead_data)
                        except Exception as parse_err:
                            print(f"[GoogleMapsAdapter] Direct page parse failed: {parse_err}")
                    else:
                        print("[GoogleMapsAdapter] Running fast feed card extraction...")
                        raw_leads = page.evaluate("""
                            ({ targetUrls }) => {
                                const cleanUrl = (u) => (u || '').split('?')[0].replace(/\\/$/, '').trim();
                                const targetSet = new Set((targetUrls || []).map(cleanUrl));
                                const cards = Array.from(document.querySelectorAll('div.Nv2PK')).filter(card => {
                                    const href = card.querySelector('a.hfpxzc')?.href || '';
                                    return targetSet.has(cleanUrl(href));
                                });
                                return cards.map(card => {
                                    const name = card.getAttribute('aria-label') || card.querySelector('a.hfpxzc')?.getAttribute('aria-label') || '';
                                    const mapsUrl = card.querySelector('a.hfpxzc')?.href || '';
                                    
                                    let website = '';
                                    const links = Array.from(card.querySelectorAll('a'));
                                    for (const a of links) {
                                        const href = a.href;
                                        const text = a.textContent.trim().toLowerCase();
                                        const label = (a.getAttribute('aria-label') || '').toLowerCase();
                                        if (href && (!href.includes('/maps/place/') && !href.includes('google.com/maps') || href.includes('/aclk'))) {
                                            if (text === 'website' || text === 'visit site' || label.includes('website') || label.includes('visit')) {
                                                website = href;
                                                break;
                                            }
                                        }
                                    }
                                    if (!website) {
                                        for (const a of links) {
                                            const href = a.href;
                                            if (href && !href.includes('/maps/place/') && !href.includes('google.com/maps') && !href.includes('google.com/url')) {
                                                website = href;
                                                break;
                                            }
                                        }
                                    }
                                    
                                    const walk = document.createTreeWalker(card, NodeFilter.SHOW_TEXT, null, false);
                                    const texts = [];
                                    let node;
                                    while (node = walk.nextNode()) {
                                        const t = node.textContent.trim();
                                        if (t && t.length > 2 && t !== 'Sponsored' && t !== 'Website' && t !== 'Directions' && !t.includes('Closes') && !t.includes('Open') && !t.includes('Closed') && !t.includes('Reopens')) {
                                            if (!texts.includes(t)) {
                                                texts.push(t);
                                            }
                                        }
                                    }
                                    
                                    let rating = '';
                                    let reviews = '';
                                    let phone = '';
                                    let category = '';
                                    let address = '';
                                    
                                    const allSpans = Array.from(card.querySelectorAll('span')).map(s => s.textContent.trim()).filter(Boolean);
                                    for (const s of allSpans) {
                                        if (/^[1-5]\.[0-9]$/.test(s)) {
                                            rating = s;
                                        }
                                        if (s.startsWith('(') && s.endsWith(')')) {
                                            const cleanStr = s.replace(/[()]/g, '').trim();
                                            const parts = cleanStr.split(/\s+/);
                                            if (parts.length > 0 && /^\d+[\d,.]*[km]?$/i.test(parts[0])) {
                                                reviews = parts[0];
                                            }
                                        }
                                    }
                                    
                                    const phoneRegex = /^(\+?\d{1,4}[- ]?)?\d{3,5}[- ]?\d{3,5}[- ]?\d{2,6}$/;
                                    for (const s of allSpans) {
                                        if (phoneRegex.test(s) && s.replace(/[- ]/g, '').length >= 8) {
                                            phone = s;
                                            break;
                                        }
                                    }
                                    if (!phone) {
                                        phone = card.querySelector('span.UsdlK')?.textContent?.trim() || '';
                                    }
                                    
                                    let nameIdx = texts.indexOf(name);
                                    if (nameIdx === -1) {
                                        nameIdx = 0;
                                    }
                                    
                                    let dataTexts = texts.slice(nameIdx + 1);
                                    dataTexts = dataTexts.filter(t => t !== rating && t !== phone && !t.startsWith('('));
                                    
                                    if (dataTexts.length > 0) {
                                        category = dataTexts[0];
                                    }
                                    if (dataTexts.length > 1) {
                                        address = dataTexts[1];
                                    }
                                    
                                    return { name, category, address, phone, rating, reviews, website, mapsUrl };
                                });
                            }
                        """, {"targetUrls": place_urls})
                        
                        # Visit detail page ONLY if phone or website is missing from card
                        for idx, lead in enumerate(raw_leads, 1):
                            if (not lead.get("website") or not lead.get("phone")) and lead.get("mapsUrl"):
                                print(f"[GoogleMapsAdapter] Sidebar card {idx}/{len(raw_leads)} is missing details. Navigating to place detail page: {lead['mapsUrl']}")
                                try:
                                    page.goto(lead["mapsUrl"], timeout=15000)
                                    page.wait_for_selector('h1.DUwDvf', timeout=8000)
                                    time.sleep(1.5) # Short sleep to let attributes load
                                    
                                    detailed_data = page.evaluate(extract_js)
                                    if detailed_data:
                                        if detailed_data.get("website"):
                                            lead["website"] = detailed_data["website"]
                                        if detailed_data.get("phone"):
                                            lead["phone"] = detailed_data["phone"]
                                        if detailed_data.get("address"):
                                            lead["address"] = detailed_data["address"]
                                        if detailed_data.get("category"):
                                            lead["category"] = detailed_data["category"]
                                        print(f"      -> Updated details from page: Phone: {lead['phone']} | Website: {lead['website']}")
                                except Exception as parse_err:
                                    print(f"[GoogleMapsAdapter] Failed to parse details on fallback page navigation: {parse_err}")
                                    
                            leads.append(lead)
                    
                    # Clean string values from PUA (Private Use Area) icons to prevent print errors on Windows
                    cleaned_leads = []
                    for lead in leads:
                        cleaned_lead = {}
                        for key in ["name", "category", "address", "phone", "rating", "reviews", "website", "mapsUrl"]:
                            val = lead.get(key)
                            if isinstance(val, str):
                                val_clean = "".join(c for c in val if not (0xe000 <= ord(c) <= 0xf8ff))
                                cleaned_lead[key] = val_clean.strip()
                            else:
                                cleaned_lead[key] = ""
                        cleaned_leads.append(cleaned_lead)
                        phone_lbl = cleaned_lead["phone"] or "no phone"
                        safe_name = cleaned_lead["name"].encode('ascii', errors='ignore').decode('ascii')
                        print(f"      -> {safe_name} | {phone_lbl}")
                        
                    browser.close()
                    return cleaned_leads
            except Exception as ex:
                print(f"[GoogleMapsAdapter] Playwright scraping failed: {ex}")
                
            return leads
 
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_in_thread)
            return future.result()

    def crawl_website_for_emails(self, url: str) -> list:
        print(f"[GoogleMapsAdapter] Crawling website: {url}")
        emails_found = set()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        try:
            resp = requests.get(url, headers=headers, timeout=8.0, allow_redirects=True)
            if resp.status_code != 200:
                return []
            
            html = resp.text
            soup = BeautifulSoup(html, "html.parser")
            
            # Extract from homepage
            self.extract_emails_from_text(html, emails_found)
            
            # Find candidate contact links to crawl (up to 3 links)
            candidate_links = []
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                text = a.get_text().lower()
                # Check if link points to contact, about, or support page
                if any(x in href.lower() or x in text for x in ["contact", "about", "support", "info", "help", "team"]):
                    full_url = urljoin(url, href)
                    # Stay within same domain to avoid external crawling
                    if self.get_domain(url) == self.get_domain(full_url):
                        if full_url not in candidate_links and full_url != url:
                            candidate_links.append(full_url)
            
            # Crawl up to 3 candidate links
            for link in candidate_links[:3]:
                try:
                    c_resp = requests.get(link, headers=headers, timeout=5.0)
                    if c_resp.status_code == 200:
                        self.extract_emails_from_text(c_resp.text, emails_found)
                except Exception:
                    pass
        except Exception as e:
            print(f"[GoogleMapsAdapter] Crawl failed for {url}: {e}")

        # Filter out common false positives or image files
        filtered_emails = []
        for email in emails_found:
            email_lower = email.lower()
            if not any(email_lower.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"]):
                filtered_emails.append(email)
                
        return filtered_emails

    def extract_emails_from_text(self, text: str, email_set: set):
        pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,6}"
        found = re.findall(pattern, text)
        for email in found:
            email_set.add(email)

    def get_domain(self, url: str) -> str:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.netloc

    def crawl_website_for_socials(self, url: str) -> dict:
        print(f"[GoogleMapsAdapter] Crawling website for social links: {url}")
        socials = {"linkedin": None, "facebook": None, "twitter": None}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        try:
            resp = requests.get(url, headers=headers, timeout=8.0, allow_redirects=True)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"].strip().lower()
                    if "linkedin.com/company/" in href or "linkedin.com/in/" in href:
                        # Keep original case for URL
                        socials["linkedin"] = a["href"].strip()
                    elif "facebook.com/" in href:
                        socials["facebook"] = a["href"].strip()
                    elif "twitter.com/" in href or "x.com/" in href:
                        socials["twitter"] = a["href"].strip()
        except Exception as e:
            print(f"[GoogleMapsAdapter] Crawl socials failed for {url}: {e}")
        return socials

    def crawl_website_for_owner_name(self, url: str, company_name: str) -> str:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        try:
            resp = requests.get(url, headers=headers, timeout=8.0, allow_redirects=True)
            if resp.status_code != 200:
                return None
            
            # 1. Search homepage
            name = self.extract_owner_name_from_html(resp.text, company_name)
            if name:
                return name
                
            # 2. Search about/team pages
            soup = BeautifulSoup(resp.text, "html.parser")
            candidate_links = []
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                text = a.get_text().lower()
                if any(x in href.lower() or x in text for x in ["about", "team", "leadership", "people", "staff", "management"]):
                    full_url = urljoin(url, href)
                    if self.get_domain(url) == self.get_domain(full_url):
                        if full_url not in candidate_links and full_url != url:
                            candidate_links.append(full_url)
                            
            for link in candidate_links[:3]:
                try:
                    c_resp = requests.get(link, headers=headers, timeout=5.0)
                    if c_resp.status_code == 200:
                        name = self.extract_owner_name_from_html(c_resp.text, company_name)
                        if name:
                            return name
                except Exception:
                    pass
        except Exception as e:
            print(f"[GoogleMapsAdapter] Owner crawl failed for {url}: {e}")
        return None

    def extract_owner_name_from_html(self, html_text: str, company_name: str) -> str:
        try:
            soup = BeautifulSoup(html_text, "html.parser")
            for script in soup(["script", "style", "header", "footer", "nav"]):
                script.decompose()
            text = soup.get_text(separator="\n")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            
            import re
            keywords = r"\b(ceo|founder|owner|president|managing director|principal|md)\b"
            
            for line in lines:
                if len(line) < 150 and re.search(keywords, line, re.IGNORECASE):
                    # Extract capitalized word sequences (2-3 words)
                    matches = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b", line)
                    for m in matches:
                        if self.is_likely_person_name(m, company_name):
                            return m
        except Exception:
            pass
        return None

    def is_likely_person_name(self, name: str, company_name: str = None) -> bool:
        name_lower = name.lower()
        blacklist = {
            "about", "team", "home", "contact", "services", "solutions", "consulting",
            "inc", "llc", "corp", "ltd", "company", "group", "agency", "firm",
            "privacy", "policy", "terms", "careers", "jobs", "blog", "news",
            "office", "address", "phone", "email", "support", "help", "hiring",
            "management", "board", "leadership", "founded", "established", "welcome",
            "january", "february", "march", "april", "may", "june", "july", "august",
            "september", "october", "november", "december", "monday", "tuesday",
            "wednesday", "thursday", "friday", "saturday", "sunday",
            "founding", "member", "members", "executive", "executives", "advisor", 
            "advisors", "associate", "associates", "director", "directors", "manager", 
            "managers", "officer", "officers", "vice", "president", "presidents", 
            "chief", "head", "lead", "leads", "founder", "founders", "owner", 
            "owners", "staff", "intern", "employee", "employees", "specialist", 
            "specialists", "engineer", "engineers", "developer", "developers", 
            "architect", "architects", "designer", "designers", "analyst", "analysts", 
            "consultant", "consultants", "representative", "agent", "assistant", 
            "admin", "administrator", "coordinator", "creative", "technical", 
            "sales", "marketing", "operations", "finance", "engineering", "product", 
            "business", "corporate", "team", "partner", "partners", "general",
            "transforming", "building", "digital", "success", "marketing", "your", 
            "our", "their", "premier", "visions", "vision", "growth", "creative", 
            "agency", "media", "social", "web", "design", "development"
        }
        words = name_lower.split()
        if len(words) < 2 or len(words) > 3:
            return False
        for w in words:
            if w in blacklist or len(w) < 2:
                return False
        if company_name:
            co_words = {w.strip().lower() for w in company_name.split() if len(w.strip()) > 1}
            common_words = {"and", "the", "a", "of", "in", "for", "on", "at", "to", "by", "with", "ltd", "inc", "llc", "group", "co", "design", "creative", "studio", "nursery"}
            co_words = co_words - common_words
            overlap = set(words) & co_words
            if overlap:
                return False
        return True

    def extract_website_summary_from_url(self, url: str) -> str:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        try:
            resp = requests.get(url, headers=headers, timeout=8.0, allow_redirects=True)
            if resp.status_code == 200:
                return self.extract_website_summary(resp.text)
        except Exception:
            pass
        return None

    def extract_website_summary(self, html_text: str) -> str:
        try:
            soup = BeautifulSoup(html_text, "html.parser")
            
            # 1. Try meta description tag
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc and meta_desc.get("content"):
                return meta_desc["content"].strip()
                
            # 2. Try og:description tag
            og_desc = soup.find("meta", attrs={"property": "og:description"})
            if og_desc and og_desc.get("content"):
                return og_desc["content"].strip()
                
            # 3. Fallback: extract the first rich paragraph
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            for p in soup.find_all("p"):
                txt = p.get_text().strip()
                if len(txt) > 40 and len(txt) < 300:
                    return txt
        except Exception:
            pass
        return None

    def crawl_website_for_contacts(self, url: str, company_name: str) -> list:
        contacts = []
        seen_names = set()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        try:
            resp = requests.get(url, headers=headers, timeout=8.0, allow_redirects=True)
            if resp.status_code == 200:
                # 1. Scrape homepage
                self.extract_contacts_from_html(resp.text, company_name, contacts, seen_names)
                
                # 2. Scrape about/team pages
                soup = BeautifulSoup(resp.text, "html.parser")
                candidate_links = []
                for a in soup.find_all("a", href=True):
                    href = a["href"].strip()
                    text = a.get_text().lower()
                    if any(x in href.lower() or x in text for x in ["about", "team", "leadership", "people", "staff", "management"]):
                        full_url = urljoin(url, href)
                        if self.get_domain(url) == self.get_domain(full_url):
                            if full_url not in candidate_links and full_url != url:
                                candidate_links.append(full_url)
                
                for link in candidate_links[:3]:
                    if len(contacts) >= 5:
                        break
                    try:
                        c_resp = requests.get(link, headers=headers, timeout=5.0)
                        if c_resp.status_code == 200:
                            self.extract_contacts_from_html(c_resp.text, company_name, contacts, seen_names)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[GoogleMapsAdapter] Contact crawl failed for {url}: {e}")
        return contacts

    def extract_contacts_from_html(self, html_text: str, company_name: str, contacts: list, seen_names: set):
        try:
            soup = BeautifulSoup(html_text, "html.parser")
            for script in soup(["script", "style", "header", "footer", "nav"]):
                script.decompose()
            text = soup.get_text(separator="\n")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            
            import re
            keywords = r"\b(ceo|founder|owner|president|managing director|principal|hr|human resources|md)\b"
            
            for line in lines:
                if len(line) < 150 and re.search(keywords, line, re.IGNORECASE):
                    role_match = re.search(keywords, line, re.IGNORECASE)
                    role = role_match.group(1).title() if role_match else "Executive"
                    
                    matches = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b", line)
                    for m in matches:
                        if m not in seen_names and self.is_likely_person_name(m, company_name):
                            seen_names.add(m)
                            contacts.append({
                                "name": m,
                                "title": role,
                                "email": "Pending lookup",
                                "source": "Website Scraper"
                            })
                            if len(contacts) >= 5:
                                return
        except Exception:
            pass
