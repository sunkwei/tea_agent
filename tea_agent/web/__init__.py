import sys

from tea_agent.web.server import create_app, run_server

__all__ = ["create_app", "run_server"]


def main():
    """CLI entry point for python -m tea_agent.web"""
    import argparse
    parser = argparse.ArgumentParser(description="Tea Agent Web 服务器")
    parser.add_argument("--config", type=str, default=None, help="配置文件路径")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8080, help="监听端口")
    args = parser.parse_args()

    run_server(
        config_path=args.config,
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
