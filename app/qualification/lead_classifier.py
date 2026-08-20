import os
import json
import httpx
from app.core.config import settings

def clean_json_response(response_text):
    cleaned = response_text.strip()
    
    # Remove markdown formatting wraps
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
        
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
        
    cleaned = cleaned.strip()
    
    start = cleaned.find('{')
    end = cleaned.rfind('}')
    if start != -1 and end != -1:
        return cleaned[start:end+1]
    return cleaned

def classify_lead_intent(title: str, snippet: str, search_type: str = "sales", platform: str = None) -> dict:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    platform_clean = str(platform or "").lower().strip()
    if platform_clean in ["weworkremotely", "freelancer", "upwork"]:
        filename = "project_prompt.txt"
    elif str(search_type).lower().strip() == "recruiter":
        filename = "candidate_prompt.txt"
    else:
        filename = "lead_prompt.txt"
        
    prompt_path = os.path.join(base_dir, "prompts", filename)
    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read()

    prompt = template.format(title=title, snippet=snippet)

    # Attempt to use Groq API first
    api_key = settings.GROQ_API_KEY
    if api_key and api_key.strip():
        try:
            print(f"[LeadClassifier] Trying Groq classification for {title[:40]}...")
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "groq/compound-mini",
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0
            }
            with httpx.Client(timeout=25.0) as client:
                res = client.post(url, headers=headers, json=payload)
                if res.status_code == 200:
                    raw_content = res.json()["choices"][0]["message"]["content"]
                    cleaned = clean_json_response(raw_content)
                    return json.loads(cleaned)
                else:
                    print(f"[LeadClassifier] Groq returned status {res.status_code}: {res.text}")
        except Exception as e:
            print(f"[LeadClassifier] Groq classification failed: {e}")

    # Fallback to Gemini API
    try:
        gemini_key = settings.GEMINI_API_KEY
        if gemini_key and gemini_key.strip():
            print(f"[LeadClassifier] Falling back to Gemini API classification for {title[:40]}...")
            contents = [
                {
                    "role": "user",
                    "parts": [{"text": prompt}]
                }
            ]
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
            headers = {"Content-Type": "application/json"}
            payload = {
                "contents": contents,
                "generationConfig": {"responseMimeType": "application/json"}
            }
            with httpx.Client(timeout=25.0) as client:
                res = client.post(url, headers=headers, json=payload)
                if res.status_code == 200:
                    raw_content = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                    cleaned = clean_json_response(raw_content)
                    return json.loads(cleaned)
                else:
                    print(f"[LeadClassifier] Gemini returned status {res.status_code}: {res.text}")
    except Exception as e:
        print(f"[LeadClassifier] Gemini classification failed: {e}")

    # Fallback to Ollama
    try:
        print(f"[LeadClassifier] Falling back to Ollama classification for {title[:40]}...")
        url = f"{settings.OLLAMA_BASE_URL}/api/generate"
        payload = {
            "model": "llama3.1:8b",
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }
        with httpx.Client(timeout=30.0) as client:
            res = client.post(url, json=payload)
            if res.status_code == 200:
                raw_content = res.json().get("response", "")
                cleaned = clean_json_response(raw_content)
                return json.loads(cleaned)
            else:
                print(f"[LeadClassifier] Ollama returned status {res.status_code}: {res.text}")
    except Exception as e:
        print(f"[LeadClassifier] Ollama classification failed: {e}")

    return {}
