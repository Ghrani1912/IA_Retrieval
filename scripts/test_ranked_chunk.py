"""Test if RankedChunk creation works now."""
import sys
sys.path.insert(0, ".")

from app.models.pydantic_models import Chunk, RankedChunk, SourceMetadata

# Create a test chunk like the on-demand pipeline returns
test_chunk = Chunk(
    id=9310,
    source_id=15858,
    text="Test text for cs.stanford.edu",
    page_or_section=None,
    char_range_start=0,
    char_range_end=50,
    token_count=10,
    capture_timestamp=None,
)

try:
    rc = RankedChunk(
        chunk=test_chunk,
        rank=0,
        score=0.0,
        source_metadata=SourceMetadata(
            ia_identifier="cs.stanford.edu",
            title="Website: cs.stanford.edu",
            collection="cs.stanford.edu",
        ),
    )
    print(f"SUCCESS: RankedChunk created: rank={rc.rank}, score={rc.score}, collection={rc.source_metadata.collection}")
except Exception as e:
    print(f"FAILED: {type(e).__name__}: {e}")
