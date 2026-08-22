"""Debug the filter regex."""
import sys, re
sys.path.insert(0, ".")

JUNK_RE = re.compile(
    r"(window\.|function\s|var\s|const\s|let\s|__wm\."
    r"|<script|<style|<html|<head|<body|<div|<span|<link|<meta"
    r"|RufflePlayer|archive\.org/web/|_wm\.)",
    re.IGNORECASE,
)

# Test against the actual chunk text
texts = [
    "[[PAGE:1]]window.RufflePlayer=window.RufflePlayer||{};window.RufflePlayer.config={}",
    "[[PAGE:1]]Spotlight: Pierre Labroche, BS|MS '26 Computer Science",
]

for t in texts:
    clean = re.sub(r"\[\[PAGE:\d+\]\]", "", t).strip()
    junk_match = JUNK_RE.search(clean)
    junk_ratio = len(re.findall(r"[{};=()]", clean)) / max(len(clean), 1)
    print(f"Text: {clean[:60]}...")
    print(f"  len={len(clean)} junk_match={bool(junk_match)} junk_ratio={junk_ratio:.3f}")
    print(f"  filtered: {len(clean) < 40 or (junk_match and junk_ratio > 0.05)}")
    print()
