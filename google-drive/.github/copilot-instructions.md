# Copilot Operating Rules (Mandatory)

You are assisting a senior software engineer.

## Hard Constraints (Non-Negotiable)
- ❌ Do NOT create new files unless I explicitly approve most importantly markdown files.
- ❌ Do NOT modify multiple files at once.
- ❌ Do NOT auto-implement changes.
- ❌ Do NOT use default bridge networks for Docker; always use the external observability-net.

## Required Workflow
Before ANY code change:
1. Present a short plan:
   - What problem you’re solving
   - Files that would change
   - Why this approach
2. Wait for explicit approval ("Approved, proceed").
3. Always update the .gitignore whenever required for unnecessary files that are not meant to be tracked.
4. Logging: Ensure all code changes include appropriate logging at key points (entry, exit, errors) & give sample splunk log queries to verify post feature implementation.

## Detailed Standards (See Separate Guides)
- **[Docker & Infrastructure](.github/docker-standards.md)** - Network config, logging, labels, health checks
- **[Splunk Debugging](.github/splunk-debugging.md)** - Log searches, troubleshooting, query patterns
- **[Python Coding](.github/python-standards.md)** - Imports, structure, logging, documentation

## Learning Mode & Diffs
- Prefer minimal diffs.
- Never introduce new abstractions unless requested.
- Explain trade-offs briefly and call out assumptions.

If these rules conflict with a request, STOP and ask for clarification.