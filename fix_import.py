"""Fix missing re import in cdx_evolution_analysis endpoint."""
with open('app/api/routes/corpus.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add re import at the top of the cdx_evolution_analysis function
old = 'async def cdx_evolution_analysis(domain: str):\n    """Use LLM to analyze CDX metadata and provide historical context."""\n    conn = await asyncpg.connect(DB_URL, ssl=False)'
new = 'async def cdx_evolution_analysis(domain: str):\n    """Use LLM to analyze CDX metadata and provide historical context."""\n    import re\n    conn = await asyncpg.connect(DB_URL, ssl=False)'

if old in content:
    content = content.replace(old, new)
    with open('app/api/routes/corpus.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Added re import to cdx_evolution_analysis')
else:
    print('Pattern not found')
