# Codex Session Recovery Skill Design

Date: 2026-06-13

## Goal

Create a reusable `codex-session-recovery` skill for finding and safely recovering local Codex session history after account switches, provider switches, Desktop sidebar gaps, or similar local-history visibility problems.

The skill is CLI-first. Its default behavior is read-only discovery from local Codex state, followed by concrete recovery instructions such as `codex resume <thread_id>`, `codex fork <thread_id>`, and `codex://threads/<thread_id>` links. Desktop visibility actions are optional, capability-gated, and only run after the user explicitly asks for Desktop-visible recovery.

## Product Positioning

This skill is a local session archaeology and recovery-assistance workflow, not a Desktop database repair tool.

It should help Codex:

- Locate candidate sessions in `CODEX_HOME`.
- Explain why a session is likely relevant.
- Separate active sessions, archived sessions, subagent sessions, forks, and damaged or partial records.
- Produce CLI recovery commands and deep links.
- Optionally create, title, and pin a Desktop-visible helper thread when the current environment exposes the required thread tools and the user asks for that action.

It must not promise to import JSONL history into the Desktop sidebar or to repair `state_5.sqlite`.

## Sources And Product Boundaries

Official Codex behavior used by the design:

- `CODEX_HOME` is the root for Codex state and defaults to `~/.codex`.
- Session transcripts live under `$CODEX_HOME/sessions`; archived sessions live under `$CODEX_HOME/archived_sessions`.
- `codex resume`, `codex fork`, `codex archive`, and `codex unarchive` are stable CLI commands.
- Codex Desktop supports thread search and `codex://threads/<thread_id>` links, but Desktop UI presence is not the same thing as a callable thread-management tool surface.

Reference docs:

- https://developers.openai.com/codex/cli/reference
- https://developers.openai.com/codex/app/commands
- https://developers.openai.com/codex/app/troubleshooting
- https://developers.openai.com/codex/config-advanced

## Repository Layout

Use the repository root for development artifacts and keep the installable skill as a clean subdirectory:

```text
codex-session-recovery/
├── README.md
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-06-13-codex-session-recovery-design.md
├── codex-session-recovery/
│   ├── SKILL.md
│   ├── agents/
│   │   └── openai.yaml
│   └── scripts/
│       └── scan_codex_sessions.py
└── tests/
    ├── fixtures/
    │   └── codex_home/
    └── test_scan_codex_sessions.py
```

The installable skill folder is `codex-session-recovery/` under the repo root. That folder should contain only skill-relevant files. Tests and design docs stay outside the installable skill folder.

## Skill Trigger Description

Use this frontmatter description as the implementation baseline:

```yaml
name: codex-session-recovery
description: Find Codex session and thread IDs from read-only local Codex session history or copied fixtures, then produce CLI-first recovery instructions. Use when Codex history appears lost after account or provider changes, Codex Desktop does not show older threads, or the user asks to find, resume, fork, recover, pin, or make visible a prior Codex session. Optionally, when the current Codex environment exposes the required thread tools and the user explicitly requests Desktop visibility, create, title, and pin a helper thread.
```

## User Flows

### CLI-Only Recovery

1. Resolve the scan root from `CODEX_HOME`, or `~/.codex` when unset.
2. Run the scanner in read-only mode.
3. Filter by project path, date range, archive policy, subagent policy, and optional keywords.
4. Return a ranked list of candidates.
5. Output commands:
   - `codex resume <thread_id>` to continue an original local session.
   - `codex fork <thread_id>` to branch history without continuing the original.
   - `codex://threads/<thread_id>` as a Desktop deep link when useful.

### Desktop Visibility Request

Desktop visibility is not inferred from being in a Desktop context.

Before any Desktop-visible action, the acting agent must call `tool_search` in the current conversation and confirm that the specific needed tools are callable. The minimum action set is:

- `fork_thread`
- `set_thread_title`
- `set_thread_pinned`

Verification also needs:

- `list_threads`
- `read_thread`

Decision table:

| Runtime capability | User request | Behavior |
| --- | --- | --- |
| No required thread tools | Any request | Output CLI commands and deep links only. |
| Required tools available | User did not ask for Desktop visibility | Output CLI commands and mention Desktop visibility as optional. |
| Required tools available | User explicitly asked for Desktop visibility | Dry-run the proposed fork/title/pin actions, then execute only after confirmation or when the user's instruction already gave clear authorization. Verify with `list_threads` or `read_thread`. |

Desktop visible recovery means creating or organizing an auxiliary visible thread that points to the recovered session. It is not a byte-for-byte import of the JSONL transcript into Desktop state.

## Scanner Script

Create `scripts/scan_codex_sessions.py` as a deterministic, read-only scanner.

Primary arguments:

- `--codex-home PATH`: scan root. Defaults to `${CODEX_HOME:-~/.codex}`.
- `--cwd PATH`: filter by session working directory.
- `--since DATETIME_OR_DATE`: include sessions at or after this time.
- `--until DATETIME_OR_DATE`: include sessions before or at this time.
- `--timezone NAME`: interpret date-only input and relative labels in this timezone. Default to local timezone.
- `--query TEXT`: keyword match over user prompts, titles, paths, and summaries.
- `--include-archived`: include archived sessions. Default false.
- `--include-subagents`: include sessions marked as subagents. Default false.
- `--limit N`: limit ranked candidates.
- `--format table|json`: default table for humans, JSON for automation.
- `--show-prompts`: include short prompt snippets. Default false for privacy.

Read sources:

- `$CODEX_HOME/session_index.jsonl`
- `$CODEX_HOME/sessions/**/*.jsonl`
- `$CODEX_HOME/archived_sessions/*.jsonl`

Evidence priority:

1. Session JSONL files are the primary evidence source.
2. `session_index.jsonl` is an index and hint source.
3. File names are fallback evidence for IDs and timestamps.

Output record fields:

- `thread_id`
- `cwd`
- `started_at`
- `updated_at`
- `archived`
- `subagent`
- `source_paths`
- `first_user_prompt`
- `last_user_prompt`
- `matching_reasons`
- `confidence`
- `resume_command`
- `fork_command`
- `deep_link`
- `warnings`

The scanner should tolerate malformed JSONL lines, missing fields, duplicate IDs, and active/archived conflicts. It should skip bad lines, count them, and report warnings instead of failing the whole scan.

## Ranking

Rank candidates with stable, explainable weights:

1. Exact normalized `cwd` match.
2. Non-archived unless `--include-archived` was requested.
3. Non-subagent unless `--include-subagents` was requested.
4. Keyword matches in real user prompts.
5. Recent `updated_at`.
6. Lower confidence for path-only or filename-only evidence.

Each candidate should include `matching_reasons` so the user can judge whether to resume, fork, ignore, or ask for more detail.

## Safety Rules

Default behavior:

- Read local Codex state only.
- Do not edit real `$CODEX_HOME`.
- Do not edit `state_5.sqlite`.
- Do not copy rollout JSONL files into live Codex state.
- Do not unarchive sessions.
- Do not create, rename, pin, or archive Desktop threads.
- Do not print full conversation content by default.

Allowed only after explicit user request:

- Include archived sessions in candidate results.
- Include subagent sessions in candidate results.
- Print fuller prompt snippets or selected transcript excerpts.
- Execute Desktop-visible fork/title/pin actions when the required tools are available.

Out of scope:

- SQLite repair.
- Direct state migration between accounts.
- Direct provider metadata rewriting.
- Automatic import of arbitrary JSONL files into Desktop.

## Testing

Tests must never operate on the user's real `$CODEX_HOME`.

Test strategy:

1. Store minimal fixture files under `tests/fixtures/codex_home`.
2. Each test copies that fixture tree into a temporary directory.
3. Tests invoke the scanner with `--codex-home <tmp_copy>`.
4. Tests assert that the scanner refuses to run write-like test helpers against `Path.home() / ".codex"` or the real `CODEX_HOME`.
5. Tests do not read or write real `sessions/`, `archived_sessions/`, or `state_5.sqlite`.

Required test cases:

- Finds active sessions by exact `cwd`.
- Excludes archived sessions by default.
- Includes archived sessions only with `--include-archived`.
- Excludes subagent sessions by default.
- Includes subagent sessions only with `--include-subagents`.
- Handles malformed JSONL lines with warnings.
- Handles duplicate active/archived IDs with warnings.
- Applies date filters in the configured timezone.
- Produces stable JSON output with recovery commands.

## Error Handling

The scanner should produce actionable errors:

- Missing `CODEX_HOME`: report the resolved path and say it does not exist.
- Permission denied: report the unreadable path and continue scanning readable sources when possible.
- Empty state: report searched paths and suggest `codex resume --all` as a manual check.
- No matches: report active filters and suggest relaxing cwd, date, archive, or subagent filters.
- Incomplete Desktop tool surface: name the missing tools and fall back to CLI output.

## Implementation Constraints

- Use Python standard library only unless a strong need appears during implementation.
- Keep `SKILL.md` concise and procedural.
- Keep detailed deterministic logic in `scan_codex_sessions.py`.
- Generate `agents/openai.yaml` with the skill-creator tooling.
- Validate the skill with `quick_validate.py`.
- Run scanner tests before claiming the skill is ready.

## Acceptance Criteria

- The installable skill folder has valid `SKILL.md` frontmatter and `agents/openai.yaml`.
- The scanner can run against copied fixtures without touching real `$CODEX_HOME`.
- The scanner emits ranked candidates and recovery commands for representative fixture sessions.
- Default output excludes archived and subagent sessions.
- Desktop action instructions are capability-gated by current-session `tool_search` results and explicit user intent.
- The design avoids claims that Desktop context guarantees thread tools.
