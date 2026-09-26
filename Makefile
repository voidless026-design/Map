# OpenAtlas developer tasks. All targets use free/local tooling.

.PHONY: help install install-all test lint verify fetch-data robots maturin-develop web clean

help:
	@echo "OpenAtlas make targets:"
	@echo "  install          Install core deps (Poetry)"
	@echo "  install-all      Install core + all optional groups (search,email,image,browser,web)"
	@echo "  test             Run the pytest suite (network/LLM mocked)"
	@echo "  lint             Run ruff + the secret/paid-key lint"
	@echo "  verify           Run the OpenAtlas self-verifier over all functions"
	@echo "  fetch-data       Download the WhatsMyName dataset into data/"
	@echo "  robots DOMAIN=x  Snapshot robots.txt/security.txt/... for a domain"
	@echo "  maturin-develop  Build the optional Rust binwalk bindings"
	@echo "  web              Launch the Streamlit UI"

install:
	poetry install

install-all:
	poetry install --with search,email,image,browser,web

test:
	poetry run pytest -q || pytest -q

lint:
	-poetry run ruff check openatlas || ruff check openatlas
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

web:
	poetry run python3 openatlas.py --start-web-server || python3 openatlas.py --start-web-server

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache
