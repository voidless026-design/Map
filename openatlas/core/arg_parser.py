"""Command-line argument parsing (mirrors OAtlas flag names where sensible)."""

from __future__ import annotations

import argparse

from openatlas.config import Config
from openatlas.version import version_info


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openatlas",
        description="OpenAtlas - free / local / no-key OSINT toolkit (OAtlas AA mode).",
        add_help=True,
    )

    engine_opts = parser.add_argument_group("Engine options")
    engine_opts.add_argument(
        "-V", "--version", dest="show_version", action="store_true",
        default=Config.settings.show_version, help="Display the software version",
    )
    engine_opts.add_argument(
        "--show-api-services", dest="show_api_services", action="store_true",
        default=Config.settings.show_api_services,
        help="Show all the (free/local) backend services OpenAtlas uses",
    )
    engine_opts.add_argument(
        "--show-all-functions", dest="show_all_functions", action="store_true",
        default=Config.settings.show_all_functions,
        help="Show every function available in AA mode",
    )

    web_opts = parser.add_argument_group("WebServer options")
    web_opts.add_argument(
        "--start-web-server", dest="start_web_server", action="store_true",
        default=Config.web.start_api_server,
        help="Start the local Streamlit web UI for interactive use",
    )
    web_opts.add_argument(
        "--visualize", dest="visualize", nargs="?", const="latest", default=None,
        metavar="SESSION_ID",
        help="Render an investigation session (default: latest) as an interactive "
        "knowledge graph in the ATSMATRIX visualizer, served locally",
    )
    web_opts.add_argument(
        "--viz-port", dest="viz_port", type=int, default=8765,
        help="Local port for --visualize (default 8765)",
    )
    web_opts.add_argument(
        "--viz-no-serve", dest="viz_no_serve", action="store_true",
        help="With --visualize: only write the bundle to output/visualizer/, don't serve",
    )

    atlas_opts = parser.add_argument_group("Atlas (AA) options")
    atlas_opts.add_argument(
        "-f", "--functions", dest="functions", nargs="+", default=list(Config.settings.functions),
        metavar="FUNC",
        help="Select one or more functions to run, e.g. -f verify_email_address check_usernames",
    )
    atlas_opts.add_argument(
        "-v", "--verbose", dest="verbose_mode", action="store_true",
        default=Config.settings.verbose_mode, help="Enable verbose responses",
    )
    atlas_opts.add_argument(
        "-o", "--use-llm", dest="use_llm", action="store_true",
        default=Config.settings.use_llm,
        help="Use the local Ollama LLM to auto-fill arguments and reason over outputs "
        "(replaces OAtlas's -o/--use-openai; NO OpenAI key involved)",
    )
    atlas_opts.add_argument(
        "--authorized-target", dest="authorized_target", action="store_true",
        default=Config.settings.authorized_target,
        help="Assert you are authorized to actively scan the given target(s). "
        "Required for the network-scanning engine.",
    )
    atlas_opts.add_argument(
        "--snapshot-txt", dest="snapshot_txt", metavar="DOMAIN", default=None,
        help="Download & cache robots.txt / security.txt / humans.txt / ads.txt for a domain",
    )
    atlas_opts.add_argument(
        "--verify", dest="verify", nargs="*", metavar="FUNC", default=None,
        help="Run the verification harness over all functions, or the named ones",
    )
    return parser


def parse_args(argv=None) -> argparse.Namespace:
    ns = build_parser().parse_args(argv)
    if ns.show_version:
        print(version_info())
    return ns
