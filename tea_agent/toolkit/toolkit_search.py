# version: 1.3.0
# 2026-06-01 gen by agent, 添加 GitHub 搜索能力（repos/code/issues）

import logging

logger = logging.getLogger("toolkit")

def toolkit_search(query: str, max_results: int = 10, lang: str = "", engine: str = "duckduckgo",
                   search_type: str = "web", root_path: str = "", glob_pattern: str = ""):
    """
    搜索工具，支持互联网搜索（DuckDuckGo/百度/GitHub）和项目内代码搜索。

    search_type='web' (默认): 互联网搜索
        toolkit_search(query='Python tutorial', engine='duckduckgo')

    search_type='code': 项目内全文搜索（类似 grep/ripgrep）
        toolkit_search(query='def login', search_type='code', root_path='/path/to/project', glob_pattern='*.py')

    search_type='symbol': 符号搜索（查找函数/类定义）
        toolkit_search(query='MyClass', search_type='symbol', root_path='/path/to/project')

    search_type='github': GitHub 搜索（仓库/代码/Issues）
        toolkit_search(query='tea-agent', search_type='github', engine='repos')  # 搜索仓库
        toolkit_search(query='def toolkit_search', search_type='github', engine='code')  # 搜索代码
        toolkit_search(query='bug fix', search_type='github', engine='issues')  # 搜索 Issues

    Args:
        query: 搜索关键词
        max_results: 返回结果数量上限，默认10，最大50
        lang: 语言偏好，如 zh-cn, en，空=不限（仅 web 搜索）
        engine: 搜索引擎，duckduckgo（默认）/ baidu / repos / code / issues
        search_type: 搜索类型，web/code/symbol/github，默认 web
        root_path: 搜索根目录（code/symbol 搜索需要）
        glob_pattern: 文件过滤模式，如 '*.py'（仅 code 搜索）
    """
    logger.info(f"toolkit_search called: query={repr(query)[:80]}, search_type={search_type!r}")


    max_results = min(max(max_results, 1), 50)

    if search_type == "code":
        return _search_codebase(query, root_path, glob_pattern, max_results)
    elif search_type == "symbol":
        return _search_symbol(query, root_path, max_results)
    elif search_type == "github":
        return _search_github(query, engine, max_results)
    else:
        if engine == "baidu":
            return _search_baidu(query, max_results)
        else:
            return _search_duckduckgo(query, max_results, lang)

def _search_duckduckgo(query: str, max_results: int, lang: str):
    """Internal: search duckduckgo.

    Args:
        query: Description.
        max_results: Description.
        lang: Description.
    """
    import json
    import re
    from urllib.parse import parse_qs, unquote, urlparse

    import requests
    from bs4 import BeautifulSoup

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

def _search_baidu(query: str, max_results: int):
    """Internal: search baidu.

    Args:
        query: Description.
        max_results: Description.
    """
    import json
    from urllib.parse import parse_qs, urlparse

    import requests
    from bs4 import BeautifulSoup

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
                logger.exception("operation failed")


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
    """Meta toolkit search."""
    return {"type": "function", "function": {"name": "toolkit_search", "description": "搜索工具，支持互联网搜索（DuckDuckGo/百度/GitHub）和项目内代码搜索（全文搜索/符号搜索）。GitHub 搜索支持仓库、代码、Issues 搜索。", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "搜索关键词，如 'Python async tutorial' 或 'def login'"}, "max_results": {"type": "integer", "description": "返回结果数量上限，默认10，最大50", "default": 10}, "lang": {"type": "string", "description": "语言偏好，如 zh-cn, en, 空=不限。仅 web 搜索支持", "default": ""}, "engine": {"type": "string", "enum": ["duckduckgo", "baidu", "repos", "code", "issues"], "description": "搜索引擎，默认 duckduckgo。repos/code/issues 为 GitHub 搜索", "default": "duckduckgo"}, "search_type": {"type": "string", "enum": ["web", "code", "symbol", "github"], "description": "搜索类型: web=互联网搜索, code=代码全文搜索, symbol=符号搜索, github=GitHub搜索", "default": "web"}, "root_path": {"type": "string", "description": "搜索根目录路径。code/symbol 搜索需要"}, "glob_pattern": {"type": "string", "description": "文件过滤模式，如 '*.py'。仅 code 搜索"}}, "required": ["query"]}}}

def _search_codebase(query: str, root_path: str, glob_pattern: str, max_results: int):
    """项目内全文搜索（优先使用 ripgrep，回退到 Python 实现）"""
    import json
    import os
    import subprocess

    if not root_path:
        return (1, "", "root_path 不能为空（代码搜索需要）")

    if not os.path.isdir(root_path):
        return (1, "", f"目录不存在: {root_path}")

    results = []

    # 尝试使用 ripgrep (rg)
    rg_cmd = None
    for cmd in ["rg", "grep"]:
        import shutil
        if shutil.which(cmd):
            rg_cmd = cmd
            break

    if rg_cmd == "rg":
        # 使用 ripgrep
        rg_args = ["--no-heading", "--line-number", "--color=never", "-C", "2",  # 上下文 2 行
                   "--max-count", str(max_results), "--json", query, root_path]

        if glob_pattern:
            rg_args.insert(-2, "--glob")
            rg_args.insert(-2, glob_pattern)

        try:
            result = subprocess.run(rg_args, capture_output=True, text=True, timeout=30)
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                    if parsed.get('type') == 'match':
                        data = parsed['data']
                        path = data['path']['text']
                        for match in data.get('submatches', []):
                            line_text = data['lines']['text']
                            line_num = data['line_number']
                            results.append({
                                "file": os.path.relpath(path, root_path),
                                "line": line_num,
                                "content": line_text.strip(),
                                "match": match.get('match', {}).get('text', ''),
                            })
                            if len(results) >= max_results:
                                break
                except json.JSONDecodeError:
                    continue
        except subprocess.TimeoutExpired:
            return (1, "", "代码搜索超时")
        except Exception as e:
            # ripgrep 失败，回退到 Python 实现
            logger.info(f"ripgrep 失败，回退到 Python 实现: {e}")
            return _search_codebase_python(query, root_path, glob_pattern, max_results)

    else:
        # 直接使用 Python 实现
        return _search_codebase_python(query, root_path, glob_pattern, max_results)

    if not results:
        return (0, "[]", "未找到匹配的代码")

    return (0, json.dumps(results, ensure_ascii=False, indent=2), "")

def _search_codebase_python(query: str, root_path: str, glob_pattern: str, max_results: int):
    """Python 实现的代码全文搜索（ripgrep 不可用时的回退方案）"""
    import fnmatch
    import json
    import os
    import re

    results = []
    pattern = re.compile(re.escape(query), re.IGNORECASE)

    for root, dirs, files in os.walk(root_path):
        # 跳过隐藏目录和常见忽略目录
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in
                   ('node_modules', '__pycache__', '.git', 'venv', 'env', 'dist', 'build')]

        for filename in files:
            if glob_pattern and not fnmatch.fnmatch(filename, glob_pattern):
                continue

            if not filename.endswith(('.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cpp', '.c', '.h', '.go', '.rs', '.rb', '.md', '.txt', '.yaml', '.yml', '.json', '.xml', '.html', '.css')):
                continue

            filepath = os.path.join(root, filename)
            try:
                with open(filepath, encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()

                for line_num, line in enumerate(lines, 1):
                    if pattern.search(line):
                        results.append({
                            "file": os.path.relpath(filepath, root_path),
                            "line": line_num,
                            "content": line.strip(),
                            "match": query,
                        })
                        if len(results) >= max_results:
                            return (0, json.dumps(results, ensure_ascii=False, indent=2), "")
            except Exception:
                continue

    if not results:
        return (0, "[]", "未找到匹配的代码")

    return (0, json.dumps(results, ensure_ascii=False, indent=2), "")

def _search_symbol(query: str, root_path: str, max_results: int):
    """符号搜索（查找函数/类定义）"""
    import ast
    import json
    import os

    if not root_path:
        return (1, "", "root_path 不能为空（符号搜索需要）")

    if not os.path.isdir(root_path):
        return (1, "", f"目录不存在: {root_path}")

    results = []
    abs_root_path = os.path.abspath(root_path)

    # 搜索的目录列表
    search_dirs = [abs_root_path]
    # 如果 root_path 是 toolkit 目录，也搜索其父目录（tlk.py 等在上层）
    if 'toolkit' in abs_root_path.replace('\\', '/'):
        parent_dir = os.path.dirname(abs_root_path)
        if os.path.isdir(parent_dir) and parent_dir not in search_dirs:
            search_dirs.append(parent_dir)

    for search_dir in search_dirs:
        if not os.path.isdir(search_dir):
            continue

        for root, dirs, files in os.walk(search_dir):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in
                       ('node_modules', '__pycache__', '.git', 'venv', 'env', 'dist', 'build')]

            for filename in files:
                if not filename.endswith('.py'):
                    continue

                filepath = os.path.join(root, filename)
                try:
                    with open(filepath, encoding='utf-8') as f:
                        source = f.read()

                    tree = ast.parse(source, filename=filepath)

                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            if node.name == query or query in node.name:
                                # 相对于 abs_root_path 计算相对路径
                                rel_path = os.path.relpath(filepath, abs_root_path)
                                results.append({
                                    "file": rel_path,
                                    "line": node.lineno,
                                    "type": "class" if isinstance(node, ast.ClassDef) else "function",
                                    "name": node.name,
                                    "args": _extract_args(node),
                                })
                                if len(results) >= max_results:
                                    return (0, json.dumps(results, ensure_ascii=False, indent=2), "")

                except Exception:
                    continue

    if not results:
        return (0, "[]", f"未找到符号: {query}")

    return (0, json.dumps(results, ensure_ascii=False, indent=2), "")

def _extract_args(node):
    """从 AST 节点提取函数参数"""
    args = []
    for arg in node.args.args:
        args.append(arg.arg)
    if node.args.vararg:
        args.append(f"*{node.args.vararg.arg}")
    if node.args.kwarg:
        args.append(f"**{node.args.kwarg.arg}")
    return args

def _search_github(query: str, search_type: str, max_results: int):
    """
    GitHub 搜索（使用公开 API，无需 token）

    Args:
        query: 搜索关键词
        search_type: repos/code/issues
        max_results: 最大结果数
    """
    import json

    import requests

    # GitHub API 端点映射
    endpoints = {
        "repos": "https://api.github.com/search/repositories",
        "code": "https://api.github.com/search/code",
        "issues": "https://api.github.com/search/issues",
    }

    # 默认搜索仓库
    api_type = search_type if search_type in endpoints else "repos"
    url = endpoints[api_type]

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "TeaAgent/1.0",
    }

    # 添加 GitHub Token（如果存在）
    import os
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"

    params = {
        "q": query,
        "per_page": min(max_results, 30),  # GitHub API 最大 100，但 30 足够
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        results = []
        items = data.get("items", [])

        for item in items[:max_results]:
            if api_type == "repos":
                results.append({
                    "title": item.get("full_name", ""),
                    "url": item.get("html_url", ""),
                    "snippet": item.get("description", "") or "",
                    "stars": item.get("stargazers_count", 0),
                    "forks": item.get("forks_count", 0),
                    "language": item.get("language", ""),
                    "updated": item.get("updated_at", "")[:10],  # 只取日期部分
                })
            elif api_type == "code":
                repo = item.get("repository", {})
                results.append({
                    "title": item.get("name", ""),
                    "url": item.get("html_url", ""),
                    "snippet": f"仓库: {repo.get('full_name', '')}",
                    "path": item.get("path", ""),
                    "repo_stars": repo.get("stargazers_count", 0),
                })
            elif api_type == "issues":
                labels = [l.get("name", "") for l in item.get("labels", [])]
                is_pr = "pull_request" in item
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("html_url", ""),
                    "snippet": (item.get("body", "") or "")[:200],  # 截取前 200 字符
                    "state": item.get("state", ""),
                    "type": "PR" if is_pr else "Issue",
                    "labels": labels,
                    "comments": item.get("comments", 0),
                    "created": item.get("created_at", "")[:10],
                })

        if not results:
            return (0, "[]", f"GitHub 未找到相关{api_type}结果")

        return (0, json.dumps(results, ensure_ascii=False, indent=2), "")

    except requests.Timeout:
        return (1, "", "GitHub API 请求超时")
    except requests.ConnectionError:
        return (1, "", "网络连接失败，请检查网络")
    except requests.HTTPError as e:
        if e.response.status_code == 403:
            return (1, "", "GitHub API 速率限制，请稍后再试（未认证限制 10 次/分钟）")
        elif e.response.status_code == 401:
            if api_type == "code":
                return (1, "", "GitHub 代码搜索需要认证。请使用仓库搜索(repos)或 Issues 搜索(issues)")
            return (1, "", "GitHub API 认证失败")
        elif e.response.status_code == 422:
            return (1, "", "GitHub 搜索语法错误，请简化关键词后重试")
        return (1, "", f"GitHub API 错误: {e.response.status_code}")
    except Exception as e:
        return (1, "", f"GitHub 搜索出错: {str(e)}")
