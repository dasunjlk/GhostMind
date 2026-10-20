# Security Policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| 1.0.x   | Yes       |
| < 1.0   | No        |

## Reporting a vulnerability

Please report security issues **privately** — do not open a public issue.

1. Go to the [Security tab](https://github.com/dasunjlk/GhostMind/security).
2. Click **Report a vulnerability** (private vulnerability reporting).
3. Include:
   - GhostMind version and Windows version
   - Steps to reproduce
   - Impact (what an attacker could achieve)
   - Relevant logs or screenshots (remove API keys first)

You will receive an acknowledgement as soon as possible. A fix and disclosure
timeline will be coordinated privately.

## Scope

**In scope:** the GhostMind desktop application, installer, update mechanism,
and build/release scripts in this repository.

**Out of scope:**

- Vulnerabilities in third-party dependencies — please report them upstream.
- Social engineering, physical access, or issues that require an already
  compromised machine.
- Exposed Groq API keys — revoke the key in the
  [Groq console](https://console.groq.com) and rotate it.

## Handling API keys safely

GhostMind stores your key in Windows Credential Manager (with a local settings
fallback). Never paste your key into issues, logs, screenshots, or pull
requests.
