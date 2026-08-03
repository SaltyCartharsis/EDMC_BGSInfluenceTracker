# Project Rules for Grok Build

## Safety & Permissions
- Do not touch '.env', secrets, or credential files.
- Prefer Plan Mode for any structural or multi-file changes.
- Ask before running destructive shell commands or external network calls that mutate state.

## Tech Stack
- Language: [Python]
- Package manager: [pip / pacman]
- Testing: [pytest]
- Linting/Formatting: [ruff + black]

## Coding Standards
- Prefer clear, explicit code over cleverness.
- Use type hints / strong typing everywhere.
- Prefer 'const' / immutable patterns where practical.
- Keep functions small and focused.
- Never introduce breaking changes to public APIs without discussion.

## Build, Test & Verification (mandatory)
Before declaring any non-trivial work done:
1. Run the linter/formatter
2. Run the full test suite
3. Manually smoke-test the changed path if applicable

## Git Discipline
- Conventional Commits
- Feature branches only ('feature/', 'fix/', 'chore/')
- Never force-push to main/master
- Squash-merge preferred