# NOTE: 2026-05-02 09:58:03, self-evolved by tea_agent --- toolkit_search 增加百度搜索引擎支持，通过 engine 参数切换
# @2026-05-01 gen by tea_agent, 互联网搜索（DuckDuckGo + 百度）
# version: 1.1.0

def toolkit_search(query: str, max_results: int = 10, lang: str = "", engine: str = "duckduckgo"):
    """互联网搜索，支持 DuckDuckGo 和百度两个搜索引擎。
    
    Args:
        query: 搜索关键词
        max_results: 返回结果数量上限，默认10，最大20
        lang: 语言偏好，如 zh-cn, en，空=不限
        engine: 搜索引擎，duckduckgo（默认）或 baidu
    """
    import json
    
    max_results = min(max(max_results, 1), 20)
    
    if engine == "baidu":
        return _search_baidu(query, max_results)
    else:
        return _search_duckduckgo(query, max_results, lang)


def _search_duckduckgo(query: str, max_results: int, lang: str):
    import requests
    from bs4 import BeautifulSoup
    from urllib.parse import urlparse, parse_qs, unquote
    import re
    import json
    
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
        return (1, '', 'DuckDuckGo 搜索超时')
    except requests.ConnectionError:
        return (1, '', '网络连接失败')
    except Exception as e:
        return (1, '', f'DuckDuckGo 搜索出错: {str(e)}')
    
    if not results:
        return (0, '[]', '未找到相关结果')
    
    return (0, json.dumps(results, ensure_ascii=False, indent=2), '')


# NOTE: 2026-05-02 09:50:00, self-evolved by tea_agent --- 新增百度搜索，先访问首页获取cookie，再解析搜索结果
def _search_baidu(query: str, max_results: int):
    import requests
    from bs4 import BeautifulSoup
    from urllib.parse import urlparse, parse_qs
    import json
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    })
    
    try:
        # 先访问百度首页获取 cookie，否则可能被反爬
        session.get('https://www.baidu.com/', timeout=10)
        
        # 搜索
        resp = session.get(
            f'https://www.baidu.com/s?wd={requests.utils.quote(query)}&rn={max_results}',
            timeout=15
        )
        resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.text, 'lxml')
        
        result_divs = soup.select('div.c-container')
        results = []
        
        for r in result_divs:
            if len(results) >= max_results:
                break
            
            h3 = r.find('h3')
            if not h3:
                continue
            a = h3.find('a')
            if not a:
                continue
            
            title = a.get_text(strip=True)
            if not title:
                continue
            
            href = a.get('href', '')
            real_url = href
            
            # 尝试解析百度跳转链接获取真实URL
            try:
                if 'baidu.com/link' in href:
                    # 跟随跳转获取真实URL
                    try:
                        head_resp = session.head(href, allow_redirects=True, timeout=5)
                        real_url = head_resp.url
                    except Exception:
                        # HEAD失败时保持原href
                        pass
                elif 'baidu.php' in href:
                    # 广告链接，尝试从url参数提取
                    qp = parse_qs(urlparse(href).query)
                    encoded = qp.get('url', [''])[0]
                    if encoded.startswith('http'):
                        real_url = encoded
            except Exception:
                pass
            
            # 摘要
            snippet = ''
            for cls_name in ['c-abstract', 'c-span-last']:
                span = r.find('span', class_=cls_name)
                if span:
                    t = span.get_text(strip=True)
                    if len(t) > len(snippet):
                        snippet = t
            
            # 显示URL
            display_url = ''
            for cls_name in ['c-showurl', 'showurl']:
                el = r.find(class_=cls_name)
                if el:
                    display_url = el.get_text(strip=True)
                    break
            
            results.append({
                'title': title,
                'url': real_url,
                'display_url': display_url,
                'snippet': snippet,
            })
        
        if not results:
            return (0, '[]', '未找到相关结果')
        
        return (0, json.dumps(results, ensure_ascii=False, indent=2), '')
    
    except requests.Timeout:
        return (1, '', '百度搜索超时')
    except requests.ConnectionError:
        return (1, '', '网络连接失败')
    except Exception as e:
        return (1, '', f'百度搜索出错: {str(e)}')


def meta_toolkit_search() -> dict:
    return {"type": "function", "function": {"name": "toolkit_search", "description": "互联网搜索工具，通过DuckDuckGo或百度搜索引擎搜索网页。返回结果包含标题、URL和摘要。无需API key。", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "搜索关键词，如 'Python async tutorial'"}, "max_results": {"type": "integer", "description": "返回结果数量上限，默认10，最大20", "default": 10}, "lang": {"type": "string", "description": "语言偏好，如 zh-cn, en, 空=不限。仅 DuckDuckGo 引擎支持", "default": ""}, "engine": {"type": "string", "enum": ["duckduckgo", "baidu"], "description": "搜索引擎，默认 duckduckgo", "default": "duckduckgo"}}, "required": ["query"]}}}
