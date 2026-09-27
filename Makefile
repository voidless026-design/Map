# OpenAtlas developer tasks. All targets use free/local tooling.

.PHONY: help install install-all test lint verify doctor skills fetch-data robots maturin-develop web brain viz clean

help:
	@echo "OpenAtlas make targets:"
	@echo "  install          Install core deps (Poetry)"
	@echo "  install-all      Install core + all optional groups (search,email,image,browser)"
	@echo "  test             Run the pytest suite (network/LLM mocked)"
	@echo "  lint             Run ruff + the secret/paid-key lint"
	@echo "  verify           Run the OpenAtlas self-verifier over all functions"
	@echo "  fetch-data       Download the WhatsMyName dataset into data/"
	@echo "  robots DOMAIN=x  Snapshot robots.txt/security.txt/... for a domain"
	@echo "  maturin-develop  Build the optional Rust binwalk bindings"
	@echo "  doctor           Verify every tool the skills use (LIVE=1 also probes public sources)"
	@echo "  skills           Lint every SKILL.md and run its documented commands"
	@echo "  web              Launch the web GUI on http://127.0.0.1:8600"
	@echo "  brain            Grow the knowledge base in the foreground (Ctrl-C to stop)"
	@echo "  viz [SESSION=id] Knowledge-graph visualizer for a session (default: latest)"

install:
	poetry install

install-all:
	poetry install --with search,email,image,browser

test:
	poetry run pytest -q || pytest -q

lint:
	-poetry run ruff check openatlas tests || ruff check openatlas tests
	poetry run python -m openatlas.utils.secret_lint openatlas || python -m openatlas.utils.secret_lint openatlas

verify:
	poetry run python3 openatlas.py --verify || python3 openatlas.py --verify

fetch-data:
	mkdir -p data
	curl -sSL -o data/wmn-data.json https://raw.githubusercontent.com/WebBreacher/WhatsMyName/main/wmn-data.json
	@echo "downloaded data/wmn-data.json"

robots:
	poetry run python3 openatlas.py --snapshot-txt $(DOMAIN) || python3 openatlas.py --snapshot-txt $(DOMAIN)

maturin-develop:
	cd rust_ext && maturin develop --release

doctor:
	python3 -m openatlas doctor $(if $(LIVE),--live,)

skills:
	python3 -m openatlas.utils.forge verify-skill --all

web:
	python3 -m openatlas serve

brain:
	python3 -m openatlas kb daemon

viz:
	poetry run python3 openatlas.py --visualize $(SESSION) || python3 openatlas.py --visualize $(SESSION)

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache
