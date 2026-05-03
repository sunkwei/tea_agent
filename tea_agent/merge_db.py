#!/usr/bin/env python3
"""
合并两个 chat_history.db 数据库。

用法:
    python merge_db.py <target_db> <source_db>

行为:
    target_db: 目标数据库，保留其所有 topic_id 不变
    source_db: 源数据库，内容合并到 target_db：
        - topics: 分配新 topic_id（从 target 最大 ID + 1 开始）
        - conversations / agent_rounds: 级联映射新 ID
        - topic_token_stats / t_conv_summary: 按新 topic_id 插入
        - memories: 去重合并（基于 Jaccard 关键词相似度），映射 source_topic_id
        - system_prompts: 追加为新版本（跳过完全重复内容）
        - reflections / config_history: 映射 topic_id 后追加
        - _meta: 仅插入 target 中不存在的 key（保留 target 的 week_key）
"""

import sqlite3
import sys
import os
import re
import logging
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("merge_db")


# ============================================================
# 工具函数
# ============================================================

def _extract_keywords(text: str) -> set:
    """从文本中提取关键词（与 memory.py 一致的 jieba/降级策略）"""
    keywords = set()
    try:
        import jieba
        words = jieba.lcut(text)
        for w in words:
            w = w.strip()
            if len(w) >= 2 and not w.isspace():
                keywords.add(w)
    except ImportError:
        chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
        for i in range(len(chinese_chars) - 1):
            keywords.add(chinese_chars[i] + chinese_chars[i + 1])
    english = re.findall(r'[a-zA-Z]{3,}', text)
    keywords.update(w.lower() for w in english)
    return keywords


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """计算两段文本的关键词 Jaccard 相似度 (0~1)"""
    if not text_a or not text_b:
        return 0.0
    kw_a = _extract_keywords(text_a.lower())
    kw_b = _extract_keywords(text_b.lower())
    if not kw_a or not kw_b:
        set_a = set(text_a)
        set_b = set(text_b)
        if not set_a or not set_b:
            return 0.0
        return len(set_a & set_b) / len(set_a | set_b)
    return len(kw_a & kw_b) / len(kw_a | kw_b)


# ============================================================
# 核心合并逻辑
# ============================================================

class DbMerger:
    def __init__(self, target_path: str, source_path: str, dedup_threshold: float = 0.35):
        self.target_path = target_path
        self.source_path = source_path
        self.dedup_threshold = dedup_threshold

        # ID 映射表
        self.topic_map: Dict[int, int] = {}        # old_topic_id → new_topic_id
        self.conv_map: Dict[int, int] = {}          # old_conv_id → new_conv_id

        # 连接
        self.target = sqlite3.connect(target_path)
        self.source = sqlite3.connect(source_path)

    # ------------------------------------------------------------------
    # 步骤 0: 预检 & 最大 ID 收集
    # ------------------------------------------------------------------

    def _get_max_ids(self, conn: sqlite3.Connection) -> Dict[str, int]:
        """获取各表当前最大 ID"""
        max_ids = {}
        for table, col in [
            ("topics", "topic_id"),
            ("conversations", "id"),
            ("agent_rounds", "id"),
            ("memories", "id"),
            ("system_prompts", "id"),
            ("reflections", "id"),
            ("config_history", "id"),
        ]:
            try:
                cur = conn.execute(f"SELECT COALESCE(MAX({col}), 0) FROM {table}")
                max_ids[table] = cur.fetchone()[0]
            except sqlite3.OperationalError:
                max_ids[table] = 0
        return max_ids

    def _get_table_columns(self, conn: sqlite3.Connection, table: str) -> List[str]:
        """获取表的所有列名"""
        cur = conn.execute(f"PRAGMA table_info({table})")
        return [row[1] for row in cur.fetchall()]

    # ------------------------------------------------------------------
    # 步骤 1: 合并 _meta
    # ------------------------------------------------------------------

    def _merge_meta(self):
        """合并 _meta 表：仅插入 target 不存在的 key"""
        logger.info("  合并 _meta ...")
        try:
            src_meta = self.source.execute("SELECT key, value FROM _meta").fetchall()
        except sqlite3.OperationalError:
            logger.info("    source 无 _meta 表，跳过")
            return

        existing = {row[0] for row in self.target.execute("SELECT key FROM _meta").fetchall()}
        inserted = 0
        for key, value in src_meta:
            if key not in existing:
                self.target.execute("INSERT INTO _meta (key, value) VALUES (?, ?)", (key, value))
                inserted += 1
                existing.add(key)
        self.target.commit()
        logger.info(f"    _meta: 新增 {inserted} 条 (跳过 {len(src_meta) - inserted} 条已存在)")

    # ------------------------------------------------------------------
    # 步骤 2: 合并 topics
    # ------------------------------------------------------------------

    def _merge_topics(self, next_topic_id: int):
        """将 source 的 topics 全部插入 target，分配新 topic_id"""
        logger.info("  合并 topics ...")
        src_topics = self.source.execute(
            "SELECT topic_id, title, create_stamp, last_update_stamp FROM topics ORDER BY topic_id"
        ).fetchall()

        if not src_topics:
            logger.info("    source 无 topics，跳过")
            return

        for old_id, title, create_stamp, last_update_stamp in src_topics:
            new_id = next_topic_id
            self.topic_map[old_id] = new_id
            self.target.execute(
                "INSERT INTO topics (topic_id, title, create_stamp, last_update_stamp) VALUES (?, ?, ?, ?)",
                (new_id, title, create_stamp, last_update_stamp),
            )
            next_topic_id += 1

        self.target.commit()
        logger.info(f"    topics: 合并 {len(src_topics)} 条, ID 映射 {min(self.topic_map.keys())}→{min(self.topic_map.values())} ... {max(self.topic_map.keys())}→{max(self.topic_map.values())}")

    # ------------------------------------------------------------------
    # 步骤 3: 合并 conversations
    # ------------------------------------------------------------------

    def _merge_conversations(self, next_conv_id: int):
        """合并 conversations，映射 topic_id → 新 topic_id"""
        logger.info("  合并 conversations ...")
        cols = self._get_table_columns(self.source, "conversations")

        src_convs = self.source.execute(
            f"SELECT {', '.join(cols)} FROM conversations ORDER BY id"
        ).fetchall()

        if not src_convs:
            logger.info("    source 无 conversations，跳过")
            return

        col_idx = {name: i for i, name in enumerate(cols)}
        for row in src_convs:
            old_conv_id = row[col_idx["id"]]
            old_topic_id = row[col_idx["topic_id"]]
            new_topic_id = self.topic_map.get(old_topic_id)
            if new_topic_id is None:
                logger.warning(f"    跳过 conversation {old_conv_id}: topic_id={old_topic_id} 无映射")
                continue

            new_conv_id = next_conv_id
            self.conv_map[old_conv_id] = new_conv_id

            # 构建插入数据
            values = list(row)
            values[col_idx["id"]] = new_conv_id
            values[col_idx["topic_id"]] = new_topic_id

            placeholders = ", ".join("?" for _ in cols)
            self.target.execute(
                f"INSERT INTO conversations ({', '.join(cols)}) VALUES ({placeholders})",
                values,
            )
            next_conv_id += 1

        self.target.commit()
        logger.info(f"    conversations: 合并 {len(self.conv_map)} 条")

    # ------------------------------------------------------------------
    # 步骤 4: 合并 agent_rounds
    # ------------------------------------------------------------------

    def _merge_agent_rounds(self, next_round_id: int):
        """合并 agent_rounds，映射 conversation_id"""
        logger.info("  合并 agent_rounds ...")
        cols = self._get_table_columns(self.source, "agent_rounds")

        src_rounds = self.source.execute(
            f"SELECT {', '.join(cols)} FROM agent_rounds ORDER BY id"
        ).fetchall()

        if not src_rounds:
            logger.info("    source 无 agent_rounds，跳过")
            return

        col_idx = {name: i for i, name in enumerate(cols)}
        count = 0
        for row in src_rounds:
            old_conv_id = row[col_idx["conversation_id"]]
            new_conv_id = self.conv_map.get(old_conv_id)
            if new_conv_id is None:
                continue  # conversation 已被跳过

            values = list(row)
            values[col_idx["id"]] = next_round_id
            values[col_idx["conversation_id"]] = new_conv_id

            placeholders = ", ".join("?" for _ in cols)
            self.target.execute(
                f"INSERT INTO agent_rounds ({', '.join(cols)}) VALUES ({placeholders})",
                values,
            )
            next_round_id += 1
            count += 1

        self.target.commit()
        logger.info(f"    agent_rounds: 合并 {count} 条")

    # ------------------------------------------------------------------
    # 步骤 5: 合并 topic_token_stats
    # ------------------------------------------------------------------

    def _merge_topic_token_stats(self):
        """合并 topic_token_stats，映射 topic_id（不存在才插入，避免冲突）"""
        logger.info("  合并 topic_token_stats ...")
        try:
            cols = self._get_table_columns(self.source, "topic_token_stats")
            src_stats = self.source.execute(
                f"SELECT {', '.join(cols)} FROM topic_token_stats"
            ).fetchall()
        except sqlite3.OperationalError:
            logger.info("    source 无 topic_token_stats 表，跳过")
            return

        if not src_stats:
            return

        col_idx = {name: i for i, name in enumerate(cols)}
        target_tids = {row[0] for row in self.target.execute("SELECT topic_id FROM topic_token_stats").fetchall()}
        merged = 0
        for row in src_stats:
            old_topic_id = row[col_idx["topic_id"]]
            new_topic_id = self.topic_map.get(old_topic_id)
            if new_topic_id is None:
                continue

            values = list(row)
            values[col_idx["topic_id"]] = new_topic_id

            if new_topic_id in target_tids:
                # 已存在 → 累加 token 统计
                self._accumulate_token_stats(new_topic_id, row, col_idx)
            else:
                placeholders = ", ".join("?" for _ in cols)
                self.target.execute(
                    f"INSERT INTO topic_token_stats ({', '.join(cols)}) VALUES ({placeholders})",
                    values,
                )
                target_tids.add(new_topic_id)
            merged += 1

        self.target.commit()
        logger.info(f"    topic_token_stats: 合并 {merged} 条")

    def _accumulate_token_stats(self, topic_id: int, src_row: tuple, col_idx: dict):
        """将 source 的 token 统计累加到 target 已有记录"""
        token_fields = [
            "total_tokens", "total_prompt_tokens", "total_completion_tokens",
            "total_cheap_tokens", "total_cheap_prompt_tokens", "total_cheap_completion_tokens",
        ]
        set_clauses = []
        values = []
        for field in token_fields:
            if field in col_idx:
                val = src_row[col_idx[field]] or 0
                if val > 0:
                    set_clauses.append(f"{field} = {field} + ?")
                    values.append(val)
        if "conversation_count" in col_idx:
            val = src_row[col_idx["conversation_count"]] or 0
            set_clauses.append("conversation_count = conversation_count + ?")
            values.append(val)
        set_clauses.append("last_update = CURRENT_TIMESTAMP")
        if set_clauses:
            self.target.execute(
                f"UPDATE topic_token_stats SET {', '.join(set_clauses)} WHERE topic_id = ?",
                values + [topic_id],
            )

    # ------------------------------------------------------------------
    # 步骤 6: 合并 t_conv_summary
    # ------------------------------------------------------------------

    def _merge_t_conv_summary(self):
        """合并 t_conv_summary，映射 topic_id"""
        logger.info("  合并 t_conv_summary ...")
        try:
            cols = self._get_table_columns(self.source, "t_conv_summary")
            src_summaries = self.source.execute(
                f"SELECT {', '.join(cols)} FROM t_conv_summary"
            ).fetchall()
        except sqlite3.OperationalError:
            logger.info("    source 无 t_conv_summary 表，跳过")
            return

        if not src_summaries:
            return

        col_idx = {name: i for i, name in enumerate(cols)}
        existing = {row[0] for row in self.target.execute("SELECT topic_id FROM t_conv_summary").fetchall()}
        inserted = 0
        for row in src_summaries:
            old_topic_id = row[col_idx["topic_id"]]
            new_topic_id = self.topic_map.get(old_topic_id)
            if new_topic_id is None or new_topic_id in existing:
                continue

            values = list(row)
            values[col_idx["topic_id"]] = new_topic_id
            placeholders = ", ".join("?" for _ in cols)
            self.target.execute(
                f"INSERT INTO t_conv_summary ({', '.join(cols)}) VALUES ({placeholders})",
                values,
            )
            existing.add(new_topic_id)
            inserted += 1

        self.target.commit()
        logger.info(f"    t_conv_summary: 合并 {inserted} 条")

    # ------------------------------------------------------------------
    # 步骤 7: 合并 memories（带去重）
    # ------------------------------------------------------------------

    def _merge_memories(self, next_mem_id: int):
        """合并 memories，去重 + 映射 source_topic_id"""
        logger.info("  合并 memories (带去重, threshold=%.2f) ...", self.dedup_threshold)
        try:
            cols = self._get_table_columns(self.source, "memories")
            src_memories = self.source.execute(
                f"SELECT {', '.join(cols)} FROM memories WHERE is_active = 1 ORDER BY id"
            ).fetchall()
        except sqlite3.OperationalError:
            logger.info("    source 无 memories 表，跳过")
            return

        if not src_memories:
            return

        col_idx = {name: i for i, name in enumerate(cols)}

        # 加载 target 已有活跃记忆用于去重比对
        target_memories = self.target.execute(
            "SELECT id, content, category, priority, importance, tags, expires_at FROM memories WHERE is_active = 1"
        ).fetchall()

        new_count = 0
        merged_count = 0
        skipped_count = 0

        for src_row in src_memories:
            src_content = src_row[col_idx["content"]] or ""
            src_category = src_row[col_idx["category"]] or "general"

            if not src_content.strip():
                skipped_count += 1
                continue

            # 去重检测
            dup = self._find_duplicate(src_content, src_category, target_memories)
            if dup:
                self._merge_memory_record(dup, src_row, col_idx)
                merged_count += 1
            else:
                values = list(src_row)
                values[col_idx["id"]] = next_mem_id
                # 映射 source_topic_id
                if "source_topic_id" in col_idx:
                    old_stid = values[col_idx["source_topic_id"]]
                    if old_stid is not None:
                        values[col_idx["source_topic_id"]] = self.topic_map.get(old_stid, old_stid)

                placeholders = ", ".join("?" for _ in cols)
                self.target.execute(
                    f"INSERT INTO memories ({', '.join(cols)}) VALUES ({placeholders})",
                    values,
                )
                # 同时更新内存中的列表用于后续去重
                new_dict = dict(zip(cols, values))
                target_memories.append((
                    next_mem_id,
                    new_dict.get("content", ""),
                    new_dict.get("category", "general"),
                    new_dict.get("priority", 2),
                    new_dict.get("importance", 3),
                    new_dict.get("tags", ""),
                    new_dict.get("expires_at", None),
                ))
                next_mem_id += 1
                new_count += 1

        self.target.commit()
        logger.info(f"    memories: 新增 {new_count}, 合并更新 {merged_count}, 跳过 {skipped_count}")

    def _find_duplicate(self, content: str, category: str, existing: List[tuple]) -> Optional[tuple]:
        """在已有记忆中查找相似度超过阈值的记忆"""
        best = None
        best_score = 0.0
        for mem in existing:
            mem_content = mem[1]  # content
            mem_category = mem[2]  # category
            score = _jaccard_similarity(content, mem_content)
            if category and mem_category == category:
                score *= 1.1
            if score > best_score:
                best_score = score
                best = mem
        if best and best_score >= self.dedup_threshold:
            logger.info(f"      去重命中 #{best[0]}: sim={best_score:.2f} \"{content[:60]}...\"")
            return best
        return None

    def _merge_memory_record(self, existing: tuple, src_row: tuple, col_idx: dict):
        """合并 source memory 到 target 已有记录"""
        mem_id = existing[0]
        old_priority = existing[3] or 2
        old_importance = existing[4] or 3
        old_tags = set((existing[5] or "").split(",")) if existing[5] else set()
        old_expires = existing[6]

        new_priority = src_row[col_idx["priority"]] if "priority" in col_idx else 2
        new_importance = src_row[col_idx["importance"]] if "importance" in col_idx else 3
        new_tags_str = src_row[col_idx["tags"]] if "tags" in col_idx else ""
        new_expires = src_row[col_idx["expires_at"]] if "expires_at" in col_idx else None

        # 合并后取更关键的值
        merged_priority = min(old_priority, new_priority or 2)
        merged_importance = max(old_importance, new_importance or 3)
        new_tag_set = {t.strip() for t in (new_tags_str or "").split(",") if t.strip()}
        merged_tags = ", ".join(sorted(old_tags | new_tag_set))

        # 过期时间取更早
        merged_expires = old_expires
        if old_expires and new_expires:
            merged_expires = min(str(old_expires), str(new_expires))
        elif new_expires:
            merged_expires = new_expires

        self.target.execute(
            """UPDATE memories SET priority = ?, importance = ?, tags = ?, expires_at = ?,
               updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (merged_priority, merged_importance, merged_tags, merged_expires, mem_id),
        )

    # ------------------------------------------------------------------
    # 步骤 8: 合并 system_prompts
    # ------------------------------------------------------------------

    def _merge_system_prompts(self):
        """合并 system_prompts：跳过内容完全相同的，其余追加为新版本"""
        logger.info("  合并 system_prompts ...")
        try:
            cols = self._get_table_columns(self.source, "system_prompts")
            src_prompts = self.source.execute(
                f"SELECT {', '.join(cols)} FROM system_prompts ORDER BY id"
            ).fetchall()
        except sqlite3.OperationalError:
            logger.info("    source 无 system_prompts 表，跳过")
            return

        if not src_prompts:
            return

        col_idx = {name: i for i, name in enumerate(cols)}

        # 获取 target 已有内容用于去重
        existing_contents = {
            row[0] for row in
            self.target.execute("SELECT content FROM system_prompts").fetchall()
        }

        # 获取 target 最大 version
        max_ver_row = self.target.execute(
            "SELECT MAX(CAST(version AS INTEGER)) FROM system_prompts"
        ).fetchone()
        max_ver = max_ver_row[0] or 0

        inserted = 0
        skipped = 0
        for row in src_prompts:
            content = row[col_idx["content"]] if "content" in col_idx else ""
            if content in existing_contents:
                skipped += 1
                continue

            max_ver += 1
            values = list(row)
            if "id" in col_idx:
                values[col_idx["id"]] = None  # 自动分配
            if "version" in col_idx:
                values[col_idx["version"]] = str(max_ver)
            if "is_active" in col_idx:
                values[col_idx["is_active"]] = 0  # 合并来的默认为非活跃

            placeholders = ", ".join("?" for _ in cols)
            self.target.execute(
                f"INSERT INTO system_prompts ({', '.join(cols)}) VALUES ({placeholders})",
                values,
            )
            existing_contents.add(content)
            inserted += 1

        self.target.commit()
        logger.info(f"    system_prompts: 新增 {inserted}, 跳过重复 {skipped}")

    # ------------------------------------------------------------------
    # 步骤 9: 合并 reflections
    # ------------------------------------------------------------------

    def _merge_reflections(self, next_ref_id: int):
        """合并 reflections，映射 topic_id"""
        logger.info("  合并 reflections ...")
        try:
            cols = self._get_table_columns(self.source, "reflections")
            src_refs = self.source.execute(
                f"SELECT {', '.join(cols)} FROM reflections ORDER BY id"
            ).fetchall()
        except sqlite3.OperationalError:
            logger.info("    source 无 reflections 表，跳过")
            return

        if not src_refs:
            return

        col_idx = {name: i for i, name in enumerate(cols)}
        count = 0
        for row in src_refs:
            values = list(row)
            values[col_idx["id"]] = next_ref_id

            if "topic_id" in col_idx:
                old_tid = values[col_idx["topic_id"]]
                if old_tid is not None:
                    values[col_idx["topic_id"]] = self.topic_map.get(old_tid, old_tid)

            placeholders = ", ".join("?" for _ in cols)
            self.target.execute(
                f"INSERT INTO reflections ({', '.join(cols)}) VALUES ({placeholders})",
                values,
            )
            next_ref_id += 1
            count += 1

        self.target.commit()
        logger.info(f"    reflections: 合并 {count} 条")

    # ------------------------------------------------------------------
    # 步骤 10: 合并 config_history
    # ------------------------------------------------------------------

    def _merge_config_history(self, next_cfg_id: int):
        """合并 config_history（无外键，直接追加）"""
        logger.info("  合并 config_history ...")
        try:
            cols = self._get_table_columns(self.source, "config_history")
            src_cfgs = self.source.execute(
                f"SELECT {', '.join(cols)} FROM config_history ORDER BY id"
            ).fetchall()
        except sqlite3.OperationalError:
            logger.info("    source 无 config_history 表，跳过")
            return

        if not src_cfgs:
            return

        col_idx = {name: i for i, name in enumerate(cols)}
        count = 0
        for row in src_cfgs:
            values = list(row)
            values[col_idx["id"]] = next_cfg_id
            placeholders = ", ".join("?" for _ in cols)
            self.target.execute(
                f"INSERT INTO config_history ({', '.join(cols)}) VALUES ({placeholders})",
                values,
            )
            next_cfg_id += 1
            count += 1

        self.target.commit()
        logger.info(f"    config_history: 合并 {count} 条")

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------

    def merge(self):
        """执行完整合并流程"""
        logger.info("=" * 60)
        logger.info(f"合并数据库: {self.source_path} → {self.target_path}")
        logger.info("=" * 60)

        # 预检
        max_target = self._get_max_ids(self.target)
        max_source = self._get_max_ids(self.source)
        logger.info(f"  target 最大 ID: {max_target}")
        logger.info(f"  source 最大 ID: {max_source}")

        # 按依赖顺序执行
        self._merge_meta()
        self._merge_topics(next_topic_id=max_target["topics"] + 1)
        self._merge_conversations(next_conv_id=max_target["conversations"] + 1)
        self._merge_agent_rounds(next_round_id=max_target["agent_rounds"] + 1)
        self._merge_topic_token_stats()
        self._merge_t_conv_summary()
        self._merge_memories(next_mem_id=max_target["memories"] + 1)
        self._merge_system_prompts()
        self._merge_reflections(next_ref_id=max_target["reflections"] + 1)
        self._merge_config_history(next_cfg_id=max_target["config_history"] + 1)

        logger.info("=" * 60)
        logger.info("合并完成！")
        logger.info(f"  topics: {len(self.topic_map)} 条映射")
        logger.info(f"  conversations: {len(self.conv_map)} 条映射")
        logger.info("=" * 60)

    def close(self):
        self.target.close()
        self.source.close()


# ============================================================
# CLI 入口
# ============================================================

def main():
    if len(sys.argv) < 3:
        print(__doc__)
        print("示例: python merge_db.py chat_history.db old_backup.db")
        sys.exit(1)

    target_path = sys.argv[1]
    source_path = sys.argv[2]

    if not os.path.exists(target_path):
        logger.error(f"目标数据库不存在: {target_path}")
        sys.exit(1)
    if not os.path.exists(source_path):
        logger.error(f"源数据库不存在: {source_path}")
        sys.exit(1)

    # 可选: dedup threshold
    threshold = 0.35
    if len(sys.argv) >= 4:
        try:
            threshold = float(sys.argv[3])
        except ValueError:
            logger.warning(f"无效的 threshold 参数 '{sys.argv[3]}'，使用默认值 0.35")

    # 自动备份 target
    backup_path = target_path + ".bak_before_merge"
    import shutil
    shutil.copy2(target_path, backup_path)
    logger.info(f"已备份目标数据库: {backup_path}")

    merger = DbMerger(target_path, source_path, dedup_threshold=threshold)
    try:
        merger.merge()
    except Exception as e:
        logger.exception(f"合并失败: {e}")
        logger.info(f"目标数据库已自动备份到 {backup_path}，可手动恢复")
        sys.exit(1)
    finally:
        merger.close()


if __name__ == "__main__":
    main()
