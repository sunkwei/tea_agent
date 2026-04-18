## llm generated tool func, self-evolved

def toolkit_predict_csi300(max_news: int = 25, verbose: bool = False) -> dict:
    """
    从新华网多个频道（首页、财经、国际、时政）获取最新新闻，通过LLM分析推测对第二天沪深300指数的影响。
    相比旧版，增加了多新闻源、智能去重、更全面的分类分析。
    
    Args:
        max_news: 最多获取的新闻条数，默认25
        verbose: 是否显示详细分析过程
        
    Returns:
        dict: 包含prediction(看平/看跌/看涨)、news_list、analysis、bullish_factors、bearish_factors等
    """
    import requests
    from bs4 import BeautifulSoup
    import os
    import json
    import re
    from urllib.parse import urljoin

    def fetch_news_from_channel(base_url, channel_name, max_count=10):
        """从新华网指定频道抓取新闻"""
        news_list = []
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            r = requests.get(base_url, headers=headers, timeout=15)
            r.encoding = 'utf-8'
            soup = BeautifulSoup(r.text, 'html.parser')
            
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                title = link.get_text(strip=True)
                # 过滤：标题长度>8，包含202年份，排除无关内容
                if (title and len(title) > 8 
                    and '/202' in href
                    and not any(x in title for x in ['周学智', '君乐宝', '不吃碳水', '科学减重', 'Vlog', '娃衣'])):
                    full_url = urljoin(base_url, href)
                    news_list.append({'title': title, 'url': full_url, 'channel': channel_name})
                    if len(news_list) >= max_count:
                        break
            return news_list
        except Exception as e:
            if verbose: 
                print(f"  [{channel_name}] 获取失败: {e}")
            return []

    def fetch_all_news(max_total=25):
        """从多个频道抓取新闻，按优先级分配名额"""
        channels = [
            ('https://www.news.cn/politics/leaders/index.htm', '时政', 5),
            ('https://www.news.cn/fortune/index.htm', '财经', 10),
            ('https://www.xinhuanet.com/world/', '国际', 6),
            ('https://www.news.cn/politics/xsj/index.htm', '新时代', 4),
        ]
        
        all_news = []
        for url, name, count in channels:
            news = fetch_news_from_channel(url, name, count)
            if verbose:
                print(f"  [{name}] 获取 {len(news)} 条")
            all_news.extend(news)
        
        # 按标题去重
        seen = set()
        unique = []
        for n in all_news:
            # 标题标准化后去重
            key = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', n['title'])[:20]
            if key not in seen:
                seen.add(key)
                unique.append(n)
        
        return unique[:max_total]

    def analyze_with_llm(news_items):
        """调用LLM分析新闻对沪深300的影响"""
        api_key = os.environ.get('TEA_AGENT_KEY', '')
        api_url = os.environ.get('TEA_AGENT_URL', '')
        model = os.environ.get('TEA_AGENT_MODEL', 'qwen3.6-plus')
        
        if not api_key or not api_url:
            return {"error": "API配置未找到，请设置TEA_AGENT_KEY和TEA_AGENT_URL环境变量"}
        
        # 构建带频道标签的新闻列表
        news_text = "\n".join([
            f"{i+1}. [{n['channel']}] {n['title']}" 
            for i, n in enumerate(news_items)
        ])
        
        system_prompt = """你是资深A股市场分析师，擅长从宏观政策、经济数据、国际局势等多维度研判市场走势。

请分析以下最新新闻对第二天沪深300指数的影响，要求：

1. **分类识别**：对每条新闻判断利好/利空/中性，注意频道来源（时政>财经>国际的权重递减）
2. **关键因素**：重点关注：
   - 央行货币政策动向（降准降息预期）
   - 财政政策（特别国债、减税降费）
   - 监管政策变化
   - 外围市场（美股、港股）趋势
   - 地缘政治风险
   - 行业政策利好/利空
3. **综合研判**：权衡多空力量，给出最终判断
4. **置信度**：基于信息充分度判断

严格按以下JSON格式输出（不要输出其他内容）：
{
  "bullish_factors": ["利好因素1", "利好因素2"],
  "bearish_factors": ["利空因素1", "利空因素2"],
  "neutral_factors": ["中性因素1"],
  "analysis": "综合分析文字，200字以内",
  "prediction": "看涨/看跌/看平",
  "confidence": "高/中/低"
}"""
        
        user_prompt = f"以下是今天从新华网各频道获取的最新新闻：\n\n{news_text}\n\n请分析这些新闻对明天沪深300指数的影响，输出JSON。"
        
        try:
            headers = {
                'Authorization': f'Bearer {api_key}', 
                'Content-Type': 'application/json'
            }
            payload = {
                "model": model, 
                "messages": [
                    {"role": "system", "content": system_prompt}, 
                    {"role": "user", "content": user_prompt}
                ], 
                "temperature": 0.3,
                "max_tokens": 1500
            }
            response = requests.post(
                f'{api_url}/chat/completions', 
                headers=headers, 
                json=payload, 
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content']
                # 尝试提取JSON
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group())
                    return parsed
                return {"error": "JSON解析失败", "raw_content": content}
            return {"error": f"API请求失败: HTTP {response.status_code}"}
        except requests.Timeout:
            return {"error": "API请求超时"}
        except json.JSONDecodeError as e:
            return {"error": f"JSON解析错误: {e}"}
        except Exception as e:
            return {"error": f"分析异常: {e}"}

    # 主流程
    if verbose:
        print("=== 沪深300指数预测 ===")
        print("正在从新华网多频道获取新闻...")
    
    news_list = fetch_all_news(max_news)
    
    if not news_list:
        return {
            "prediction": "未知", 
            "news_list": [], 
            "analysis": "未能获取任何新闻，请检查网络连接", 
            "bullish_factors": [], 
            "bearish_factors": [], 
            "neutral_factors": [], 
            "confidence": "无"
        }
    
    if verbose:
        print(f"\n共获取 {len(news_list)} 条新闻（去重后）：")
        for i, n in enumerate(news_list, 1):
            print(f"  {i}. [{n['channel']}] {n['title']}")
        print("\n正在调用LLM分析...")
    
    result = analyze_with_llm(news_list)
    
    if "error" in result:
        return {
            "prediction": "分析失败",
            "news_list": [n['title'] for n in news_list],
            "analysis": result.get("error", "未知错误"),
            "bullish_factors": [],
            "bearish_factors": [],
            "neutral_factors": [],
            "confidence": "无",
            "raw_content": result.get("raw_content", "")
        }
    
    return {
        "prediction": result.get("prediction", "未知"),
        "news_list": [f"[{n['channel']}] {n['title']}" for n in news_list],
        "analysis": result.get("analysis", ""),
        "bullish_factors": result.get("bullish_factors", []),
        "bearish_factors": result.get("bearish_factors", []),
        "neutral_factors": result.get("neutral_factors", []),
        "confidence": result.get("confidence", "")
    }

def meta_toolkit_predict_csi300() -> dict:
    return {
        "type": "function", 
        "function": {
            "name": "toolkit_predict_csi300", 
            "description": "从新华网多个频道（首页、财经、国际、时政）获取最新经济新闻，通过LLM分析推测对第二天沪深300指数的影响，输出看平/看跌/看涨，包含利好利空因素分析", 
            "parameters": {
                "type": "object", 
                "properties": {
                    "max_news": {
                        "type": "integer", 
                        "description": "最多获取的新闻条数，默认25"
                    }, 
                    "verbose": {
                        "type": "boolean", 
                        "description": "是否显示详细分析过程"
                    }
                }, 
                "required": []
            }
        }
    }

if __name__ == "__main__":
    print(toolkit_predict_csi300(verbose=True))
