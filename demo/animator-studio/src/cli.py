"""
Animator Studio CLI — 命令行生成/录制/LLM
"""
import os
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from src.config import config
from src.core.generator import generator, llm_generate
from src.core.recorder import recorder


def main():
    parser = argparse.ArgumentParser(
        description="🎬 Animator Studio CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  python -m src.cli "彩色粒子"              # 关键词模式
  python -m src.cli "手机进化史"             # 故事模式
  python -m src.cli --llm "两只小猫玩毛线球" # LLM 模式
  python -m src.cli --serve                  # 启动 Web 服务""")

    parser.add_argument("text", nargs="*", default=None, help="动画描述文字（多词自动拼接）")
    parser.add_argument("-d", "--duration", type=float, default=None, help="时长(秒)")
    parser.add_argument("--record", action="store_true", help="录制 MP4")
    parser.add_argument("--no-tts", action="store_true", help="禁用语音")
    parser.add_argument("--no-play", action="store_true", help="生成后不播放")
    parser.add_argument("--llm", action="store_true", help="使用 LLM 模式（AI 生成动画脚本）")
    parser.add_argument("--config", type=str, default=None,
                        help="LLM 配置文件路径 (YAML)")
    parser.add_argument("--serve", action="store_true", help="启动 Web 服务")
    parser.add_argument("--host", default=config.host, help="Web 服务地址")
    parser.add_argument("--port", type=int, default=config.port, help="Web 服务端口")
    parser.add_argument("--fps", type=int, default=24, help="录制帧率")
    parser.add_argument("--width", type=int, default=1280, help="视频宽度")
    parser.add_argument("--height", type=int, default=720, help="视频高度")

    args = parser.parse_args()

    if args.serve:
        from src.app import main as serve
        config.host = args.host
        config.port = args.port
        serve()
        return

    # 拼接多词描述
    desc = " ".join(args.text) if args.text else None
    if not desc:
        parser.print_help()
        print("\n❌ 请提供动画描述")
        sys.exit(1)

    config.ensure_dirs()
    is_llm = args.llm or _detect_llm_needed(desc)

    if is_llm:
        print("=" * 50)
        print("🤖 LLM 模式 — AI 生成动画脚本")
        print("=" * 50)
        result = llm_generate(
            text=desc,
            duration=args.duration or 8,
            tts=not args.no_tts,
            config_path=args.config,
        )
    else:
        print("=" * 50)
        print("🎯 关键词模式 — 匹配动画类型")
        print("=" * 50)
        result = generator.generate(
            text=desc,
            duration=args.duration or 5,
            tts=not args.no_tts,
        )

    print(f"✅ 生成: {result['html_path']}")

    if args.record:
        print(f"🎬 录制: {result['duration']}s @ {args.fps}fps")
        try:
            job = recorder.record(
                html_path=result["html_path"],
                duration=result["duration"],
                width=args.width,
                height=args.height,
                fps=args.fps,
            )
            print(f"✅ 视频: {job['video_path']} ({job['size_mb']} MB)")
        except Exception as e:
            print(f"❌ 录制失败: {e}")

    if not args.no_play:
        try:
            from animator import WebviewPlayer
            tts_str = "" if args.no_tts else "🔊 含语音"
            print(f"\n▶️ 播放动画 (点击「▶ 点击开始」启动{tts_str})...")
            player = WebviewPlayer(
                title=f"Animator: {desc[:40]}",
                fullscreen=False,
            )
            player.play(result["html_path"])
        except ImportError:
            print("⚠️ 无法播放（pywebview 未安装）")
            print(f"  文件: {result['html_path']}")


def _detect_llm_needed(text: str) -> bool:
    keyword_types = {"粒子","烟火","星星","球","彩虹","波浪","螺旋","极光","几何",
                     "文字","手机","大哥大","翻盖","触屏","折叠"}
    if len(text) > 15:
        return True
    has_keyword = any(k in text for k in keyword_types)
    return not has_keyword


if __name__ == "__main__":
    main()
