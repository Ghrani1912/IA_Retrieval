"""Fix the broken regex in corpus.py"""
with open('app/api/routes/corpus.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find and fix the broken json_match line
for i, line in enumerate(lines):
    if 'json_match = re.search' in line:
        # Check if the regex spans multiple lines (unterminated string)
        if 'content, re.DOTALL' not in line:
            # Find where it ends
            end = i
            for j in range(i+1, min(i+5, len(lines))):
                if 'content, re.DOTALL' in lines[j]:
                    end = j
                    break
            # Replace with single line
            indent = "                "
            lines[i:end+1] = [indent + "json_match = re.search(r'```(?:json)?\\s*\\n(.*?)\\n\\s*```', content, re.DOTALL)\n"]
            print(f"Fixed regex on line {i+1} (was spanning lines {i+1}-{end+1})")
            break

with open('app/api/routes/corpus.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
print("Done")
