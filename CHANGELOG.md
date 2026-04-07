# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project adheres to Semantic Versioning.

## [Unreleased]

## [1.5.1] - 2026-04-07

### Added
- Remote gateway startup now logs a full environment snapshot of runtime parameters for MCP/Qlik initialization

### Security
- Sensitive startup values are redacted in logs (`MCP_AUTH_TOKEN`, `MCP_AUTH_PASSPHRASE`, `MCP_JWT_SECRET`, and related secret-like keys)
- Certificate environment variables keep full paths visible (`QLIK_CLIENT_CERT_PATH`, `QLIK_CLIENT_KEY_PATH`, `QLIK_CA_CERT_PATH`) for operational troubleshooting

## [1.5.0] - 2026-04-06

### Added
- JWT HS256 authentication support for the remote gateway with configurable authentication modes: `token` (static bearer), `jwt` (HS256 signed tokens), and `both` (dual support)
- MCP_AUTH_MODE environment variable to switch between authentication modes
- JWT validation with claim verification: signature verification, exp/nbf temporal claims, optional aud/iss validation
- Complete MCP_JWT_SECRET, MCP_JWT_AUDIENCE, and MCP_JWT_ISSUER configuration variables for JWT setup
- Comprehensive documentation in README.md (new "Remote Gateway Authentication Modes" section) with auth mode examples and security recommendations
- Unit tests for JWT HS256 validation and dual authentication mode (token + JWT) in test_remote_gateway.py
- COMMANDS.md and .env.example updated with JWT authentication examples and setup instructions

### Changed
- Remote gateway initialization now accepts auth_mode parameter to support multiple authentication strategies
- Pydantic config models extended with cross-field validation to ensure authentication credentials/mode alignment
- GatewayConfig loads JWT parameters from environment variables during initialization

## [1.4.7] - 2026-04-05

### Added
- Docker healthcheck for the remote Streamable HTTP gateway and local Make targets for `remote-up`, `remote-down`, `remote-logs`, and `remote-smoke`
- Readiness endpoint `/readyz` for the remote gateway and HTTP-level tests covering auth, path normalization, and Streamable HTTP probing

### Changed
- Remote gateway startup now validates auth, Qlik connection settings, certificate paths, bind host/port, and normalized MCP route before binding the socket
- Docker Compose files now support `DOCKER_IMAGE_REF` overrides and use transport-specific behavior: stdio compose without host port publishing, remote compose with published `MCP_PUBLIC_PORT`
- README, quick commands, and example MCP client configs were fully realigned with the current stdio and remote gateway behavior

### Fixed
- Removed unsafe remote compose overrides that could clear `MCP_AUTH_TOKEN` or `MCP_AUTH_PASSPHRASE` loaded from `.env`
- Removed obsolete Compose `version` metadata from the stdio compose file to avoid Docker warnings

## [1.4.6] - 2026-03-16

### Changed
- Extended Linux setup instructions with explicit `uv` installation, PATH export steps, and validation command to resolve `uv: command not found` onboarding issues

## [1.4.5] - 2026-03-16

### Fixed
- Makefile `bootstrap-venv`: tenta `ensurepip` prima di fallire su venv privi di pip (Debian/Ubuntu senza `python3.12-full`)
- README: pacchetto corretto `python3.12-full` al posto del non esistente `python3.12-pip` per Debian/Ubuntu

## [1.4.4] - 2026-03-16

### Added
- Installation section extended with step-by-step Python 3.12 setup for macOS (Homebrew) and Linux (apt/dnf/deadsnakes PPA)
- COMMANDS.md now includes a Python Environment section for quick reference

## [1.4.3] - 2026-03-16

### Changed
- Refined README installation, configuration, Docker, usage, troubleshooting, performance, and security guidance into a more linear operational sequence
- Updated COMMANDS.md to match the current repository workflow for local setup, Docker runtime, release updates, and Docker Hub publishing
- Finalized Makefile fallback behavior for Python 3.12+ environments by preferring a local virtualenv when `uv` is unavailable

### Fixed
- Added `.venv-test` to `.gitignore` so local test virtual environments no longer leave the repository dirty

## [1.4.2] - 2026-03-16

### Changed
- Added automatic fallback in the Makefile from `uv` to `python3 -m pip` / `python3 -m ...` so development targets work in freshly cloned environments where `uv` is not installed
- Extended README setup instructions to document the `uv` fallback behavior, Linux/macOS development notes, and updated release examples to `1.4.2`

### Fixed
- Resolved `make dev` failures on clean Linux environments caused by a hard dependency on the `uv` executable

## [1.4.1] - 2026-03-16

### Changed
- Refined README instructions for macOS and Linux, including Docker prerequisites, path conventions, Claude Desktop config locations, and Git update workflow
- Improved Makefile portability for Linux by introducing configurable `UV` and `DOCKER` commands and documenting `DOCKER='sudo docker'` usage
- Extended release and deployment documentation for private Docker Hub usage and repository maintenance workflows

### Fixed
- Corrected repository update examples and release-tag references in the documentation
- Made `git-clean` prompt shell-compatible with Linux `/bin/sh` environments by replacing `read -p` with a POSIX-safe prompt flow

## [1.4.0] - 2026-03-16

### Added
- Remote MCP gateway over Streamable HTTP with dedicated `qlik-sense-mcp-gateway` entrypoint
- Token/passphrase protection for remote MCP access via `Authorization: Bearer` or `X-MCP-Token`
- Docker deployment assets for remote mode, including `docker-compose.remote.yml`
- Docker Hub publishing workflow via Makefile targets: `docker-build`, `docker-push`, `docker-push-latest`
- Shell helper script `scripts/push_dockerhub.sh` for building and pushing images to Docker Hub
- Test coverage for remote gateway auth/path helpers

### Changed
- Upgraded package metadata for the `1.4.0` release and extended project authors list with Data4Prime maintainer information
- Added `starlette` and `uvicorn` runtime dependencies to support remote HTTP transport
- Docker image metadata now points to the `data4prime/qlik-sense-mcp-d4p` repository
- Repository URLs in project metadata, CLI help, changelog links and documentation now reference `data4prime/qlik-sense-mcp-d4p`
- README significantly expanded with:
	- local Docker usage
	- private Docker Hub deployment sequence
	- remote gateway startup and validation steps
	- Claude Desktop remote MCP configuration examples

### Fixed
- Clearer initialization diagnostics when certificate files are missing, including the exact missing path
- Docker Hub publish targets now accept both `DOCKERHUB_USER` and `DOCKERHUB` variables and fail with explicit validation messages instead of shell error `127`

### Security
- Remote MCP deployment now supports configurable access control through `MCP_AUTH_TOKEN` or `MCP_AUTH_PASSPHRASE`
- Added gitignore rules for local Docker Hub credential/config helper files

## [1.3.4] - 2025-10-10

### Added
- Enhanced hypercube creation with explicit sorting options for dimensions and measures
- Support for custom sorting expressions in dimensions
- Option to create hypercubes without dimensions (measures-only)
- Improved sorting defaults: dimensions sort by ASCII ascending, measures sort by numeric descending

### Changed
- New configuration parameter `QLIK_HTTP_PORT` for metadata requests to `/api/v1/apps/{id}/data/metadata` endpoint
- Dynamic X-Qlik-Xrfkey generation for enhanced security (16 random alphanumeric characters)
- Utility function `generate_xrfkey()` for secure key generation

### Changed
- Replaced all static "0123456789abcdef" XSRF keys with dynamic generation
- Updated help output to use stderr instead of print to maintain MCP protocol compatibility
- Enhanced logging system throughout the codebase - replaced print statements with proper logging

### Removed
- Removed `size_bytes` parameter from `get_app_details` tool output (non-functional parameter)
- Eliminated all print() statements in favor of logging for MCP server compliance

### Documentation
- Updated README.md with new QLIK_HTTP_PORT configuration parameter
- Updated .env.example and mcp.json.example with QLIK_HTTP_PORT settings
- Enhanced configuration documentation with detailed parameter descriptions

## [1.3.2] - 2025-10-06

### Fixed
- Fixed published filter in get_apps function to properly handle filtering logic
- Removed numeric_value field from user variables and switched to text_value for more accurate data representation

### Changed
- Improved code readability by removing verbose output of user variable lists
- Enhanced user variable handling with better filtering for script-created variables
- Optimized variable data processing for improved performance and accuracy

## [1.3.1] - 2025-09-08

### Fixed
- Proxy API metadata request now respects `verify_ssl` configuration. Replaced conditional CA path logic with `self.config.verify_ssl` in `server.py` to ensure proper TLS verification behavior.

## [1.3.0] - 2025-09-08

### Added
- get_app_sheets: list sheets with titles and descriptions (Engine API)
- get_app_sheet_objects: list objects on a specific sheet with id, type, description (Engine API)
- get_app_object: retrieve specific object layout via GetObject + GetLayout (Engine API)

### Changed
- Upgraded MCP dependency to `mcp>=1.1.0`
- Improved logging configuration with LOG_LEVEL and structured stderr output
- Tunable Engine WebSocket behavior via environment variables: `QLIK_WS_TIMEOUT`, `QLIK_WS_RETRIES`
- Enhanced field statistics calculation and debug information in server responses
- README updated to include new tools and examples; MCP configuration extended

### Fixed
- More robust app open logic (`open_doc_safe`) and better error messages for Engine operations
- Safer cleanup for temporary session objects during Engine operations

### Documentation
- Updated `README.md` with API Reference for new tools and optional environment variables
- Updated `mcp.json.example` autoApprove list to include new tools

[Unreleased]: https://github.com/data4prime/qlik-sense-mcp-d4p/compare/v1.4.7...HEAD
[1.4.7]: https://github.com/data4prime/qlik-sense-mcp-d4p/compare/v1.4.6...v1.4.7
[1.4.6]: https://github.com/data4prime/qlik-sense-mcp-d4p/compare/v1.4.5...v1.4.6
[1.4.5]: https://github.com/data4prime/qlik-sense-mcp-d4p/compare/v1.4.4...v1.4.5
[1.4.4]: https://github.com/data4prime/qlik-sense-mcp-d4p/compare/v1.4.3...v1.4.4
[1.4.3]: https://github.com/data4prime/qlik-sense-mcp-d4p/compare/v1.4.2...v1.4.3
[1.4.2]: https://github.com/data4prime/qlik-sense-mcp-d4p/compare/v1.4.1...v1.4.2
[1.4.1]: https://github.com/data4prime/qlik-sense-mcp-d4p/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/data4prime/qlik-sense-mcp-d4p/compare/v1.3.4...v1.4.0
[1.3.4]: https://github.com/data4prime/qlik-sense-mcp-d4p/compare/v1.3.3...v1.3.4
[1.3.2]: https://github.com/data4prime/qlik-sense-mcp-d4p/compare/v1.3.1...v1.3.2
[1.3.1]: https://github.com/data4prime/qlik-sense-mcp-d4p/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/data4prime/qlik-sense-mcp-d4p/compare/v1.2.0...v1.3.0
