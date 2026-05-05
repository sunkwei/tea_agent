"""Skill: 交互 — 语音合成、语音识别、网络搜索"""
SKILL_MANIFEST = {
    "name": "interaction",
    "version": "1.0.0",
    "description": "外部交互：文本转语音(TTS)、语音识别(STT)、互联网搜索",
    "tools": [
        "toolkit_speak",
        "toolkit_listen",
        "toolkit_search",
    ],
    "prompt_inject": """交互准则：
1. 需要朗读内容时用 speak，支持中英文
2. 需要语音输入时用 listen（Google STT 或本地引擎）
3. 需要查互联网信息时用 search（DuckDuckGo/百度）""",
    "activation": "auto",
    "dependencies": ["pyttsx3", "gtts", "speechrecognition"],
    "trigger_words": [
        "朗读", "说出来", "语音", "听听", "搜索",
        "查一下", "搜一下", "网上", "百度", "google",
    ],
}
