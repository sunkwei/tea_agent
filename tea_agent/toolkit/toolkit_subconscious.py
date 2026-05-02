## llm generated tool func, created Fri May  1 09:58:16 2026
# version: 1.0.4


def toolkit_subconscious(action: str, focus: str = None):
    import os, json, time, sqlite3, threading, random, re, subprocess
    from datetime import datetime
    from pathlib import Path
    from collections import Counter

    STATE_FILE = os.path.expanduser("~/.tea_agent/subconscious_state.json")
    KB_DIR = os.path.expanduser("~/.tea_agent/kb")
    DEFAULT_DB = "chat_history.db"
    CYCLE_INTERVAL = 3600      # 1小时
    CHECK_INTERVAL = 30        # 检查间隔

    _jieba = None
    try:
        import jieba
        import jieba.analyse
        jieba.setLogLevel(20)
        _jieba = jieba
    except ImportError:
        pass

    def _ensure_dir(path):
        os.makedirs(path, exist_ok=True)

    def _read_state():
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r') as f:
                    return json.load(f)
            except: pass
        return {"running":False,"pid":os.getpid(),"started_at":None,"last_cycle_at":None,
                "cycles_completed":0,"insights":[],"goals":[],"last_focus":"mixed",
                "stats":{"memories_digested":0,"conversations_digested":0,"insights_generated":0,"goals_set":0,"auto_memories":0}}

    def _write_state(state):
        _ensure_dir(os.path.dirname(STATE_FILE))
        state["_updated"] = datetime.now().isoformat()
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

    def _get_db_path():
        if os.path.exists(DEFAULT_DB):
            return os.path.abspath(DEFAULT_DB)
        for c in [os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","..","chat_history.db"),
                  os.path.expanduser(f"~/.tea_agent/{DEFAULT_DB}")]:
            if os.path.exists(c): return c
        return os.path.abspath(DEFAULT_DB)

    def _extract_keywords(text, topn=20):
        sw = {'the','and','for','with','this','that','from','have','are','was','has','been','not','but',
              '的','了','是','在','和','也','就','都','而','及','与','或','一个','可以','这个',
              '如果','因为','所以','但是','然后','之后','之前','已经','还是','没有','什么','怎么',
              '要','会','能','被','把','让','给','对','向','从','到','用','以','为','着','呢','吗','啊','吧','么'}
        if _jieba:
            try:
                kw = _jieba.analyse.extract_tags(text, topK=topn, withWeight=True)
                return [(w, round(s*100)) for w, s in kw if w not in sw and len(w)>=2]
            except: pass
        ch = re.findall(r'[\u4e00-\u9fff]{2,4}', text)
        en = re.findall(r'[a-zA-Z]{3,}', text.lower())
        c = Counter(ch+en)
        return [(w,n) for w,n in c.most_common(topn*2) if w.lower() not in sw and n>=2][:topn]

    def _is_jieba_available():
        return _jieba is not None

    # === 阶段1: 消化记忆 ===
    def _digest_memories(db_path):
        if not os.path.exists(db_path): return None
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM memories WHERE is_active=1 ORDER BY priority ASC, updated_at DESC LIMIT 200")
        mems = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT * FROM reflections WHERE is_applied=0 ORDER BY created_at DESC LIMIT 20")
        refs = [dict(r) for r in cur.fetchall()]
        conn.close()
        if not mems: return None
        r = {"total_memories":len(mems),"by_category":dict(Counter(m["category"] for m in mems)),
             "by_priority":dict(Counter(m["priority"] for m in mems)),
             "untagged":sum(1 for m in mems if not (m.get("tags") or "").strip()),
             "stale_memories":[],"top_keywords":[],"unapplied_reflections":len(refs),
             "jieba_available":_is_jieba_available()}
        now = datetime.now()
        for m in mems:
            last = m.get("last_accessed_at")
            if last:
                try:
                    ld = datetime.fromisoformat(str(last).replace("Z","+00:00").replace(" ","T")[:19])
                    if (now-ld).days>7: r["stale_memories"].append(str(m["content"])[:80])
                except: pass
        all_txt = " ".join(str(m["content"]) for m in mems if m.get("content"))
        r["top_keywords"] = _extract_keywords(all_txt, 20)
        # 场景检测
        r["focus"] = _detect_focus(mems, r["top_keywords"])
        return r

    # === 场景检测 ===
    def _detect_focus(mems, keywords):
        """自动检测当前场景是创意期还是修复期"""
        all_text = " ".join(str(m["content"]) for m in mems if m.get("content"))
        kw_str = " ".join(w for w,_ in keywords)

        # 修复期关键词
        bug_kw = ['bug','错误','修复','fix','问题','异常','crash','崩溃','超时','失败',
                   '不兼容','兼容','黑屏','报错','400','500','error','Exception','defect']
        # 创意期关键词
        creative_kw = ['创意','设计','架构','想象','如果','进化','改进','新增','feat',
                        '优化','增强','梦想','未来','可能','探索','实验']

        bug_score = sum(all_text.lower().count(kw.lower()) for kw in bug_kw)
        creative_score = sum(all_text.lower().count(kw.lower()) for kw in creative_kw)
        # 也检查关键词
        bug_score += sum(n for w,n in keywords if any(bk in w.lower() for bk in bug_kw))
        creative_score += sum(n for w,n in keywords if any(ck in w.lower() for ck in creative_kw))

        if bug_score > creative_score * 1.5:
            return "pragmatic"
        elif creative_score > bug_score * 1.5:
            return "creative"
        else:
            return "mixed"

    # === 阶段2: 消化对话 ===
    def _digest_conversations(db_path, state):
        if not os.path.exists(db_path): return {"processed":0,"extracted":[]}
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        last_id = state.get("last_conversation_id", 0)
        cur.execute(
            "SELECT id, topic_id, user_msg, ai_msg, stamp FROM conversations WHERE id > ? ORDER BY id ASC LIMIT 50",
            (last_id,)
        )
        convs = [dict(r) for r in cur.fetchall()]
        extracted = []
        max_id = last_id
        for conv in convs:
            max_id = max(max_id, conv["id"])
            user_msg = str(conv.get("user_msg",""))
            ai_msg = str(conv.get("ai_msg",""))
            candidates = _extract_memory_candidates(user_msg, ai_msg)
            for cand in candidates:
                if not _is_duplicate_memory(cur, cand["content"]):
                    try:
                        cur.execute(
                            "INSERT INTO memories (content, category, priority, importance, tags, source_topic_id) VALUES (?,?,?,?,?,?)",
                            (cand["content"], cand.get("category","general"),
                             cand.get("priority",3), cand.get("importance",2),
                             cand.get("tags","auto-extracted"), conv.get("topic_id"))
                        )
                        conn.commit()
                        extracted.append(cand["content"][:60])
                    except: pass
        conn.close()
        return {"processed":len(convs),"extracted":extracted,"last_id":max_id}

    def _extract_memory_candidates(user_msg, ai_msg):
        candidates = []
        text = user_msg
        for pat in [r'记住[：:]\s*(.+?)(?:[。！\n]|$)',
                     r'以后\s*(.+?)(?:[。！\n]|$)',
                     r'偏好[：:]\s*(.+?)(?:[。！\n]|$)']:
            m = re.search(pat, text)
            if m and len(m.group(1))>5:
                candidates.append({"content":m.group(1).strip(),"category":"preference","priority":1,"importance":4})
        for pat in [r'(?:总是|一直|经常)\s*(.+?)(?:[。！\n]|$)',
                     r'(?:不要|别|禁止)\s*(.+?)(?:[。！\n]|$)',
                     r'(?:必须|一定要)\s*(.+?)(?:[。！\n]|$)']:
            for m in re.finditer(pat, text):
                if len(m.group(1).strip())>5:
                    candidates.append({"content":m.group(1).strip(),"category":"instruction","priority":0,"importance":5})
        for pat in [r'(?:发现|注意到)\s*(.+?)(?:[。！\n]|$)',
                     r'问题[：:]\s*(.+?)(?:[。！\n]|$)']:
            m = re.search(pat, text)
            if m and len(m.group(1))>10:
                candidates.append({"content":m.group(1).strip(),"category":"fact","priority":2,"importance":3})
        tech_kw = ['工具','toolkit','agent','python','sqlite','截屏','ocr','self_evolve',
                    '记忆','memory','反思','reflection','配置','config','进化','evolve']
        for sent in re.split(r'[。！\n]', text):
            sent = sent.strip()
            if len(sent)>20 and any(kw in sent.lower() for kw in tech_kw):
                if not any(c["content"]==sent for c in candidates):
                    candidates.append({"content":sent,"category":"fact","priority":2,"importance":2})
        return candidates[:10]

    def _is_duplicate_memory(cur, content):
        cur.execute("SELECT content FROM memories WHERE is_active=1")
        for (existing,) in cur.fetchall():
            if existing and content:
                sa, sb = set(existing), set(content)
                if len(sa|sb)>0 and len(sa&sb)/len(sa|sb) > 0.6:
                    return True
        return False

    # === 阶段3: 交叉关联 ===
    def _cross_link(db_path, kb_dir, state):
        finds = []
        if not os.path.exists(db_path): return finds
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM reflections WHERE is_applied=0 ORDER BY created_at DESC LIMIT 10")
        refs = [dict(r) for r in cur.fetchall()]
        for ref in refs:
            sugs = ref.get("suggestions","[]")
            if isinstance(sugs,str):
                try: sugs = json.loads(sugs)
                except: sugs = []
            for s in (sugs if isinstance(sugs,list) else [])[:3]:
                finds.append({"type":"unapplied_suggestion","reflection_id":ref["id"],
                              "content":str(s)[:200],"created_at":str(ref.get("created_at",""))})
        cur.execute("SELECT * FROM config_history ORDER BY created_at DESC LIMIT 10")
        cfgs = [dict(r) for r in cur.fetchall()]
        if len(cfgs)>=5:
            finds.append({"type":"frequent_config_changes",
                          "content":f"最近有{len(cfgs)}次配置变更，建议回顾是否需要固化某些配置",
                          "detail":[f"{c['key']}={c['new_value']}" for c in cfgs[:5]]})
        conn.close()
        if os.path.exists(kb_dir):
            now = datetime.now()
            old = []
            for f in Path(kb_dir).glob("*.md"):
                days = (now - datetime.fromtimestamp(f.stat().st_mtime)).days
                if days>7: old.append((f.stem, days))
            if old:
                finds.append({"type":"stale_kb","content":f"{len(old)}个KB文档超过7天未更新",
                              "detail":[f"{n}({d}天)" for n,d in old[:5]]})
        return finds

    # === 阶段4: 洞察 ===
# NOTE: 2026-05-02 10:23:38, self-evolved by tea_agent --- 潜意识引擎在产生重要洞察时发送桌面通知
    def _generate_insights(digest, links, conv_digest, kb_dir, state):
        ins = []
        if not digest: return ins
        unapp = digest.get("unapplied_reflections",0)
        if unapp>=3:
            ins.append({"level":"important","content":f"有{unapp}条未应用的反思建议等待处理","action":"review_reflections"})
        elif unapp>0:
            ins.append({"level":"info","content":f"有{unapp}条未应用的反思建议","action":"review_reflections"})
        bycat = digest.get("by_category",{})
        if bycat.get("instruction",0) > bycat.get("fact",0)*2:
            ins.append({"level":"info","content":"指令级记忆多于事实记忆，可能存在过度约束","action":"rebalance_memories"})
        stale = digest.get("stale_memories",[])
        if len(stale)>=5:
            ins.append({"level":"info","content":f"有{len(stale)}条记忆超过7天未访问，建议清理","action":"cleanup_memories"})
        for lk in links:
            if lk["type"]=="stale_kb":
                ins.append({"level":"info","content":lk["content"],"action":"update_kb"})
        top = digest.get("top_keywords",[])[:5]
        if top:
            kw = ", ".join(f"{w}({n})" for w,n in top)
            ins.append({"level":"info","content":f"记忆高频主题: {kw} | 场景: {digest.get('focus','mixed')}","action":"deep_dive"})
        if conv_digest.get("extracted"):
            n = len(conv_digest["extracted"])
            ins.append({"level":"info","content":f"从{n}条新对话中自动提取了记忆","action":"review_auto_memories"})
        # NOTE: 2026-05-02, self-evolved by tea_agent --- 重要洞察主动发送桌面通知
        for insight in ins:
            if insight["level"] == "important":
                _send_notification("🧠 潜意识洞察", insight["content"][:80])
        if ins:
            _ensure_dir(kb_dir)
            fpath = os.path.join(kb_dir,"潜意识洞察.md")
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            txt = f"# 潜意识洞察\n\n> 更新: {ts} | 循环: {state.get('cycles_completed',0)} | 间隔: 1小时\n> 分词: {'jieba' if digest.get('jieba_available') else 'bigram'} | 场景: {digest.get('focus','mixed')}\n\n## 最新洞察\n\n"
            for i,insight in enumerate(ins[-10:],1):
                icon = {"important":"🔴","warning":"🟡","info":"🔵"}.get(insight["level"],"⚪")
                txt += f"{i}. {icon} **{insight['content']}**\n"
                if insight.get("action"): txt += f"   → 建议: `{insight['action']}`\n"
            txt += "\n---\n*由潜意识引擎自动生成*\n"
            with open(fpath,'w') as f: f.write(txt)
        return ins

    def _set_goals(digest, links, insights, conv_digest, state, db_path):
        goals = []
        unapp = digest.get("unapplied_reflections",0) if digest else 0
        if unapp>=3:
            goals.append({"priority":1,"goal":f"回顾并应用{unapp}条未处理的反思建议","action":"toolkit_reflection(action='list')"})
        for lk in links:
            if lk["type"]=="stale_kb":
                goals.append({"priority":2,"goal":"更新过期KB文档","action":"toolkit_kb(action='list')"})
        for ins in insights:
            if ins.get("action")=="cleanup_memories":
                goals.append({"priority":3,"goal":"清理超过7天未访问的记忆","action":"toolkit_memory(action='search')"})
            elif ins.get("action")=="review_auto_memories":
                goals.append({"priority":2,"goal":"审查自动提取的记忆","action":"toolkit_memory(action='list')"})
        goals.append({"priority":3,"goal":"运行自检: toolkit_self_report()","action":"toolkit_self_report()"})
        seen=set(); uniq=[]
        for g in sorted(goals,key=lambda x:x["priority"]):
            if g["goal"] not in seen: seen.add(g["goal"]); uniq.append(g)
        return uniq[:7]

# NOTE: 2026-05-02 10:58:26, self-evolved by tea_agent --- 添加 _send_cycle_summary 函数，每轮循环后发送综合摘要通知
    def _send_notification(title, msg):
        try:
            subprocess.run(["notify-send",title,msg,"--expire-time=5000"],capture_output=True,timeout=3)
        except: pass

    def _send_cycle_summary(result, state, first_run=False):
        """每轮循环后发送摘要通知，让用户感知后台运行结果"""
        digest = result.get("digest") or {}
        insights = result.get("insights") or []
        goals = result.get("goals") or []
        conv = result.get("conv_digest") or {}
        n_insights = len(insights)
        n_goals = len(goals)
        n_auto = len(conv.get("extracted", []))
        focus = digest.get("focus", "mixed") if digest else "mixed"
        mode_label = {"pragmatic":"🔧务实", "creative":"🎨创意", "mixed":"🔀混合"}.get(focus, focus)
        cycle_n = state.get("cycles_completed", 0)
        prefix = "首轮" if first_run else f"第{cycle_n}轮"

        lines = [f"🧠 潜意识 {prefix}完成 [{mode_label}]"]
        if digest:
            lines.append(f"记忆: {digest.get('total_memories',0)}条活跃")
            kw = digest.get("top_keywords", [])[:3]
            if kw:
                lines.append(f"主题: {', '.join(w for w,_ in kw)}")
        if n_auto:
            lines.append(f"新提取: {n_auto}条记忆")
        if n_insights:
            lines.append(f"洞察: {n_insights}条")
            # 列出 important 级洞察
            for ins in insights:
                if ins.get("level") == "important":
                    lines.append(f"  ⚠️ {ins['content'][:60]}")
        if n_goals:
            lines.append(f"目标: {n_goals}个待办")
        lines.append(f"📁 详情: ~/.tea_agent/kb/潜意识洞察.md")

        msg = "\n".join(lines)
        try:
            subprocess.run(["notify-send", "🧠 潜意识引擎", msg, "--expire-time=8000"],
                          capture_output=True, timeout=3)
        except:
            pass

    # === 执行一次完整循环 ===
    def _run_cycle(state):
        db_path = _get_db_path()
        kb_dir = KB_DIR
        digest = _digest_memories(db_path)
        conv_digest = _digest_conversations(db_path, state)
        links = _cross_link(db_path, kb_dir, state)
        insights = _generate_insights(digest, links, conv_digest, kb_dir, state)
        goals = _set_goals(digest, links, insights, conv_digest, state, db_path)
        state["last_cycle_at"] = datetime.now().isoformat()
        state["cycles_completed"] = state.get("cycles_completed", 0) + 1
        state["insights"] = [i["content"] for i in insights[-5:]]
        state["goals"] = [g["goal"] for g in goals[:7]]
        state["last_focus"] = digest.get("focus", "mixed") if digest else "mixed"
        if conv_digest.get("last_id", 0) > state.get("last_conversation_id", 0):
            state["last_conversation_id"] = conv_digest["last_id"]
        if digest:
            state["stats"]["memories_digested"] = state["stats"].get("memories_digested", 0) + digest["total_memories"]
        state["stats"]["conversations_digested"] = state["stats"].get("conversations_digested", 0) + conv_digest.get("processed", 0)
        state["stats"]["insights_generated"] = state["stats"].get("insights_generated", 0) + len(insights)
        state["stats"]["goals_set"] = state["stats"].get("goals_set", 0) + len(goals)
        state["stats"]["auto_memories"] = state["stats"].get("auto_memories", 0) + len(conv_digest.get("extracted", []))
        _write_state(state)
        return {"digest": digest, "insights": insights, "goals": goals, "conv_digest": conv_digest}

    def _subconscious_loop():
        state = _read_state()
        _ensure_dir(os.path.dirname(STATE_FILE))
        state["running"] = True
        state["pid"] = os.getpid()
        state["started_at"] = datetime.now().isoformat()
        _write_state(state)
        _send_notification("🧠 潜意识引擎 v2.1", "已启动！场景自适应：修bug收敛分析，做创意发散联想")

# NOTE: 2026-05-02 10:58:03, self-evolved by tea_agent --- 潜意识引擎每轮循环后始终发送桌面通知摘要（洞察数、目标数、自动记忆、场景模式）
        try:
            result = _run_cycle(state)
            _send_cycle_summary(result, state, first_run=True)
        except Exception as e:
            state = _read_state()
            state["_last_error"] = str(e)[:200]
            _write_state(state)

        checks_per_cycle = CYCLE_INTERVAL // CHECK_INTERVAL
        while True:
            for _ in range(checks_per_cycle):
                time.sleep(CHECK_INTERVAL)
                state = _read_state()
                if not state.get("running") or state.get("pid") != os.getpid():
                    state["running"] = False
                    _write_state(state)
                    return
            try:
                result = _run_cycle(state)
                _send_cycle_summary(result, state)
            except Exception as e:
                state = _read_state()
                state["_last_error"] = str(e)[:200]
                _write_state(state)

    # ========================
    # 强化 Dream：创意 + 务实双模式
    # ========================
    def _dream(focus_override=None):
        db_path = _get_db_path()
        kb_dir = KB_DIR
        if not os.path.exists(db_path): return {"error":"数据库不存在"}
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT content, category, tags FROM memories WHERE is_active=1 ORDER BY RANDOM() LIMIT 30")
        mems = [dict(r) for r in cur.fetchall()]
        conn.close()

        # 读取对话中最近的错误/bug信息
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT user_msg, ai_msg FROM conversations ORDER BY id DESC LIMIT 30")
        recent = [dict(r) for r in cur.fetchall()]
        conn.close()

        if len(mems) < 2: return {"dream":"记忆不足","sparks":[]}

        # 场景检测
        all_text = " ".join(str(m["content"]) for m in mems)
        keywords = _extract_keywords(all_text, 20) if all_text else []
        detected_focus = _detect_focus(mems, keywords)
        effective_focus = focus_override or detected_focus

        results = []

        # === 务实分析模式 ===
        if effective_focus in ("pragmatic", "mixed"):
            prag = _pragmatic_analysis(mems, recent, keywords)
            results.extend(prag)

        # === 创意发散模式 ===
        if effective_focus in ("creative", "mixed"):
            creative = _creative_dream(mems)
            results.extend(creative)

        # 确保至少有一些产出
        if not results:
            creative = _creative_dream(mems)
            results = creative

        random.shuffle(results)

        # 写入 KB
        _ensure_dir(kb_dir)
        fpath = os.path.join(kb_dir, "创意火花.md")
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        mode_label = {"pragmatic":"🔧 务实分析","creative":"🎨 创意发散","mixed":"🔀 混合模式"}.get(effective_focus, "🔀 混合")
        txt = f"# 💫 创意火花\n\n> 生成: {ts} | Dream v2.1 | 场景: {mode_label}\n> 修bug时收敛分析 · 做创意时发散联想\n\n"
        for i, s in enumerate(results[:12], 1):
            txt += f"## 火花 {i}: {s['mode']}\n\n**{s.get('combination', '')}**\n\n💡 {s.get('creative_prompt', '')}\n\n---\n"
        txt += "\n*由潜意识引擎 v2.1 自动生成 — 场景自适应*\n"
        with open(fpath, 'w') as f: f.write(txt)

        return {"dream":f"产生了{len(results)}个火花", "focus": effective_focus,
                "mode_label": mode_label, "sparks": results[:12], "saved_to": fpath}

    def _pragmatic_analysis(mems, recent_convs, keywords):
        """务实分析：模式识别、根因分析、修复建议"""
        sparks = []
        mem_texts = [str(m["content"]) for m in mems]

        # 1. 错误模式识别 — 从记忆和对话中找重复问题
        error_patterns = []
        error_kw = ['超时','timeout','失败','fail','错误','error','异常','exception',
                     '不兼容','incompatible','黑屏','黑','崩溃','crash','400','401','403','404','500',
                     '未找到','not found','None','null','undefined']
        for mt in mem_texts:
            for kw in error_kw:
                if kw.lower() in mt.lower():
                    error_patterns.append((kw, mt))
                    break

        # 统计重复出现的错误关键词
        err_counter = Counter(ep[0] for ep in error_patterns)
        if err_counter:
            top_errors = err_counter.most_common(3)
            err_list = ", ".join(f"{k}({v}次)" for k,v in top_errors)
            sparks.append({
                "mode": "🔧 错误模式",
                "combination": f"记忆中出现 {len(error_patterns)} 个问题信号",
                "creative_prompt": f"高频错误: {err_list}。建议逐一排查：① 检查是否有共同的底层原因 ② 优先修复出现次数最多的 ③ 考虑添加针对性的错误处理/重试机制"
            })

        # 2. 兼容性问题链
        compat_issues = [mt for mt in mem_texts if any(k in mt.lower() for k in ['wayland','x11','kde','gnome','兼容','compatible'])]
        if len(compat_issues) >= 2:
            sparks.append({
                "mode": "🔧 兼容性链",
                "combination": f"发现 {len(compat_issues)} 条环境兼容性相关记忆",
                "creative_prompt": f"这些兼容性问题可能共享同一个根因：环境检测不够全面。建议：创建统一的环境适配层（Adapter Pattern），集中管理平台差异，而不是在每个工具中各自处理。"
            })

        # 3. 工具依赖链分析
        tool_issues = [mt for mt in mem_texts if any(k in mt.lower() for k in ['toolkit','工具','安装','install','import','缺失','module'])]
        if tool_issues:
            sparks.append({
                "mode": "🔧 依赖分析",
                "combination": f"发现 {len(tool_issues)} 条工具/依赖相关记忆",
                "creative_prompt": f"建议运行 toolkit_pkg(action='ensure') 确保所有依赖就绪。考虑在启动时自动检查核心依赖，减少运行时发现缺失模块的绕路。"
            })

        # 4. 从最近对话中检测修复意向
        fix_intents = []
        for conv in recent_convs:
            user = str(conv.get("user_msg", ""))
            if any(k in user.lower() for k in ['修复','fix','修','改','bug','问题','错误']):
                fix_intents.append(user[:80])
        if fix_intents:
            sparks.append({
                "mode": "🔧 修复意向",
                "combination": f"最近对话中有 {len(fix_intents)} 条修复意图",
                "creative_prompt": f"待修复问题预览: {'; '.join(fix_intents[:3])}。建议将这些修复任务添加到记忆系统并标记优先级。"
            })

        # 5. 建议：当前最值得做的事
        priorities = []
        if err_counter:
            priorities.append(f"修复高频错误: {err_counter.most_common(1)[0][0]}")
        if compat_issues:
            priorities.append("创建统一环境适配层")
        if len(mems) > 10:
            priorities.append("清理冗余/过期记忆")
        if priorities:
            sparks.append({
                "mode": "🔧 优先级建议",
                "combination": "基于记忆分析的行动建议",
                "creative_prompt": " → ".join([f"① {p}" for p in priorities[:3]])
            })

        return sparks

    def _creative_dream(mems):
        """创意发散：跨域碰撞、反向思维、极端假设、隐喻映射"""
        random.shuffle(mems)
        sparks = []

        for i in range(0, len(mems)-1, 2):
            a, b = mems[i], mems[i+1]
            if a["category"] != b["category"]:
                sparks.append({
                    "mode": "🌐 跨域碰撞",
                    "combination": f"「{str(a['content'])[:50]}...」 × 「{str(b['content'])[:50]}...」",
                    "categories": f"{a['category']} × {b['category']}",
                    "creative_prompt": f"如果将'{str(a['content'])[:40]}'的思想应用到'{str(b['content'])[:40]}'领域会怎样？"
                })

        for m in mems[:4]:
            rev = _reverse_thinking(str(m["content"]))
            if rev:
                sparks.append({"mode":"🔄 反向思维", "combination": f"原始: 「{str(m['content'])[:60]}...」",
                               "categories": m['category'], "creative_prompt": rev})

        for m in mems[4:8]:
            ext = _extreme_scenario(str(m["content"]))
            if ext:
                sparks.append({"mode":"🔬 极端假设", "combination": f"原始: 「{str(m['content'])[:60]}...」",
                               "categories": m['category'], "creative_prompt": ext})

        domains = ["生物学/生态系统","物理学/量子力学","建筑学/城市设计","音乐/作曲","烹饪/美食",
                    "游戏设计","军事战略","心理学/认知科学","经济学/市场","天文学/宇宙"]
        for i, m in enumerate(mems[:4]):
            domain = domains[i % len(domains)]
            sparks.append({
                "mode": "🎭 隐喻映射",
                "combination": f"「{str(m['content'])[:60]}...」 → {domain}",
                "categories": m['category'],
                "creative_prompt": f"如果把'{str(m['content'])[:40]}'比作{domain}中的现象，会有什么惊人的洞察？"
            })

        return sparks

    def _reverse_thinking(text):
        reversals = [("删除","创建"),("启动","停止"),("增加","减少"),("加速","减慢"),
                     ("自动","手动"),("集中","分散"),("保存","丢弃"),("优化","简化"),
                     ("记住","遗忘"),("优先","延后"),("公开","隐藏"),("永久","临时")]
        for a,b in reversals:
            if a in text:
                return f"反过来想：如果'{text[:50]}'被反转，即'{b}'而不是'{a}'，系统会变成什么样？"
            if b in text:
                return f"反过来想：如果'{text[:50]}'被反转，即'{a}'而不是'{b}'，系统会变成什么样？"
        return f"如果完全忽略'{text[:40]}'这个约束，会释放什么新的可能性？"

    def _extreme_scenario(text):
        scenarios = [
            f"假设'{text[:40]}'放大100倍——如果有100倍的数据量/规模/频率，会发生什么？",
            f"假设'{text[:40]}'完全归零——如果这个条件突然消失，系统如何应对？",
            f"假设'{text[:40]}'在极端环境下运行——没有网络、没有内存、没有用户输入，还能工作吗？",
            f"假设'{text[:40]}'是唯一的约束——如果所有其他规则都删除，只保留这一个，系统会怎样简化？",
        ]
        return random.choice(scenarios)

    # === 主逻辑 ===
    state = _read_state()

    if action == "start":
        if state.get("running") and state.get("pid") == os.getpid():
            return {"status":"already_running","started_at":state.get("started_at"),
                    "cycles_completed":state.get("cycles_completed",0)}
        if state.get("running") and state.get("pid") != os.getpid():
            state["running"]=False; _write_state(state)
        t = threading.Thread(target=_subconscious_loop, daemon=True)
        t.start()
        time.sleep(0.5)
        state = _read_state()
        return {"status":"started","pid":os.getpid(),"started_at":state.get("started_at"),
                "version":"v2.1","cycle_interval":"1小时","first_run_immediate":True,
                "adaptive_focus":True,
                "message":"🧠 潜意识引擎 v2.1 — 场景自适应 Dream。修bug→收敛分析，做创意→发散联想"}

    elif action == "stop":
        state["running"]=False; state["stopped_at"]=datetime.now().isoformat()
        _write_state(state)
        return {"status":"stopped","cycles_completed":state.get("cycles_completed",0)}

    elif action == "status":
        running = state.get("running") and state.get("pid")==os.getpid()
        return {"running":running,"pid":state.get("pid"),"started_at":state.get("started_at"),
                "last_cycle_at":state.get("last_cycle_at"),"cycles_completed":state.get("cycles_completed",0),
                "cycle_interval":"1小时","last_focus":state.get("last_focus","mixed"),
                "stats":state.get("stats",{}),"goals_count":len(state.get("goals",[])),
                "insights_count":len(state.get("insights",[])),"jieba":_is_jieba_available(),
                "last_conversation_id":state.get("last_conversation_id",0)}

    elif action == "dream":
        result = _run_cycle(state)
        dream_result = _dream(focus_override=focus)
        state = _read_state()
        state["insights"]=[i["content"] for i in result["insights"][-5:]]
        state["goals"]=[g["goal"] for g in result["goals"][:7]]
        state["last_dream_at"]=datetime.now().isoformat()
        _write_state(state)
        return {"digest":{"total_memories":result["digest"]["total_memories"] if result["digest"] else 0,
                          "focus":result["digest"].get("focus","mixed") if result["digest"] else "mixed"},
                "conversations":{"processed":result["conv_digest"].get("processed",0),
                                 "auto_extracted":len(result["conv_digest"].get("extracted",[]))},
                "insights":[i["content"] for i in result["insights"]],
                "goals":[g["goal"] for g in result["goals"][:5]],
                "dream":dream_result}

    elif action == "goals":
        return {"goals":state.get("goals",[]),"last_updated":state.get("last_cycle_at"),
                "total_cycles":state.get("cycles_completed",0)}

    elif action == "insights":
        return {"insights":state.get("insights",[]),"last_updated":state.get("last_cycle_at"),
                "focus":state.get("last_focus","mixed"),
                "kb_file":os.path.join(KB_DIR,"潜意识洞察.md")}

    else:
        return {"error":f"未知action: {action}","supported":["start","stop","status","dream","goals","insights"],
                "dream_focus":"dream支持focus参数: pragmatic(务实)/creative(创意)/mixed(混合)"}


def meta_toolkit_subconscious() -> dict:
    return {"type": "function", "function": {"name": "toolkit_subconscious", "description": "潜意识引擎 v2.1 — 场景自适应Dream。自动检测场景（修bug→收敛务实分析/做创意→发散联想），dream支持focus参数手动指定。start启动后每1小时循环。", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["start", "stop", "status", "dream", "goals", "insights"], "description": "start=启动, stop=停止, status=状态, dream=深度消化(支持focus参数: pragmatic/creative/mixed), goals=目标, insights=洞察"}, "focus": {"type": "string", "enum": ["pragmatic", "creative", "mixed"], "description": "[dream] 手动指定Dream模式: pragmatic=务实分析(bug模式识别/根因分析), creative=创意发散(跨域/反向/极端/隐喻), mixed=混合(自动)"}}, "required": ["action"]}}}
