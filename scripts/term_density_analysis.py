"""Analyze why base retrieval favors Americana: term density, chunk length, etc."""
import asyncio
import asyncpg
import re
from collections import Counter


async def main():
    conn = await asyncpg.connect(
        "postgresql://postgres:postgres@localhost:5432/platform", ssl=False
    )

    # Get chunk stats by collection
    rows = await conn.fetch("""
        SELECT c.id, c.text, s.collection, LENGTH(c.text) as tlen
        FROM chunks c JOIN sources s ON c.source_id = s.id
        WHERE s.collection IN ('americana', 'dticarchive', 'ericarchive')
    """)

    # Analyze by collection
    stats = {}
    for r in rows:
        coll = r["collection"]
        if coll not in stats:
            stats[coll] = {
                "count": 0, "total_len": 0,
                "total_words": 0, "unique_words": 0,
                "total_sentences": 0,
                "ai_keyword_hits": 0,
            }
        s = stats[coll]
        s["count"] += 1
        text = r["text"]
        s["total_len"] += len(text)
        words = text.split()
        s["total_words"] += len(words)
        s["unique_words"] += len(set(w.lower() for w in words))
        sentences = len(re.split(r'[.!?]+', text))
        s["total_sentences"] += sentences
        # Count AI-specific keywords
        ai_terms = len(re.findall(
            r'\b(semantic network|expert system|knowledge representation|'
            r'machine learning|natural language|inference|heuristic|'
            r'production rule|backward chaining|forward chaining|'
            r'planning|search algorithm|LISP|Prolog|MYCIN|PROSPECTOR)\b',
            text, re.IGNORECASE
        ))
        s["ai_keyword_hits"] += ai_terms

    print("=== COLLECTION STATISTICS ===\n")
    for coll, s in sorted(stats.items(), key=lambda x: -x[1]["count"]):
        avg_len = s["total_len"] / s["count"]
        avg_words = s["total_words"] / s["count"]
        avg_unique = s["unique_words"] / s["count"]
        avg_sentences = s["total_sentences"] / s["count"]
        lexical_diversity = s["unique_words"] / max(s["total_words"], 1)
        keywords_per_chunk = s["ai_keyword_hits"] / s["count"]
        keywords_per_1000w = s["ai_keyword_hits"] / max(s["total_words"], 1) * 1000

        print(f"{coll:15s}: {s['count']:5d} chunks")
        print(f"  avg length:     {avg_len:7.0f} chars, {avg_words:6.0f} words")
        print(f"  avg sentences:  {avg_sentences:6.1f}")
        print(f"  lexical div:    {lexical_diversity:.3f}")
        print(f"  AI keywords/chunk: {keywords_per_chunk:.1f}")
        print(f"  AI keywords/1000w: {keywords_per_1000w:.1f}")
        print()

    # Now check: for a specific query, how does term overlap compare?
    query = "semantic networks knowledge representation"
    query_words = set(query.lower().split())

    print(f"\n=== TERM OVERLAP ANALYSIS for '{query}' ===\n")
    for coll in ["americana", "dticarchive", "ericarchive"]:
        coll_rows = await conn.fetch("""
            SELECT c.text FROM chunks c
            JOIN sources s ON c.source_id = s.id
            WHERE s.collection = $1
            LIMIT 100
        """, coll)

        overlaps = []
        for r in coll_rows:
            chunk_words = set(r["text"].lower().split())
            overlap = len(query_words & chunk_words) / len(query_words)
            overlaps.append(overlap)

        if overlaps:
            avg_overlap = sum(overlaps) / len(overlaps)
            max_overlap = max(overlaps)
            print(f"  {coll:15s}: avg_overlap={avg_overlap:.3f}, max_overlap={max_overlap:.3f}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
