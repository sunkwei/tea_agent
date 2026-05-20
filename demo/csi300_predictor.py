#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-05-20 gen by Claude, CSI300 predictor
基于新华网新闻预测沪深300日内走势（策略型分类器）

核心思路:
  1. 从日内每10分钟数据中提取5个关键转折点，二次曲线拟合捕捉走势形态
  2. 将每日 9:00 新闻做向量化（embedding API 或 TF-IDF 回退）
  3. 训练: 存储 (日期, 新闻向量, 曲线参数, 实际涨跌标签)
  4. 预测: KNN + 余弦相似度加权投票 -> 涨/平/跌 概率 + 二次曲线形态
  5. 回测: 对比预测与真实结果，输出准确率报告

标签定义:
  涨: 15:00 价格相比 9:00 上涨 > 0.3%
  跌: 下跌 > 0.3%
  平: -0.3% ~ +0.3%

依赖: pip install numpy requests pyyaml
"""

import os, re, sys, json, time, sqlite3, logging, argparse, math
from pathlib import Path
from datetime import datetime
from collections import defaultdict, Counter
from typing import Optional, List, Tuple

import numpy as np

# ============================================================
# 配置
# ============================================================
DB_PATH = Path(__file__).parent / "news_csi300.db"
LOG_PATH = Path(__file__).parent / "csi300_predictor.log"

UP_THRESHOLD = 0.003
DOWN_THRESHOLD = -0.003
DEFAULT_K = 5

# 策略关键词: 利好/利空
POSITIVE_KEYWORDS = [
    "增长", "上涨", "利好", "突破", "创新高", "回升", "反弹",
    "扩张", "回暖", "盈利", "净利润", "营收增长", "政策支持",
    "降息", "降准", "减税", "基建", "投资", "放量",
    "稳增长", "积极", "向好", "提振", "复苏", "开放",
]
NEGATIVE_KEYWORDS = [
    "下跌", "暴跌", "利空", "下滑", "衰退", "萎缩", "低迷",
    "亏损", "风险", "危机", "制裁", "贸易摩擦", "加息",
    "收紧", "去杠杆", "监管", "调查", "违约", "暴雷",
    "下行", "压力", "冲击", "不确定性", "疲软", "抛售",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# ============================================================
# 数据加载
# ============================================================
def load_data(db_path: Path = DB_PATH):
    """从 DB 加载新闻和指数数据，按日期配对。
    返回: (news_by_date, idx_series_by_date)
      news_by_date: {date: [{channel, title, summary}, ...]}
      idx_series_by_date: {date: [(time_str, price), ...]}  按时间排序
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT date, time, price FROM index_data ORDER BY date, time")
    idx_rows = c.fetchall()

    idx_series_by_date = defaultdict(list)
    for r in idx_rows:
        idx_series_by_date[r["date"]].append((r["time"], r["price"]))

    c.execute("SELECT date, channel, title, summary FROM news ORDER BY date, channel, rank")
    news_rows = c.fetchall()
    conn.close()

    news_by_date = defaultdict(list)
    for r in news_rows:
        news_by_date[r["date"]].append(dict(r))

    return news_by_date, idx_series_by_date


def build_samples(news_by_date, idx_series_by_date):
    """构建训练样本: 每日新闻 + 标签 + 曲线特征"""
    samples = []
    skipped_no_news = 0
    skipped_no_idx = 0

    for date in sorted(news_by_date.keys()):
        news_list = news_by_date[date]
        if not news_list:
            skipped_no_news += 1
            continue

        series = idx_series_by_date.get(date, [])
        if len(series) < 3:
            skipped_no_idx += 1
            continue

        # 提取关键点并拟合曲线
        keypoints = CurveFitter.extract_keypoints(series, n=5)
        curve = CurveFitter.fit_quadratic(keypoints)
        curve_feat = CurveFitter.curve_to_features(curve)

        # 9:00 和 15:00 价格（从 series 中找）
        idx_dict = dict(series)
        price_9 = _find_closest(idx_dict, "09:00")
        price_15 = _find_closest(idx_dict, "15:00")

        if price_9 is None or price_15 is None:
            skipped_no_idx += 1
            continue

        change_pct = (price_15 - price_9) / price_9
        if change_pct > UP_THRESHOLD:
            label = "up"
        elif change_pct < DOWN_THRESHOLD:
            label = "down"
        else:
            label = "flat"

        text = " ".join(
            n["title"] + ("。" + n["summary"] if n["summary"] else "")
            for n in news_list
        )

        samples.append({
            "date": date,
            "text": text,
            "price_9": price_9,
            "price_15": price_15,
            "change_pct": round(change_pct * 100, 2),
            "label": label,
            "news_count": len(news_list),
            "curve": curve,           # (a, b, c, r2)
            "curve_feat": curve_feat, # {a, b, c, r2, convexity, trend}
            "keypoints": keypoints,   # [(t_min, price), ...]
        })

    logger.info(
        f"build_samples: {len(samples)} samples, "
        f"skipped no_news={skipped_no_news} no_idx={skipped_no_idx}"
    )
    return samples


def _find_closest(idx_data: dict, target_time: str):
    """找最接近 target_time 的价格（容差10分钟）"""
    target = datetime.strptime(target_time, "%H:%M")
    best_time = None
    best_price = None
    best_diff = None

    for t_str, price in idx_data.items():
        try:
            t = datetime.strptime(t_str, "%H:%M")
        except ValueError:
            continue
        diff = abs((t - target).total_seconds())
        if diff > 600:
            continue
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best_time = t_str
            best_price = price

    return best_price


# ============================================================
# 曲线拟合: 从日内数据提取走势形态
# ============================================================
class CurveFitter:
    """从日内每10分钟指数数据中提取走势形态。
    1. 抽样 n 个关键转折点（默认5个）
    2. 二次曲线拟合 y = a*t^2 + b*t + c
    3. 输出 (a, b, c, r2) 描述走势形状
    """

    @staticmethod
    def extract_keypoints(
        series: List[Tuple[str, float]], n: int = 5
    ) -> List[Tuple[float, float]]:
        """从日内序列中抽样 n 个最具代表性的点 (t_minutes, price)。
        策略: 首尾必选 + 中间选局部极值点（二阶差分符号变化处）。
        """
        if len(series) < n:
            # 数据不够，全部使用
            points = []
            for t_str, price in series:
                try:
                    h, m = map(int, t_str.split(":"))
                    points.append((h * 60 + m, price))
                except ValueError:
                    continue
            return points

        # 解析为 (minutes, price)
        parsed = []
        for t_str, price in series:
            try:
                h, m = map(int, t_str.split(":"))
                parsed.append((h * 60 + m, price))
            except ValueError:
                continue
        if len(parsed) < n:
            return parsed

        parsed.sort(key=lambda x: x[0])
        prices = np.array([p for _, p in parsed])

        # 计算二阶差分
        d2 = np.diff(prices, 2)  # length = len(prices)-2

        # 找局部极值点: 一阶差分符号变化处
        d1 = np.diff(prices)
        turning = []  # [(index_in_parsed, abs_d2)]
        for i in range(1, len(d1)):
            if d1[i] * d1[i - 1] < 0:  # 符号变化 = 极值点
                turning.append((i, abs(d2[i - 1]) if i - 1 < len(d2) else 0))

        # 按二阶差分绝对值排序，取 top-(n-2)
        turning.sort(key=lambda x: x[1], reverse=True)
        selected_indices = {0, len(parsed) - 1}  # 首尾必选
        for idx, _ in turning:
            if len(selected_indices) >= n:
                break
            selected_indices.add(idx)

        # 如果不够 n 个，均匀采样补齐
        if len(selected_indices) < n:
            step = max(1, (len(parsed) - 1) // (n - 1))
            for i in range(0, len(parsed), step):
                if len(selected_indices) >= n:
                    break
                selected_indices.add(i)

        result = [parsed[i] for i in sorted(selected_indices)[:n]]
        return result

    @staticmethod
    def fit_quadratic(
        points: List[Tuple[float, float]]
    ) -> Tuple[float, float, float, float]:
        """二次曲线拟合 y = a*t^2 + b*t + c。
        返回: (a, b, c, r2)
          a > 0: 加速上涨/下跌 (凸)
          a < 0: 涨势趋缓/跌势趋缓 (凹)
          b > 0: 整体上行
          r2:   拟合优度 [0, 1]
        """
        if len(points) < 3:
            return (0.0, 0.0, points[0][1] if points else 0.0, 0.0)

        xs = np.array([p[0] for p in points], dtype=np.float64)
        ys = np.array([p[1] for p in points], dtype=np.float64)

        # 归一化 x 到 [0, 1] 避免数值问题
        x_min, x_max = xs.min(), xs.max()
        if x_max > x_min:
            x_norm = (xs - x_min) / (x_max - x_min)
        else:
            x_norm = np.zeros_like(xs)

        # 最小二乘二次拟合
        coeffs = np.polyfit(x_norm, ys, 2)
        a, b, c = float(coeffs[0]), float(coeffs[1]), float(coeffs[2])

        # R?
        y_pred = np.polyval(coeffs, x_norm)
        ss_res = np.sum((ys - y_pred) ** 2)
        ss_tot = np.sum((ys - ys.mean()) ** 2)
        r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0

        return (a, b, c, r2)

    @staticmethod
    def curve_to_features(curve: Tuple[float, float, float, float]) -> dict:
        """将曲线参数转为可解释的特征字典"""
        a, b, c, r2 = curve
        return {
            "a": round(a, 6),       # 曲率
            "b": round(b, 6),       # 整体斜率
            "c": round(c, 2),       # 开盘附近水平
            "r2": round(r2, 4),     # 拟合优度
            "convexity": "convex" if a > 0 else "concave",  # 凸/凹
            "trend": "rising" if b > 0 else "falling",       # 升/降
        }

# ============================================================
# 向量化
# ============================================================
class Vectorizer:
    """新闻文本 -> 向量。优先 embedding API，回退 TF-IDF。"""

    def __init__(self):
        self._tfidf_vocab = None
        self._tfidf_idf = None
        self.dim = 256

    def fit_transform(self, texts: list):
        api_vecs = self._try_embed(texts)
        if api_vecs is not None:
            self.dim = api_vecs.shape[1]
            logger.info(f"使用 Embedding API，维度={self.dim}")
            return api_vecs
        logger.info("Embedding API 不可用，使用 TF-IDF 回退 (dim=256)")
        return self._fit_tfidf(texts)

    def transform(self, texts: list):
        api_vecs = self._try_embed(texts)
        if api_vecs is not None:
            return api_vecs
        if self._tfidf_vocab is not None:
            return self._transform_tfidf(texts)
        raise RuntimeError("Vectorizer 未训练，请先调用 fit_transform")

    def _try_embed(self, texts: list):
        try:
            cfg = self._load_config()
            emb_cfg = cfg.get("embedding", {})
            api_key = emb_cfg.get("api_key") or os.environ.get("EMBEDDING_API_KEY")
            api_url = emb_cfg.get("api_url") or os.environ.get("EMBEDDING_API_URL")
            model = emb_cfg.get("model_name") or os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
            if not api_key or not api_url:
                return None
            if not api_url.rstrip("/").endswith("/v1"):
                api_url = api_url.rstrip("/") + "/v1"
            import requests
            resp = requests.post(
                f"{api_url.rstrip('/')}/embeddings",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "input": texts},
                timeout=30,
            )
            if resp.status_code != 200:
                logger.warning(f"Embedding API 返回 {resp.status_code}: {resp.text[:200]}")
                return None
            data = resp.json()
            return np.array([d["embedding"] for d in data["data"]], dtype=np.float32)
        except Exception as e:
            logger.warning(f"Embedding API 异常: {e}")
            return None

    def _load_config(self):
        cfg_path = Path.home() / ".tea_agent" / "config.yaml"
        if cfg_path.exists():
            import yaml
            with open(cfg_path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def _fit_tfidf(self, texts: list):
        all_tokens = [_tokenize(t) for t in texts]
        df = defaultdict(int)
        for tokens in all_tokens:
            for tok in set(tokens):
                df[tok] += 1
        n = len(texts)
        valid_tokens = [tok for tok, cnt in df.items() if 1 < cnt < n * 0.8]
        if not valid_tokens:
            # 样本太少，放宽条件：使用所有出现过的 token
            valid_tokens = list(df.keys())
        idf_scores = {tok: math.log((n + 1) / (df[tok] + 1)) + 1 for tok in valid_tokens}
        sorted_tokens = sorted(idf_scores, key=idf_scores.get, reverse=True)[:256]
        self._tfidf_vocab = {tok: i for i, tok in enumerate(sorted_tokens)}
        self._tfidf_idf = np.array([idf_scores[tok] for tok in sorted_tokens], dtype=np.float32)
        self.dim = len(self._tfidf_vocab)

        vecs = np.zeros((n, self.dim), dtype=np.float32)
        for i, tokens in enumerate(all_tokens):
            counts = Counter(tokens)
            for tok, cnt in counts.items():
                if tok in self._tfidf_vocab:
                    j = self._tfidf_vocab[tok]
                    vecs[i, j] = cnt * self._tfidf_idf[j]
            norm = np.linalg.norm(vecs[i])
            if norm > 0:
                vecs[i] /= norm
        return vecs

    def _transform_tfidf(self, texts: list):
        vecs = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            tokens = _tokenize(text)
            counts = Counter(tokens)
            for tok, cnt in counts.items():
                if tok in self._tfidf_vocab:
                    j = self._tfidf_vocab[tok]
                    vecs[i, j] = cnt * self._tfidf_idf[j]
            norm = np.linalg.norm(vecs[i])
            if norm > 0:
                vecs[i] /= norm
        return vecs


def _tokenize(text: str) -> list:
    """中文 bigram + 关键词分词"""
    tokens = []
    for i in range(len(text) - 1):
        pair = text[i:i+2]
        if re.match(r'[\u4e00-\u9fff]{2}', pair):
            tokens.append(pair)
    for kw in POSITIVE_KEYWORDS + NEGATIVE_KEYWORDS:
        if kw in text:
            tokens.append(f"KW:{kw}")
    return tokens


# ============================================================
# 策略特征
# ============================================================
def sentiment_score(text: str) -> float:
    """简单情感得分: [-1, 1]"""
    pos = sum(1 for kw in POSITIVE_KEYWORDS if kw in text)
    neg = sum(1 for kw in NEGATIVE_KEYWORDS if kw in text)
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total


def extract_strategy_features(text: str) -> dict:
    return {
        "sentiment": sentiment_score(text),
        "positive_count": sum(1 for kw in POSITIVE_KEYWORDS if kw in text),
        "negative_count": sum(1 for kw in NEGATIVE_KEYWORDS if kw in text),
        "text_len": len(text),
    }

# ============================================================
# 预测器
# ============================================================
class CSIPredictor:
    """策略型 KNN 分类器：余弦相似度 + 加权投票"""

    def __init__(self, k: int = DEFAULT_K):
        self.k = k
        self.vectorizer = Vectorizer()
        self.vectors = None
        self.labels = []
        self.dates = []
        self.features = []
        self.samples = []
        self.label_map = {"up": 0, "flat": 1, "down": 2}
        self.idx_to_label = {0: "up", 1: "flat", 2: "down"}

    def fit(self, samples: list):
        """训练: 向量化新闻 + 存储曲线参数"""
        self.samples = samples
        self.dates = [s["date"] for s in samples]
        self.labels = [s["label"] for s in samples]
        texts = [s["text"] for s in samples]
        self.features = [extract_strategy_features(t) for t in texts]
        self.vectors = self.vectorizer.fit_transform(texts)
        # 曲线参数向量: (a, b, c, r2)
        self.curve_vectors = np.array(
            [s["curve"] for s in samples], dtype=np.float64
        )
        logger.info(
            f"训练完成: {len(samples)} 样本, "
            f"新闻向量维度={self.vectors.shape[1]}, 曲线特征维度=4"
        )
        self._print_distribution()

    def _print_distribution(self):
        counter = Counter(self.labels)
        total = len(self.labels)
        if total > 0:
            logger.info(
                f"标签分布: up={counter.get('up',0)}({counter.get('up',0)/total*100:.1f}%) "
                f"flat={counter.get('flat',0)}({counter.get('flat',0)/total*100:.1f}%) "
                f"down={counter.get('down',0)}({counter.get('down',0)/total*100:.1f}%)"
            )

    def predict(self, text: str) -> dict:
        """
        预测单条文本 -> {up: prob, flat: prob, down: prob}
        策略: KNN 余弦相似度加权投票 + 情感得分微调
        """
        vec = self.vectorizer.transform([text])[0]
        strat = extract_strategy_features(text)

        if self.vectors.shape[1] == 0:
            # 无有效特征，基于策略特征和先验分布
            strat = extract_strategy_features(text)
            return self._predict_from_strategy(strat)
        similarities = np.dot(self.vectors, vec)

        k = min(self.k, len(self.samples))
        top_indices = np.argpartition(similarities, -k)[-k:]
        top_indices = top_indices[np.argsort(similarities[top_indices])[::-1]]

        weights = {"up": 0.0, "flat": 0.0, "down": 0.0}
        for idx in top_indices:
            sim = similarities[idx]
            if sim < 0:
                sim = 0
            label = self.labels[idx]
            weights[label] += sim

        total = sum(weights.values())
        if total > 0:
            for kk in weights:
                weights[kk] /= total
        else:
            weights = {"up": 0.333, "flat": 0.334, "down": 0.333}

        # 策略微调: 情感得分影响概率 +/-15%
        sent = strat["sentiment"]
        adjust = 0.15
        if sent > 0.2:
            weights["up"] += adjust
            weights["down"] -= adjust * 0.5
            weights["flat"] -= adjust * 0.5
        elif sent < -0.2:
            weights["down"] += adjust
            weights["up"] -= adjust * 0.5
            weights["flat"] -= adjust * 0.5

        for kk in weights:
            weights[kk] = max(0.0, min(1.0, weights[kk]))
        total = sum(weights.values())
        if total > 0:
            for kk in weights:
                weights[kk] = round(weights[kk] / total, 4)

        return weights

    def _predict_from_strategy(self, strat: dict) -> dict:
        """当向量维度为0时的回退预测：基于情感+先验分布"""
        counter = Counter(self.labels)
        total = len(self.labels)
        if total == 0:
            return {"up": 0.333, "flat": 0.334, "down": 0.333}
        weights = {k: counter[k]/total for k in ["up", "flat", "down"]}
        sent = strat["sentiment"]
        adjust = 0.20
        if sent > 0.2:
            weights["up"] += adjust
            weights["flat"] -= adjust * 0.5
            weights["down"] -= adjust * 0.5
        elif sent < -0.2:
            weights["down"] += adjust
            weights["up"] -= adjust * 0.5
            weights["flat"] -= adjust * 0.5
        for kk in weights:
            weights[kk] = max(0.0, min(1.0, weights[kk]))
        total_w = sum(weights.values())
        if total_w > 0:
            for kk in weights:
                weights[kk] = round(weights[kk] / total_w, 4)
        return weights

    def predict_curve(self, text: str) -> dict:
        """预测日内走势曲线: 新闻 -> 二次曲线参数 (a, b, c, r2)。
        策略: KNN 新闻相似度加权平均历史曲线参数。
        """
        vec = self.vectorizer.transform([text])[0]
        if self.vectors.shape[1] == 0:
            return {"a": 0, "b": 0, "c": 0, "r2": 0, "warning": "no features"}

        similarities = np.dot(self.vectors, vec)
        k = min(self.k, len(self.samples))
        top_indices = np.argpartition(similarities, -k)[-k:]
        top_indices = top_indices[np.argsort(similarities[top_indices])[::-1]]

        # 加权平均曲线参数
        total_sim = 0.0
        weighted_curve = np.zeros(4, dtype=np.float64)
        for idx in top_indices:
            sim = max(0.0, similarities[idx])
            weighted_curve += sim * self.curve_vectors[idx]
            total_sim += sim

        if total_sim > 0:
            weighted_curve /= total_sim
        a, b, c, r2 = weighted_curve

        return {
            "a": round(float(a), 6),
            "b": round(float(b), 6),
            "c": round(float(c), 2),
            "r2": round(float(r2), 4),
            "convexity": "convex(加速)" if a > 0 else "concave(趋缓)",
            "trend": "rising" if b > 0 else "falling",
            "shape_desc": _describe_curve(a, b),
        }

    def predict_multi(self, texts: list) -> list:
        return [self.predict(t) for t in texts]



def _describe_curve(a: float, b: float) -> str:
    """用自然语言描述曲线形态"""
    parts = []
    if b > 0.01:
        parts.append("整体上行")
    elif b < -0.01:
        parts.append("整体下行")
    else:
        parts.append("横盘震荡")

    if a > 0.005:
        parts.append("加速" + ("上涨" if b > 0 else "下跌"))
    elif a < -0.005:
        parts.append(("涨势" if b > 0 else "跌势") + "趋缓")
    else:
        parts.append("匀速变动")

    return "，".join(parts)

    def evaluate(self, samples: list = None):
        """回测评估: 留一法交叉验证"""
        if samples is None:
            samples = self.samples

        if len(samples) < 2:
            logger.warning("样本数不足，无法评估")
            return None

        correct = 0
        total = 0
        confusion = {
            "up": {"up": 0, "flat": 0, "down": 0},
            "flat": {"up": 0, "flat": 0, "down": 0},
            "down": {"up": 0, "flat": 0, "down": 0},
        }
        detail_results = []

        for s in samples:
            other = [o for o in samples if o["date"] != s["date"]]
            if len(other) < 1:
                continue

            tmp = CSIPredictor(k=self.k)
            tmp.fit(other)
            pred = tmp.predict(s["text"])
            actual = s["label"]
            predicted = max(pred, key=pred.get)

            correct += (predicted == actual)
            total += 1
            confusion[actual][predicted] += 1
            detail_results.append({
                "date": s["date"],
                "actual": actual,
                "predicted": predicted,
                "pred_prob": pred,
                "change_pct": s["change_pct"],
            })

        acc = correct / total if total > 0 else 0
        logger.info(f"回测准确率: {correct}/{total} = {acc:.2%}")

        # 混淆矩阵
        logger.info("混淆矩阵:")
        logger.info(f"          预测up  预测flat 预测down")
        for label in ["up", "flat", "down"]:
            row = confusion[label]
            logger.info(f"  实际{label:4s}  {row['up']:5d}   {row['flat']:7d}   {row['down']:6d}")

        # 各标签召回率
        for label in ["up", "flat", "down"]:
            tp = confusion[label][label]
            total_actual = sum(confusion[label].values())
            recall = tp / total_actual if total_actual > 0 else 0
            logger.info(f"  {label} 召回率: {tp}/{total_actual} = {recall:.2%}")

        return {"accuracy": acc, "correct": correct, "total": total,
                "confusion": confusion, "details": detail_results}

# ============================================================
# 主流程
# ============================================================
def _eval_curve(predictor, samples):
    """曲线回测: 对比预测曲线参数 vs 真实曲线参数"""
    n = len(samples)
    if n < 2:
        print("样本不足，无法回测")
        return

    errors_a = []
    errors_b = []
    errors_r2 = []
    label_correct = 0
    shape_correct = 0

    print(f"\n{'日期':<12} {'实际a':>10} {'预测a':>10} {'实际b':>10} {'预测b':>10} {'实际R?':>8} {'形态匹配':8}")
    print("-" * 78)

    for s in samples:
        other = [o for o in samples if o["date"] != s["date"]]
        if len(other) < 1:
            continue

        tmp = CSIPredictor(k=predictor.k)
        tmp.fit(other)

        # 预测曲线
        curve_pred = tmp.predict_curve(s["text"])
        actual = s["curve_feat"]

        err_a = abs(curve_pred["a"] - actual["a"])
        err_b = abs(curve_pred["b"] - actual["b"])
        err_r2 = abs(curve_pred.get("r2", 0) - actual["r2"])
        errors_a.append(err_a)
        errors_b.append(err_b)
        errors_r2.append(err_r2)

        # 形态匹配: convexity + trend 一致
        shape_ok = (
            curve_pred["convexity"].startswith(actual["convexity"])
            and curve_pred["trend"] == actual["trend"]
        )
        if shape_ok:
            shape_correct += 1

        # 涨跌方向
        pred_label = tmp.predict(s["text"])
        if max(pred_label, key=pred_label.get) == s["label"]:
            label_correct += 1

        print(f"{s['date']:<12} {actual['a']:10.4f} {curve_pred['a']:10.4f} "
              f"{actual['b']:10.4f} {curve_pred['b']:10.4f} {actual['r2']:8.4f} "
              f"{'✓' if shape_ok else '✗':8}")

    print(f"\n曲线参数 MAE:  a={np.mean(errors_a):.4f}  b={np.mean(errors_b):.4f}  R?{np.mean(errors_r2):.4f}")
    print(f"形态方向准确率: {shape_correct}/{n} = {shape_correct/n:.2%}")
    print(f"涨跌方向准确率: {label_correct}/{n} = {label_correct/n:.2%}")


def main():
    parser = argparse.ArgumentParser(description="CSI300 Predictor - 新闻预测沪深300走势")
    parser.add_argument("--k", type=int, default=DEFAULT_K, help=f"KNN 近邻数 (默认:{DEFAULT_K})")
    parser.add_argument("--db", type=str, default=str(DB_PATH), help="SQLite 数据库路径")
    parser.add_argument("--eval", action="store_true", help="仅回测评估")
    parser.add_argument("--curve", action="store_true", help="回测并对比预测曲线 vs 真实曲线")
    parser.add_argument("--predict", type=str, default=None, help="预测指定日期的走势 (格式: YYYY-MM-DD)")
    parser.add_argument("--list", action="store_true", help="列出所有样本日期")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        logger.error(f"数据库不存在: {db_path}")
        sys.exit(1)

    news_by_date, idx_series_by_date = load_data(db_path)
    samples = build_samples(news_by_date, idx_series_by_date)

    if not samples:
        logger.error("无有效样本 (需要新闻 + >=3条日内指数数据)")
        sys.exit(1)

    logger.info(f"共 {len(samples)} 个有效样本日")

    if args.list:
        print("\n样本日期列表:")
        for s in samples:
            cf = s["curve_feat"]
            print(f"  {s['date']}  {s['label']:5s}  {s['change_pct']:+.2f}%  "
                  f"曲线:{cf['convexity']}/{cf['trend']}  R?{cf['r2']}  ({s['news_count']}条新闻)")
        return

    # 训练
    predictor = CSIPredictor(k=args.k)
    predictor.fit(samples)

    if args.predict:
        date = args.predict
        news_list = news_by_date.get(date, [])
        if not news_list:
            logger.error(f"日期 {date} 无新闻数据")
            sys.exit(1)
        text = " ".join(
            n["title"] + ("。" + n["summary"] if n["summary"] else "")
            for n in news_list
        )
        # 涨跌概率
        pred = predictor.predict(text)
        print(f"\n日期 {date} 预测结果:")
        print(f"  上涨概率: {pred['up']:.2%}")
        print(f"  持平概率: {pred['flat']:.2%}")
        print(f"  下跌概率: {pred['down']:.2%}")
        print(f"  预测方向: {max(pred, key=pred.get)}")
        print(f"  情感得分: {extract_strategy_features(text)['sentiment']:+.2f}")

        # 曲线预测
        curve_pred = predictor.predict_curve(text)
        print(f"\n  预测日内曲线: y = {curve_pred['a']:.4f}t? + {curve_pred['b']:.4f}t + {curve_pred['c']:.2f}")
        print(f"  形态描述: {curve_pred['shape_desc']}")
        print(f"  拟合R? {curve_pred['r2']}")

        # 如果有实际结果，对比
        sample = next((s for s in samples if s["date"] == date), None)
        if sample:
            print(f"\n  实际结果: {sample['label']} ({sample['change_pct']:+.2f}%)")
            match = "✓" if max(pred, key=pred.get) == sample["label"] else "✗"
            print(f"  涨跌预测正确: {match}")
            # 曲线对比
            actual_c = sample["curve_feat"]
            print(f"  实际曲线: y = {actual_c['a']:.4f}t? + {actual_c['b']:.4f}t + {actual_c['c']:.2f}")
            print(f"  实际形态: {_describe_curve(sample['curve'][0], sample['curve'][1])}")
        return

    # 回测评估
    if args.curve:
        logger.info("=" * 60)
        logger.info("曲线拟合回测 (LOOCV + 曲线参数对比)")
        logger.info("=" * 60)
        _eval_curve(predictor, samples)
    elif args.eval or True:
        logger.info("=" * 60)
        logger.info("留一法交叉验证 (Leave-One-Out CV)")
        logger.info("=" * 60)
        result = predictor.evaluate(samples)
        if result:
            print(f"\n整体准确率: {result['accuracy']:.2%} ({result['correct']}/{result['total']})")
            print(f"\n{'日期':<12} {'实际':6} {'预测':6} {'涨':>8} {'平':>8} {'跌':>8} {'变动%':>8} {'正确':4}")
            print("-" * 68)
            for d in result["details"]:
                p = d["pred_prob"]
                match = "✓" if d["actual"] == d["predicted"] else "✗"
                print(f"{d['date']:<12} {d['actual']:6} {d['predicted']:6} "
                      f"{p['up']:7.1%} {p['flat']:7.1%} {p['down']:7.1%} "
                      f"{d['change_pct']:+7.2f}% {match:4}")


if __name__ == "__main__":
    main()
