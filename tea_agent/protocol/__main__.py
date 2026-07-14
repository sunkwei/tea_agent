"""ACP Protocol — CLI entry point.

Usage:
    python -m tea_agent.protocol                # stdio mode (ACP v1.2.1)
    python -m tea_agent.protocol --http          # HTTP legacy mode
    python -m tea_agent.protocol --port 8082     # HTTP on custom port
    python -m tea_agent.protocol --verbose       # stdio with verbose logging
"""
import argparse
import logging
import sys


def main():
    parser = argparse.ArgumentParser(
        description="Tea Agent — ACP Protocol Server",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Run in legacy HTTP mode (instead of stdio JSON-RPC)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="HTTP bind host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8082,
        help="HTTP bind port (default: 8082)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to config file",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress non-essential output",
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.INFO
    if args.verbose:
        log_level = logging.DEBUG
    elif args.quiet:
        log_level = logging.WARNING

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,  # Always log to stderr (stdout is for JSON-RPC)
    )

    if args.http:
        # Legacy HTTP mode
        from tea_agent.protocol.acp_server import run_server

        logging.getLogger("acp_server").info(
            f"Starting HTTP server on {args.host}:{args.port}"
        )
        run_server(
            host=args.host,
            port=args.port,
            config_path=args.config,
        )
    else:
        # ACP stdio JSON-RPC mode (default)
        try:
            from tea_agent.protocol.acp_agent import AcpAgent

            agent = AcpAgent(config_path=args.config)
            agent.run()
        except KeyboardInterrupt:
            logging.getLogger("acp.agent").info("Shutting down")
            sys.exit(0)


if __name__ == "__main__":
    main()
