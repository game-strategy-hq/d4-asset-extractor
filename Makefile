# D4 Asset Extractor Makefile
# Common development tasks

# Default to local D4-install if it exists, otherwise use env var
GAME_DIR ?= $(shell test -d "D4-install/Diablo IV" && echo "D4-install/Diablo IV" || echo "$(D4_GAME_DIR)")
PYTHON ?= python
PYTEST ?= pytest

.PHONY: help install clean clean-output clean-fixtures test test-fast test-format fixtures extract

help:
	@echo "D4 Asset Extractor"
	@echo ""
	@echo "Setup:"
	@echo "  make install          Install package in editable mode"
	@echo "  make fixtures         Build test fixtures from game (requires GAME_DIR)"
	@echo ""
	@echo "Testing:"
	@echo "  make test             Run all tests"
	@echo "  make test-fast        Run fixture-based tests only (no game access needed)"
	@echo "  make test-format F=9  Run tests for specific format"
	@echo ""
	@echo "Extraction:"
	@echo "  make extract          Extract 2DUI textures (requires GAME_DIR)"
	@echo "  make extract-sample   Extract 10 textures for quick test"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean            Remove all generated files"
	@echo "  make clean-output     Remove extracted textures only"
	@echo "  make clean-fixtures   Remove test fixtures only"
	@echo ""
	@echo "Variables:"
	@echo "  GAME_DIR=/path/to/diablo  Set game directory"
	@echo "  F=9                        Format ID for test-format"
	@echo ""
	@echo "Example:"
	@echo "  make fixtures GAME_DIR=/Applications/Diablo\\ IV"
	@echo "  make test-fast"

install:
	pip install -e .

# === Fixtures ===

fixtures:
ifndef GAME_DIR
	$(error GAME_DIR is not set. Use: make fixtures GAME_DIR=/path/to/diablo)
endif
	$(PYTHON) scripts/build_test_fixtures.py "$(GAME_DIR)"

# === Testing ===

test:
	$(PYTEST) tests/ -v

test-fast:
	$(PYTEST) tests/test_format_coverage.py tests/test_corrections.py -v

test-format:
ifndef F
	$(error F is not set. Use: make test-format F=9)
endif
	$(PYTEST) tests/test_format_coverage.py -v -k "format_$(F)"

# === Extraction ===

extract:
ifndef GAME_DIR
	$(error GAME_DIR is not set. Use: make extract GAME_DIR=/path/to/diablo)
endif
	$(PYTHON) -m d4_asset_extractor extract "$(GAME_DIR)" --filter "2DUI*" --verbose

extract-sample:
ifndef GAME_DIR
	$(error GAME_DIR is not set. Use: make extract-sample GAME_DIR=/path/to/diablo)
endif
	$(PYTHON) -m d4_asset_extractor extract "$(GAME_DIR)" --filter "2DUI*" --limit 10 --verbose

extract-all:
ifndef GAME_DIR
	$(error GAME_DIR is not set. Use: make extract-all GAME_DIR=/path/to/diablo)
endif
	$(PYTHON) -m d4_asset_extractor extract "$(GAME_DIR)" --filter "*" --verbose

# === Cleanup ===

clean: clean-output clean-fixtures
	rm -rf .pytest_cache
	rm -rf src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

clean-output:
	rm -rf d4-data/textures
	rm -rf d4-data/icons
	rm -f d4-data/version.txt

clean-fixtures:
	rm -rf tests/fixtures/textures

# === Debug ===

show-offsets:
	$(PYTHON) -c "from d4_asset_extractor.texture_definition import print_offset_table; print_offset_table()"

show-formats:
	$(PYTHON) -c "from d4_asset_extractor.tex_converter import TEXTURE_FORMATS; import json; print(json.dumps(TEXTURE_FORMATS, indent=2))"
