# version: 1.0.0 — 公共 API 入口冒烟（运行时实证，检出「入口级」静默失效）

import json
import logging

logger = logging.getLogger("toolkit")


def toolkit_api_smoke(scope: str = "all", verbose: bool = False) -> str:
    """对存活的公共 API 入口做最小冒烟调用，检出「入口级」静默失效。

    为什么需要（静态检查的盲区）：本仓库有两个真实缺陷只有运行期才暴露 ——
    `Storage.generate_l2_to_l3_summary` 委托层签名漂移（调用即 TypeError，被
    except 吞成 WARNING）、`tea_agent.__all__` 声明 8 个公开名却只绑定 2 个
    （`from tea_agent import Storage` 直接 ImportError）。静态扫描看到的是
    「代码存在」，看不到「调用得通不通」。

    Args:
        scope: public=仅包公开名（验可解析）; storage=Storage 公共方法（实际调用）;
            all=两者（默认）。
        verbose: 是否在结果中返回已检入口清单与待审阅异常。

    Returns:
        JSON 字符串：{ok, checked, discovered, failures, unexpected, scope}
        ok 为 True 表示无入口级致命失败（TypeError/ImportError/NameError/
        AttributeError）；合法入参拒绝（ValueError 等）视为通过。
    """
    logger.info("toolkit_api_smoke called: scope=%r verbose=%r", scope, verbose)
    try:
        from tea_agent.evaluation.api_smoke import run
    except ImportError as e:
        return json.dumps({"ok": False, "error": f"冒烟模块不可用: {e}"},
                          ensure_ascii=False)

    try:
        out = run(scope=scope, with_entries=bool(verbose))
    except Exception as e:  # noqa: BLE001 — 工具边界：返回结构化错误而非抛出
        logger.exception("api_smoke op_failed")
        return json.dumps({"ok": False, "error": f"冒烟执行失败: {e}"},
                          ensure_ascii=False)

    res = {
        "ok": not out.get("failures"),
        "scope": out.get("scope", scope),
        "checked": out.get("checked", 0),
        "discovered": out.get("discovered", 0),
        "failures": out.get("failures", []),
    }
    if verbose:
        res["unexpected"] = out.get("unexpected", [])
        res["skipped"] = out.get("skipped", [])
        res["entries"] = out.get("entries", [])
    return json.dumps(res, ensure_ascii=False, indent=2)


def meta_toolkit_api_smoke() -> dict:
    """Meta toolkit api_smoke."""
    return {"type": "function", "function": {
        "name": "toolkit_api_smoke",
        "description": "公共 API 入口冒烟：以最小良性入参调用存活入口，检出「入口级」静默"
                       "失效（委托层签名漂移、符号缺失、__all__ 承诺未兑现）。只把 "
                       "TypeError/ImportError/NameError/AttributeError 计为失败；合法入参"
                       "拒绝（ValueError 等）视为通过。使用临时数据库，不触碰真实数据。",
        "parameters": {"type": "object", "properties": {
            "scope": {"type": "string", "enum": ["public", "storage", "all"],
                      "description": "public=仅包公开名; storage=Storage 公共方法; all=两者",
                      "default": "all"},
            "verbose": {"type": "boolean",
                        "description": "返回已检入口清单与待审阅异常", "default": False},
        }}}}
