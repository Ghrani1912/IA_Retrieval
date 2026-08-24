"""Fix Source Explorer to remove hardcoded date limits and use live data."""
with open('historical-intelligence/src/components/SourceExplorerView.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Remove min/max constraints from date inputs
content = content.replace('min={1970}\n                max={1998}\n                value={filters.dateFrom}', 'value={filters.dateFrom}')
content = content.replace('min={1970}\n                max={1998}\n                value={filters.dateTo}', 'value={filters.dateTo}')

# 2. Update collection dropdown to show "All Collections" without hardcoded count
content = content.replace(
    '<option value="All">All Collections (44)</option>',
    '<option value="All">All Collections</option>'
)

# 3. Update placeholder text
content = content.replace('placeholder="1970"', 'placeholder="From year"')
content = content.replace('placeholder="1998"', 'placeholder="To year"')

with open('historical-intelligence/src/components/SourceExplorerView.tsx', 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed Source Explorer date limits')
