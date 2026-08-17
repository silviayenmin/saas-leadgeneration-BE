import re
from typing import Optional

def extract_founded_year_from_text(text: str) -> Optional[int]:
    """
    Extracts founded/established year from a block of text.
    """
    if not text:
        return None
        
    # Look for patterns like: established 1999, founded 2005, est. 1888, since 1994, etc.
    patterns = [
        r"\b(?:established|founded|est\.?|since)\s+(\d{4})\b",
        r"\b(?:est\.|established|founded|since)\b.+(?:in|since)?\s+(\d{4})\b"
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            year = int(match)
            if 1700 <= year <= 2026:
                return year
                
    # Fallback to look for any 4 digit year between 1800 and 2026 in the text
    matches = re.findall(r"\b(1[89]\d{2}|20[0-2]\d)\b", text)
    if matches:
        return int(matches[0])
        
    return None
