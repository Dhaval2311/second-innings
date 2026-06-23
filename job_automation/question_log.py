from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

DEFAULT_ANSWERS_FILE = "user_answers.yaml"
DEFAULT_PENDING_FILE = "pending_questions.yaml"


def _answers_path(base_dir: Path, config: dict[str, Any]) -> Path:
    rel = config.get("applier", {}).get("answers_file", DEFAULT_ANSWERS_FILE)
    path = Path(rel)
    return path if path.is_absolute() else base_dir / path


def _pending_path(base_dir: Path) -> Path:
    return base_dir / DEFAULT_PENDING_FILE


def load_answers(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): str(v) for k, v in data.items() if v not in (None, "", "null")}


def save_answers(path: Path, answers: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(dict(sorted(answers.items())), allow_unicode=True), encoding="utf-8")


def load_pending(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return data if isinstance(data, list) else []


def save_pending(path: Path, entries: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(entries, allow_unicode=True), encoding="utf-8")


def learn_answers(base_dir: Path, config: dict[str, Any], new_answers: dict[str, str]) -> int:
    """Merge new Q&A pairs into user_answers.yaml. Returns count of new keys."""
    path = _answers_path(base_dir, config)
    existing = load_answers(path)
    added = 0
    for question, answer in new_answers.items():
        q = question.strip()
        a = str(answer).strip()
        if not q or not a:
            continue
        if existing.get(q) != a:
            existing[q] = a
            added += 1
    if added:
        save_answers(path, existing)
    return added


def log_unanswered(
    base_dir: Path,
    config: dict[str, Any],
    questions: list[str],
    *,
    source: str,
    company: str,
    role: str,
    job_url: str,
) -> None:
    """Record questions we could not auto-answer for later learning."""
    pending_path = _pending_path(base_dir)
    pending = load_pending(pending_path)
    answers = load_answers(_answers_path(base_dir, config))
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    for q in questions:
        q = q.strip()
        if not q or len(q) > 300:
            continue
        if any(k in q.lower() for k in answers if k.lower() in q.lower()):
            continue
        entry = {
            "question": q,
            "source": source,
            "company": company,
            "role": role,
            "job_url": job_url,
            "logged_at": ts,
            "status": "needs_answer",
        }
        if not any(e.get("question") == q and e.get("job_url") == job_url for e in pending):
            pending.append(entry)

    save_pending(pending_path, pending)


def resolve_pending_with_answers(base_dir: Path, config: dict[str, Any]) -> int:
    """Mark pending questions as resolved if we now have answers."""
    pending_path = _pending_path(base_dir)
    pending = load_pending(pending_path)
    answers = load_answers(_answers_path(base_dir, config))
    resolved = 0
    for entry in pending:
        if entry.get("status") == "resolved":
            continue
        q = entry.get("question", "")
        for key, val in answers.items():
            if key.lower() in q.lower() or q.lower() in key.lower():
                entry["status"] = "resolved"
                entry["answer"] = val
                resolved += 1
                break
    save_pending(pending_path, pending)
    return resolved