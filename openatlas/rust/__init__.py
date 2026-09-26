"""Optional Rust-accelerated binary analysis (binwalk-style signature carving).

The compiled extension module ``binwalk_bindings`` is built from ``rust_ext/`` via
maturin (``make maturin-develop``). It is entirely optional: if it is not built,
``StaticImageExtractionEngine.scan_firmware`` transparently falls back to the
pure-Python signature scanner, so nothing depends on a Rust toolchain being present.
"""
