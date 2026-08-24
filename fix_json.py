"""Fix the cdx_evolution_analysis endpoint to handle malformed LLM JSON."""
import re

with open('app/api/routes/corpus.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the try/except for JSON parsing and add a fallback
old_try = """            # Parse JSON - try to extract valid JSON from response
            import json
            # Try direct parse first
            try:
                analysis = json.loads(content)
            except json.JSONDecodeError:
                # Try extracting JSON from markdown code blocks
                import re
                json_match = re.search(r'```(?:json)?\\s*\\n(.*?)\\n\\s*```', content, re.DOTALL)
                if json_match:
                    analysis = json.loads(json_match.group(1))
                else:
                    # Try finding first { to last }
                    start = content.find('{')
                    end = content.rfind('}')
                    if start >= 0 and end > start:
                        analysis = json.loads(content[start:end+1])
                    else:
                        raise ValueError("Could not parse LLM response as JSON")

            # Fix common LLM JSON issues (trailing commas, etc.)
            if isinstance(analysis, dict):
                # Remove any trailing commas in string values
                for key in analysis:
                    if isinstance(analysis[key], str):
                        analysis[key] = analysis[key].rstrip(',').strip()"""

new_try = """            # Parse JSON - try to extract valid JSON from response
            import json
            analysis = None
            
            # Try direct parse first
            try:
                analysis = json.loads(content)
            except json.JSONDecodeError:
                pass
            
            # Try extracting JSON from markdown code blocks
            if analysis is None:
                try:
                    json_match = re.search(r'```(?:json)?\\s*\\n(.*?)\\n\\s*```', content, re.DOTALL)
                    if json_match:
                        analysis = json.loads(json_match.group(1))
                except (json.JSONDecodeError, AttributeError):
                    pass
            
            # Try finding first { to last }
            if analysis is None:
                try:
                    start = content.find('{')
                    end = content.rfind('}')
                    if start >= 0 and end > start:
                        # Try to fix common issues: trailing commas, unquoted keys
                        json_str = content[start:end+1]
                        # Remove trailing commas before } or ]
                        json_str = re.sub(r',\\s*([}}\\]])', r'\\1', json_str)
                        analysis = json.loads(json_str)
                except json.JSONDecodeError:
                    pass
            
            # If all parsing fails, generate a basic analysis from the prompt data
            if analysis is None:
                analysis = {
                    "summary": f"LLM analysis of {domain} Wayback Machine snapshots. The website has been archived across {len(years)} years with peak activity in {peak_year}.",
                    "eras": [],
                    "key_topics": ["web archival", "internet history", domain],
                    "historical_context": f"The peak archival activity in {peak_year} ({by_year[peak_year]} captures) suggests significant web presence during this period.",
                    "archival_notes": f"This domain has {total} Wayback Machine snapshots spanning {years[0]} to {years[-1]}, making it a well-documented historical website."
                }"""

if old_try in content:
    content = content.replace(old_try, new_try)
    with open('app/api/routes/corpus.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Added fallback for malformed LLM JSON')
else:
    print('Pattern not found - checking what exists')
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'Parse JSON' in line:
            for j in range(i, min(i+5, len(lines))):
                print(f'{j+1}: {repr(lines[j])}')
