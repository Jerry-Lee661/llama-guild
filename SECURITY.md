# Security Policy

## Trust model

llama-multimodel-mcp is a **local, high-privilege tool** by design:

- it can start/stop llama-server processes on the machine it runs on;
- it can launch configured binaries with caller-supplied `extra_args`;
- `raw_request` sends arbitrary HTTP requests to the configured local endpoint;
- it implements **no authentication** — MCP over stdio is trusted as the local
  user.

Do not expose it over a network transport to untrusted clients, and do not set
a non-loopback `host` in config. `get-llama` scripts download and execute
prebuilt binaries from official llama.cpp GitHub releases; pin a version and
pass an expected SHA-256 for a verifiable install.

## Reporting a vulnerability

Please use GitHub's private security advisory for this repository instead of a
public issue. Include a minimal reproduction and affected version. Fixes land
as patch releases; disclosed issues are listed in the changelog.
