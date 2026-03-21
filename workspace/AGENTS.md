# Operating Instructions

## Task Pipeline
1. **Analysis**: Assess task clarity, identify affected files, classify risk
2. **Clarification**: Ask questions if task is genuinely ambiguous (max 2 rounds)
3. **Planning**: Generate step-by-step plan with file paths and actions
4. **Approval**: Human reviews plan (risk-dependent gating)
5. **Execution**: Apply SEARCH/REPLACE patches on a git branch
6. **Validation**: Run tests, verify no regressions
7. **Commit**: Git commit with structured message, blockchain audit log

## Analysis Phase Rules
- Default to clear=true unless the task is genuinely ambiguous about WHAT to do
- Questions about code quality, edge cases, or implementation details do NOT block progress
- Those are handled during planning
- Output format: {"clear": bool, "files": ["path"], "risk": "low|medium|high", "questions": ["..."], "summary": "..."}

## Planning Phase Rules
- Each step specifies: file path, action (create/modify), description
- Keep changes minimal — do NOT add unrequested features
- Maximum 10 steps per task; exceed → ask user to break task down
- Output format: {"steps": [{"file": "path", "action": "modify|create", "description": "what to change"}]}

## Execution Phase Rules
- SEARCH/REPLACE patches only — never full-file rewrites
- SEARCH block must match file content EXACTLY (whitespace-sensitive)
- SEARCH string must be unique in the file
- Reject patches that delete >MAX_NET_DELETIONS net lines (configurable, default 20)
- Reject patches that shrink file by >20%
- Git branch per task, rollback on any failure

## Safety Rails (Programmatic)
- Scope enforcement: sub-tasks declare affected files upfront
- Git branch isolation: every task on its own branch
- Pre-commit hooks block protected paths
- Retry policy: max 2 retries with error context injection
- Coder health check: pause if ThinkPad offline instead of falling back to wrong model
