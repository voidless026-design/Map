"""OpenAtlas entry point (``openatlas`` console script and ``python -m openatlas``)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from openatlas.config import Config
from openatlas.core.arg_parser import parse_args
from openatlas.logger import get_logger

log = get_logger("openatlas")


def _print_banner() -> None:
    try:
        print(Path(Config.files.banner).read_text(encoding="utf-8"))
    except OSError:
        pass


def _cli_commands() -> set:
    from openatlas.cli import COMMANDS

    return COMMANDS


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in _cli_commands():
        from openatlas.cli import main as cli_main

        return cli_main(argv)
    args = parse_args(argv)

    if args.show_version:
        return 0  # already printed by parse_args

    # Info-only commands
    if args.show_api_services:
        from openatlas.utils.tool_descriptions import api_services_text

        _print_banner()
        print(api_services_text())
        return 0

    if args.show_all_functions:
        from openatlas.utils.tool_descriptions import all_functions_text

        _print_banner()
        print(all_functions_text())
        return 0

    if args.snapshot_txt:
        from openatlas.utils.robots import snapshot_txt_files

        print(json.dumps(snapshot_txt_files(args.snapshot_txt), indent=2))
        return 0

    if args.verify is not None:
        from openatlas.utils.smoke_run import verify_all, verify_function

        if args.verify:
            report = {f: verify_function(f) for f in args.verify}
            ok = all(r["ok"] for r in report.values())
        else:
            report = verify_all()
            ok = report["ok"]
        print(json.dumps(report, indent=2))
        return 0 if ok else 1

    if args.visualize is not None:
        from openatlas.utils import knowledge_graph

        sid = None if args.visualize == "latest" else args.visualize
        try:
            graph = knowledge_graph.build_graph(sid)
        except LookupError as exc:
            print(f"Cannot visualize: {exc}")
            return 1
        out = knowledge_graph.write_bundle(graph)
        meta = graph["meta"]
        print(f"Session {meta['session_id']}: {len(graph['nodes'])} nodes, "
              f"{len(graph['edges'])} edges -> {out}")
        if not args.viz_no_serve:
            knowledge_graph.serve(out, port=args.viz_port)
        return 0

    if args.start_web_server:
        from openatlas.web.server import serve

        return serve()

    # Default: AA-mode function runner
    from openatlas.core.app import OpenAtlas

    # Propagate the authorization flag so the scanning engine can read it.
    Config.settings.authorized_target = bool(getattr(args, "authorized_target", False))

    _print_banner()
    OpenAtlas(args).run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
