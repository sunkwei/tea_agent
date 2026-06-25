"""
动画 HTML 生成器 — 文字→Canvas 动画/手机故事

支持:
  - 关键词驱动的粒子/图形动画
  - 手机进化史故事场景 (story 模式)
"""

import os, re, json, random

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
_TEMPLATE_FILE = os.path.join(_TEMPLATE_DIR, "animation.html")


class AnimationGenerator:
    """生成动画 HTML"""

    KEYWORD_MAP = {
        "粒子":"particles","烟火":"particles","星星":"particles","星":"particles","气泡":"particles","泡":"particles",
        "弹跳球":"bouncing_balls","弹球":"bouncing_balls","球":"bouncing_balls","碰撞":"bouncing_balls",
        "彩虹":"rainbow","渐变":"rainbow","色":"rainbow",
        "波浪":"wave","波":"wave","海浪":"wave",
        "螺旋":"spiral","旋转":"spiral","万花筒":"spiral",
        "极光":"aurora","光":"aurora",
        "几何":"geometric","多边形":"geometric","图形":"geometric",
        "文字":"text_anim","文本":"text_anim","字":"text_anim","hello":"text_anim",
        "手机":"story","大哥大":"story","翻盖":"story","触屏":"story","折叠":"story",
        "进化":"story","发展":"story","历程":"story","历史":"story",
    }

    COLOR_MAP = {"红":0,"赤":0,"橙":30,"橘":30,"黄":60,"绿":120,"翠":120,"青":180,"水":180,"蓝":240,"碧":240,"紫":300,"粉":300,"彩":None}

    # ── 📱 手机进化史 5 个时代场景配置（含语音旁白）──
    PHONE_STORY_SCENES = [
        {
            "phone": "brick",
            "year": "1983",
            "era": "1G · 模拟时代",
            "title": "大哥大 · 时代起点",
            "sub": "Motorola DynaTAC 8000X",
            "desc": "重若板砖，却开启了移动通信时代",
            "narration": "1983年，摩托罗拉推出了世界上第一款商用手机，大哥大。它重达一公斤，像一块板砖，却开启了人类移动通信的新纪元。",
            "emote": "surprised",
            "dur": 6,
            "bg": ["#1a1a0a", "#2a1a0a", "#0a0a0a"]
        },
        {
            "phone": "flip",
            "year": "1996",
            "era": "2G · 数字时代",
            "title": "翻盖 · 时尚新潮",
            "sub": "Motorola StarTAC",
            "desc": "小巧翻盖，人人都想拥有一部",
            "narration": "1996年，翻盖手机问世。它小巧时尚，轻轻一翻就能接听电话，成为身份的象征。",
            "emote": "smile",
            "dur": 6,
            "bg": ["#0a1a2a", "#0a0a2a", "#0a0a1a"]
        },
        {
            "phone": "candy",
            "year": "2000s",
            "era": "2.5G · 全民手机",
            "title": "按键 · 全民手机",
            "sub": "Nokia 3310 / 6600",
            "desc": "贪吃蛇、和弦铃音，诺基亚的黄金时代",
            "narration": "2000年代，按键手机走入千家万户。诺基亚称霸全球，贪吃蛇游戏风靡一时，和弦铃声成为个性的标签。",
            "emote": "happy",
            "dur": 6,
            "bg": ["#1a0a1a", "#2a1a2a", "#0a0a0a"]
        },
        {
            "phone": "touch",
            "year": "2007",
            "era": "3G · 智能手机",
            "title": "触屏 · 指尖革命",
            "sub": "iPhone / 多点触控",
            "desc": "一块大屏，重新定义了手机",
            "narration": "2007年，苹果发布了第一代iPhone，多点触控彻底改变了人机交互。手机从此只剩一块大屏，世界在指尖流转。",
            "emote": "smile",
            "dur": 6,
            "bg": ["#000a1a", "#001a2a", "#000000"]
        },
        {
            "phone": "fold",
            "year": "2020s",
            "era": "5G · 折叠未来",
            "title": "折叠 · 未来已来",
            "sub": "Samsung Galaxy Z Fold / Mate X",
            "desc": "柔性屏幕，手机与平板的融合",
            "narration": "2020年代，折叠屏手机惊艳登场。柔性屏幕让手机和平板合二为一，未来已然到来。",
            "emote": "happy",
            "dur": 8,
            "bg": ["#0a001a", "#1a002a", "#0a0a1a"]
        }
    ]

    def __init__(self, template_path=None):
        self.template_path = template_path or _TEMPLATE_FILE
        if not os.path.exists(self.template_path):
            raise FileNotFoundError(f"模板不存在: {self.template_path}")

    def _parse_text(self, text: str) -> dict:
        config = {}
        tl = text.lower()
        # 类型
        for kw, t in sorted(self.KEYWORD_MAP.items(), key=lambda x: -len(x[0])):
            if kw in text:
                config["type"] = t
                break
        config.setdefault("type", "particles")
        # 颜色
        for cw, hue in self.COLOR_MAP.items():
            if cw in text:
                if hue is not None: config["hue"] = hue
                elif "彩" in cw: config["palette"] = "rainbow"
                break
        # 数量
        if re.search(r"[多众繁]", text): config.setdefault("count", 200)
        elif re.search(r"[少稀]", text): config.setdefault("count", 30)
        elif re.search(r"\d+", text):
            n = int(re.findall(r"\d+", text)[0])
            t = config.get("type")
            if t in ("particles","spiral","geometric"): config["count"] = min(max(n*10,20),1000)
            elif t == "bouncing_balls": config["count"] = min(max(n,3),50)
        # 速度
        if re.search(r"[快疾速]", text): config["speed"] = random.uniform(1.5,3.0)
        elif re.search(r"[慢缓]", text): config["speed"] = random.uniform(0.2,0.6)
        # 文字
        if config.get("type") == "text_anim":
            q = re.findall(r'[""「」\'](.+?)[""」\']', text)
            if q: config["text"] = q[0]
            else:
                w = text
                for kw in self.KEYWORD_MAP: w = w.replace(kw,"")
                w = re.sub(r"\s+","",w)
                config["text"] = w[:10] if w else "动画"
        return config

    def generate(self, text: str, duration: float = 5,
                 output_path: str = None) -> str:
        config = self._parse_text(text)
        config["duration"] = duration

        # 如果是 story 类型，自动用手机进化史
        if config.get("type") == "story":
            return self.generate_story(text, duration, output_path)

        with open(self.template_path, "r", encoding="utf-8") as f:
            html = f.read()
        config_json = json.dumps(config, ensure_ascii=False)
        html = html.replace("{{CONFIG_JSON}}", config_json)
        html = html.replace("{{DESCRIPTION}}", text.strip()[:60])
        html = html.replace("{{DURATION}}", str(duration))

        if not output_path:
            fname = re.sub(r'[\\/:*?"<>|]', "_", text.strip())[:30] or "anim"
            output_path = f"demo_{fname}_{int(duration)}s.html"
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"✅ 动画 HTML: {output_path}  [{config.get('type','?')}]")
        return os.path.abspath(output_path)

    def generate_story(self, text: str = None, duration: float = 30,
                       output_path: str = None,
                       scenes: list = None,
                       tts: bool = True) -> str:
        """
        生成手机进化史故事动画 HTML

        参数:
            text: 描述文本（可选，用于文件名）
            duration: 总时长（将被场景实际时长覆盖）
            output_path: 输出路径
            scenes: 自定义场景列表，默认使用 PHONE_STORY_SCENES
            tts: 是否启用语音旁白（默认 True）
        """
        scenes = scenes or self.PHONE_STORY_SCENES
        total_dur = sum(s.get("dur", 6) for s in scenes)

        config = {
            "type": "story",
            "scenes": scenes,
            "duration": total_dur,
            "tts": tts,
        }

        with open(self.template_path, "r", encoding="utf-8") as f:
            html = f.read()

        config_json = json.dumps(config, ensure_ascii=False)
        desc = text or "手机进化史"
        html = html.replace("{{CONFIG_JSON}}", config_json)
        html = html.replace("{{DESCRIPTION}}", desc.strip()[:60])
        html = html.replace("{{DURATION}}", str(total_dur))

        if not output_path:
            fname = re.sub(r'[\\/:*?"<>|]', "_", desc.strip())[:30] or "phone_story"
            output_path = f"demo_{fname}_{int(total_dur)}s.html"
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

        tts_str = "🔊 含语音旁白" if tts else "🔇 无声"
        print(f"✅ 手机故事 HTML: {output_path}")
        print(f"   ├─ {len(scenes)} 个场景, 共 {total_dur}s")
        for i, s in enumerate(scenes):
            print(f"   ├─ [{i+1}] {s.get('year','?')} {s.get('title','?')} ({s.get('phone','?')}) - {s.get('dur',6)}s")
        print(f"   ├─ {tts_str}")
        print(f"   └─ 风格: 卡通拟人化 ✨")

        return os.path.abspath(output_path)

