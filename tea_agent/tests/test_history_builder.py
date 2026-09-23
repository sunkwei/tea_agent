"""
历史消息构建模块单元测试 — 覆盖 to_multimodal。

测试范围:
- to_multimodal: 支持视觉 / 不支持视觉 / 有图片 / 无图片
- _extract_files_from_text: 符号索引损坏时的静默降级
"""

import logging

import pytest


# ============================================================
# to_multimodal
# ============================================================

class TestToMultimodal:
    """多模态消息转换测试"""

    def test_no_images_returns_unchanged(self):
        """无图片时应原样返回"""
        from tea_agent.session.history_builder import to_multimodal
        msg = {"role": "user", "content": "hello"}
        result = to_multimodal(msg, supports_vision=True)
        assert result["content"] == "hello"
        assert "images" not in result

    def test_empty_images_returns_unchanged(self):
        """空图片列表应原样返回"""
        from tea_agent.session.history_builder import to_multimodal
        msg = {"role": "user", "content": "hello", "images": []}
        result = to_multimodal(msg, supports_vision=True)
        assert result["content"] == "hello"
        assert "images" not in result

    def test_vision_supported_converts_to_multimodal(self, tmp_path):
        """支持视觉时应转换为多模态格式"""
        from tea_agent.session.history_builder import to_multimodal
        # 创建临时图片文件
        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"fake png data")

        msg = {
            "role": "user",
            "content": "描述这张图片",
            "images": [str(img_path)]
        }
        result = to_multimodal(msg, supports_vision=True)
        assert "images" not in result
        assert isinstance(result["content"], list)
        assert len(result["content"]) == 2  # text + image
        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == "描述这张图片"
        assert result["content"][1]["type"] == "image_url"

    def test_vision_not_supported_removes_images(self, tmp_path):
        """不支持视觉时应移除图片"""
        from tea_agent.session.history_builder import to_multimodal
        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"fake png data")

        msg = {
            "role": "user",
            "content": "描述这张图片",
            "images": [str(img_path)]
        }
        result = to_multimodal(msg, supports_vision=False)
        assert result["content"] == "描述这张图片"
        assert "images" not in result

    def test_multiple_images(self, tmp_path):
        """多图片应全部转换"""
        from tea_agent.session.history_builder import to_multimodal
        # 创建多个临时图片文件
        img1 = tmp_path / "test1.png"
        img1.write_bytes(b"fake png 1")
        img2 = tmp_path / "test2.jpg"
        img2.write_bytes(b"fake jpg 2")

        msg = {
            "role": "user",
            "content": "比较这两张图",
            "images": [str(img1), str(img2)]
        }
        result = to_multimodal(msg, supports_vision=True)
        assert isinstance(result["content"], list)
        assert len(result["content"]) == 3  # text + 2 images

    def test_removes_images_key_from_result(self, tmp_path):
        """转换后应移除 images 键"""
        from tea_agent.session.history_builder import to_multimodal
        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"fake png data")

        msg = {
            "role": "user",
            "content": "test",
            "images": [str(img_path)]
        }
        result = to_multimodal(msg, supports_vision=True)
        assert "images" not in result

    def test_data_url_passthrough(self):
        """data URL 图片（API server 传入）应直接透传，不当作文件路径处理"""
        from tea_agent.session.history_builder import to_multimodal
        data_url = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

        msg = {
            "role": "user",
            "content": "看看这张图",
            "images": [data_url],
        }
        result = to_multimodal(msg, supports_vision=True)
        parts = result["content"]
        assert isinstance(parts, list)
        assert len(parts) == 2  # text + image
        assert parts[0]["type"] == "text"
        assert parts[1]["type"] == "image_url"
        assert parts[1]["image_url"]["url"] == data_url
        assert "images" not in result

    def test_reentrant_content_list_is_flattened(self):
        """content 已是多模态 parts 列表时再次转换应幂等（不嵌套、不重复图片）

        回归：历史回写 + images 键仍在导致重复转换，旧实现把 list 再包一层，
        产出 {"type": "text", "text": [...]}，服务端 pydantic 报 400。
        """
        from tea_agent.session.history_builder import to_multimodal
        data_url = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

        msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": "看看这张图"},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
            "images": [data_url],  # 同一张图仍在 → 旧实现会自动发两遍
        }
        result = to_multimodal(msg, supports_vision=True)
        parts = result["content"]
        assert isinstance(parts, list)
        assert isinstance(parts[0]["text"], str), "text 段必须是字符串，不能是嵌套 list"
        assert parts[0]["text"] == "看看这张图"
        assert [p["type"] for p in parts] == ["text", "image_url"], "同一 URL 不应重复出现"
        assert parts[1]["image_url"]["url"] == data_url
        assert "images" not in result

    def test_reentrant_is_idempotent_after_writeback(self, tmp_path):
        """回写后的 parts 再次过一遍 to_multimodal，结构不应继续变形"""
        from tea_agent.session.history_builder import to_multimodal
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake png data")

        msg = {"role": "user", "content": "看图", "images": [str(img)]}
        first = to_multimodal(msg, supports_vision=True)

        # 模拟历史回写：把 parts 塞回 content，images 键被重新附上
        msg2 = {"role": "user", "content": list(first["content"]), "images": [str(img)]}
        second = to_multimodal(msg2, supports_vision=True)

        assert [p["type"] for p in second["content"]] == [p["type"] for p in first["content"]]
        assert isinstance(second["content"][0]["text"], str)

    def test_reentrant_nested_text_list_flattened(self):
        """历史里已嵌套的 text 列表应被递归展平，保持原有顺序"""
        from tea_agent.session.history_builder import to_multimodal
        data_url = "data:image/png;base64,AAA"
        msg = {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": [
                        {"type": "text", "text": "第一段"},
                        {"type": "text", "text": [{"type": "text", "text": "第二段"}]},
                    ],
                },
            ],
            "images": [data_url],
        }
        result = to_multimodal(msg, supports_vision=True)
        parts = result["content"]
        assert parts[0]["text"] == "第一段\n第二段"
        assert parts[1]["type"] == "image_url"

    def test_messages_contain_images_detects_image_url(self):
        """含 image_url 内容的消息应被识别为含图"""
        from tea_agent.session.history_builder import messages_contain_images
        msgs = [
            {"role": "user", "content": "文本"},
            {"role": "user", "content": [
                {"type": "text", "text": "描述"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,xx"}},
            ]},
        ]
        assert messages_contain_images(msgs) is True

    def test_messages_contain_images_detects_images_field(self):
        """含未转换 images 字段的消息应被识别为含图"""
        from tea_agent.session.history_builder import messages_contain_images
        msgs = [{"role": "user", "content": "文本", "images": ["/tmp/a.png"]}]
        assert messages_contain_images(msgs) is True

    def test_messages_contain_images_false_for_text(self):
        """纯文本消息列表返回 False"""
        from tea_agent.session.history_builder import messages_contain_images
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！"},
        ]
        assert messages_contain_images(msgs) is False


# ============================================================
# _extract_files_from_text — 符号索引容错（Linux 启动报错同源回归）
# ============================================================

class TestExtractFilesFromSymbolIndex:
    """.tea_agent_run/symbol_index.json 损坏时必须静默降级。

    回归背景：与 os_info_injector 同一模式 —— 旁路缓存文件被中断写入留下
    空文件/半截 JSON，旧实现宽捕获后用 logger.exception 打成 ERROR + traceback，
    在 Linux(RK 设备) 上每次启动刷屏。索引只用于「多找几个相关文件」，
    坏了就当没有，不得冒泡。
    """

    @staticmethod
    def _make_index(tmp_path, content: str, encoding="utf-8"):
        run_dir = tmp_path / ".tea_agent_run"
        run_dir.mkdir(exist_ok=True)
        (run_dir / "symbol_index.json").write_text(content, encoding=encoding)
        return run_dir

    def test_valid_index_resolves_symbol_to_path(self, tmp_path, monkeypatch):
        """正常索引应把符号映射到文件路径。"""
        monkeypatch.chdir(tmp_path)
        self._make_index(tmp_path, '{"build_history": [{"path": "tea_agent/session/history_builder.py"}]}')
        from tea_agent.session.history_builder import _extract_files_from_text

        files = _extract_files_from_text("请检查 build_history 的实现")
        assert "tea_agent/session/history_builder.py" in files

    def test_bom_prefixed_index_is_read(self, tmp_path, monkeypatch):
        """带 UTF-8 BOM 的索引应能正常读出（旧实现用 utf-8 读会抛 char 0 错误）。"""
        monkeypatch.chdir(tmp_path)
        self._make_index(
            tmp_path,
            '{"build_history": [{"path": "a/b.py"}]}',
            encoding="utf-8-sig",
        )
        from tea_agent.session.history_builder import _extract_files_from_text

        assert "a/b.py" in _extract_files_from_text("build_history")

    @pytest.mark.parametrize("bad", [
        "",                       # 0 字节：上次写入被中断
        "{incomplete",            # 半截 JSON
        "[]",                     # 顶层不是对象
        '{"sym": "not-a-list"}',  # 值类型不对
        '{"sym": ["not-a-dict"]}',  # 元素类型不对
    ])
    def test_corrupted_index_degrades_silently(self, tmp_path, monkeypatch, caplog, bad):
        """索引损坏应只返回正则提取到的路径，不抛异常、不打 ERROR。"""
        import logging
        monkeypatch.chdir(tmp_path)
        self._make_index(tmp_path, bad)
        with caplog.at_level(logging.WARNING):
            from tea_agent.session.history_builder import _extract_files_from_text
            files = _extract_files_from_text("看看 build_history 和 a/b.py")
        assert "a/b.py" in files                 # 正则通路不受影响
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]

    def test_missing_index_is_fine(self, tmp_path, monkeypatch):
        """没有索引文件时正常工作（裸进程/新装环境）。"""
        monkeypatch.chdir(tmp_path)
        from tea_agent.session.history_builder import _extract_files_from_text
        assert "x/y.py" in _extract_files_from_text("参考 x/y.py 里的 build_history")


# ============================================================
# strip_historical_images — 历史轮图像剥离（400 回归）
# ============================================================

class TestStripHistoricalImages:
    """历史轮图像剥离：构造 API 历史的最后一步。

    回归场景：历史轮发送过图像后，images/_b64_cache/image_url 残留回传
    非视觉端点（或 cheap 摘要路径）→ API 400；且历史图会让
    messages_contain_images 持续命中，把后续纯文本轮锁死在 vision 模型。
    """

    @staticmethod
    def _msgs():
        return [
            {"role": "system", "content": "sp"},
            {"role": "user", "content": "看这张图",
             "images": ["/old.png"], "_b64_cache": {"/old.png": "xxxx"}},
            {"role": "assistant", "content": "图里是一只猫"},
            {"role": "user",
             "content": [{"type": "text", "text": "再看这张"},
                          {"type": "image_url",
                           "image_url": {"url": "data:image/png;base64,QQ=="}}]},
            {"role": "assistant",
             "content": [{"type": "text", "text": "回复"},
                          {"type": "image_url",
                           "image_url": {"url": "data:image/png;base64,QQ=="}}]},
            {"role": "user", "content": "当前轮纯文本追问"},
            {"role": "user", "content": "[动态上下文] 时间: 2026-09-23"},
        ]

    def test_strips_old_turns_keeps_current(self):
        from tea_agent.session.history_builder import strip_historical_images
        out = strip_historical_images(self._msgs())
        # 历史 user：images / _b64_cache 私有键被剥
        assert "images" not in out[1]
        assert "_b64_cache" not in out[1]
        # 历史 content=parts：image_url 段剥掉、文本归一为 str
        assert out[3]["content"] == "再看这张"
        assert out[4]["content"] == "回复"
        # 真实当前轮（尾部 [动态上下文 之前的最后一条真实 user）原样
        assert out[5]["content"] == "当前轮纯文本追问"
        # 尾部合成动态上下文不受影响（且不参与当前轮定位）
        assert out[6]["content"].startswith("[动态上下文")

    def test_current_turn_with_image_kept(self):
        """当前轮（最后一条真实 user）带图必须原样保留（交给视觉切换）。"""
        from tea_agent.session.history_builder import strip_historical_images
        msgs = self._msgs()
        msgs[5] = {"role": "user", "content": "看这张", "images": ["/new.png"]}
        out = strip_historical_images(msgs)
        assert out[5].get("images") == ["/new.png"]   # 当前轮保留
        assert "images" not in out[1]                  # 历史仍剥

    def test_idempotent(self):
        """幂等：重复剥离结果不变。"""
        import copy
        from tea_agent.session.history_builder import strip_historical_images
        once = strip_historical_images(self._msgs())
        snap = copy.deepcopy(once)
        assert strip_historical_images(once) == snap

    def test_no_real_user_returns_unchanged(self):
        """无真实 user 轮（仅 system/合成消息）→ 原样返回，不误剥。"""
        from tea_agent.session.history_builder import strip_historical_images
        msgs = [
            {"role": "system", "content": "sp"},
            {"role": "user", "content": "[动态上下文] x", "images": ["y"]},
        ]
        out = strip_historical_images(msgs)
        assert out[1].get("images") == ["y"]
