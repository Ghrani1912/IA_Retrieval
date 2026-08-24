"""Test the CDX analysis LLM response parsing."""
import asyncio
import httpx
import re
import json
import sys
sys.stdout.reconfigure(encoding='utf-8')

async def test():
    from app.config import settings
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f'{settings.llm_base_url}/chat/completions',
            headers={'Authorization': f'Bearer {settings.llm_api_key}'},
            json={
                'model': settings.llm_model,
                'messages': [{'role': 'user', 'content': 'Return a JSON object with keys: summary, eras, key_topics, historical_context, archival_notes. Domain: ai.mit.edu. Years: 1996-2026. Total: 1803 snapshots. Peak: 2000 (514 captures).'}],
                'temperature': 0.3,
                'max_tokens': 600,
            },
        )
        resp.raise_for_status()
        content = resp.json()['choices'][0]['message']['content'].strip()
        
        print('RAW RESPONSE:')
        print(content[:500])
        print()
        
        # Try all parsing methods
        analysis = None
        
        # Method 1: Direct parse
        try:
            analysis = json.loads(content)
            print('Method 1 (direct): OK')
        except json.JSONDecodeError as e:
            print(f'Method 1 (direct): FAILED - {e}')
        
        # Method 2: Code block extract
        if analysis is None:
            try:
                m = re.search(r'```(?:json)?\s*\n(.*?)\n\s*```', content, re.DOTALL)
                if m:
                    analysis = json.loads(m.group(1))
                    print('Method 2 (code block): OK')
                else:
                    print('Method 2 (code block): No block found')
            except json.JSONDecodeError as e:
                print(f'Method 2 (code block): FAILED - {e}')
        
        # Method 3: Brace extraction + trailing comma fix
        if analysis is None:
            try:
                start = content.find('{')
                end = content.rfind('}')
                if start >= 0 and end > start:
                    json_str = content[start:end+1]
                    json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
                    analysis = json.loads(json_str)
                    print('Method 3 (brace+fix): OK')
                else:
                    print('Method 3 (brace+fix): No braces found')
            except json.JSONDecodeError as e:
                print(f'Method 3 (brace+fix): FAILED - {e}')
        
        # Method 4: More aggressive fix - remove all newlines in strings
        if analysis is None:
            try:
                start = content.find('{')
                end = content.rfind('}')
                if start >= 0 and end > start:
                    json_str = content[start:end+1]
                    json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
                    # Fix unescaped newlines inside strings
                    json_str = re.sub(r'(?<=")\n(?=")', ' ', json_str)
                    analysis = json.loads(json_str)
                    print('Method 4 (aggressive fix): OK')
            except json.JSONDecodeError as e:
                print(f'Method 4 (aggressive fix): FAILED - {e}')
        
        if analysis is None:
            print('\nAll methods failed. Raw content around error:')
            # Find the problematic area
            for m in re.finditer(r'JSONDecodeError', str(e)):
                pass
            # Show chars around position
            pos = int(str(e).split('char ')[-1].rstrip(')')) if 'char' in str(e) else 0
            if pos > 0:
                print(f'Around position {pos}: ...{content[max(0,pos-50):pos+50]}...')

asyncio.run(test())
