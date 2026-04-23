from tea_agent.config import get_config

def print_config_as_markdown_table():
    """
    获取当前配置并以 Markdown 表格形式输出。
    """
    try:
        cfg = get_config()
    except Exception as e:
        print(f"Error loading config: {e}")
        return

    # Table Header
    header = "| Model Type | API Key | API URL | Model Name | Status |"
    separator = "| :--- | :--- | :--- | :--- | :--- |"
    
    print("# Agent Configuration Report\n")
    print(header)
    print(separator)

    # Helper to format rows
    def format_row(model_type, model_cfg):
        # Mask API Key (show only first 8 chars)
        key = model_cfg.api_key
        masked_key = f"{key[:8]}..." if len(key) > 8 else (key if key else "N/A")
        
        url = model_cfg.api_url if model_cfg.api_url else "N/A"
        name = model_cfg.model_name if model_cfg.model_name else "N/A"
        status = "✅ Configured" if model_cfg.is_configured else "❌ Not Configured"
        
        return f"| {model_type} | `{masked_key}` | `{url}` | `{name}` | {status} |"

    # Rows
    print(format_row("Main Model", cfg.main_model))
    print(format_row("Cheap Model", cfg.cheap_model))

if __name__ == "__main__":
    print_config_as_markdown_table()
