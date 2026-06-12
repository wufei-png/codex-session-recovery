#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


@dataclass
class MutableRecord:
    thread_id: str
    cwd: str | None = None
    started_at: datetime | None = None
    updated_at: datetime | None = None
    archived_sources: int = 0
    active_sources: int = 0
    subagent: bool = False
    source_paths: set[str] = field(default_factory=set)
    user_prompts: list[str] = field(default_factory=list)
    summaries: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    score: int = 0
    matching_reasons: list[str] = field(default_factory=list)

    @property
    def archived(self) -> bool:
        return self.archived_sources > 0 and self.active_sources == 0

    def merge_source(self, source_path: Path, archived: bool) -> None:
        self.source_paths.add(str(source_path))
        if archived:
            self.archived_sources += 1
        else:
            self.active_sources += 1

    def absorb(self, other: "MutableRecord") -> None:
        if self.cwd is None and other.cwd is not None:
            self.cwd = other.cwd
        self.started_at = earlier(self.started_at, other.started_at)
        self.updated_at = later(self.updated_at, other.updated_at)
        self.archived_sources += other.archived_sources
        self.active_sources += other.active_sources
        self.subagent = self.subagent or other.subagent
        self.source_paths.update(other.source_paths)
        self.user_prompts.extend(other.user_prompts)
        self.summaries.extend(other.summaries)
        self.warnings.extend(other.warnings)


def default_codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_boundary(value: str | None, tz_name: str, end_of_day: bool = False) -> datetime | None:
    if value is None:
        return None
    tz = ZoneInfo(tz_name)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        parsed_date = datetime.strptime(value, "%Y-%m-%d").date()
        parsed_time = time.max if end_of_day else time.min
        return datetime.combine(parsed_date, parsed_time, tzinfo=tz)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed


def earlier(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def later(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def is_archived_path(path: Path) -> bool:
    return "archived_sessions" in path.parts


def candidate_paths(codex_home: Path, include_archived: bool) -> list[Path]:
    paths: list[Path] = []
    session_index = codex_home / "session_index.jsonl"
    if session_index.exists():
        paths.append(session_index)
    sessions_dir = codex_home / "sessions"
    if sessions_dir.exists():
        paths.extend(sorted(sessions_dir.glob("**/*.jsonl")))
    archived_dir = codex_home / "archived_sessions"
    if include_archived and archived_dir.exists():
        paths.extend(sorted(archived_dir.glob("*.jsonl")))
    return paths


def id_from_filename(path: Path) -> str | None:
    uuid_match = UUID_RE.search(path.name)
    if uuid_match:
        return uuid_match.group(0)
    match = re.search(r"rollout-\d{4}-\d{2}-\d{2}T[^-]+-(.+)\.jsonl$", path.name)
    if match:
        return match.group(1)
    return None


def extract_content_text(content: Any) -> str | None:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        return " ".join(part for part in parts if part).strip() or None
    return None


def is_subagent_source(source: Any) -> bool:
    if source == "subagent":
        return True
    if isinstance(source, dict):
        return bool(source.get("subagent"))
    return False


def record_from_index_line(obj: dict[str, Any], path: Path) -> MutableRecord | None:
    thread_id = obj.get("id") or obj.get("thread_id") or obj.get("session_id")
    if not isinstance(thread_id, str):
        return None
    path_hint = obj.get("path")
    archived = isinstance(path_hint, str) and path_hint.startswith("archived_sessions/")
    record = MutableRecord(thread_id=thread_id)
    record.merge_source(path, archived)
    cwd = obj.get("cwd")
    if isinstance(cwd, str):
        record.cwd = cwd
    record.started_at = parse_timestamp(obj.get("created_at") or obj.get("started_at"))
    record.updated_at = parse_timestamp(obj.get("updated_at") or obj.get("timestamp"))
    record.subagent = is_subagent_source(obj.get("source"))
    summary = obj.get("summary") or obj.get("title")
    if isinstance(summary, str):
        record.summaries.append(summary)
    return record


def payload_for(obj: dict[str, Any]) -> dict[str, Any]:
    payload = obj.get("payload")
    if isinstance(payload, dict):
        return payload
    return obj


def parse_jsonl(path: Path, include_archived: bool) -> tuple[list[MutableRecord], list[str]]:
    archived = is_archived_path(path)
    if archived and not include_archived:
        return [], []

    warnings: list[str] = []
    records: list[MutableRecord] = []
    current: MutableRecord | None = None

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [], [f"{path}: unreadable: {exc}"]

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            warnings.append(f"{path}:{line_number}: malformed JSON")
            continue
        if not isinstance(obj, dict):
            continue

        if path.name == "session_index.jsonl":
            indexed = record_from_index_line(obj, path)
            if indexed is not None and (include_archived or not indexed.archived):
                records.append(indexed)
            continue

        payload = payload_for(obj)
        event_time = parse_timestamp(obj.get("timestamp") or payload.get("timestamp"))

        if obj.get("type") == "session_meta" or "cwd" in payload or "id" in payload:
            thread_id = payload.get("id") or payload.get("thread_id") or id_from_filename(path)
            if not isinstance(thread_id, str):
                continue
            if current is None:
                current = MutableRecord(thread_id=thread_id)
                current.merge_source(path, archived)
            current.thread_id = thread_id
            cwd = payload.get("cwd")
            if isinstance(cwd, str):
                current.cwd = cwd
            current.started_at = earlier(current.started_at, event_time)
            current.updated_at = later(current.updated_at, event_time)
            current.subagent = current.subagent or is_subagent_source(payload.get("source"))
            continue

        if current is None:
            fallback_id = id_from_filename(path)
            if fallback_id is None:
                continue
            current = MutableRecord(thread_id=fallback_id)
            current.merge_source(path, archived)

        current.started_at = earlier(current.started_at, event_time)
        current.updated_at = later(current.updated_at, event_time)

        role = payload.get("role")
        if role == "user":
            text = extract_content_text(payload.get("content"))
            if text:
                current.user_prompts.append(text)

        summary = payload.get("summary") or payload.get("title")
        if isinstance(summary, str):
            current.summaries.append(summary)

    if current is not None:
        current.warnings.extend(warnings)
        records.append(current)
    elif warnings:
        fallback_id = id_from_filename(path)
        if fallback_id is not None:
            record = MutableRecord(thread_id=fallback_id)
            record.merge_source(path, archived)
            record.warnings.extend(warnings)
            records.append(record)
    return records, warnings


def merge_records(records: list[MutableRecord]) -> dict[str, MutableRecord]:
    merged: dict[str, MutableRecord] = {}
    for record in records:
        existing = merged.get(record.thread_id)
        if existing is None:
            merged[record.thread_id] = record
        else:
            existing.absorb(record)
    for record in merged.values():
        if record.active_sources and record.archived_sources:
            record.warnings.append("appears in active and archived sources")
    return merged


def normalize_path(value: str | None) -> str | None:
    if not value:
        return None
    return str(Path(value).expanduser())


def matches_cwd(record: MutableRecord, cwd: str | None) -> bool:
    if cwd is None:
        return True
    target = normalize_path(cwd)
    actual = normalize_path(record.cwd)
    return actual == target


def searchable_blob(record: MutableRecord) -> str:
    return "\n".join(
        [
            record.thread_id,
            record.cwd or "",
            "\n".join(record.user_prompts),
            "\n".join(record.summaries),
            "\n".join(record.source_paths),
        ]
    )


def matches_query(record: MutableRecord, query: str | None) -> bool:
    if query is None:
        return True
    return query.casefold() in searchable_blob(record).casefold()


def matches_dates(record: MutableRecord, since: datetime | None, until: datetime | None) -> bool:
    stamp = record.updated_at or record.started_at
    if stamp is None:
        return True
    if since is not None and stamp < since:
        return False
    if until is not None and stamp > until:
        return False
    return True


def score_record(record: MutableRecord, cwd: str | None, query: str | None) -> None:
    score = 0
    reasons: list[str] = []
    if cwd is not None and matches_cwd(record, cwd):
        score += 60
        reasons.append("cwd exact match")
    if not record.archived:
        score += 10
        reasons.append("active source")
    if not record.subagent:
        score += 10
        reasons.append("main session")
    if query is not None and matches_query(record, query):
        score += 20
        reasons.append("query match")
    if record.user_prompts:
        score += 5
        reasons.append("has user prompts")
    record.score = score
    record.matching_reasons = reasons


def short_prompt(record: MutableRecord, show_prompts: bool) -> tuple[str | None, str | None]:
    if not show_prompts or not record.user_prompts:
        return None, None
    first = record.user_prompts[0][:160]
    last = record.user_prompts[-1][:160]
    return first, last


def serialize_record(record: MutableRecord, show_prompts: bool) -> dict[str, Any]:
    first_prompt, last_prompt = short_prompt(record, show_prompts)
    return {
        "thread_id": record.thread_id,
        "cwd": record.cwd,
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        "archived": record.archived,
        "subagent": record.subagent,
        "source_paths": sorted(record.source_paths),
        "first_user_prompt": first_prompt,
        "last_user_prompt": last_prompt,
        "matching_reasons": record.matching_reasons,
        "confidence": record.score,
        "resume_command": f"codex resume {record.thread_id}",
        "fork_command": f"codex fork {record.thread_id}",
        "deep_link": f"codex://threads/{record.thread_id}",
        "warnings": record.warnings,
    }


def scan(options: dict[str, Any]) -> dict[str, Any]:
    codex_home = Path(options["codex_home"]).expanduser()
    include_archived = bool(options.get("include_archived", False))
    include_subagents = bool(options.get("include_subagents", False))
    cwd = options.get("cwd")
    query = options.get("query")
    tz_name = options.get("timezone") or "UTC"
    since = parse_boundary(options.get("since"), tz_name)
    until = parse_boundary(options.get("until"), tz_name, end_of_day=True)
    limit = int(options.get("limit") or 20)
    show_prompts = bool(options.get("show_prompts", False))

    warnings: list[str] = []
    if not codex_home.exists():
        return {
            "codex_home": str(codex_home),
            "records": [],
            "warnings": [f"{codex_home} does not exist"],
            "filters": options,
        }

    parsed_records: list[MutableRecord] = []
    for path in candidate_paths(codex_home, include_archived):
        records, path_warnings = parse_jsonl(path, include_archived)
        parsed_records.extend(records)
        warnings.extend(path_warnings)

    merged = merge_records(parsed_records)
    filtered: list[MutableRecord] = []
    for record in merged.values():
        if record.archived and not include_archived:
            continue
        if record.subagent and not include_subagents:
            continue
        if not matches_cwd(record, cwd):
            continue
        if not matches_query(record, query):
            continue
        if not matches_dates(record, since, until):
            continue
        score_record(record, cwd, query)
        filtered.append(record)

    floor = datetime.min.replace(tzinfo=ZoneInfo(tz_name))
    filtered.sort(
        key=lambda item: (
            item.score,
            item.updated_at or item.started_at or floor,
            item.thread_id,
        ),
        reverse=True,
    )
    selected = filtered[:limit]
    return {
        "codex_home": str(codex_home),
        "records": [serialize_record(record, show_prompts) for record in selected],
        "warnings": warnings,
        "filters": {
            "cwd": cwd,
            "since": options.get("since"),
            "until": options.get("until"),
            "timezone": tz_name,
            "query": query,
            "include_archived": include_archived,
            "include_subagents": include_subagents,
            "limit": limit,
        },
    }


def format_table(result: dict[str, Any]) -> str:
    lines = [
        f"codex_home: {result['codex_home']}",
        "thread_id | confidence | flags | updated_at | resume",
        "--- | ---: | --- | --- | ---",
    ]
    for record in result["records"]:
        flags = []
        if record["archived"]:
            flags.append("archived")
        if record["subagent"]:
            flags.append("subagent")
        if not flags:
            flags.append("active-main")
        lines.append(
            " | ".join(
                [
                    record["thread_id"],
                    str(record["confidence"]),
                    ",".join(flags),
                    record["updated_at"] or "",
                    record["resume_command"],
                ]
            )
        )
    if result["warnings"]:
        lines.append("")
        lines.append("warnings:")
        lines.extend(f"- {warning}" for warning in result["warnings"])
    if not result["records"]:
        lines.append("")
        lines.append("No matching sessions found. Relax cwd, date, archive, subagent, or query filters.")
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find local Codex sessions safely.")
    parser.add_argument("--codex-home", type=Path, default=default_codex_home())
    parser.add_argument("--cwd")
    parser.add_argument("--since")
    parser.add_argument("--until")
    parser.add_argument("--timezone", default="UTC")
    parser.add_argument("--query")
    parser.add_argument("--include-archived", action="store_true")
    parser.add_argument("--include-subagents", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--format", choices=["table", "json"], default="table")
    parser.add_argument("--show-prompts", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    result = scan(vars(args))
    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(format_table(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
