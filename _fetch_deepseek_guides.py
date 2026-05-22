"""Fetch more DeepSeek API guide pages."""
import requests, json
from bs4 import BeautifulSoup

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

# Try to discover the correct URLs
base = 'https://api-docs.deepseek.com'
paths = [
    '/guides/thinking_mode',
    '/guides/context_caching', 
    '/guides/prefix_completion',
    '/guides/function_calling',
    '/guides/fim_completion',
    '/guides/rate-limits',
    '/features/thinking-mode',
    '/api/tool-use',
]

for path in paths:
    url = base + path
    try:
        r = requests.get(url, headers=headers, timeout=10)
        print(f'{r.status_code} {url}')
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            for tag in soup(['script', 'style', 'nav', 'footer']):
                tag.decompose()
            text = soup.get_text(separator='\n', strip=True)
            print(f'  -> {len(text)} chars')
            print(text[:800])
            print('---')
    except Exception as e:
        print(f'ERR {url}: {e}')
