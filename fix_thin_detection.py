"""Update thin-result detection to also check citation confidence after synthesis."""
with open('app/api/routes/query.py', 'r', encoding='utf-8') as f:
    content = f.read()

# In the non-streaming endpoint, add post-synthesis citation check
# The current flow is: Step 5b (thin detection) -> Step 6 (synthesize)
# We want to add: Step 6b (check citations, trigger IA if all UNKNOWN)

old_nonstream = """        # Step 6: synthesize
        answer = await synthesize_answer(sq.raw_query, ranked)
        return answer"""

new_nonstream = """        # Step 6: synthesize
        answer = await synthesize_answer(sq.raw_query, ranked)

        # Step 6b: post-synthesis relevance check — if all citations are UNKNOWN,
        # the evidence is irrelevant. Trigger IA fetch for future queries.
        total_segs = len(answer.answer_segments)
        if total_segs > 0:
            unknown_count = sum(1 for s in answer.answer_segments if s.citation_type == "UNKNOWN")
            unknown_pct = (unknown_count / total_segs) * 100

            if unknown_pct >= 80 and not sq.domain:
                logger.info(
                    "[RELEVANCE] Low relevance (%d%% UNKNOWN citations) for %r — triggering IA fetch",
                    unknown_pct, body.query[:60],
                )
                try:
                    asyncio.create_task(_background_ingest(body.query))
                except Exception as od_exc:
                    logger.warning("Failed to trigger relevance-based IA fetch: %s", od_exc)

        return answer"""

if old_nonstream in content:
    content = content.replace(old_nonstream, new_nonstream)
    print('Updated non-streaming endpoint with post-synthesis check')
else:
    print('WARNING: non-streaming pattern not found')

# In the streaming endpoint, add post-synthesis check in event_generator
old_stream_done = """                elif etype == "done":
                    # Frontend expects the AnswerResponse object directly
                    data = json.dumps(event.get("answer", {}))"""

new_stream_done = """                elif etype == "done":
                    # Frontend expects the AnswerResponse object directly
                    answer_data = event.get("answer", {})
                    
                    # Post-synthesis relevance check
                    segments = answer_data.get("answer_segments", [])
                    if segments:
                        unknown_count = sum(1 for s in segments if s.get("citation_type") == "UNKNOWN")
                        unknown_pct = (unknown_count / len(segments)) * 100
                        if unknown_pct >= 80 and not sq.domain:
                            logger.info(
                                "[RELEVANCE] Low relevance (%d%% UNKNOWN) for %r — triggering IA fetch",
                                unknown_pct, body.query[:60],
                            )
                            try:
                                asyncio.create_task(_background_ingest(body.query))
                            except Exception as od_exc:
                                logger.warning("Failed to trigger relevance-based IA fetch: %s", od_exc)
                    
                    data = json.dumps(answer_data)"""

if old_stream_done in content:
    content = content.replace(old_stream_done, new_stream_done)
    print('Updated streaming endpoint with post-synthesis check')
else:
    print('WARNING: streaming pattern not found')

with open('app/api/routes/query.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Done')
