"""API 测试"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.core.generator import generator


def test_generate_story():
    """测试生成手机故事"""
    result = generator.generate("手机进化史", tts=True)
    assert result is not None
    assert result["type"] == "story"
    assert len(result.get("scenes", [])) == 5
    assert "html_path" in result
    print(f"✅ 故事生成: {result['id']} ({result['html_path']})")
    return result


def test_generate_particles():
    """测试生成粒子动画"""
    result = generator.generate("彩色粒子 快 3秒", duration=3)
    assert result is not None
    assert result["type"] == "auto"
    print(f"✅ 粒子生成: {result['id']}")
    return result


def test_list():
    """测试列表"""
    items = generator.list_animations()
    assert len(items) >= 2
    print(f"✅ 列表: {len(items)} 项")
    return items


def test_get():
    """测试按 ID 获取"""
    items = generator.list_animations()
    if items:
        item = generator.get(items[0]["id"])
        assert item is not None
        assert item["id"] == items[0]["id"]
        print(f"✅ 按 ID 获取: {item['id']}")


if __name__ == "__main__":
    print("=" * 40)
    print("🧪 Studio Core 测试")
    print("=" * 40)
    test_generate_story()
    test_generate_particles()
    test_list()
    test_get()
    print("=" * 40)
    print("✅ 全部通过")
