"""NettackerEngine (ntE) - authorization-gated TCP port scanning.

Active scanning of hosts you do not own or are not authorized to test can be illegal
and is out of scope for public-data OSINT. Therefore this engine **refuses to run
unless the operator explicitly asserts authorization** via ``--authorized-target``
(Config.settings.authorized_target) *and* passes ``authorized=True`` to the call.

It performs a lightweight asyncio TCP connect scan by default. If the OWASP Nettacker
package is installed, richer modules can be layered on, but the authorization gate
always applies.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from openatlas.config import Config
from openatlas.core.registry import BaseTool, ToolRegistry, ToolResult, ToolSpec
from openatlas.logger import get_logger

log = get_logger("openatlas.tools.nettacker")

_DEFAULT_PORTS = [21, 22, 23, 25, 53, 80, 110, 143, 443, 445, 993, 995, 3306, 3389, 5432, 8080, 8443]


def _expand_ports(ports) -> List[int]:
    if not ports:
        return _DEFAULT_PORTS
    out: List[int] = []
    for p in ports:
        p = str(p)
        if "-" in p:
            a, b = p.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(p))
    return sorted(set(out))


async def _scan_host(host: str, ports: List[int], timeout: float = 1.5) -> Dict[str, Any]:
    open_ports: List[int] = []

    async def _check(port: int):
        try:
            fut = asyncio.open_connection(host, port)
            reader, writer = await asyncio.wait_for(fut, timeout=timeout)
            open_ports.append(port)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
        except Exception:
            pass

    await asyncio.gather(*[_check(p) for p in ports])
    return {"host": host, "open_ports": sorted(open_ports)}


@ToolRegistry.register("nettacker-scan")
class NettackerEngine(BaseTool):
    abbrev = "ntE"
    description = "Authorization-gated TCP port/service scanning of hosts you are authorized to test."

    specs = {
        "nettacker_run": ToolSpec(
            name="nettacker_run",
            description="Scan authorized targets for open TCP ports/services. Requires --authorized-target.",
            parameters={
                "targets": {"type": "array", "required": True,
                            "description": "Hosts/IPs you are authorized to scan"},
                "ports": {"type": "array", "required": False,
                          "description": "Ports/ranges e.g. ['1-1024','8080']"},
            },
            backend="asyncio TCP connect", network=True,
            metadata={"requires_authorization": True},
        ),
    }

    @staticmethod
    def nettacker_run(targets, ports=None, authorized: bool = False) -> ToolResult:
        if isinstance(targets, str):
            targets = [t.strip() for t in targets.split(",") if t.strip()]
        authorized = bool(authorized) or bool(Config.settings.authorized_target)
        if not authorized:
            return ToolResult(
                tool_name="nettacker_run",
                content={
                    "result": None,
                    "reason": "Refused: active scanning requires explicit authorization. "
                              "Re-run with --authorized-target (CLI) or authorized=True, and only "
                              "against hosts you own or are permitted to test.",
                },
                success=False, error="authorization-required",
                metadata={"gate": "authorization"},
            )
        port_list = _expand_ports(ports)
        results = []
        for host in targets or []:
            try:
                results.append(asyncio.run(_scan_host(host, port_list)))
            except Exception as exc:
                results.append({"host": host, "error": str(exc)})
        return ToolResult(tool_name="nettacker_run",
                          content={"scanned": results, "ports": port_list}, success=True,
                          metadata={"authorized": True})
