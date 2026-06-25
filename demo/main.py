#!/usr/bin/env python3
"""
🎬 Animator — AI 动画生成工具

根据文字描述生成 HTML Canvas 动画，支持 webview 播放。
录制为 MP4 需显式指定 --record。

用法:
    python main.py "红色弹跳球"             # 生成 + 播放
    python main.py "彩色粒子" --record      # 生成 + 播放 + 录制
    python main.py "手机进化史"              # 生成手机故事动画
    python main.py --list-config            # 查看所有动画类型
"""

import os, sys, argparse, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(
        description="🎬 Animator - 动画生成·播放·录制",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  python main.py "红色弹跳球 5秒"           # 生成 + 播放
  python main.py "手机进化史"                # 手机故事动画
  python main.py "彩色粒子" --record        # 生成 + 播放 + 录制MP4
  python main.py --record demo_xxx.html     # 仅录制已有文件
  python main.py --list-config              # 查看动画类型""")

    parser.add_argument("text", nargs="?", default=None, help="动画描述，如 '红色弹跳球 5秒'")
    parser.add_argument("-d", "--duration", type=float, default=5, help="动画时长(秒)，默认5")
    parser.add_argument("--record", nargs="?", const="_auto_", default=None,
                        help="录制为 MP4（默认不录制）")
    parser.add_argument("--play", nargs="?", const="_auto_", default=None,
                        help="播放指定 HTML 文件")
    parser.add_argument("--no-play", action="store_true", help="生成后不播放")
    parser.add_argument("--no-tts", action="store_true", help="禁用语音旁白")
    parser.add_argument("--fullscreen", action="store_true", help="全屏播放")
    parser.add_argument("--output-dir", default="./output", help="输出目录")
    parser.add_argument("--fps", type=int, default=24, help="录制帧率")
    parser.add_argument("--quality", type=int, default=23, help="视频质量 CRF")
    parser.add_argument("--width", type=int, default=1280, help="视频宽度")
    parser.add_argument("--height", type=int, default=720, help="视频高度")
    parser.add_argument("--list-config", action="store_true", help="列出支持的动画类型")

    args = parser.parse_args()

    if args.list_config:
        _show_config(); return

    if args.play and args.play != "_auto_":
        _play_file(args.play, args.fullscreen); return

    if args.record and args.record != "_auto_":
        _record_file(args.record, args); return

    if not args.text:
        parser.print_help()
        print("\n❌ 请提供动画描述，或使用 --play/--record")
        sys.exit(1)

    # 生成 → 播放（可选手动录制）
    _generate_and_play(args)


def _generate_and_play(args):
    from animator import AnimationGenerator, WebviewPlayer, Recorder

    print("=" * 50)
    print("🎬 Animator — 动画生成器")
    print("=" * 50)
    print(f"  描述: {args.text}")
    print(f"  时长: {args.duration}s")
    os.makedirs(args.output_dir, exist_ok=True)

    gen = AnimationGenerator()

    # 检测是否手机故事
    story_keywords = ["手机","进化","发展","历程","历史","大哥大","翻盖","折叠","触屏"]
    is_story = any(k in args.text for k in story_keywords)

    if is_story:
        html_path = gen.generate_story(
            text=args.text,
            tts=not args.no_tts,
            output_path=os.path.join(args.output_dir, f"story_{int(time.time())}.html"),
        )
        # 从场景配置获取实际时长
        duration = sum(s.get("dur",6) for s in gen.PHONE_STORY_SCENES)
    else:
        html_path = gen.generate(
            text=args.text,
            duration=args.duration,
            output_path=os.path.join(args.output_dir, f"anim_{int(time.time())}.html"),
        )
        duration = args.duration

    # 录制（仅当显式指定 --record）
    if args.record is not None:
        _do_record(html_path, duration, args)

    # 播放（默认播放，除非 --no-play）
    if not args.no_play:
        tts_str = "🔊 含语音" if not args.no_tts and is_story else ""
        print(f"\n▶️ 播放动画 (点击窗口中的「▶ 点击开始」启动{tts_str})...")
        player = WebviewPlayer(
            title=f"Animator: {args.text[:40]}",
            fullscreen=args.fullscreen,
        )
        try:
            player.play(html_path)
        except KeyboardInterrupt:
            print("\n⏹️ 停止")


def _do_record(html_path, duration, args):
    from animator import Recorder
    rec = Recorder(
        fps=args.fps, quality=args.quality,
        temp_dir=os.path.join(args.output_dir, ".frames"),
    )
    try:
        mp4 = rec.record(
            html_path=html_path, duration=duration,
            output_path=os.path.join(args.output_dir,
                f"{os.path.splitext(os.path.basename(html_path))[0]}.mp4"),
            width=args.width, height=args.height,
        )
        print(f"\n🎉 MP4: {mp4}")
    except Exception as e:
        print(f"\n❌ 录制失败: {e}")
        print("  需安装: pip install playwright && playwright install chromium")
    finally:
        rec.cleanup()


def _play_file(html_path, fullscreen):
    from animator import WebviewPlayer
    if not os.path.exists(html_path):
        print(f"❌ 文件不存在: {html_path}"); sys.exit(1)
    print(f"▶️ 播放: {html_path}")
    player = WebviewPlayer(fullscreen=fullscreen)
    try: player.play(html_path)
    except KeyboardInterrupt: print("\n⏹️ 停止")


def _record_file(html_path, args):
    from animator import Recorder
    if not os.path.exists(html_path):
        print(f"❌ 文件不存在: {html_path}"); sys.exit(1)
    os.makedirs(args.output_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(html_path))[0]
    rec = Recorder(fps=args.fps, quality=args.quality,
                   temp_dir=os.path.join(args.output_dir,".frames"))
    try:
        mp4 = rec.record(html_path=html_path, duration=args.duration,
            output_path=os.path.join(args.output_dir,f"{base}.mp4"),
            width=args.width, height=args.height)
        print(f"\n🎉 MP4: {mp4}")
    except Exception as e: print(f"\n❌ 录制失败: {e}")
    finally: rec.cleanup()


def _show_config():
    from animator.html_generator import AnimationGenerator
    gen = AnimationGenerator()
    print("=" * 50)
    print("🎨 支持的动画类型与关键词")
    print("=" * 50)
    types = {}
    for kw, t in sorted(gen.KEYWORD_MAP.items(), key=lambda x: x[1]):
        types.setdefault(t, []).append(kw)
    descs = {
        "particles":"粒子系统 (烟火/星星)", "bouncing_balls":"弹跳球 (碰撞/物理)",
        "rainbow":"彩虹渐变 (色彩流动)", "wave":"波浪 (动态波形)",
        "spiral":"螺旋 (旋转/万花筒)", "aurora":"极光 (星空/光幕)",
        "geometric":"几何图形 (多边形旋转)", "text_anim":"文字动画 (环绕文字)",
        "story":"📱 手机进化史 (卡通拟人化故事)",
    }
    for at, kws in types.items():
        d = descs.get(at, "")
        print(f"\n  {d}")
        print(f"    关键词: {', '.join(kws)}")
    print("\n颜色词: 红, 橙, 黄, 绿, 青, 蓝, 紫, 彩")
    print("修饰词: 快/慢, 多/少, 数字(数量)")
    print("=" * 50)


if __name__ == "__main__":
    main()
