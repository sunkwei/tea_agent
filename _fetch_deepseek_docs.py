"""Fetch DeepSeek API documentation pages for analysis."""
import requests, json, re
from bs4 import BeautifulSoup

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

pages = {
    'main': 'https://api-docs.deepseek.com/',
    'chat': 'https://api-docs.deepseek.com/api/create-chat-completion',
    'pricing': 'https://api-docs.deepseek.com/quick_start/pricing',
    'rate_limits': 'https://api-docs.deepseek.com/quick_start/rate_limits',
    'function_calling': 'https://api-docs.deepseek.com/features/function_calling',
    'news_0424': 'https://api-docs.deepseek.com/news/news260424',
}

results = {}
for name, url in pages.items():
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.encoding = 'utf-8'
        soup = BeautifulSoup(r.text, 'html.parser')
        # Remove script/style elements
        for tag in soup(['script', 'style', 'nav', 'footer']):
            tag.decompose()
        text = soup.get_text(separator='\n', strip=True)
        results[name] = text[:5000]
        print(f'✅ {name}: {url} ({len(r.text)}b -> {len(text)}c text)')
    except Exception as e:
        results[name] = f'ERROR: {e}'
        print(f'❌ {name}: {e}')

# Save to file for analysis
with open('_deepseek_docs.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print('\nSaved to _deepseek_docs.json')

# Print key sections
for name in ['main', 'chat', 'function_calling', 'pricing', 'rate_limits']:
    text = results.get(name, '')
    print(f'\n{"="*60}')
    print(f'=== {name} ({len(text)} chars) ===')
    print(f'{"="*60}')
    print(text[:2000])
