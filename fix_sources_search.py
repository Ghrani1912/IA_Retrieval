"""Add search (q) parameter to /sources endpoint."""
with open('app/api/routes/sources.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add q parameter to function signature
old_sig = '''    language: str | None = Query(None),
    page: int = Query(1, ge=1),'''

new_sig = '''    language: str | None = Query(None),
    q: str | None = Query(None, description="Search title, author, subject"),
    page: int = Query(1, ge=1),'''

content = content.replace(old_sig, new_sig)

# Add search condition after language condition
old_where = '''    if language:
        conditions.append(f"s.language = ${idx}")
        params.append(language)
        idx += 1

    where = "WHERE " + " AND ".join(conditions) if conditions else ""'''

new_where = '''    if language:
        conditions.append(f"s.language = ${idx}")
        params.append(language)
        idx += 1
    if q:
        conditions.append(f"(s.title ILIKE ${idx} OR s.author ILIKE ${idx} OR s.ia_identifier ILIKE ${idx})")
        params.append(f"%{q}%")
        idx += 1

    where = "WHERE " + " AND ".join(conditions) if conditions else ""'''

content = content.replace(old_where, new_where)

with open('app/api/routes/sources.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Added search (q) parameter to /sources endpoint')
