import json

raw = json.loads(open(r"C:\Users\Hetin\.tea_agent\model_config.json", encoding="utf-8").read())
print("top keys:", list(raw.keys()))
for pname, p in (raw.get("providers") or {}).items():
    models = p.get("models") or {}
    for mid, m in models.items():
        if not isinstance(m, dict):
            continue
        cw = m.get("context_window")
        out = m.get("max_output_tokens")
        role = m.get("role", "")
        print(f"{pname:14s} {mid:34s} cw={cw!s:<10} out={out!s:<8} role={role}")
