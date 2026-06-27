import re

class Cleaner:
    @staticmethod
    async def clean(text: str) -> str:
        if not text:
            return ""

        # Remove navigation/header/footer boilerplate by keywords
        lines = text.split("\n")
        cleaned_lines = []
        
        boilerplate_patterns = [
            r'log\s*in|sign\s*in|register|login|signup',
            r'privacy\s*policy|terms\s*of\s*service|terms\s*&\s*conditions|cookies|cookie\s*policy',
            r'customer\s*care|customer\s*support|help\s*center|faq|newsletter|subscribe',
            r'gift\s*card|download\s*app|social\s*media|follow\s*us|facebook|instagram|twitter|linkedin',
            r'all\s*rights\s*reserved|copyright|©',
            r'related\s*searches|people\s*also\s*ask|more\s*results|sponsored|advertisement|ad\b',
            r'shopping\s*cart|my\s*cart|view\s*cart|checkout',
            r'become\s*a\s*seller|sell\s*on|delivery\s*information|shipping\s*policy|return\s*policy'
        ]
        
        compiled_patterns = [re.compile(p, re.IGNORECASE) for p in boilerplate_patterns]
        
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue
                
            # Skip boilerplate if the line is short (navigation anchors are typically short)
            if len(line_stripped) < 120 and any(pat.search(line_stripped) for pat in compiled_patterns):
                continue
                
            cleaned_lines.append(line_stripped)

        # Re-join lines
        cleaned_text = "\n".join(cleaned_lines)
        
        # Remove duplicate paragraphs / blocks of text
        paragraphs = cleaned_text.split("\n\n")
        seen_paragraphs = set()
        unique_paragraphs = []
        for p in paragraphs:
            p_clean = re.sub(r'\s+', ' ', p.strip())
            if p_clean and p_clean not in seen_paragraphs:
                seen_paragraphs.add(p_clean)
                unique_paragraphs.append(p.strip())
                
        cleaned_text = "\n\n".join(unique_paragraphs)
        
        # Remove repeated text/lines
        lines = cleaned_text.split("\n")
        seen_lines = set()
        unique_lines = []
        for line in lines:
            line_clean = line.strip().lower()
            if line_clean and line_clean not in seen_lines:
                seen_lines.add(line_clean)
                unique_lines.append(line)
        
        cleaned_text = "\n".join(unique_lines)
        
        # Normalize double/multiple empty lines and spaces (Preserving markdown links, images, and headers)
        cleaned_text = re.sub(r'\n\s*\n+', '\n\n', cleaned_text)
        cleaned_text = re.sub(r'[ \t]+', ' ', cleaned_text)
        
        return cleaned_text.strip()
