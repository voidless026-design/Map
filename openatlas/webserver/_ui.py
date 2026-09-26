"""Streamlit page for OpenAtlas. Run via openatlas.webserver.app.launch()."""

from __future__ import annotations

import json

import streamlit as st

from openatlas.core.database import db_funcs
from openatlas.core.registry import ToolRegistry, ToolResult, load_all_engines
from openatlas.utils.tool_descriptions import api_services_text

load_all_engines()

st.set_page_config(page_title="OpenAtlas", page_icon="🗺️", layout="wide")
st.title("🗺️ OpenAtlas — free / local / no-key OSINT")
st.caption("AA (Aggregate & Analyze) mode. Public data only. Respects robots.txt. No paid API keys.")

with st.sidebar:
    st.header("Backends")
    st.code(api_services_text())

engines = ToolRegistry.engines()
all_fns = ToolRegistry.all_functions()

col1, col2 = st.columns([1, 2])
with col1:
    engine_name = st.selectbox("Engine", sorted(engines.keys()))
    engine = engines[engine_name]
    fname = st.selectbox("Function", engine.function_names())
    spec = engine.specs.get(fname)
    st.write(spec.description if spec else "")

with col2:
    st.subheader(f"Arguments for `{fname}`")
    kwargs = {}
    if spec:
        for arg, meta in spec.parameters.items():
            atype = meta.get("type", "string")
            required = meta.get("required", False)
            label = f"{arg} ({atype}{', required' if required else ''})"
            if atype == "boolean":
                kwargs[arg] = st.checkbox(label)
            elif atype in ("integer", "number"):
                val = st.text_input(label, value="")
                if val.strip():
                    kwargs[arg] = int(val) if atype == "integer" else float(val)
            elif atype == "array":
                val = st.text_input(label + " (comma-separated)", value="")
                if val.strip():
                    kwargs[arg] = [x.strip() for x in val.split(",") if x.strip()]
            else:
                val = st.text_input(label, value="")
                if val.strip():
                    kwargs[arg] = val

    if st.button("Run", type="primary"):
        fn = engine.get_callable(fname)
        with st.spinner(f"Running {fname}..."):
            result = fn(**kwargs)
        if isinstance(result, ToolResult):
            (st.success if result.success else st.warning)(
                "ok" if result.success else f"degraded: {result.error}"
            )
            st.json(result.to_dict())
            sid = db_funcs.new_session(label=f"web:{fname}")
            db_funcs.add_logs_to_database(sid, fname, result.to_dict(),
                                          engine_name=engine.__name__, arguments=kwargs,
                                          success=result.success)
        else:
            st.json(json.loads(json.dumps(result, default=str)))
