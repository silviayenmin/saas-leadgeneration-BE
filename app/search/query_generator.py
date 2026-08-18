class IntentQueryGenerator:
    @staticmethod
    def generate(keyword: str) -> list:
        import re
        
        # Clean common intent prefixes to avoid double-prefixing
        cleaned_keyword = keyword.strip()
        prefixes = [
            r"looking\s+to\s+hire",
            r"looking\s+to\s+find",
            r"recommendation\s+for",
            r"recommendations\s+for",
            r"searching\s+for",
            r"looking\s+for",
            r"in\s+search\s+of",
            r"in\s+need\s+of",
            r"seek\s+partner",
            r"seeking\s+partner",
            r"seeking",
            r"hire",
            r"hiring",
            r"needed",
            r"needs",
            r"need",
            r"wanted",
            r"want",
            r"recommend",
            r"recommends",
        ]
        
        for prefix in prefixes:
            pattern = re.compile(rf"^{prefix}\b\s*", re.IGNORECASE)
            if pattern.match(cleaned_keyword):
                cleaned_keyword = pattern.sub("", cleaned_keyword).strip()
                break
                
        keyword_lower = cleaned_keyword.lower().strip()
        if not keyword_lower:
            keyword_lower = keyword.lower().strip()
            
        # Check if the keyword represents a service that needs a suffix (like "company")
        # to avoid queries like "looking for software development" when we want "looking for software development company"
        needs_suffix = True
        for suffix in ["company", "agency", "partner", "consultant", "developer", "designer", "firm", "service", "provider", "expert", "lawyer", "attorney", "accountant", "freelancer", "intern", "paralegal", "copywriter", "specialist", "engineer", "advisor", "adviser"]:
            if suffix in keyword_lower:
                needs_suffix = False
                break
                
        # Ensure we cover both singular and plural forms of the keyword
        keyword_variants = [keyword_lower]
        if keyword_lower.endswith("s"):
            if len(keyword_lower) > 3 and not keyword_lower.endswith("ss") and not keyword_lower.endswith("us"):
                if keyword_lower.endswith("ies"):
                    keyword_variants.append(keyword_lower[:-3] + "y")
                else:
                    keyword_variants.append(keyword_lower[:-1])
        else:
            if len(keyword_lower) > 3:
                if keyword_lower.endswith("y"):
                    keyword_variants.append(keyword_lower[:-1] + "ies")
                else:
                    keyword_variants.append(keyword_lower + "s")
                    
        intent_terms = [
            '"looking for"', '"hiring"', '"seeking"', '"need"', '"wanted"',
            '"vacancy"', '"open position"', '"job opening"', '"hiring for"',
            '"looking to hire"', '"recommendation"', '"opportunities"', '"freelance"', '"contract"'
        ]
        intent_clause = " OR ".join(intent_terms)
        
        queries = []
        for variant in keyword_variants:
            # 1. Broad combined intent search
            queries.append(f'({intent_clause}) {variant}')
            
            # 2. Service-level templates (only if needs_suffix is True)
            if needs_suffix:
                queries.append(f'({intent_clause}) {variant} company')
                queries.append(f'({intent_clause}) {variant} partner')
                
            # 3. Special rule for development keywords
            if "development" in variant:
                base = variant.replace("software", "").strip()
                if base == "development" or not base:
                    base = "web development"
                else:
                    if "development" not in base:
                        base = f"{base} development"
                queries.append(f'{base} agency')

        # De-duplicate queries list
        result = []
        for q in queries:
            if q.strip() and q.strip() not in result:
                result.append(q.strip())
                
        if result:
            combined_query = " OR ".join(f"({q})" for q in result)
            return [combined_query]
        return []
