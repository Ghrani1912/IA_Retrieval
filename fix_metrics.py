"""Add live corpus metrics to Source Explorer."""
with open('historical-intelligence/src/components/SourceExplorerView.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

# Add state for live metrics after the existing state declarations
old_state = '  const [selectedSource, setSelectedSource] = useState<SourceDocument | null>(null);'

new_state = '''  const [selectedSource, setSelectedSource] = useState<SourceDocument | null>(null);
  const [liveMetrics, setLiveMetrics] = useState<{totalSources: number; totalChunks: number} | null>(null);'''

content = content.replace(old_state, new_state)

# Add useEffect to fetch live metrics
old_effect = '''  useEffect(() => {
    let isMounted = true;
    HistoricalApiService.getSources(filters, page, pageSize).then(res => {'''

new_effect = '''  // Fetch live corpus metrics
  useEffect(() => {
    fetch(`${HistoricalApiService.getBackendUrl()}/corpus/stats`)
      .then(r => r.json())
      .then(data => {
        setLiveMetrics({ totalSources: data.total_sources, totalChunks: data.total_chunks });
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    let isMounted = true;
    HistoricalApiService.getSources(filters, page, pageSize).then(res => {'''

content = content.replace(old_effect, new_effect)

# Update the metric badge to use live data
old_badge = '''              <div className=\"text-xs font-mono text-[#2b2620]\">
                <span className=\"font-bold\">{CORPUS_METRICS.totalChunks.toLocaleString()} chunks</span> across{' '}
                <span className=\"font-bold\">{CORPUS_METRICS.totalSources} primary volumes</span>
              </div>'''

new_badge = '''              <div className=\"text-xs font-mono text-[#2b2620]\">
                <span className=\"font-bold\">{(liveMetrics?.totalChunks ?? CORPUS_METRICS.totalChunks).toLocaleString()} chunks</span> across{' '}
                <span className=\"font-bold\">{liveMetrics?.totalSources ?? CORPUS_METRICS.totalSources} primary volumes</span>
              </div>'''

content = content.replace(old_badge, new_badge)

with open('historical-intelligence/src/components/SourceExplorerView.tsx', 'w', encoding='utf-8') as f:
    f.write(content)

print('Added live corpus metrics to Source Explorer')
