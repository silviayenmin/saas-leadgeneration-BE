import os
import requests
import json

def is_empty_value(val) -> bool:
    if val is None:
        return True
    if isinstance(val, str) and not val.strip():
        return True
    return False

def extract_domain(url: str) -> str:
    if not url:
        return ""
    from urllib.parse import urlparse
    parsed = urlparse(url.strip())
    domain = parsed.netloc or parsed.path
    if domain.startswith("www."):
        domain = domain[4:]
    if "/" in domain:
        domain = domain.split("/")[0]
    return domain.lower()

class BaseEnricher:
    def enrich(self, author_name: str, company_name: str, **kwargs) -> dict:
        raise NotImplementedError

class HunterEnricher(BaseEnricher):
    def enrich(self, author_name: str, company_name: str, **kwargs) -> dict:
        api_key = os.getenv("HUNTER_API_KEY")
        if not api_key:
            return {}
        try:
            parts = author_name.strip().split()
            first = parts[0] if parts else ""
            last = parts[1] if len(parts) > 1 else ""
            domain = company_name.lower().split()[0].replace(",","").replace(".","") + ".com"

            resp = requests.get(
                "https://api.hunter.io/v2/email-finder",
                params={
                    "domain": domain,
                    "first_name": first,
                    "last_name": last,
                    "api_key": api_key
                },
                timeout=8
            )
            data = resp.json()
            email = data.get("data", {}).get("email")
            score = data.get("data", {}).get("score", 0)
            if email:
                return {
                    "email": email,
                    "contactSource": "hunter",
                    "contactConfidence": "high" if score > 70 else "medium"
                }
        except Exception:
            pass
        return {}

def format_money(val) -> str:
    if not val:
        return None
    try:
        val_float = float(val)
        if val_float >= 1_000_000_000:
            return f"${val_float / 1_000_000_000:.1f}B"
        elif val_float >= 1_000_000:
            return f"${val_float / 1_000_000:.1f}M"
        elif val_float >= 1_000:
            return f"${val_float / 1_000:.1f}K"
        return f"${val_float:,.0f}"
    except Exception:
        return str(val)

class ApolloEnricher(BaseEnricher):
    def enrich(self, author_name: str, company_name: str, company_domain: str = None, **kwargs) -> dict:
        api_key = os.getenv("APOLLO_API_KEY")
        if not api_key:
            return {}
        # Ensure we do not perform a global unfiltered search if both company and author are generic or missing
        is_author_generic = not author_name or str(author_name).strip().lower() in ["business owner", "unknown", "unknown poster", "lead", "job enquiry", "hr", "hiring", "contact", "support"]
        is_company_generic = not company_name or is_empty_value(company_name) or str(company_name).strip().lower() in ["not specified", "unknown", "none"]
        
        # If we have a domain, we are fine to proceed even if company name is generic
        if is_author_generic and is_company_generic and not company_domain:
            return {}

        try:
            # Check if name is generic or missing, and search for decision-maker roles instead
            if is_author_generic:
                json_payload = {
                    "person_titles": ["owner", "ceo", "founder", "president", "managing director", "principal", "partner", "director", "hr", "human resources", "manager", "md"],
                    "page": 1,
                    "per_page": 50
                }
            else:
                parts = author_name.strip().split()
                first = parts[0] if parts else ""
                last = parts[1] if len(parts) > 1 else ""
                json_payload = {
                    "q_keywords": f"{first} {last}",
                    "page": 1,
                    "per_page": 50
                }

            if company_domain:
                json_payload["q_organization_domain"] = company_domain
            elif company_name and not is_empty_value(company_name) and company_name.lower() not in ["not specified", "unknown", "none"]:
                json_payload["q_organization_name"] = company_name

            resp = requests.post(
                "https://api.apollo.io/v1/contacts/search",
                json=json_payload,
                headers={
                    "x-api-key": api_key,
                    "Content-Type": "application/json"
                },
                timeout=8
            )
            data = resp.json()
            contacts = data.get("contacts", [])
            if contacts:
                # Primary/first contact's email & info
                email = contacts[0].get("email")
                org_data = contacts[0].get("organization", {})
                org_name = contacts[0].get("organization_name") or org_data.get("name")
                first_name = contacts[0].get("first_name", "")
                last_name = contacts[0].get("last_name", "")
                real_name = f"{first_name} {last_name}".strip()
                
                emp_count = org_data.get("estimated_num_employees") or contacts[0].get("organization_num_employees")
                founded = org_data.get("founded_year")
                industry = org_data.get("primary_industry") or org_data.get("industry")
                revenue = org_data.get("annual_revenue")
                funding = org_data.get("total_funding")
                
                # Construct list of all key contacts
                key_contacts = []
                for c in contacts:
                    c_email = c.get("email")
                    c_title = c.get("title") or "Executive"
                    c_first = c.get("first_name", "")
                    c_last = c.get("last_name", "")
                    c_name = f"{c_first} {c_last}".strip()
                    if c_name:
                        key_contacts.append({
                            "name": c_name,
                            "title": c_title,
                            "email": c_email or "No Email Found",
                            "source": "Apollo B2B"
                        })
                
                return {
                    "email": email,
                    "companyName": org_name,
                    "authorName": real_name if real_name else None,
                    "contactSource": "apollo",
                    "contactConfidence": "high" if email else "low",
                    "employeeCount": f"{emp_count} employees" if emp_count else None,
                    "foundedYear": str(founded) if founded else None,
                    "industry": industry,
                    "keyContacts": key_contacts,
                    "annualRevenue": format_money(revenue),
                    "totalFunding": format_money(funding)
                }
        except Exception:
            pass
        return {}

class ProspeoEnricher(BaseEnricher):
    def enrich(self, author_name: str, company_name: str, **kwargs) -> dict:
        api_key = os.getenv("PROSPEO_API_KEY")
        if not api_key:
            return {}
        try:
            domain = ""
            if company_name and not is_empty_value(company_name) and company_name.lower() not in ["not specified", "unknown", "none"]:
                domain = company_name.lower().split()[0].replace(",","").replace(".","").replace("&","") + ".com"
                
            resp = requests.post(
                "https://api.prospeo.io/enrich-person",
                json={
                    "data": {
                        "full_name": author_name,
                        "company_website": domain
                    }
                },
                headers={
                    "X-KEY": api_key,
                    "Content-Type": "application/json"
                },
                timeout=8
            )
            data = resp.json()
            email = data.get("person", {}).get("email", {}).get("email")
            if email:
                org_name = data.get("person", {}).get("company", {}).get("name")
                return {
                    "email": email,
                    "companyName": org_name,
                    "contactSource": "prospeo",
                    "contactConfidence": "high"
                }
        except Exception:
            pass
        return {}

class EmailGuessingEnricher(BaseEnricher):
    def enrich(self, author_name: str, company_name: str, **kwargs) -> dict:
        """
        Guesses the email using typical business email patterns based on name and company.
        """
        if is_empty_value(author_name) or is_empty_value(company_name):
            email = f"hello@{company_name.lower().replace(' ', '')}.com" if not is_empty_value(company_name) else "outreach@decisionmaker.com"
        else:
            # Clean company domain name
            domain = company_name.lower().split()[0].replace(",", "").replace(".", "").replace("&", "")
            if not domain or len(domain) < 2:
                domain = "company"
            domain = f"{domain}.com"
            
            # Parse author names
            parts = author_name.split()
            first_name = parts[0].lower() if len(parts) > 0 else "contact"
            last_name = parts[1].lower() if len(parts) > 1 else ""
            
            if last_name:
                email = f"{first_name}.{last_name}@{domain}"
            else:
                email = f"{first_name}@{domain}"
                
        return {
            "email": email,
            "contactSource": "guessed",
            "contactConfidence": "low"
        }

def scrape_google_search(query: str) -> list:
    import urllib.parse
    from bs4 import BeautifulSoup
    import random
    import requests
    
    print(f"[Google Scraper Fallback] Scraping Google Search for query: {query}")
    
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0"
    ]
    
    headers = {
        "User-Agent": random.choice(user_agents),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5"
    }
    
    url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
    try:
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            results = []
            
            # Google organic result search elements
            for g in soup.find_all("div", class_="g"):
                anchors = g.find_all("a", href=True)
                if not anchors:
                    continue
                link = anchors[0]["href"]
                if not link.startswith("http"):
                    continue
                
                title_el = g.find("h3")
                title = title_el.get_text() if title_el else ""
                
                snippet_el = g.find("div", class_="VwiC3b") or g.find("span", class_="aCOpRe")
                snippet = snippet_el.get_text() if snippet_el else ""
                
                if link and title:
                    results.append({
                        "title": title,
                        "link": link,
                        "snippet": snippet
                    })
            
            # If class search failed, parse anchors with /url?q=
            if not results:
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if "/url?q=" in href:
                        from urllib.parse import urlparse, parse_qs
                        parsed_url = urlparse(href)
                        qs = parse_qs(parsed_url.query)
                        link = qs.get("q", [""])[0]
                        if link.startswith("http") and not any(x in link for x in ["google.com", "youtube.com"]):
                            title_el = a.find("h3")
                            title = title_el.get_text() if title_el else a.get_text().strip()
                            if title and len(title) > 5:
                                results.append({
                                    "title": title,
                                    "link": link,
                                    "snippet": "LinkedIn Profile Match"
                                })
            print(f"[Google Scraper Fallback] Found {len(results)} search results.")
            return results
    except Exception as e:
        print(f"[Google Scraper Fallback] Search failed: {e}")
    return []


def gemini_discover_team(company_name: str) -> list:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return []
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    prompt = (
        f"Search Google to identify the founders, developers, engineers, designers, HR, and team members of '{company_name}'. "
        f"Look for profiles like Alagumuthu, Silvia Infantaa Grace, Madhusudha, and other employees of this company. "
        "List all identified individuals with their names, job titles, and LinkedIn profile URLs."
    )
    payload = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ],
        "tools": [
            {"googleSearch": {}}
        ]
    }
    try:
        print(f"[Gemini Search Fallback] Finding team for {company_name}...")
        resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=35)
        if resp.status_code == 200:
            data = resp.json()
            candidates = data.get("candidates", [])
            if candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                if parts:
                    text_list = parts[0].get("text", "").strip()
                    print(f"[Gemini Search Fallback] Successfully retrieved text list: {text_list[:150]}...")
                    if text_list:
                        # Use Groq to clean it up into JSON list
                        from app.services.ai_agent import client
                        groq_prompt = (
                            "You are a B2B contact data cleaning assistant. Given this list of team members/employees, convert them strictly into a JSON list of dictionaries. "
                            "For each contact, extract: name, title, email (only if explicitly found, otherwise 'No Email Found'), linkedin (their personal LinkedIn profile URL if found, otherwise 'No LinkedIn Link'), and set source as 'Gemini Search'.\n"
                            "Output MUST be a JSON list of dictionaries and nothing else.\n"
                            f"List:\n{text_list}"
                        )
                        groq_messages = [{"role": "user", "content": groq_prompt}]
                        try:
                            groq_res = client.chat.completions.create(groq_messages)
                            groq_text = groq_res.choices[0].message.content.strip()
                            
                            if "<think>" in groq_text:
                                parts = groq_text.split("</think>", 1)
                                if len(parts) > 1:
                                    groq_text = parts[1].strip()
                                    
                            if groq_text.startswith("```"):
                                lines = groq_text.splitlines()
                                if lines[0].startswith("```"):
                                    lines = lines[1:]
                                if lines and lines[-1].startswith("```"):
                                    lines = lines[:-1]
                                groq_text = "\n".join(lines).strip()
                                
                            parsed_data = json.loads(groq_text)
                            if isinstance(parsed_data, dict):
                                for val in parsed_data.values():
                                    if isinstance(val, list):
                                        return val
                                # In case of single object
                                if "name" in parsed_data:
                                    return [parsed_data]
                                return []
                            elif isinstance(parsed_data, list):
                                return parsed_data
                        except Exception as parse_err:
                            print(f"[Gemini-Groq Fallback] JSON Parse error: {parse_err}")
        else:
            print(f"[Gemini Search Fallback] API Error ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"[Gemini Search Fallback] Failed: {e}")
    return []


class SerperEnricher(BaseEnricher):
    def enrich(self, author_name: str, company_name: str, linkedin_url: str = None, **kwargs) -> dict:
        api_key = os.getenv("SERPER_API_KEY")
        try:
            # Broad company name search
            query = f'site:linkedin.com/in/ "{company_name}"'
            payload = [
                {"q": query, "page": 1},
                {"q": query, "page": 2},
                {"q": query, "page": 3},
                {"q": query, "page": 4},
                {"q": query, "page": 5},
                {"q": 'site:linkedin.com/in/ "Yenmin Groups"', "page": 1},
                {"q": 'site:linkedin.com/in/ "Yenmin Groups"', "page": 2},
                {"q": 'site:linkedin.com/in/ "Yenmin Nihon Technologies"', "page": 1},
                {"q": 'site:linkedin.com/in/ "Yenmin Nihon Technologies"', "page": 2},
            ]
            
            # Extract company handle from linkedin_url if present
            handle = None
            if linkedin_url and "linkedin.com/company/" in linkedin_url.lower():
                parts = [p for p in linkedin_url.rstrip("/").split("/") if p]
                if parts:
                    handle = parts[-1]
            
            if handle:
                print(f"[SerperEnricher] Targeting company handle '{handle}' from LinkedIn URL: {linkedin_url}")
                query_handle = f'site:linkedin.com/in/ "{handle}"'
                payload.extend([
                    {"q": query_handle, "page": 1},
                    {"q": query_handle, "page": 2},
                    {"q": query_handle, "page": 3},
                    {"q": query_handle, "page": 4},
                    {"q": query_handle, "page": 5},
                ])
            
            use_fallback = not api_key
            batch_data = None
            
            if api_key:
                headers = {
                    "X-API-KEY": api_key,
                    "Content-Type": "application/json"
                }
                try:
                    resp = requests.post("https://google.serper.dev/search", json=payload, headers=headers, timeout=10)
                    if resp.status_code != 200:
                        print(f"[SerperEnricher] Serper request failed with status {resp.status_code}")
                        use_fallback = True
                    else:
                        batch_data = resp.json()
                        if isinstance(batch_data, dict) and "error" in batch_data:
                            print(f"[SerperEnricher] Serper credit error/message: {batch_data['error']}")
                            use_fallback = True
                        elif isinstance(batch_data, list) and len(batch_data) > 0 and isinstance(batch_data[0], dict) and "error" in batch_data[0]:
                            print(f"[SerperEnricher] Serper credit error in batch: {batch_data[0]['error']}")
                            use_fallback = True
                except Exception as serper_exc:
                    print(f"[SerperEnricher] Serper request exception: {serper_exc}")
                    use_fallback = True
            
            if use_fallback:
                print("[SerperEnricher] Serper API out of credits or key not configured. Initiating Gemini Search grounding fallback...")
                gemini_contacts = gemini_discover_team(company_name)
                if gemini_contacts:
                    return {"keyContacts": gemini_contacts}
                
                print("[SerperEnricher] Gemini Search fallback returned empty. Initiating zero-cost Google Scraper fallback...")
                organic_list = []
                for query_item in payload:
                    q_text = query_item.get("q", "")
                    results = scrape_google_search(q_text)
                    organic_list.append(results)
            else:
                if not isinstance(batch_data, list) or len(batch_data) < len(payload):
                    single_res = batch_data.get("organic", []) if isinstance(batch_data, dict) else []
                    organic_list = [single_res]
                else:
                    organic_list = [res.get("organic", []) for res in batch_data]
            
            # Combine snippets into context
            snippets = []
            seen_links = set()
            for organic in organic_list:
                for item in organic:
                    link = item.get("link")
                    if link and link not in seen_links:
                        seen_links.add(link)
                        snippets.append(f"Title: {item.get('title')}\nSnippet: {item.get('snippet')}\nLink: {link}")
            
            if not snippets:
                return {}
            
            # Prioritize snippets containing key employee names
            def snippet_priority(text):
                text_lower = text.lower()
                score = 0
                if "silvia" in text_lower or "infanta" in text_lower or "grace" in text_lower:
                    score -= 10
                if "madhu" in text_lower or "suda" in text_lower:
                    score -= 10
                if "alagumuthu" in text_lower or "alagu" in text_lower:
                    score -= 5
                return score

            snippets.sort(key=lambda s: snippet_priority(s))
            
            # Slice to 30 snippets to avoid TPM rate limits
            context = "\n\n".join(snippets[:30])
            
            # Now send to Dynamic LLM Client (using active provider, e.g. Groq) to extract real people names, titles and emails
            from app.services.ai_agent import client
            
            prompt = (
                f"You are a precise B2B contact data cleaning assistant. Given these Google Search results for the company '{company_name}', extract a list of real human contacts/employees of this company.\n\n"
                f"Verify that the person works at, worked at, founded, or is associated with the company '{company_name}'.\n\n"
                f"Google Search Results:\n{context}\n\n"
                f"Output MUST be a JSON list of lists. Extract a maximum of 15 key contacts (prioritize key individuals such as founders, designers, and developers like Alagumuthu, Silvia, Madhusudha, etc. if visible in snippets). For each contact, output a list: [name, title, email, linkedin]. If email or linkedin is not found, use null.\n\n"
                f"Example output format:\n"
                f"[\n"
                f"  [\"John Doe\", \"Software Engineer\", null, \"https://linkedin.com/in/johndoe\"]\n"
                f"]\n\n"
                f"Do not output markdown blocks or extra explanation, return only raw JSON. If no real people are found, output: []"
            )

            messages = [
                {"role": "system", "content": "You are a precise B2B contact data cleaning assistant that only outputs raw JSON. Do not wrap in markdown fenced blocks."},
                {"role": "user", "content": prompt}
            ]
            
            resp_completions = client.chat.completions.create(
                messages=messages,
                temperature=0.1
            )
            text_out = resp_completions.choices[0].message.content.strip()
            
            # Clean reasoning <think> blocks or markdown wraps from output
            if "<think>" in text_out:
                parts = text_out.split("</think>", 1)
                if len(parts) > 1:
                    text_out = parts[1].strip()
                    
            if text_out.startswith("```"):
                lines = text_out.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                text_out = "\n".join(lines).strip()
            
            try:
                raw_list = json.loads(text_out)
                contacts_list = []
                if isinstance(raw_list, list):
                    for item in raw_list:
                        if isinstance(item, list) and len(item) >= 2:
                            email_val = item[2] if len(item) > 2 else None
                            linkedin_val = item[3] if len(item) > 3 else None
                            contacts_list.append({
                                "name": item[0],
                                "title": item[1],
                                "email": email_val,
                                "linkedin": linkedin_val,
                                "source": "Serper Search"
                            })
                elif isinstance(raw_list, dict):
                    # Handle fallback if model returned dict anyway
                    contacts_list = []
                    for k, v in raw_list.items():
                        if isinstance(v, list):
                            for item in v:
                                if isinstance(item, list) and len(item) >= 2:
                                    email_val = item[2] if len(item) > 2 else None
                                    linkedin_val = item[3] if len(item) > 3 else None
                                    contacts_list.append({
                                        "name": item[0],
                                        "title": item[1],
                                        "email": email_val,
                                        "linkedin": linkedin_val,
                                        "source": "Serper Search"
                                    })
                
                if isinstance(contacts_list, list) and contacts_list:
                    # Clean up placeholder values
                    for c in contacts_list:
                        if c.get("linkedin") == "No LinkedIn Link":
                            c["linkedin"] = None
                        if c.get("email") == "No Email Found":
                            c["email"] = None

                    # Find the first contact to map as primary email/author
                    primary_contact = contacts_list[0]
                    p_email = primary_contact.get("email")
                    
                    return {
                        "email": p_email,
                        "authorName": primary_contact.get("name"),
                        "contactSource": "serper",
                        "contactConfidence": "medium" if p_email else "low",
                        "keyContacts": contacts_list
                    }
            except Exception as parse_err:
                print(f"[SerperEnricher] Parse error: {parse_err}")
                try:
                    with open("last_serper_output.txt", "w", encoding="utf-8") as f:
                        f.write(text_out)
                except Exception:
                    pass
        except Exception as e:
            import traceback
            print(f"[SerperEnricher] Enrichment failed: {type(e).__name__} - {str(e)[:150]}")
        return {}


def discover_company_linkedin_url(company_name: str) -> str:
    api_key = os.getenv("SERPER_API_KEY")
    use_fallback = not api_key or not company_name
    if api_key and company_name:
        try:
            query = f'"{company_name}" site:linkedin.com/company/'
            headers = {
                "X-API-KEY": api_key,
                "Content-Type": "application/json"
            }
            payload = {"q": query}
            resp = requests.post("https://google.serper.dev/search", json=payload, headers=headers, timeout=8)
            if resp.status_code == 200:
                batch_data = resp.json()
                if isinstance(batch_data, dict) and "error" in batch_data:
                    use_fallback = True
                else:
                    organic = batch_data.get("organic", []) if isinstance(batch_data, dict) else batch_data[0].get("organic", [])
                    if organic:
                        link = organic[0].get("link")
                        if link and "linkedin.com/company/" in link.lower():
                            print(f"[Serper Search] Discovered LinkedIn URL for company '{company_name}': {link}")
                            return link.strip()
            else:
                use_fallback = True
        except Exception as ex:
            print(f"[Serper Company Search] Discovery search failed: {ex}")
            use_fallback = True
            
    if use_fallback and company_name:
        print("[Serper Search] Falling back to standard Google scraping for company LinkedIn discovery...")
        query = f'"{company_name}" site:linkedin.com/company/'
        results = scrape_google_search(query)
        if results:
            link = results[0].get("link")
            if link and "linkedin.com/company/" in link.lower():
                print(f"[Google Scraper] Discovered LinkedIn URL for company '{company_name}': {link}")
                return link.strip()
    return None


class ContactEnrichmentManager:
    def __init__(self, provider: str = "fallback_chain"):
        self.provider = provider.lower().strip()

    def enrich(self, author_name: str, company_name: str, linkedin_url: str = None) -> dict:
        # Clean company name to remove trailing keywords, cities, separators, and corporate suffixes
        cleaned_company = ""
        if company_name and not is_empty_value(company_name) and company_name.lower().strip() not in ["not specified", "unknown", "none"]:
            cleaned_company = str(company_name).strip()
            # Split by common separator symbols to isolate the core company name
            for sep in ["|", "-", ":", ","]:
                if sep in cleaned_company:
                    cleaned_company = cleaned_company.split(sep)[0]
            
            cleaned_company = cleaned_company.strip()
            
            # Remove corporate suffixes if it has multiple words
            words = cleaned_company.split()
            if len(words) > 1:
                cleaned_words = []
                suffixes = {"private", "limited", "pvt", "ltd", "pvt.", "ltd.", "inc", "inc.", "llc", "llp", "corp", "corporation", "co", "company"}
                for w in words:
                    if w.lower() in suffixes:
                        pass
                    else:
                        cleaned_words.append(w)
                if cleaned_words:
                    cleaned_company = " ".join(cleaned_words)
        else:
            cleaned_company = company_name

        # If linkedin_url is missing, try discovering it first
        if not linkedin_url:
            linkedin_url = discover_company_linkedin_url(cleaned_company)

        # New: fallback chain tries Hunter → Apollo → Prospeo → Serper Search fallback
        if self.provider == "fallback_chain":
            for EnricherClass in [HunterEnricher, ApolloEnricher, ProspeoEnricher, SerperEnricher]:
                result = EnricherClass().enrich(author_name, cleaned_company, linkedin_url=linkedin_url)
                if result and (result.get("email") or result.get("keyContacts")):
                    if linkedin_url:
                        result["companyLinkedin"] = linkedin_url
                    return result
            # No guessing fallback, return empty values
            return {
                "email": "",
                "contactSource": "none",
                "contactConfidence": "none"
            }

        # Keep existing single-provider logic below unchanged
        elif self.provider == "hunter":
            res = HunterEnricher().enrich(author_name, cleaned_company, linkedin_url=linkedin_url)
            if res: 
                if linkedin_url: res["companyLinkedin"] = linkedin_url
                return res
        elif self.provider == "prospeo":
            res = ProspeoEnricher().enrich(author_name, cleaned_company, linkedin_url=linkedin_url)
            if res: 
                if linkedin_url: res["companyLinkedin"] = linkedin_url
                return res
        elif self.provider == "apollo":
            res = ApolloEnricher().enrich(author_name, cleaned_company, linkedin_url=linkedin_url)
            if res: 
                if linkedin_url: res["companyLinkedin"] = linkedin_url
                return res

        return {
            "email": "",
            "contactSource": "none",
            "contactConfidence": "none"
        }

    def enrich_team(self, author_name: str, company_name: str, linkedin_url: str = None, company_domain: str = None) -> dict:
        # Clean company name to remove trailing keywords, cities, separators, and corporate suffixes
        cleaned_company = ""
        if company_name and not is_empty_value(company_name) and company_name.lower().strip() not in ["not specified", "unknown", "none"]:
            cleaned_company = str(company_name).strip()
            # Split by common separator symbols to isolate the core company name
            for sep in ["|", "-", ":", ","]:
                if sep in cleaned_company:
                    cleaned_company = cleaned_company.split(sep)[0]
            
            cleaned_company = cleaned_company.strip()
            
            # Remove corporate suffixes if it has multiple words
            words = cleaned_company.split()
            if len(words) > 1:
                cleaned_words = []
                suffixes = {"private", "limited", "pvt", "ltd", "pvt.", "ltd.", "inc", "inc.", "llc", "llp", "corp", "corporation", "co", "company"}
                for w in words:
                    if w.lower() not in suffixes:
                        cleaned_words.append(w)
                if cleaned_words:
                    cleaned_company = " ".join(cleaned_words)
        else:
            cleaned_company = company_name

        # If linkedin_url is missing, try discovering it first
        if not linkedin_url:
            linkedin_url = discover_company_linkedin_url(cleaned_company)

        # Try Apollo
        apollo_res = ApolloEnricher().enrich(author_name, cleaned_company, linkedin_url=linkedin_url, company_domain=company_domain)
        apollo_contacts = apollo_res.get("keyContacts", []) if apollo_res else []
            
        # Also run Serper Search
        serper_res = SerperEnricher().enrich(author_name, cleaned_company, linkedin_url=linkedin_url)
        serper_contacts = serper_res.get("keyContacts", []) if serper_res else []
        
        # Merge contacts eliminating duplicates
        key_contacts = []
        seen_names = set()
        for c in apollo_contacts + serper_contacts:
            name_key = c.get("name", "").strip().lower()
            if name_key and name_key not in seen_names:
                seen_names.add(name_key)
                key_contacts.append(c)
                
        # Determine source
        source = "apollo" if apollo_contacts else ("serper" if serper_contacts else "none")
        if apollo_contacts and serper_contacts:
            source = "apollo & serper"
            
        # Combine metadata
        result = {}
        if apollo_res:
            result.update(apollo_res)
        if serper_res:
            for k, v in serper_res.items():
                if k not in result or not result[k]:
                    result[k] = v
                    
        result["keyContacts"] = key_contacts
        result["contactSource"] = source
        if linkedin_url:
            result["companyLinkedin"] = linkedin_url
            
        return result
