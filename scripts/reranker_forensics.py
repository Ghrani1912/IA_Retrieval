"""Per-query reranker forensics: rrf vs full_pipeline top-10 comparison."""
import sys, os, asyncio, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

from app.eval.configs import CONFIGS
from app.models.pydantic_models import StructuredQuery

QUERIES_PATH = "app/eval/queries.json"

def _first_200(text: str) -> str:
    """Show first 200 chars, replacing whitespace for readability."""
    if not text:
        return "(empty)"
    t = text.replace("\n", " ")
    # Collapse multiple spaces
    import re
    t = re.sub(r"  +", " ", t).strip()
    return t[:200]

def _has_header_noise(text: str) -> bool:
    """Check if first 200 chars contain OCR/report header noise."""
    if not text:
        return False
    first200 = text[:200]
    # Report numbers, page markers, all-caps headers, garbled OCR
    import re
    noise_patterns = [
        r"\[\[PAGE:\d+\]\]",           # page markers
        r"AD[-\s]?[A-Z0-9]{6,}",      # DTIC report numbers
        r"ERIC_ED\d+",                 # ERIC identifiers
        r"^(Report\s+No\s*\.)",        # report headers
        r"^([A-Z0-9\s\-]{10,60})$",   # all-caps lines
        r"DOCUMENT\s+RESUME",          # ERIC document resume
    ]
    for pat in noise_patterns:
        if re.search(pat, first200, re.MULTILINE):
            return True
    # Also check: if first 200 chars have >50% uppercase letters
    letters = [c for c in first200 if c.isalpha()]
    if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.5:
        return True
    return False

async def main():
    with open(QUERIES_PATH) as f:
        data = json.load(f)

    labeled, gt_map = [], {}
    for q in data["queries"]:
        labeled.append({
            "query_id": q["id"], "query": q["query"],
            "query_type": q["query_type"], "date_range": q.get("date_range"),
        })
        if q.get("relevant_chunk_ids"):
            gt_map[q["id"]] = set(q["relevant_chunk_ids"])

    eval_q = [l for l in labeled if l["query_id"] in gt_map]

    rrf_fn = CONFIGS["rrf"]
    fp_fn = CONFIGS["full_pipeline"]

    stats = {
        "queries_improved": 0,
        "queries_hurt": 0,
        "queries_unchanged": 0,
        "chunks_demoted_total": 0,
        "chunks_promoted_total": 0,
        "promoted_with_noise": 0,
        "promoted_without_noise": 0,
        "promoted_total": 0,
        "demoted_relevant": 0,
    }

    for i, lq in enumerate(eval_q, 1):
        dr = lq.get("date_range") or {}
        sq = StructuredQuery(
            raw_query=lq["query"],
            topic_keywords=lq["query"].split()[:8],
            date_range_start=dr.get("from"),
            date_range_end=dr.get("to"),
            source_type_hint=None,
            is_temporal_comparison=(lq["query_type"] == "cross_decade_comparison"),
        )
        relevant = gt_map[lq["query_id"]]

        try:
            rrf_ranked = await rrf_fn(sq)
            fp_ranked = await fp_fn(sq)
        except Exception as e:
            logger.warning("FAILED %s: %s", lq["query_id"], e)
            continue

        rrf_top10_ids = set(r.chunk.id for r in rrf_ranked[:10] if r.chunk.id)
        fp_top10_ids = set(r.chunk.id for r in fp_ranked[:10] if r.chunk.id)

        demoted = rrf_top10_ids - fp_top10_ids
        promoted = fp_top10_ids - rrf_top10_ids

        rrf_recall = len(rrf_top10_ids & relevant)
        fp_recall = len(fp_top10_ids & relevant)
        recall_delta = fp_recall - rrf_recall

        if recall_delta > 0:
            stats["queries_improved"] += 1
        elif recall_delta < 0:
            stats["queries_hurt"] += 1
        else:
            stats["queries_unchanged"] += 1

        stats["chunks_demoted_total"] += len(demoted)
        stats["chunks_promoted_total"] += len(promoted)

        # Check promoted chunks for OCR noise
        fp_by_id = {r.chunk.id: r for r in fp_ranked if r.chunk.id}
        demoted_by_id = {r.chunk.id: r for r in rrf_ranked if r.chunk.id}

        noise_in_promoted = 0
        for cid in promoted:
            item = fp_by_id[cid]
            text = item.chunk.text or ""
            if _has_header_noise(text):
                noise_in_promoted += 1
                stats["promoted_with_noise"] += 1
            else:
                stats["promoted_without_noise"] += 1
            stats["promoted_total"] += 1

        # Check if demoted chunks were relevant
        demoted_relevant = len(demoted & relevant)
        stats["demoted_relevant"] += demoted_relevant

        # Print detail for queries where recall changed
        if recall_delta != 0 or demoted:
            symbol = "+" if recall_delta > 0 else ("-" if recall_delta < 0 else "=")
            logger.info("")
            logger.info("Q%d %s [%s] recall %d->%d (%+d)  demoted=%d promoted=%d noise_promoted=%d",
                i, lq["query_id"], symbol, rrf_recall, fp_recall, recall_delta,
                len(demoted), len(promoted), noise_in_promoted)

            if demoted:
                logger.info("  DEMOTED (in rrf top-10, pushed out by reranker):")
                for cid in demoted:
                    item = demoted_by_id.get(cid)
                    if item:
                        relevant_mark = " [RELEVANT!]" if cid in relevant else ""
                        noise_mark = " [NOISE]" if _has_header_noise(item.chunk.text or "") else ""
                        logger.info("    chunk %d rrf_score=%.4f%s%s  text: %s",
                            cid, item.score, relevant_mark, noise_mark,
                            _first_200(item.chunk.text or ""))

            if promoted:
                logger.info("  PROMOTED (not in rrf top-10, added by reranker):")
                for cid in promoted:
                    item = fp_by_id.get(cid)
                    if item:
                        relevant_mark = " [RELEVANT]" if cid in relevant else ""
                        noise_mark = " [NOISE]" if _has_header_noise(item.chunk.text or "") else ""
                        logger.info("    chunk %d rerank_score=%.4f%s%s  text: %s",
                            cid, item.score, relevant_mark, noise_mark,
                            _first_200(item.chunk.text or ""))

    # Summary
    logger.info("\n" + "=" * 72)
    logger.info("FORENSICS SUMMARY")
    logger.info("=" * 72)
    logger.info("Queries: %d improved, %d hurt, %d unchanged",
                stats["queries_improved"], stats["queries_hurt"], stats["queries_unchanged"])
    logger.info("Chunks demoted total: %d", stats["chunks_demoted_total"])
    logger.info("Chunks promoted total: %d", stats["chunks_promoted_total"])
    logger.info("Promoted chunks WITH OCR noise: %d / %d (%.0f%%)",
                stats["promoted_with_noise"], stats["promoted_total"],
                100 * stats["promoted_with_noise"] / max(stats["promoted_total"], 1))
    logger.info("Promoted chunks WITHOUT noise: %d", stats["promoted_without_noise"])
    logger.info("Demoted chunks that were RELEVANT: %d / %d (%.0f%%)",
                stats["demoted_relevant"], stats["chunks_demoted_total"],
                100 * stats["demoted_relevant"] / max(stats["chunks_demoted_total"], 1))

if __name__ == "__main__":
    asyncio.run(main())
