"""Manage the loopback-only BrandBAI live recorder service."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from local_service import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    RecordingSettings,
    ServiceError,
    TaskManager,
    TaskStore,
    create_http_server,
    load_or_create_token,
    token_fingerprint,
)
from runtime_support import RuntimeSetupError, ensure_streamget_runtime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the localhost live-recorder task service.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    initialize = subparsers.add_parser("init", help="Create the private service token and database.")
    initialize.add_argument("--state-dir", required=True, type=Path)

    show_token = subparsers.add_parser(
        "show-token", help="Recovery only: explicitly display the persistent local API token."
    )
    show_token.add_argument("--state-dir", required=True, type=Path)

    serve = subparsers.add_parser("serve", help="Run the foreground loopback service.")
    serve.add_argument("--state-dir", required=True, type=Path)
    serve.add_argument("--output-root", required=True, type=Path)
    serve.add_argument("--host", default=DEFAULT_HOST, choices=(DEFAULT_HOST,))
    serve.add_argument("--port", default=DEFAULT_PORT, type=int)
    serve.add_argument("--ffmpeg")
    serve.add_argument("--ffprobe")
    serve.add_argument("--min-free-space-gb", default=10.0, type=float)
    return parser


def _print(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _initialize(state_dir: Path) -> int:
    token, created = load_or_create_token(state_dir)
    TaskStore(state_dir.expanduser().resolve() / "service_state.sqlite3")
    _print(
        {
            "initialized": True,
            "token_created": created,
            "token_fingerprint": token_fingerprint(token),
            "private_token_file": "auth_token.txt",
            "database": "service_state.sqlite3",
            "warning": "Keep the state directory outside every client delivery and release ZIP.",
        }
    )
    return 0


def _show_token(state_dir: Path) -> int:
    token, _ = load_or_create_token(state_dir)
    _print(
        {
            "token": token,
            "token_fingerprint": token_fingerprint(token),
            "warning": "Use only for one-time pairing; do not save, share, log, or export this token.",
        }
    )
    return 0


def _serve(args: argparse.Namespace) -> int:
    state_dir = args.state_dir.expanduser().resolve()
    token, created = load_or_create_token(state_dir)
    store = TaskStore(state_dir / "service_state.sqlite3")
    recording_settings = RecordingSettings(
        state_dir / "recording_settings.json",
        default_output_root=args.output_root,
        disallowed_roots=(state_dir,),
    )
    manager = TaskManager(
        store=store,
        output_root=args.output_root,
        runtime_preparer=lambda: ensure_streamget_runtime(auto_install=True),
        ffmpeg_path=args.ffmpeg,
        ffprobe_path=args.ffprobe,
        min_free_space_gb=args.min_free_space_gb,
        recording_settings=recording_settings,
    )
    server = create_http_server(host=args.host, port=args.port, manager=manager, token=token)
    _print(
        {
            "service": "brandbai-live-recorder",
            "status": "ready",
            "listen": f"http://{DEFAULT_HOST}:{server.server_port}",
            "token_created": created,
            "token_fingerprint": token_fingerprint(token),
            "token_value_printed": False,
            "one_click_extension_pairing": True,
            "extension_session_persisted": False,
            "prototype_scope": "immediate tasks only",
        }
    )
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        manager.shutdown(timeout=30)
        server.server_close()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            return _initialize(args.state_dir)
        if args.command == "show-token":
            return _show_token(args.state_dir)
        if args.command == "serve":
            return _serve(args)
        raise ServiceError("unknown command")
    except (ServiceError, RuntimeSetupError, OSError, ValueError) as exc:
        _print({"error": type(exc).__name__, "message": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
