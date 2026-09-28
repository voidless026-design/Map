"""E.V - OpenAtlas's local AI companion.

Everything runs on this PC: the language model is local Ollama, memory is a SQLite file in
``OPENATLAS_DATA_DIR/ev/``, speech recognition and the Australian voice are local models.
E.V converses, remembers (with your say-so), uses eight skills as tools, checks her own
factual answers, and asks before doing anything that touches the network, your files or
OpenAtlas commands.
"""

NAME = "E.V"
