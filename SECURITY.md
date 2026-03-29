# Security Policy

## Reporting a vulnerability

Please report security issues through GitHub's private vulnerability reporting:

https://github.com/boinger/give-back/security/advisories/new

Do not open a public issue for security vulnerabilities.

## Scope

give-back is a CLI tool that queries the GitHub API. It does not run a server,
store user credentials (it reads `GITHUB_TOKEN` from the environment), or
process untrusted input beyond GitHub API responses.

The most likely security-relevant issues are:

- Command injection via subprocess calls
- Token leakage in logs or error output
- Unsafe file writes (path traversal, symlink attacks)
