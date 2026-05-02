## llm generated tool func, created Sat May  2 10:18:29 2026
# version: 1.0.0

# @2026-05-02 gen by tea_agent, STT语音识别：Google Speech Recognition + 本地回退
# version: 1.0.0

def toolkit_listen(lang: str = "zh-CN", timeout: int = 5, phrase_limit: int = 10):
    """
    从麦克风录音并识别为文字。
    
    Args:
        lang: 识别语言，zh-CN=中文, en-US=英文
        timeout: 录音超时（秒），默认5
        phrase_limit: 最长说话时长（秒），默认10
    
    Returns:
        (0, 识别的文字, "")
    """
    import json
    
    try:
        import speech_recognition as sr
    except ImportError:
        return (1, "", "需安装 SpeechRecognition: pip install SpeechRecognition")
    
    r = sr.Recognizer()
    
    # 尝试使用麦克风
    try:
        mic = sr.Microphone()
    except Exception as e:
        return (1, "", f"无法访问麦克风: {e}")
    
    try:
        with mic as source:
            # 降噪校准
            r.adjust_for_ambient_noise(source, duration=0.5)
            audio = r.listen(source, timeout=timeout, phrase_time_limit=phrase_limit)
    except sr.WaitTimeoutError:
        return (1, "", "录音超时：未检测到语音")
    except Exception as e:
        return (1, "", f"录音失败: {e}")
    
    # 方案1: Google (在线，无需API key)
    errors = []
    try:
        text = r.recognize_google(audio, language=lang)
        if text.strip():
            return (0, text.strip(), "")
    except sr.UnknownValueError:
        errors.append("Google: 无法识别语音内容")
    except sr.RequestError as e:
        errors.append(f"Google: 网络错误 {e}")
    except Exception as e:
        errors.append(f"Google: {e}")
    
    # 方案2: Sphinx (离线)
    try:
        text = r.recognize_sphinx(audio)
        if text.strip():
            return (0, text.strip(), "")
    except sr.UnknownValueError:
        errors.append("Sphinx: 无法识别")
    except Exception as e:
        errors.append(f"Sphinx: {e}")
    
    if not errors:
        errors.append("所有引擎均未识别出内容")
    
    return (1, "", "; ".join(errors))


def meta_toolkit_listen() -> dict:
    return {"type": "function", "function": {"name": "toolkit_listen", "description": "语音输入 STT。从麦克风录制并转文字。支持 Google Speech Recognition（在线）和本地引擎。", "parameters": {"type": "object", "properties": {"lang": {"type": "string", "description": "识别语言，zh-CN=中文, en-US=英文。默认 zh-CN", "default": "zh-CN"}, "timeout": {"type": "integer", "description": "录音超时秒数，默认5", "default": 5}, "phrase_limit": {"type": "integer", "description": "最长识别秒数，默认10", "default": 10}}, "required": []}}}


def meta_toolkit_listen() -> dict:
    return {"type": "function", "function": {"name": "toolkit_listen", "description": "语音输入 STT。从麦克风录制并转文字。支持 Google Speech Recognition（在线）和本地引擎。", "parameters": {"type": "object", "properties": {"lang": {"type": "string", "description": "识别语言，zh-CN=中文, en-US=英文。默认 zh-CN", "default": "zh-CN"}, "timeout": {"type": "integer", "description": "录音超时秒数，默认5", "default": 5}, "phrase_limit": {"type": "integer", "description": "最长识别秒数，默认10", "default": 10}}, "required": []}}}
