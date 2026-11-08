# Portable entry points. CI systems call these targets so GitHub Actions, Azure
# DevOps and GitLab run identical commands.
SHELL := /bin/bash
PY ?= python3
VENV ?= .venv
BIN := $(VENV)/bin
ACR := $(PY) -m orchestrator
IMAGE ?= acr-reviewer:local
DIFF ?= examples/sample-repo/change.patch
PROFILE ?= balanced
OUT ?= out

.DEFAULT_GOAL := help
.PHONY: help dev lint fmt test test-fast validate docs docs-check bench bench-gate review review-offline \
        build up up-test down logs smoke e2e security sbom ci evolve deploy-test rollback watchdog clean

help: ## list targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

dev: ## create .venv with pinned dev tooling
	$(PY) -m venv $(VENV) && $(BIN)/pip install -q -r requirements-dev.txt

lint: ## ruff lint + format check
	$(BIN)/ruff check . && $(BIN)/ruff format --check .

fmt: ## apply formatting
	$(BIN)/ruff format . && $(BIN)/ruff check --fix .

validate: ## manifests, schemas, rule examples, wrapper permissions, fixture integrity
	$(ACR) validate

test: ## full test suite with coverage gate
	mkdir -p $(OUT)
	$(BIN)/pytest --cov --cov-report=term --cov-report=xml:$(OUT)/coverage.xml --junitxml=$(OUT)/junit.xml

test-fast: ## unit + contract tests only
	$(BIN)/pytest tests/unit tests/contract -q

docs: ## regenerate docs/generated from source definitions
	$(ACR) docs generate

docs-check: ## fail if generated docs drifted or links are broken
	$(ACR) docs check && $(PY) infrastructure/scripts/check_links.py

bench: ## run benchmarks (BENCH_PROFILE=offline by default for determinism)
	$(ACR) bench --profile $(or $(BENCH_PROFILE),offline) --out $(OUT)/bench.json

bench-gate: ## benchmarks + quality-gate thresholds
	$(ACR) bench --profile $(or $(BENCH_PROFILE),offline) --gate --out $(OUT)/bench.json

review: ## review DIFF in the reviewer container: make review DIFF=path/to.patch
	docker compose run --rm -T reviewer review --profile $(PROFILE) --format markdown < $(DIFF)

review-offline: ## review DIFF locally, rules only, all formats into OUT/
	$(ACR) review --profile offline --diff $(DIFF) --format json,sarif,markdown,legacy --out-dir $(OUT) --stdout markdown

build: ## build the reviewer image
	docker build -f infrastructure/docker/Dockerfile -t $(IMAGE) --build-arg REVISION=$$(git rev-parse HEAD 2>/dev/null || echo unknown) .

up: ## start reviewer + Ollama + model pull, wait for health
	docker compose --profile model up -d --build --wait

up-test: ## start reviewer + fake runtime (no model weights), wait for health
	docker compose --profile test up -d --build --wait

down: ## stop the stack (volumes are kept)
	docker compose --profile model --profile test down --remove-orphans

logs: ## follow logs
	docker compose --profile model --profile test logs -f --tail=100

smoke: ## smoke-test a running stack (BASE_URL, default http://127.0.0.1:8088)
	infrastructure/scripts/smoke.sh

e2e: ## build, start with fake runtime, smoke, review fixtures in the container, tear down
	tests/end-to-end/compose_e2e.sh

security: ## secrets, dependencies, SAST, Dockerfile and image scans (docker required)
	infrastructure/scripts/security-scan.sh $(IMAGE)

sbom: ## CycloneDX SBOM for the image
	infrastructure/scripts/security-scan.sh $(IMAGE) sbom

deploy-test: ## deploy IMAGE to a disposable test environment, smoke, auto-rollback on failure
	infrastructure/deployment/deploy.sh $(IMAGE)

rollback: ## roll back the test environment to the last verified release
	infrastructure/deployment/rollback.sh

watchdog: ## one bounded health/recovery pass over the running stack
	infrastructure/monitoring/watchdog.sh

evolve: ## evidence-based improvement proposal
	mkdir -p $(OUT)
	$(ACR) evolve --out $(OUT)/proposal.md

ci: validate lint test docs-check bench-gate ## everything CI runs without docker

clean: ## remove local build/test outputs
	rm -rf ./out ./.acr-cache ./.pytest_cache ./.coverage
