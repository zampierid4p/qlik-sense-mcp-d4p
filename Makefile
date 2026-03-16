UV ?= uv
DOCKER ?= docker

.PHONY: help install dev clean build test version-patch version-minor version-major publish create-pr git-clean docker-build docker-push docker-push-latest

# Default target
help:
	@echo "Available commands:"
	@echo "  install        - Install package in development mode"
	@echo "  dev            - Setup development environment"
	@echo "  clean          - Clean build artifacts"
	@echo "  build          - Build package for distribution"
	@echo "  test           - Run tests"
	@echo "  version-patch  - Bump patch version and create PR"
	@echo "  version-minor  - Bump minor version and create PR"
	@echo "  version-major  - Bump major version and create PR"
	@echo "  publish        - Publish to PyPI (automated via GitHub Actions)"
	@echo "  docker-build   - Build Docker image locally"
	@echo "  docker-push    - Build and push Docker image to Docker Hub"
	@echo "  docker-push-latest - Push Docker image with version and latest tags"
	@echo "  create-pr      - Create pull request for current changes"
	@echo "  git-clean      - Clean git history (DESTRUCTIVE)"
	@echo ""
	@echo "Overrides:"
	@echo "  UV=<command>           Example: UV='python -m uv'"
	@echo "  DOCKER=<command>       Example Linux with sudo: DOCKER='sudo docker'"

# Development setup
install:
	$(UV) pip install -e .

dev:
	$(UV) pip install -e ".[dev]"

# Clean build artifacts
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# Build package
build: clean
	$(UV) run python -m build

# Run tests
test:
	$(UV) run pytest tests/ -v

# Version bumping with PR creation
version-patch:
	@echo "Bumping patch version..."
	$(UV) run bump2version patch
	$(MAKE) create-pr

version-minor:
	@echo "Bumping minor version..."
	$(UV) run bump2version minor
	$(MAKE) create-pr

version-major:
	@echo "Bumping major version..."
	$(UV) run bump2version major
	$(MAKE) create-pr

# Create pull request
create-pr:
	@VERSION=$$(grep '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/'); \
	BRANCH="release/v$$VERSION"; \
	echo "Creating PR for version $$VERSION on branch $$BRANCH"; \
	git checkout -b "$$BRANCH"; \
	git add .; \
	git commit -m "chore: bump version to $$VERSION"; \
	git push origin "$$BRANCH"; \
	gh pr create --title "Release v$$VERSION" --body "Automated version bump to $$VERSION" --base main --head "$$BRANCH"

# Publish (triggered by GitHub Actions)
publish: build
	@echo "Publishing via GitHub Actions - create and push a version tag"
	@echo "Example: git tag v1.0.0 && git push origin v1.0.0"

# Docker image build
docker-build:
	@IMAGE_NAME=$${DOCKER_IMAGE_NAME:-qlik-sense-mcp-server}; \
	TAG=$${DOCKER_IMAGE_TAG:-$$(grep '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/')}; \
	echo "Building $$IMAGE_NAME:$$TAG"; \
	$(DOCKER) build -t "$$IMAGE_NAME:$$TAG" .

# Docker Hub push (single tag)
docker-push: docker-build
	@DOCKERHUB_USER=$${DOCKERHUB_USER:-$${DOCKERHUB:-}}; \
	if [ -z "$$DOCKERHUB_USER" ]; then echo "Set DOCKERHUB_USER (or DOCKERHUB)"; exit 1; fi; \
	IMAGE_NAME=$${DOCKER_IMAGE_NAME:-qlik-sense-mcp-server}; \
	TAG=$${DOCKER_IMAGE_TAG:-$$(grep '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/')}; \
	LOCAL_IMAGE="$$IMAGE_NAME:$$TAG"; \
	REMOTE_IMAGE="$$DOCKERHUB_USER/$$IMAGE_NAME:$$TAG"; \
	echo "Tagging $$LOCAL_IMAGE -> $$REMOTE_IMAGE"; \
	$(DOCKER) tag "$$LOCAL_IMAGE" "$$REMOTE_IMAGE"; \
	echo "Pushing $$REMOTE_IMAGE"; \
	$(DOCKER) push "$$REMOTE_IMAGE"

# Docker Hub push (version + latest)
docker-push-latest: docker-build
	@DOCKERHUB_USER=$${DOCKERHUB_USER:-$${DOCKERHUB:-}}; \
	if [ -z "$$DOCKERHUB_USER" ]; then echo "Set DOCKERHUB_USER (or DOCKERHUB)"; exit 1; fi; \
	IMAGE_NAME=$${DOCKER_IMAGE_NAME:-qlik-sense-mcp-server}; \
	TAG=$${DOCKER_IMAGE_TAG:-$$(grep '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/')}; \
	LOCAL_IMAGE="$$IMAGE_NAME:$$TAG"; \
	REMOTE_VERSION="$$DOCKERHUB_USER/$$IMAGE_NAME:$$TAG"; \
	REMOTE_LATEST="$$DOCKERHUB_USER/$$IMAGE_NAME:latest"; \
	echo "Tagging $$LOCAL_IMAGE -> $$REMOTE_VERSION"; \
	$(DOCKER) tag "$$LOCAL_IMAGE" "$$REMOTE_VERSION"; \
	echo "Tagging $$LOCAL_IMAGE -> $$REMOTE_LATEST"; \
	$(DOCKER) tag "$$LOCAL_IMAGE" "$$REMOTE_LATEST"; \
	echo "Pushing $$REMOTE_VERSION"; \
	$(DOCKER) push "$$REMOTE_VERSION"; \
	echo "Pushing $$REMOTE_LATEST"; \
	$(DOCKER) push "$$REMOTE_LATEST"

# Clean git history (DESTRUCTIVE)
git-clean:
	@echo "WARNING: This will completely reset git history!"
	@printf "Are you sure? (y/N): "; read confirm; [ "$$confirm" = "y" ] || exit 1
	rm -rf .git
	git init
	git add .
	git commit -m "chore: initial commit"
	@echo "Git history cleaned. Set remote with: git remote add origin <url>"
