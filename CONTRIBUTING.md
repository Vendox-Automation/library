# Contributing to vdx_auto_utils

## How this repo works

Only the repo owner can merge into `main`. All changes must come through a
pull request. CI must be fully green before a PR can be merged. Once merged,
the version bumps and a new release is published automatically.

---

## One-time setup

### 1. Clone the repo
```bash
git clone https://github.com/Vendox-Automation/library.git
cd library
```

### 2. Install the package in dev mode
```bash
pip install -e ".[dev]"
```

This installs `vdx_auto_utils` locally so you can import it and run tests
without reinstalling after every change.

---

## Making a change

### 1. Sync with main before starting
Always pull the latest before creating a branch — avoids merge conflicts later.
```bash
git checkout main
git pull origin main
```

### 2. Create a branch
Name your branch after what you're changing:
```bash
git checkout -b fix/database-timeout
git checkout -b feat/sharepoint-uploader
git checkout -b refactor/webscraper-click-logic
```

### 3. Make your changes and commit using the standard format
```
type(module): short description
```

| Type | When to use | Version bump |
|------|-------------|--------------|
| `feat(new-module)` | Adding a brand new module | Minor (0.X.0) |
| `feat(module-name)` | New feature in existing module | Patch (0.0.X) |
| `fix(module-name)` | Bug fix | Patch (0.0.X) |
| `refactor(module-name)` | Code cleanup, no behaviour change | Patch (0.0.X) |
| `chore(something)` | Maintenance, deps, config | Patch (0.0.X) |
| `docs(something)` | Documentation only | Patch (0.0.X) |
| `test(something)` | Adding or fixing tests | Patch (0.0.X) |

Examples:
```bash
git commit -m "fix(database): handle reconnect on timeout"
git commit -m "feat(new-module): add SharePoint uploader"
git commit -m "refactor(webscraper): simplify click fallback logic"
git commit -m "chore(deps): upgrade selenium to 4.x"
```

> **Why this matters:** The version bumper and Notion/Jira logger both parse
> this format. Commits that don't match are skipped in the Notion/Jira log
> and default to a patch bump.

### 4. Push your branch
```bash
git push origin fix/database-timeout
```

### 5. Open a Pull Request
- Go to the repo on GitHub
- You'll see a banner: **"Compare & pull request"** — click it
- Make sure the base branch is set to `main`
- Write a short description of what changed and why
- Submit the PR

### 6. Wait for CI and review
Four checks run automatically:

| Check | What it does |
|-------|-------------|
| Lint | ruff + black formatting |
| Test | pytest on Python 3.11 and 3.12 |
| Security | pip-audit CVE scan + bandit SAST |
| Build | Builds the .whl package |

All four must be green before the PR can be merged. If something fails,
fix it on your branch and push again — CI re-runs automatically.

The repo owner will review and either approve or request changes.

### 7. After your PR is merged
The following happens automatically — you don't need to do anything:

```
PR merged to main
      ↓
CI passes
      ↓
Version bumped in pyproject.toml
      ↓
New GitHub Release published with .whl attached
```

Sync your local main afterwards before starting the next piece of work:
```bash
git checkout main
git pull origin main
```

---

## Running tests locally

```bash
# Run the full test suite
pytest tests/ -v

# Run a specific test file
pytest tests/test_database.py -v

# Run a specific test
pytest tests/test_database.py::TestDatabase::test_connect_supabase_success -v
```

## Running lint locally

```bash
# Check for issues
python -m ruff check src/

# Auto-fix issues
python -m ruff check src/ --fix --unsafe-fixes

# Check black formatting
python -m black --check --target-version py312 src/

# Auto-format
python -m black --target-version py312 src/
```

---

## Installing the latest release

After a PR is merged a new release is published automatically. Install it with:

```bash
pip install "vdx_auto_utils @ https://github.com/Vendox-Automation/library/releases/latest/download/vdx_auto_utils-VERSION-py3-none-any.whl" --force-reinstall
```

> **Note:** Replace `VERSION` with the actual version number, e.g. `0.8.12`.
> You can find the latest version and exact filename on the
> [Releases page](https://github.com/Vendox-Automation/library/releases/latest).

To pin a specific version:
```bash
pip install "vdx_auto_utils @ https://github.com/Vendox-Automation/library/releases/download/v0.8.12/vdx_auto_utils-0.8.12-py3-none-any.whl"
```