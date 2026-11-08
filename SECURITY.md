# Security Policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| 1.1.x   | Yes       |
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
- Exposed provider API keys — revoke the key in the provider's dashboard
  (e.g. the [Groq console](https://console.groq.com) or OpenRouter) and rotate it.

## Handling API keys safely

GhostMind stores API keys in Windows Credential Manager, **one slot per
provider host** (e.g. `api.groq.com` and `openrouter.ai` each get their own
slot), with a local plaintext fallback in the app data directory only when
keyring is unavailable. Never paste your key into issues, logs, screenshots,
or pull requests — the in-app Feedback tab scrubs key patterns
(`gsk_…` / `sk-…`) before sending, but do not rely on that.
