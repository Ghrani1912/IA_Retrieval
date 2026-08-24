"""Fix max_tokens and response format for CDX analysis."""
with open('app/api/routes/corpus.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Increase max_tokens from 600 to 1500
content = content.replace('"max_tokens": 600,', '"max_tokens": 1500,', 1)

# Also add response_format to force JSON output
old = '"max_tokens": 1500,\n                },'
new = '"max_tokens": 1500,\n                    "response_format": {"type": "json_object"},\n                },'
content = content.replace(old, new)

with open('app/api/routes/corpus.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Increased max_tokens to 1500 and added json_object format')
