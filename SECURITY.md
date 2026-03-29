# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| main    | Yes       |

## Reporting a Vulnerability

If you discover a security vulnerability in NEXUS OS, please report
it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

### How to Report

Email: security@venture-verse.org

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response Timeline

- Acknowledgment: within 48 hours
- Assessment: within 1 week
- Fix (if confirmed): within 30 days for critical issues

### Scope

In scope:
- Smart contract vulnerabilities (reentrancy, overflow, access control)
- Privacy pipeline bypass (data leaking off-device)
- Authentication bypass (gateway auth, wallet impersonation)
- Cryptographic weaknesses (salt prediction, hash collision)
- Privilege escalation (non-admin accessing debug functions)

Out of scope:
- Issues requiring physical access to the device (the user owns the device)
- Denial of service on a private network (no public endpoints)
- Social engineering
- Issues in upstream dependencies (Geth, Raspberry Pi OS, Python)

### Security Architecture

- All data stays on-device (private Ethereum chain, never transmitted raw)
- Gateway requires auth token for remote connections
- Debug mode permanently disableable via smart contract
- Admin permanently lockable via ImmutableOS.finalizeLock()
- First boot forces password change
- Token enforcement enabled by default
- WireGuard for all inter-node communication

### Acknowledgments

We will credit security researchers who report valid vulnerabilities
(unless they prefer to remain anonymous).
