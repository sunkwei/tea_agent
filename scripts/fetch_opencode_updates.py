#!/usr/bin/env python3
"""
OpenCode 更新抓取 & 借鉴分析脚本
每周一 13:00 由 scheduler 触发，抓取 opencode 最新动态并写入文档。

功能：
1. 从 GitHub API 获取 opencode 的最新 release 和近期 commits
2. 与上次检查的状态比对，识别新内容
3. 追加到「文档/opencode_借鉴功能.md」
4. 按功能类别分类，附带基础分析
"""

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# ── 配置 ──
REPO = "anomalyco/opencode"
STATE_FILE = os.path.join(os.path.dirname(__file__), ".opencode_state.json")
# 使用 Windows 用户级"文档"目录 (~/Documents)
DOC_DIR = os.path.expanduser("~/Documents")
DOC_FILE = os.path.join(DOC_DIR, "opencode_借鉴功能.md")
# 高价值功能通知文件（Agent 激活时检测此文件）
HIGHLIGHTS_FILE = os.path.join(os.path.dirname(__file__), ".opencode_highlights.json")
GITHUB_API = "https://api.github.com"

# ── 借鉴度评分阈值 ──
SCORE_THRESHOLD_PROMPT = 75  # ≥75 分 → 提示用户是否实现
SCORE_THRESHOLD_NOTICE = 50  # ≥50 分 → 值得注意

# ── 工具函数 ──

def fetch_json(url, headers=None):
    """GET 请求返回 JSON"""
    req = Request(url)
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "tea-agent-scheduler/1.0")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        print(f"  ⚠ HTTP {e.code}: {e.reason}")
        if e.code == 403:
            print("  → API 限流，等待后重试")
            time.sleep(5)
            return None
        return None
    except URLError as e:
        print(f"  ⚠ 网络错误: {e.reason}")
        return None
    except Exception as e:
        print(f"  ⚠ 未知错误: {e}")
        return None


def load_state():
    """读取上次检查状态"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"last_release_id": 0, "last_commit_sha": "", "last_check": None}
    return {"last_release_id": 0, "last_commit_sha": "", "last_check": None}


def save_state(state):
    """保存检查状态"""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_doc():
    """读取现有文档内容"""
    if os.path.exists(DOC_FILE):
        with open(DOC_FILE, "r", encoding="utf-8") as f:
            return f.read()
    return None


def append_to_doc(content):
    """追加内容到文档"""
    os.makedirs(DOC_DIR, exist_ok=True)
    mode = "a" if os.path.exists(DOC_FILE) else "w"
    with open(DOC_FILE, mode, encoding="utf-8") as f:
        if mode == "w":
            f.write("# OpenCode 借鉴功能分析\n\n")
            f.write("> 自动追踪 OpenCode 新功能，评估 tea_agent 可借鉴之处。\n")
            f.write("> 每周一 13:00 自动更新。\n\n")
            f.write("---\n\n")
        f.write(content)
    print(f"  ✅ 已{'追加' if mode == 'a' else '创建'}文档: {DOC_FILE}")


def parse_datetime(iso_str):
    """解析 GitHub API 的 ISO 时间戳"""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt
    except Exception:
        return datetime.now(timezone.utc)


# ── 特征分类 & 量化评分 ──

FEATURE_CATEGORIES = {
    "mcp": "MCP / 工具集成",
    "agent": "Agent / 多智能体",
    "custom_command": "自定义命令 / Skill",
    "model": "模型支持 / LLM",
    "editor": "编辑器 / IDE",
    "terminal": "终端 / TUI",
    "lsp": "LSP / 代码智能",
    "session": "会话 / 上下文管理",
    "security": "安全 / 权限",
    "perf": "性能优化",
    "ui": "UI / 用户体验",
    "config": "配置 / 可定制性",
    "other": "其他",
}

CATEGORY_KEYWORDS = {
    "mcp": ["mcp", "tool", "plugin", "扩展", "集成"],
    "agent": ["agent", "subagent", "多智能体", "并行", "协作"],
    "custom_command": ["custom command", "skill", "命令模板", "slash command"],
    "model": ["model", "llm", "provider", "api key", "模型", "推理"],
    "editor": ["ide", "vscode", "editor", "jetbrain", "插件"],
    "terminal": ["terminal", "tui", "cli", "终端"],
    "lsp": ["lsp", "diagnostic", "completion", "definition", "代码补全"],
    "session": ["session", "context", "对话", "会话", "resume"],
    "security": ["security", "permission", "sandbox", "安全", "隐私"],
    "perf": ["performance", "cache", "优化", "加速", "速度"],
    "ui": ["ui", "interface", "桌面", "桌面版", "tab", "标签"],
    "config": ["config", "configure", "setting", "配置"],
}


def categorize(text):
    """返回 (category_key, category_label)"""
    text_lower = text.lower()
    scores = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text_lower)
        if score > 0:
            scores[cat] = score
    if not scores:
        return ("other", FEATURE_CATEGORIES["other"])
    best = max(scores, key=scores.get)
    return (best, FEATURE_CATEGORIES.get(best, "其他"))


def score_feature(name, description):
    """
    量化评估功能的「可借鉴度」— 返回 (总分0-100, 各项分数dict, 理由列表)
    
    五维评分体系：
    ┌──────────────┬──────┬────────────────────────────────────┐
    │ 维度         │ 满分 │ 评估逻辑                            │
    ├──────────────┼──────┼────────────────────────────────────┤
    │ 功能匹配度   │  30  │ tea_agent 是否有同类模块            │
    │ 工程价值     │  25  │ 是否是急需/痛点问题                 │
    │ 实现成本     │  20  │ 改动量大小（越高越容易）            │
    │ 用户感知度   │  15  │ 用户能否直接感受到                  │
    │ 架构兼容性   │  10  │ 是否与现有架构天然契合              │
    └──────────────┴──────┴────────────────────────────────────┘
    """
    text = (name + " " + description).lower()
    scores = {}
    reasons = []

    # ── 1. 功能匹配度 (0-30) ──
    match_keywords = {
        # 关键词 → (分数增量, 理由)
        "subagent": (8, "tea_agent 有 Sub-agent 系统"),
        "agent": (5, "tea_agent 有 Sub-agent 系统"),
        "custom command": (8, "tea_agent 有 Custom Commands 系统"),
        "skill": (5, "tea_agent 有 Skills 体系"),
        "mcp": (8, "tea_agent 有 MCP 客户端工具"),
        "lsp": (6, "tea_agent 有 LSP 工具"),
        "session": (6, "tea_agent 有 Plan/TODO/task_resume"),
        "context": (5, "tea_agent 有上下文管理"),
        "plan": (6, "tea_agent 有 Plan 系统"),
        "todo": (5, "tea_agent 有 TODO 系统"),
        "config": (4, "tea_agent 有配置管理"),
        "setting": (4, "tea_agent 有配置管理"),
        "prompt": (5, "tea_agent 有提示词管理"),
        "model": (4, "tea_agent 有多模型支持"),
        "provider": (4, "tea_agent 有 API 提供商管理"),
        "memory": (5, "tea_agent 有长期记忆系统"),
        "knowledge": (4, "tea_agent 有知识库"),
        "search": (3, "tea_agent 有搜索工具"),
        "file": (3, "tea_agent 有文件操作工具"),
        "terminal": (4, "tea_agent 有命令执行工具"),
        "diff": (4, "tea_agent 有 Diff 编辑工具"),
        "review": (5, "tea_agent 有代码审查工具"),
        "test": (4, "tea_agent 有测试工具"),
    }
    match_score = 0
    for kw, (val, reason) in match_keywords.items():
        if kw in text:
            match_score += val
            reasons.append(reason)
    scores["匹配度"] = min(match_score, 30)

    # ── 2. 工程价值 (0-25) ──
    value_keywords = {
        "fix": (3, "修复 Bug"),
        "bug": (3, "修复 Bug"),
        "improve": (4, "功能改进"),
        "performance": (5, "性能优化"),
        "optimize": (5, "性能优化"),
        "perf": (5, "性能优化"),
        "security": (5, "安全增强"),
        "permission": (4, "权限管理"),
        "sandbox": (6, "安全沙箱"),
        "reliability": (5, "可靠性提升"),
        "error": (3, "错误处理"),
        "crash": (4, "崩溃修复"),
        "compatible": (3, "兼容性改进"),
        "migration": (3, "迁移支持"),
    }
    value_score = 0
    for kw, (val, reason) in value_keywords.items():
        if kw in text:
            value_score += val
            reasons.append(reason)
    scores["工程价值"] = min(value_score, 25)

    # ── 3. 实现成本 (0-20) — 越低分表示越难实现，越高分表示越容易 ──
    high_cost_keywords = ["migration", "redesign", "refactor", "v2", "rewrite", "architecture"]
    low_cost_keywords = ["shortcut", "button", "keyboard", "ui", "style", "css",
                         "setting", "menu", "tooltip", "indicator", "badge"]
    cost_score = 10  # 基准分
    for kw in high_cost_keywords:
        if kw in text:
            cost_score -= 3
            reasons.append("实现成本较高")
    for kw in low_cost_keywords:
        if kw in text:
            cost_score += 3
            reasons.append("实现成本较低")
    scores["实现成本"] = max(0, min(cost_score, 20))

    # ── 4. 用户感知度 (0-15) ──
    perception_keywords = {
        "ui": 3, "interface": 3, "shortcut": 4, "button": 3,
        "menu": 3, "tab": 4, "desktop": 3, "visual": 3,
        "notification": 4, "indicator": 3, "status": 2,
        "error message": 3, "progress": 3, "loading": 2,
    }
    perception_score = 0
    for kw, val in perception_keywords.items():
        if kw in text:
            perception_score += val
    scores["用户感知度"] = min(perception_score, 15)

    # ── 5. 架构兼容性 (0-10) ──
    # 如果匹配度已经高，说明架构天然兼容
    if match_score >= 10:
        scores["架构兼容性"] = 8
        reasons.append("天然适配 tea_agent 架构")
    elif match_score >= 5:
        scores["架构兼容性"] = 5
        reasons.append("部分适配")
    else:
        scores["架构兼容性"] = 2
        reasons.append("需额外适配工作")

    total = sum(scores.values())
    return total, scores, reasons


def score_to_badge(total):
    """分数 → 可视化标签"""
    if total >= 85:
        return "🔴 强烈推荐"
    elif total >= SCORE_THRESHOLD_PROMPT:
        return "🟠 值得实现"
    elif total >= SCORE_THRESHOLD_NOTICE:
        return "🟡 可以借鉴"
    elif total >= 30:
        return "🟢 一般参考"
    else:
        return "⚪ 了解即可"


def build_analysis_section(name, description, url):
    """构建单条功能的量化借鉴分析"""
    cat_key, cat_label = categorize(name + " " + description)
    total, scores, reasons = score_feature(name, description)
    badge = score_to_badge(total)
    
    # 评分详情条
    score_bar = " · ".join(
        f"{dim}: {val}" for dim, val in sorted(scores.items(), key=lambda x: -x[1]) if val > 0
    )
    
    # 触发通知标记
    is_high_value = total >= SCORE_THRESHOLD_PROMPT
    notify_mark = " 🔔 **建议实现**" if is_high_value else ""
    
    analysis_text = "; ".join(set(reasons)) if reasons else "暂无直接关联，可做一般技术参考。"
    
    return {
        "name": name,
        "description": description,
        "url": url,
        "category": cat_label,
        "total_score": total,
        "scores": scores,
        "badge": badge,
        "score_bar": score_bar,
        "reasons": list(set(reasons)),
        "analysis": analysis_text,
        "is_high_value": is_high_value,
    }


def format_analysis_section(result):
    """将分析结果格式化为 Markdown"""
    name = result["name"][:80]
    desc = result["description"][:200]
    lines = []
    lines.append(f"### 📌 {name}\n\n")
    lines.append("| 属性 | 内容 |\n")
    lines.append("|------|------|\n")
    lines.append(f"| **分类** | {result['category']} |\n")
    lines.append(f"| **来源** | [{REPO}]({result['url']}) |\n")
    lines.append(f"| **借鉴分** | **{result['total_score']}/100** {result['badge']} |\n")
    lines.append(f"| **评分明细** | {result['score_bar']} |\n")
    lines.append(f"| **简介** | {desc}{'…' if len(result['description']) > 200 else ''} |\n")
    lines.append("\n")
    lines.append(f"**分析**：{result['analysis']}\n\n")
    if result["is_high_value"]:
        lines.append("---\n")
        lines.append("> 🔔 **高价值候选**：此功能达到推荐阈值，下次 Agent 激活时将提示是否实现。\n\n")
    return "".join(lines)


def build_daily_update(releases, commits, state, new_releases, new_commits):
    """构建本次更新的 Markdown 内容，返回 (markdown_content, high_value_features)"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = []
    high_value_features = []  # 收集 ≥75 分的功能
    
    lines.append(f"## 📡 自动更新 — {now}\n\n")
    
    # 概要
    lines.append(f"**新 release**: {len(new_releases)} | **新 commit**: {len(new_commits)}\n\n")
    
    # ── Release 部分 ──
    if new_releases:
        lines.append("### 🏷️ 新版本发布\n\n")
        for rel in new_releases:
            tag = rel.get("tag_name", "未知")
            name = rel.get("name", tag)
            url = rel.get("html_url", "")
            published = rel.get("published_at", "")
            body = rel.get("body", "无描述")[:500]
            
            lines.append(f"#### {name}\n\n")
            lines.append(f"- **版本**: `{tag}` | **日期**: {published[:10]} | **[链接]({url})**\n")
            lines.append(f"- **更新内容**:\n\n```\n{body}\n```\n\n")
            
            # 分析每个 release 中的功能点
            if body:
                lines.append("**✨ 可借鉴功能分析**\n\n")
                for line in body.split("\n"):
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith("---") or line.startswith("___"):
                        continue
                    if len(line) < 15:
                        continue
                    clean_line = line.lstrip("- *•·").strip()
                    if len(clean_line) < 10:
                        continue
                    # 量化分析
                    result = build_analysis_section(clean_line[:80], clean_line, url)
                    lines.append(format_analysis_section(result))
                    if result["is_high_value"]:
                        high_value_features.append(result)
                lines.append("---\n\n")
    
    # ── Commits 部分 ──
    if new_commits:
        lines.append("### 🔄 近期重要提交\n\n")
        lines.append("| 日期 | 提交者 | 描述 | 链接 |\n")
        lines.append("|------|--------|------|------|\n")
        for c in new_commits:
            sha = c.get("sha", "")[:7]
            msg = c.get("commit", {}).get("message", "").split("\n")[0][:80]
            author = c.get("commit", {}).get("author", {}).get("name", "unknown")
            date = c.get("commit", {}).get("author", {}).get("date", "")[:10]
            url = c.get("html_url", "")
            lines.append(f"| {date} | {author} | {msg} | [`{sha}`]({url}) |\n")
        
        lines.append("\n**✨ 值得关注的提交分析**\n\n")
        for c in new_commits:
            msg = c.get("commit", {}).get("message", "").split("\n")[0]
            sha = c.get("sha", "")[:7]
            url = c.get("html_url", "")
            if any(kw in msg.lower() for kw in ["feat", "feature", "add", "new", "support", "改进", "优化", "提升", "refactor", "redesign", "支持"]):
                result = build_analysis_section(f"提交 `{sha}`: {msg[:60]}", msg, url)
                lines.append(format_analysis_section(result))
                if result["is_high_value"]:
                    high_value_features.append(result)
    
    # ── 总结建议 ──
    lines.append("### 💡 综合建议\n\n")
    all_new = new_releases + new_commits
    if not all_new:
        lines.append("> 本次无新增内容。OpenCode 仓库无新变化。\n\n")
    else:
        cats_seen = {}
        for rel in new_releases:
            body = rel.get("body", "")
            for line in body.split("\n"):
                cat_key, _ = categorize(line)
                cats_seen[cat_key] = cats_seen.get(cat_key, 0) + 1
        for c in new_commits:
            msg = c.get("commit", {}).get("message", "").split("\n")[0]
            cat_key, _ = categorize(msg)
            cats_seen[cat_key] = cats_seen.get(cat_key, 0) + 1
        
        top_cats = sorted(cats_seen.items(), key=lambda x: -x[1])[:3]
        lines.append("重点关注的分类：\n\n")
        for cat, count in top_cats:
            label = FEATURE_CATEGORIES.get(cat, "其他")
            lines.append(f"- **{label}** ({count} 项)\n")
        lines.append("\n")
        
        # 高价值功能汇总
        if high_value_features:
            lines.append("#### 🔔 高价值候选功能（≥75分）\n\n")
            lines.append("| 功能 | 借鉴分 | 分类 |\n")
            lines.append("|------|--------|------|\n")
            for hf in high_value_features:
                lines.append(f"| {hf['name'][:50]} | **{hf['total_score']}/100** {hf['badge']} | {hf['category']} |\n")
            lines.append("\n")
            lines.append("> 🎯 **检测到高价值功能！** 下次 Agent 激活时将提示是否实现。\n\n")
        
        lines.append("> ⚡ 下次 Agent 激活时，可深入分析上述高亮功能在 tea_agent 中的落地方式。\n\n")
    
    lines.append("---\n\n")
    return "".join(lines), high_value_features


# ── 主流程 ──

def main():
    print("=" * 50)
    print(f"📡 OpenCode 更新抓取 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"   仓库: {REPO}")
    print("=" * 50)
    
    state = load_state()
    print(f"\n📋 上次检查: {state.get('last_check', '从未')}")
    
    # 1. 获取最新 release
    print("\n🔍 正在获取 releases …")
    releases = fetch_json(f"{GITHUB_API}/repos/{REPO}/releases?per_page=5")
    if releases is None:
        releases = []
    
    # 2. 获取近 30 天 commits
    print("🔍 正在获取 commits …")
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    commits = fetch_json(f"{GITHUB_API}/repos/{REPO}/commits?per_page=20&since={since}")
    if commits is None:
        commits = []
    
    # 3. 识别新内容
    last_release_id = state.get("last_release_id", 0)
    last_commit_sha = state.get("last_commit_sha", "")
    
    new_releases = [r for r in releases if r.get("id", 0) > last_release_id]
    new_commits = []
    for c in commits:
        if c.get("sha", "") == last_commit_sha:
            break
        new_commits.append(c)
    
    print(f"\n📊 发现: {len(new_releases)} 个新 release, {len(new_commits)} 个新 commit")
    
    if not new_releases and not new_commits:
        print("  ℹ 无新内容，跳过文档更新")
        # 清空高亮通知（因为无新内容）
        if os.path.exists(HIGHLIGHTS_FILE):
            os.remove(HIGHLIGHTS_FILE)
    else:
        # 4. 构建更新内容
        update_content, high_value_features = build_daily_update(
            releases, commits, state, new_releases, new_commits
        )
        
        # 5. 写入文档
        append_to_doc(update_content)
        print(f"\n📝 文档已更新: {DOC_FILE}")
        
        # 6. 写入高价值功能通知文件（Agent 激活时检测）
        if high_value_features:
            highlight_data = {
                "detected_at": datetime.now(timezone.utc).isoformat(),
                "repo": REPO,
                "threshold": SCORE_THRESHOLD_PROMPT,
                "features": [
                    {
                        "name": hf["name"],
                        "score": hf["total_score"],
                        "badge": hf["badge"],
                        "category": hf["category"],
                        "url": hf["url"],
                        "description": hf["description"],
                        "reasons": hf["reasons"],
                        "scores": hf["scores"],
                    }
                    for hf in high_value_features
                ],
            }
            with open(HIGHLIGHTS_FILE, "w", encoding="utf-8") as f:
                json.dump(highlight_data, f, ensure_ascii=False, indent=2)
            print(f"  🔔 发现 {len(high_value_features)} 个高价值功能，通知已写入: {HIGHLIGHTS_FILE}")
        else:
            # 无高价值功能时清除旧通知
            if os.path.exists(HIGHLIGHTS_FILE):
                os.remove(HIGHLIGHTS_FILE)
    
    # 6. 更新状态
    if releases:
        state["last_release_id"] = releases[0].get("id", 0)
    if commits:
        state["last_commit_sha"] = commits[0].get("sha", "")
    state["last_check"] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    print(f"\n✅ 检查完成，状态已保存")
    print(f"   下次检查将识别 {state['last_release_id']} 之后的 release")
    print("=" * 50)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
