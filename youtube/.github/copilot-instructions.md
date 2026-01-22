# Copilot Operating Rules (Mandatory)

You are assisting a senior software engineer.

## Hard Constraints (Non-Negotiable)
- ❌ Do NOT create new files unless I explicitly approve.
- ❌ Do NOT modify multiple files at once.
- ❌ Do NOT auto-implement changes.

## Required Workflow
Before ANY code change:
1. Present a short plan:
   - What problem you’re solving
   - Files that would change
   - Why this approach
2. Wait for explicit approval ("Approved, proceed").

## Python Coding Standards
- **Imports:** Always place imports at the top of the file, categorized (Standard Lib, Third Party, Local).
- **Structure:** Avoid "god methods." Decompose logic into small, testable, and reusable functions.
- **Logging:** Implement comprehensive logging. Every logical branch and major state change must be traceable.
- **Documentation:** Every method must have a clear docstring explaining:
  - **Purpose:** What it does.
  - **Consumers:** Who/what calls it.
  - **Logic:** Simple steps of how it works.
- **Maintenance:** If you encounter outdated or missing documentation in existing code, update it immediately as part of the task.

## Learning Mode & Diffs
- Prefer minimal diffs.
- Never introduce new abstractions unless requested.
- Explain trade-offs briefly and call out assumptions.

If these rules conflict with a request, STOP and ask for clarification.