# Contributing to vdx_auto_utils

## The one rule

**Never push directly to `main`.** All changes must come through a pull request.

This applies to everyone on the team, including the repo owner. Even a one-line fix.

## Workflow

1. Create a branch from `main`
   ```
   git checkout -b fix(database): handle connection timeout
   ```

2. Make your changes, commit using the standard format:
   ```
   type(module): short description
   ```
   Valid types: `feat`, `fix`, `refactor`, `chore`, `docs`, `test`

   Examples:
   - `feat(new-module): add SharePoint uploader`  ← bumps MINOR version
   - `fix(database): handle reconnect on timeout`  ← bumps PATCH version
   - `refactor(webscraper): simplify click fallback logic`  ← bumps PATCH version

3. Open a PR targeting `main`
   - CI will run automatically (lint, tests, security, build)
   - At least one teammate should review before merging
   - Don't merge a red PR

4. After merging, the version bumper and Notion/Jira logger run automatically

## Why the commit format matters

Your `version-bumper.yml` and `notionjira-commit-log.yml` workflows both
parse commit messages in the `type(module): description` format.

A commit that doesn't follow this format will:
- Default to a patch version bump
- Be skipped in the Notion/Jira log

## Installing the latest version

```bash
pip install git+https://github.com/Vendox-Automation/library
```