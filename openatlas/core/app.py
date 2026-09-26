"""The OpenAtlas AA-mode application: select functions, run them, store results, loop.

Mirrors OAtlas's ``OAtlas.run()`` flow:
  1. Map entered function names -> owning engine classes (warn+drop unknowns).
  2. For each function, collect arguments interactively (or auto-fill via Ollama
     when ``--use-llm`` is set and a backend is reachable).
  3. Execute, print the result, persist it to the database.
  4. Ask whether to chain another round of functions; repeat until the user exits.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Type

from openatlas.core.database import db_funcs
from openatlas.core.registry import BaseTool, ToolRegistry, ToolResult, ToolSpec, load_all_engines
from openatlas.llm import ollama_client
from openatlas.logger import get_logger, set_verbose

log = get_logger("openatlas.app")


class OpenAtlas:
    def __init__(self, arguments: Any):
        self.arguments = arguments
        self.session_id: Optional[str] = None
        set_verbose(getattr(arguments, "verbose_mode", False))
        load_all_engines()

    # ------------------------------------------------------------------ #
    # function <-> engine mapping
    # ------------------------------------------------------------------ #
    def map_entered_func_to_class(self, names: List[str]) -> Dict[str, Type[BaseTool]]:
        mapping: Dict[str, Type[BaseTool]] = {}
        all_fns = ToolRegistry.all_functions()
        for name in names:
            engine = all_fns.get(name)
            if engine is None:
                log.warning("unknown function '%s' - skipping", name)
                continue
            mapping[name] = engine
        return mapping

    # ------------------------------------------------------------------ #
    # argument collection
    # ------------------------------------------------------------------ #
    def _coerce(self, raw: str, atype: str) -> Any:
        raw = raw.strip()
        if atype == "integer":
            return int(raw)
        if atype == "number":
            return float(raw)
        if atype == "boolean":
            return raw.lower() in {"1", "true", "yes", "y"}
        if atype == "array":
            return [x.strip() for x in raw.split(",") if x.strip()]
        return raw

    def _get_user_arguments_for_function(self, spec: ToolSpec) -> Dict[str, Any]:
        args: Dict[str, Any] = {}
        print(f"\n>>> {spec.name}: {spec.description}")
        for name, meta in spec.parameters.items():
            required = meta.get("required", False)
            atype = meta.get("type", "string")
            desc = meta.get("description", "")
            while True:
                prompt = f"    {name} ({atype}{', required' if required else ', optional'}): "
                if desc:
                    print(f"      # {desc}")
                raw = input(prompt)
                if not raw.strip():
                    if required:
                        print("      ! required - please provide a value")
                        continue
                    break
                try:
                    args[name] = self._coerce(raw, atype)
                except ValueError:
                    print(f"      ! could not parse as {atype}")
                    continue
                break
        return args

    def _llm_fill_arguments(self, spec: ToolSpec, hint: str) -> Optional[Dict[str, Any]]:
        """Ask the local LLM to produce arguments as JSON. None if unavailable."""
        if not ollama_client.available():
            return None
        schema = {n: m for n, m in spec.parameters.items()}
        prompt = (
            "You fill arguments for an OSINT function. Return ONLY a JSON object mapping "
            "argument names to values. Omit optional args you don't know.\n"
            f"Function: {spec.name}\nDescription: {spec.description}\n"
            f"Argument schema: {json.dumps(schema)}\n"
            f"Investigator hint: {hint}\n"
        )
        raw = ollama_client.complete(prompt, system="You output strictly valid JSON.")
        if not raw:
            return None
        try:
            start, end = raw.find("{"), raw.rfind("}")
            return json.loads(raw[start : end + 1])
        except (ValueError, IndexError):
            log.debug("LLM returned non-JSON args: %s", raw)
            return None

    # ------------------------------------------------------------------ #
    # execution
    # ------------------------------------------------------------------ #
    def _process_function(self, name: str, engine: Type[BaseTool]) -> None:
        spec = engine.specs.get(name)
        fn = engine.get_callable(name)
        if spec is None or fn is None:
            log.warning("function '%s' has no spec/callable", name)
            return

        args: Optional[Dict[str, Any]] = None
        if getattr(self.arguments, "use_llm", False):
            hint = input(f"\n[LLM] one-line hint for '{name}' (target/context): ")
            args = self._llm_fill_arguments(spec, hint)
            if args is not None:
                print(f"    [LLM] proposed args: {json.dumps(args)}")
        if args is None:
            args = self._get_user_arguments_for_function(spec)

        try:
            result = fn(**args)
        except Exception as exc:
            log.error("function '%s' raised: %s", name, exc)
            result = ToolResult.failure(name, f"{type(exc).__name__}: {exc}")

        if isinstance(result, ToolResult):
            print("\n" + result.to_json())
            db_funcs.add_logs_to_database(
                self.session_id or "adhoc", name, result.to_dict(),
                engine_name=engine.__name__, arguments=args, success=result.success,
            )
        else:  # a function returning a raw value still gets logged
            print("\n" + json.dumps(result, default=str, indent=2))
            db_funcs.add_logs_to_database(
                self.session_id or "adhoc", name, result,
                engine_name=engine.__name__, arguments=args,
            )

    def _prompt_for_next_run(self) -> List[str]:
        raw = input("\nRun more functions? (comma/space-separated names, blank to exit): ")
        raw = raw.replace(",", " ").strip()
        return raw.split() if raw else []

    # ------------------------------------------------------------------ #
    # entry
    # ------------------------------------------------------------------ #
    def run(self) -> None:
        names = list(getattr(self.arguments, "functions", []) or [])
        if not names:
            print("No functions selected. Use -f, or --show-all-functions to list them.")
            return
        self.session_id = db_funcs.new_session(label=" ".join(names))
        print(f"Investigation session: {self.session_id}")

        while names:
            mapping = self.map_entered_func_to_class(names)
            for name, engine in mapping.items():
                self._process_function(name, engine)
            names = self._prompt_for_next_run()

        print(f"\nSession {self.session_id} complete. "
              f"{len(db_funcs.get_runs(self.session_id))} run(s) stored.")
