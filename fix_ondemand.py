"""Fix on-demand ingestion to also ingest NEW sources not in DB."""
with open('app/ingestion/ondemand.py', 'r', encoding='utf-8') as f:
    content = f.read()

# The bug: when a source doesn't exist in DB, it's skipped
# We need to CREATE the source row first, then ingest

old_check = """                # Check if source exists in DB
                row = await conn.fetchrow(
                    "SELECT id FROM sources WHERE ia_identifier = $1", identifier,
                )
                if row is None:
                    logger.info("[ON-DEMAND] %s not in DB — skipping", identifier)
                    continue
                source_id = row["id"]"""

new_check = """                # Check if source exists in DB, create if not
                row = await conn.fetchrow(
                    "SELECT id FROM sources WHERE ia_identifier = $1", identifier,
                )
                if row is None:
                    # New source — create source row first
                    source_id = await conn.fetchval(
                        \"\"\"
                        INSERT INTO sources (ia_identifier, title, collection, source_type, pub_date_raw, language)
                        VALUES ($1, $2, $3, 'metadata_only', $4, 'en')
                        RETURNING id
                        \"\"\",
                        identifier,
                        src_meta.title or f"IA: {identifier}",
                        src_meta.collection or "dticarchive",
                        src_meta.pub_date,
                    )
                    logger.info("[ON-DEMAND] Created new source %s (id=%d)", identifier, source_id)
                else:
                    source_id = row["id"]"""

if old_check in content:
    content = content.replace(old_check, new_check)
    with open('app/ingestion/ondemand.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Fixed on-demand ingestion to create new sources')
else:
    print('Pattern not found')
