# Codex Session Recovery Install Design

Date: 2026-06-13

## Goal

Add a one-line install path for the `codex-session-recovery` skill while keeping the installable skill folder small and keeping Superpowers design and plan documents tracked in git.

## Existing State

The repository already tracks Superpowers artifacts under `docs/superpowers/`:

- `docs/superpowers/specs/2026-06-13-codex-session-recovery-design.md`
- `docs/superpowers/plans/2026-06-13-codex-session-recovery.md`

Those docs are repository history and are not part of the installed skill payload.

## Install Shape

Use the same user-facing pattern as the `glab-cli` skill repository:

```bash
curl -fsSL https://raw.githubusercontent.com/wufei-png/codex-session-recovery/main/install.sh | bash
```

The installer copies a fixed manifest into:

```bash
${CODEX_HOME:-$HOME/.codex}/skills/codex-session-recovery
```

The manifest is intentionally small:

- `SKILL.md`
- `agents/openai.yaml`
- `scripts/scan_codex_sessions.py`

The installer does not copy `README.md`, `docs/`, or `tests/` into the installed skill directory.

## Overrides

Support environment variable overrides:

- `CODEX_SESSION_RECOVERY_SKILL_DIR`: install target, useful for tests and non-default skill roots.
- `CODEX_SESSION_RECOVERY_SOURCE_DIR`: local repository source for offline tests.
- `CODEX_SESSION_RECOVERY_RAW_BASE`: alternate raw file base URL.
- `CODEX_SESSION_RECOVERY_REPO` and `CODEX_SESSION_RECOVERY_BRANCH`: alternate GitHub repository or branch.

## Safety

The installer builds the new skill contents in a temporary directory before replacing the target directory. If a source file is missing, it exits non-zero without replacing an existing installation.

Tests must set `CODEX_SESSION_RECOVERY_SKILL_DIR` to a temporary directory and must not write to real `${CODEX_HOME:-$HOME/.codex}`.

## Verification

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_install_script -v
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
python /Users/wufei2/.codex/skills/.system/skill-creator/scripts/quick_validate.py codex-session-recovery
```
