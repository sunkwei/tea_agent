## llm generated tool func, created Sat May  2 10:18:06 2026
# version: 1.0.0

# @2026-05-02 gen by tea_agent, TTS语音合成：pyttsx3本地引擎 + gTTS在线回退
# version: 1.0.0

def toolkit_speak(text: str, lang: str = "zh", rate: int = 180):
    """
    文本转语音。优先使用 pyttsx3 本地引擎（离线，快速），失败则回退 gTTS。
    
    Args:
        text: 要朗读的文本
        lang: 语言，zh=中文, en=英文。用于选择音色
        rate: 语速（词/分钟），默认180。仅 pyttsx3 有效
    """
    import tempfile
    import os
    import subprocess
    
    if not text or not text.strip():
        return (1, "", "文本为空")
    
    text = text.strip()
    
    # 策略1: pyttsx3 (本地，141 voices)
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty('rate', rate)
        
        # 尝试匹配中文语音
        voices = engine.getProperty('voices')
        matched = None
        for v in voices:
            vname = v.name.lower()
            if lang == 'zh' and ('chinese' in vname or 'mandarin' in vname or 'cmn' in vname or 'yue' in vname):
                matched = v.id
                break
            elif lang == 'en' and 'english' in vname:
                matched = v.id
                break
        
        if not matched and lang == 'zh':
            # 尝试 zh 相关
            for v in voices:
                if 'zh' in v.id.lower() or 'cmn' in v.id.lower() or 'yue' in v.id.lower():
                    matched = v.id
                    break
        
        if matched:
            engine.setProperty('voice', matched)
        
        engine.say(text)
        engine.runAndWait()
        engine.stop()
        return (0, f"已朗读: {text[:60]}", "")
    
    except Exception as e1:
        pass
    
    # 策略2: gTTS (在线，音质好)
    try:
        from gtts import gTTS
        lang_code = "zh-cn" if lang == "zh" else "en"
        tts = gTTS(text=text, lang=lang_code, slow=False)
        
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
            tmp_path = f.name
        tts.save(tmp_path)
        
        # 播放
        subprocess.run(['mpv', '--no-terminal', '--really-quiet', tmp_path], 
                      timeout=30, capture_output=True)
        os.unlink(tmp_path)
        return (0, f"已朗读(gTTS): {text[:60]}", "")
    except Exception as e2:
        return (1, "", f"TTS失败: pyttsx3={e1}, gTTS={e2}")


def meta_toolkit_speak() -> dict:
    return {"type": "function", "function": {"name": "toolkit_speak", "description": "文本转语音 TTS。将文字朗读出来。优先级：pyttsx3本地引擎（离线141种音色）→ gTTS在线回退。", "parameters": {"type": "object", "properties": {"text": {"type": "string", "description": "要朗读的文本"}, "lang": {"type": "string", "description": "语言：zh=中文, en=英文。默认 zh", "default": "zh"}, "rate": {"type": "integer", "description": "语速（词/分钟），180=正常。仅pyttsx3", "default": 180}}, "required": ["text"]}}}


def meta_toolkit_speak() -> dict:
    return {"type": "function", "function": {"name": "toolkit_speak", "description": "文本转语音 TTS。将文字朗读出来。优先级：pyttsx3本地引擎（离线141种音色）→ gTTS在线回退。", "parameters": {"type": "object", "properties": {"text": {"type": "string", "description": "要朗读的文本"}, "lang": {"type": "string", "description": "语言：zh=中文, en=英文。默认 zh", "default": "zh"}, "rate": {"type": "integer", "description": "语速（词/分钟），180=正常。仅pyttsx3", "default": 180}}, "required": ["text"]}}}
