# Docker-first entry points: every target runs in a container, so the only host
# requirement is Docker. CI systems call these same targets (GitHub Actions, Azure
# DevOps, GitLab run identical commands). LOCAL=1 runs the commands in a host .venv.
SHELL := /bin/bash
VENV ?= .venv
TOOLBOX_HASH := $(shell cat requirements-dev.txt infrastructure/docker/Dockerfile | sha256sum | cut -c1-12)
TOOLBOX ?= acr-toolbox:$(TOOLBOX_HASH)
TOOLBOX_BUILD_ARGS ?=
ifeq ($(LOCAL),1)
  RUN :=
  PY := $(VENV)/bin/python
  BIN := $(VENV)/bin/
  NEED_TOOLBOX :=
else
  RUN := docker run --rm -i -u $$(id -u):$$(id -g) -v "$(CURDIR):/src" -w /src -e ACR_CACHE_DIR=/tmp/acr-cache $(TOOLBOX)
  PY := python
  BIN :=
  NEED_TOOLBOX := toolbox
endif
ACR := $(RUN) $(PY) -m orchestrator
IMAGE ?= acr-reviewer:local
DIFF ?= examples/sample-repo/change.patch
PROFILE ?= balanced
OUT ?= out

.DEFAULT_GOAL := help
.PHONY: help toolbox dev shell lint fmt test test-fast test-security test-resilience schema-check validate docs docs-check bench bench-gate review review-offline \
        build images up up-test down logs smoke e2e resilience security sbom ci evolve deploy-test rollback watchdog clean

help: ## list targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed 's/:[^#]*## /\t/' | awk -F'\t' '{printf "  %-14s %s\n", $$1, $$2}'

toolbox: ## build the pinned tooling image (tagged by content hash; rebuilt only when its inputs change)
	@docker image inspect $(TOOLBOX) >/dev/null 2>&1 || \
	  docker build -q $(TOOLBOX_BUILD_ARGS) -f infrastructure/docker/Dockerfile --target toolbox -t $(TOOLBOX) .

dev: ## LOCAL=1 only: create .venv with the pinned dev tooling
	python3 -m venv $(VENV) && $(VENV)/bin/pip install -q -r requirements-dev.txt

shell: toolbox ## interactive shell in the toolbox
	docker run --rm -it -u $$(id -u):$$(id -g) -v "$(CURDIR):/src" -w /src $(TOOLBOX) bash

lint: $(NEED_TOOLBOX) ## ruff lint + format check
	$(RUN) $(BIN)ruff check . && $(RUN) $(BIN)ruff format --check .

fmt: $(NEED_TOOLBOX) ## apply formatting
	$(RUN) $(BIN)ruff format . && $(RUN) $(BIN)ruff check --fix .

validate: $(NEED_TOOLBOX) ## manifests, schemas, rule examples, wrapper permissions, fixtures, pins, exceptions
	$(ACR) validate
	$(RUN) $(PY) infrastructure/scripts/check_pins.py
	$(RUN) $(PY) infrastructure/scripts/check_exceptions.py

test: $(NEED_TOOLBOX) ## full test suite with coverage gate
	mkdir -p $(OUT)
	$(RUN) $(BIN)pytest --cov --cov-report=term --cov-report=xml:$(OUT)/coverage.xml --junitxml=$(OUT)/junit.xml

test-fast: $(NEED_TOOLBOX) ## unit + contract + regression tests
	$(RUN) $(BIN)pytest tests/unit tests/contract tests/regression -q

test-security: $(NEED_TOOLBOX) ## adversarial / untrusted-input suite
	$(RUN) $(BIN)pytest tests/security -q

test-resilience: $(NEED_TOOLBOX) ## fault-injection: retry, circuit breaker, cache corruption, runtime loss, deadlines
	$(RUN) $(BIN)pytest tests/unit/test_recovery.py tests/integration -q

schema-check: $(NEED_TOOLBOX) ## validate review result JSON files: make schema-check FILES="out/*.json"
	$(RUN) $(PY) -m orchestrator.schema_check $(FILES)

docs: $(NEED_TOOLBOX) ## regenerate docs/generated from source definitions
	$(ACR) docs generate

docs-check: $(NEED_TOOLBOX) ## fail if generated docs drifted or links are broken
	$(ACR) docs check
	$(RUN) $(PY) infrastructure/scripts/check_links.py

bench: $(NEED_TOOLBOX) ## run benchmarks (BENCH_PROFILE=offline by default for determinism)
	$(ACR) bench --profile $(or $(BENCH_PROFILE),offline) --out $(OUT)/bench.json

bench-gate: $(NEED_TOOLBOX) ## benchmarks + quality-gate thresholds
	$(ACR) bench --profile $(or $(BENCH_PROFILE),offline) --gate --out $(OUT)/bench.json $(BENCH_ARGS)

review: ## review DIFF in the reviewer container: make review DIFF=path/to.patch
	docker compose run --rm -T reviewer review --profile $(PROFILE) --format markdown < $(DIFF)

review-offline: $(NEED_TOOLBOX) ## review DIFF, rules only, all formats into OUT/
	$(ACR) review --profile offline --diff $(DIFF) --format json,sarif,markdown,legacy --out-dir $(OUT) --stdout markdown

build: ## build the reviewer image
	docker build -f infrastructure/docker/Dockerfile --target reviewer -t $(IMAGE) --build-arg REVISION=$$(git rev-parse HEAD 2>/dev/null || echo unknown) .

images: ## build every published image locally (base, reviewer, toolbox, fake-runtime) as acr-<target>:local
	for t in base reviewer toolbox fake-runtime; do \
	  docker build -q -f infrastructure/docker/Dockerfile --target $$t -t acr-$$t:local . || exit 1; done

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

resilience: ## watchdog bounded restart + circuit, deploy auto-rollback
	tests/end-to-end/resilience.sh

security: ## secrets, dependencies, SAST, Dockerfile and image scans (pinned scanner images)
	infrastructure/scripts/security-scan.sh $(IMAGE)

sbom: ## CycloneDX SBOM for the image
	infrastructure/scripts/security-scan.sh $(IMAGE) sbom

deploy-test: ## deploy IMAGE to a disposable test environment, smoke, auto-rollback on failure
	infrastructure/deployment/deploy.sh $(IMAGE)

rollback: ## roll back the test environment to the last verified release
	infrastructure/deployment/rollback.sh

watchdog: ## one bounded health/recovery pass over the running stack
	infrastructure/monitoring/watchdog.sh

evolve: $(NEED_TOOLBOX) ## evidence-based improvement proposal
	mkdir -p $(OUT)
	$(ACR) evolve --out $(OUT)/proposal.md

ci: validate lint test docs-check bench-gate ## everything CI runs before the container jobs

clean: ## remove local build/test outputs
	rm -rf ./out ./.acr-cache ./.pytest_cache ./.coverage
