import json
import logging
import httpx
from typing import Dict, Any, Optional
from app.core.config import settings

logger = logging.getLogger("mapflow_ai.ai_service")

class GroqProvider:
    @staticmethod
    async def generate(prompt: str, api_key: str, model: str = "llama-3.3-70b-versatile", temperature: float = 0.7) -> str:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are MapFlow AI, an expert B2B lead generation & sales pitch assistant."},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(url, headers=headers, json=payload)
            if res.status_code == 200:
                data = res.json()
                return data["choices"][0]["message"]["content"]
            else:
                raise Exception(f"Groq API Error ({res.status_code}): {res.text}")

class OllamaProvider:
    @staticmethod
    async def generate(prompt: str, base_url: str = settings.OLLAMA_BASE_URL, model: str = "llama3.1:8b", temperature: float = 0.7) -> str:
        url = f"{base_url.rstrip('/')}/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature
            }
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(url, json=payload)
            if res.status_code == 200:
                data = res.json()
                return data.get("response", "")
            else:
                raise Exception(f"Ollama API Error ({res.status_code}): {res.text}")

class AIService:
    @staticmethod
    async def score_lead(business_data: Dict[str, Any], provider: str = "groq", api_key: str = "") -> Dict[str, Any]:
        prompt = f"""
Analyze the following local business lead and return a JSON object with:
- "score": integer from 0 to 100
- "intent": string ("HIGH", "MEDIUM", "LOW")
- "reasoning": string explanation of score rationale.

Business Details:
Name: {business_data.get('name')}
Category: {business_data.get('category')}
Rating: {business_data.get('rating')} ({business_data.get('reviewCount')} reviews)
Website: {business_data.get('website', 'None')}
Phone: {business_data.get('phone', 'None')}
Website Details: {json.dumps(business_data.get('websiteIntelligence', {}))}

Return ONLY valid JSON matching this schema:
{{"score": 85, "intent": "HIGH", "reasoning": "Strong reviews but lacks mobile optimization."}}
"""
        effective_key = api_key or settings.GROQ_API_KEY
        try:
            if provider == "groq" and effective_key:
                response_text = await GroqProvider.generate(prompt, effective_key)
            else:
                response_text = await OllamaProvider.generate(prompt)

            # Clean json fences if any
            cleaned = response_text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            return json.loads(cleaned.strip())
        except Exception as e:
            logger.warning(f"AI scoring failed: {e}. Returning rule-based calculation fallback.")
            # Fallback rule-based score logic
            rating = float(business_data.get("rating") or 0.0)
            reviews = int(business_data.get("reviewCount") or 0)
            has_web = bool(business_data.get("website"))
            
            score = 50
            if rating >= 4.0: score += 20
            if reviews > 30: score += 15
            if not has_web: score += 15  # prime web redesign candidate

            intent = "HIGH" if score >= 70 else ("MEDIUM" if score >= 40 else "LOW")
            return {
                "score": min(100, score),
                "intent": intent,
                "reasoning": f"Calculated based on rating ({rating}), review count ({reviews}), and digital presence."
            }

    @staticmethod
    async def generate_cold_pitch(business_data: Dict[str, Any], pitch_type: str, provider: str = "groq", api_key: str = "", model: str = None, temperature: float = 0.7, base_url: str = None) -> str:
        prompt = f"""
Write a highly personalized, professional cold outreach email to the owner of {business_data.get('name')}.
Pitch Type: {pitch_type}
Business Category: {business_data.get('category')}
Rating & Reviews: {business_data.get('rating')} Stars ({business_data.get('reviewCount')} reviews)
Website: {business_data.get('website', 'N/A')}

Guidelines:
- Do NOT start with 'Dear Sir/Madam' or 'To whom it may concern'. Use 'Hi [Owner Name / Team],'
- Reference their strong reputation or specific website issue.
- Concise, engaging, under 150 words.
"""
        effective_key = api_key or settings.GROQ_API_KEY
        try:
            if provider == "groq" and effective_key:
                effective_model = model or "llama-3.3-70b-versatile"
                return await GroqProvider.generate(prompt, effective_key, model=effective_model, temperature=temperature)
            else:
                effective_model = model or "llama3.1:8b"
                effective_url = base_url or settings.OLLAMA_BASE_URL
                return await OllamaProvider.generate(prompt, base_url=effective_url, model=effective_model, temperature=temperature)
        except Exception as e:
            logger.warning(f"AI pitch generation failed ({e}). Returning template pitch.")
            return f"Hi {business_data.get('name')} Team,\n\nI noticed {business_data.get('name')} has an impressive {business_data.get('rating')}-star rating on Google Maps!\n\nWe specialize in {pitch_type} for top-tier local service providers. Would you be open to a 5-minute chat this week on how we can double your online leads?\n\nBest regards,\nMapFlow AI Team"
