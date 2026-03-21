# Skill: Security Audit

## When to activate
Task contains: "security", "vulnerability", "audit", "penetration", "hardening"

## Instructions
- Check for: hardcoded secrets, exposed tokens, missing input validation
- Check for: path traversal (inputs that escape NEXUS_ROOT)
- Check for: command injection in subprocess calls
- Check for: unvalidated user input passed to LLM prompts
- Verify PROTECTED_PATHS list is comprehensive
- Verify git pre-commit hooks are active
- Output findings with CVSS-style severity ratings
- Risk level: HIGH — findings may require immediate action
