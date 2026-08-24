"""Fix frontend API to handle both items and sources response formats."""
with open('historical-intelligence/src/services/api.ts', 'r', encoding='utf-8') as f:
    content = f.read()

# Update the response handling to check for both 'sources' and 'items'
old = '''        if (Array.isArray(data)) {
          return { sources: data, total: data.length, page, pageSize };
        } else if (data.sources) {
          return {
            sources: data.sources,
            total: data.total || data.sources.length,
            page: data.page || page,
            pageSize: data.page_size || pageSize
          };
        }'''

new = '''        if (Array.isArray(data)) {
          return { sources: data, total: data.length, page, pageSize };
        } else if (data.sources || data.items) {
          return {
            sources: data.sources || data.items,
            total: data.total || (data.sources || data.items).length,
            page: data.page || page,
            pageSize: data.page_size || pageSize
          };
        }'''

content = content.replace(old, new)

with open('historical-intelligence/src/services/api.ts', 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed API response handling')
