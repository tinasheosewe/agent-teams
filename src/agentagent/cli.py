"""CLI entry point for AgentAgent."""

from __future__ import annotations

import argparse
import logging
import sys

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentAgent — Multi-agent collaborative framework")
    subparsers = parser.add_subparsers(dest="command")

    # serve command
    serve_parser = subparsers.add_parser("serve", help="Start the API server")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    serve_parser.add_argument("--reload", action="store_true", help="Enable auto-reload")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.command == "serve":
        uvicorn.run(
            "agentagent.api.server:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
