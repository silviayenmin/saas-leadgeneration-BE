import os
import requests
import json
import httpx
from app.core.config import settings
from app.qualification import is_empty_value

def get_chat_completion(messages, response_format=None, temperature=0.1) -> str:
    api_key = settings.GROQ_API_KEY
    if api_key and api_key.strip():
        try:
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "groq/compound-mini",
                "messages": messages,
                "temperature": temperature
            }
            if response_format:
                payload["response_format"] = response_format
            with httpx.Client(timeout=25.0) as client:
                res = client.post(url, headers=headers, json=payload)
                if res.status_code == 200:
                    return res.json()["choices"][0]["message"]["content"]
                else:
                    print(f"[ContactEnrichment] Groq returned status {res.status_code}: {res.text}")
        except Exception as e:
            print(f"[ContactEnrichment] Groq chat completion failed: {e}")
    
    # Fallback to Ollama
    try:
        url = f"{settings.OLLAMA_BASE_URL}/api/generate"
        prompt_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])
        payload = {
            "model": "llama3.1:8b",
            "prompt": prompt_str,
            "stream": False
        }
        if response_format and response_format.get("type") == "json_object":
            payload["format"] = "json"
        with httpx.Client(timeout=30.0) as client:
            res = client.post(url, json=payload)
            if res.status_code == 200:
                return res.json().get("response", "")
    except Exception as e:
        print(f"[ContactEnrichment] Ollama fallback chat completion failed: {e}")
    return ""


class BaseEnricher:
    def enrich(self, author_name: str, company_name: str) -> dict:
        raise NotImplementedError

class HunterEnricher(BaseEnricher):
    def enrich(self, author_name: str, company_name: str) -> dict:
        api_key = settings.HUNTER_API_KEY
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
    def enrich(self, author_name: str, company_name: str) -> dict:
        api_key = settings.APOLLO_API_KEY
        if not api_key:
            return {}
        # Ensure we do not perform a global unfiltered search if both company and author are generic or missing
        is_author_generic = not author_name or str(author_name).strip().lower() in ["business owner", "unknown", "unknown poster", "lead", "job enquiry", "hr", "hiring", "contact", "support"]
        is_company_generic = not company_name or is_empty_value(company_name) or str(company_name).strip().lower() in ["not specified", "unknown", "none"]
        
        if is_author_generic and is_company_generic:
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

            if company_name and not is_empty_value(company_name) and company_name.lower() not in ["not specified", "unknown", "none"]:
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
    def enrich(self, author_name: str, company_name: str) -> dict:
        api_key = settings.PROSPEO_API_KEY
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

# Keep ClearbitEnricher and DropcontactEnricher as placeholders for now

class EmailGuessingEnricher(BaseEnricher):
    def enrich(self, author_name: str, company_name: str) -> dict:
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


class SerperEnricher(BaseEnricher):
    def enrich(self, author_name: str, company_name: str) -> dict:
        api_key = settings.SERPER_API_KEY
        if not api_key:
            return {}
        try:
            # Query 1: General executive search
            query1 = f'"{company_name}" CEO founder owner managing director key people'
            # Query 2: Targeted LinkedIn profiles search
            query2 = f'site:linkedin.com/in/ "{company_name}"'
            
            payload = [
                {"q": query1},
                {"q": query2, "page": 1},
                {"q": query2, "page": 2},
                {"q": query2, "page": 3},
                {"q": query2, "page": 4},
                {"q": query2, "page": 5}
            ]
            
            headers = {
                "X-API-KEY": api_key,
                "Content-Type": "application/json"
            }
            
            resp = requests.post("https://google.serper.dev/search", json=payload, headers=headers, timeout=10)
            if resp.status_code != 200:
                return {}
                
            batch_data = resp.json()
            if not isinstance(batch_data, list) or len(batch_data) < 6:
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
            
            context = "\n\n".join(snippets[:50])
            
            prompt = (f"You are a B2B contact data cleaning assistant. Given these Google Search results for the company '{company_name}', extract a list of at most 8 key contacts/employees of this company.\n"
                      f"Verify that the person currently works at, founded, or is directly associated with the company '{company_name}' (or related variations like '{company_name} Systems'). If their current company is clearly listed as a different organization, or they simply used the words '{company_name}' in a sentence (like 'translating insights into design' or 'putting empathy back into design'), do NOT extract them.\n\n"
                      f"Google Search Results:\n{context}\n\n"
                      f"Output MUST be a JSON list of dictionaries. For each contact, extract: name, title, email (only if explicitly found in snippets, otherwise 'No Email Found'), linkedin (their personal LinkedIn profile URL if visible in the links or snippets, otherwise 'No LinkedIn Link'), and set source as 'Serper Search'.\n"
                      f"Example format:\n"
                      f'[\n  {{"name": "John Doe", "title": "Software Engineer", "email": "No Email Found", "linkedin": "https://linkedin.com/in/johndoe", "source": "Serper Search"}}\n]\n'
                      f"If no real individual names of actual people associated with '{company_name}' are found in the snippets, output an empty list: []\n"
                      f"Be extremely strict. Do not output company names, mock names, placeholder text, or markdown blocks except raw JSON.")

            messages = [
                {"role": "system", "content": "You are a precise data extractor helper that only outputs raw JSON. Do not wrap in markdown fenced blocks."},
                {"role": "user", "content": prompt}
            ]
            
            # Request JSON object response format
            response_format = {"type": "json_object"}
            text_out = get_chat_completion(messages, response_format=response_format, temperature=0.1).strip()
            
            try:
                contacts_list = json.loads(text_out)
                if isinstance(contacts_list, dict):
                    if "contacts" in contacts_list and isinstance(contacts_list["contacts"], list):
                        contacts_list = contacts_list["contacts"]
                    else:
                        for val in contacts_list.values():
                            if isinstance(val, list):
                                contacts_list = val
                                break

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
                print(f"[SerperEnricher] Parse error: {parse_err}. Response text: {text_out}")
        except Exception as e:
            print(f"[SerperEnricher] Enrichment failed: {e}")
        return {}


class ContactEnrichmentManager:
    def __init__(self, provider: str = "fallback_chain"):
        self.provider = provider.lower().strip()

    def enrich(self, author_name: str, company_name: str) -> dict:
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

        # New: fallback chain tries Apollo → Hunter → Prospeo → Serper Search fallback
        if self.provider == "fallback_chain":
            for EnricherClass in [ApolloEnricher, HunterEnricher, ProspeoEnricher, SerperEnricher]:
                result = EnricherClass().enrich(author_name, cleaned_company)
                if result and (result.get("email") or result.get("keyContacts")):
                    return result
            # No guessing fallback, return empty values
            return {
                "email": "",
                "contactSource": "none",
                "contactConfidence": "none"
            }

        # Keep existing single-provider logic below unchanged
        elif self.provider == "hunter":
            res = HunterEnricher().enrich(author_name, cleaned_company)
            if res: return res
        elif self.provider == "prospeo":
            res = ProspeoEnricher().enrich(author_name, cleaned_company)
            if res: return res
        elif self.provider == "apollo":
            res = ApolloEnricher().enrich(author_name, cleaned_company)
            if res: return res

        return {
            "email": "",
            "contactSource": "none",
            "contactConfidence": "none"
        }

    def enrich_team(self, author_name: str, company_name: str) -> dict:
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

        # Try Apollo first
        apollo_res = ApolloEnricher().enrich(author_name, cleaned_company)
        if apollo_res and apollo_res.get("keyContacts"):
            # Set source correctly
            apollo_res["contactSource"] = "apollo"
            return apollo_res
            
        # Fallback to Serper Search
        serper_res = SerperEnricher().enrich(author_name, cleaned_company)
        if serper_res:
            serper_res["contactSource"] = "serper"
            return serper_res
            
        return {}