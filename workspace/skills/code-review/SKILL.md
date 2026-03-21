# Skill: Code Review

## When to activate
Task contains: "review", "audit code", "check for bugs", "code quality"

## Instructions
- Read the target file(s) completely before commenting
- Check for: unused imports, dead code, error handling gaps, type mismatches
- Check for: hardcoded values that should be configurable
- Check for: missing logging at error boundaries
- Output a structured list of findings with severity (info/warning/error)
- For each finding, suggest a specific fix
