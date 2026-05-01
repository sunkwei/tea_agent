# @2026-05-01 gen by tea_agent, DuckDuckGo互联网搜索
# version: 1.0.2

def toolkit_search(query: str, max_results: int = 10, lang: str = ""):
    import requests
    from bs4 import BeautifulSoup
    from urllib.parse import urlparse, parse_qs, unquote
    import re
    import json
    
    max_results = min(max(max_results, 1), 20)
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0',
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    })
    
    results = []
    params = {'q': query}
    if lang:
        params['kl'] = lang
    
    try:
        resp = session.post('https://lite.duckduckgo.com/lite/', data=params, timeout=15)
        resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        result_links = soup.find_all('a', class_='result-link')
        result_snippets = soup.find_all('td', class_='result-snippet')
        link_texts = soup.find_all('span', class_='link-text')
        
        for i, link in enumerate(result_links):
            if len(results) >= max_results:
                break
            
            title = link.get_text(strip=True)
            href = link.get('href', '')
            real_url = href
            if 'duckduckgo.com/l/' in href:
                parsed = urlparse(href)
                qp = parse_qs(parsed.query)
                uddg = qp.get('uddg', [None])[0]
                if uddg:
                    real_url = unquote(uddg)
            
            snippet = ''
            if i < len(result_snippets):
                raw = result_snippets[i].get_text('', strip=True) or ''
                snippet = re.sub(r'<[^>]+>', '', raw).strip()
            
            display_url = ''
            if i < len(link_texts):
                display_url = link_texts[i].get_text(strip=True)
            
            results.append({
                'title': title,
                'url': real_url,
                'display_url': display_url,
                'snippet': snippet,
            })
        
    except requests.Timeout:
        return (1, '', '搜索超时')
    except requests.ConnectionError:
        return (1, '', '网络连接失败')
    except Exception as e:
        return (1, '', f'搜索出错: {str(e)}')
    
    if not results:
        return (0, '[]', '未找到相关结果')
    
    return (0, json.dumps(results, ensure_ascii=False, indent=2), '')


def meta_toolkit_search() -> dict:
    return {"type": "function", "function": {"name": "toolkit_search", "description": "互联网搜索工具，通过DuckDuckGo搜索引擎搜索网页。返回结果包含标题、URL和摘要。无需API key。", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "搜索关键词，如 'Python async tutorial'"}, "max_results": {"type": "integer", "description": "返回结果数量上限，默认10，最大20", "default": 10}, "lang": {"type": "string", "description": "语言偏好，如 zh-cn, en, 空=不限", "default": ""}}, "required": ["query"]}}}
