"""Persistent memory & learning for ARIUS.

Backed by SQLite (standard library) so it survives restarts with zero setup.

Three stores:
  * conversation log   - rolling dialogue history (for context windows)
  * facts              - things the user explicitly teaches the assistant
  * projects           - long-lived initiatives (e.g. a build/"suit" project)

"Learning" here is practical: durable recall + keyword retrieval that gets
fed back into the model's context. It is not model fine-tuning (impractical
on a personal machine); see the README for how real training would attach.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    role     TEXT NOT NULL,          -- 'user' | 'assistant' | 'system'
    content  TEXT NOT NULL,
    ts       REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    key      TEXT NOT NULL,
    value    TEXT NOT NULL,
    tags     TEXT NOT NULL DEFAULT '',
    ts       REAL NOT NULL,
    UNIQUE(username, key)
);
CREATE TABLE IF NOT EXISTS projects (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL UNIQUE,
    owner    TEXT NOT NULL,
    status   TEXT NOT NULL DEFAULT 'active',
    notes    TEXT NOT NULL DEFAULT '',
    data     TEXT NOT NULL DEFAULT '{}',
    ts       REAL NOT NULL
);
"""


@dataclass
class Fact:
    key: str
    value: str
    tags: str = ""
    ts: float = 0.0


@dataclass
class Project:
    name: str
    owner: str
    status: str = "active"
    notes: str = ""
    data: dict | None = None
    ts: float = 0.0


class Memory:
    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Memory":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- conversation log ---------------------------------------------------
    def add_message(self, username: str, role: str, content: str) -> None:
        self._conn.execute(
            "INSERT INTO messages (username, role, content, ts) VALUES (?, ?, ?, ?)",
            (username, role, content, time.time()),
        )
        self._conn.commit()

    def recent_messages(self, username: str | None = None, limit: int = 12) -> list[dict]:
        if username is None:
            rows = self._conn.execute(
                "SELECT role, content, ts FROM messages ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT role, content, ts FROM messages WHERE username = ? ORDER BY id DESC LIMIT ?",
                (username, limit),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    # -- facts (explicit learning) -----------------------------------------
    def learn_fact(self, username: str, key: str, value: str, tags: str = "") -> None:
        self._conn.execute(
            """INSERT INTO facts (username, key, value, tags, ts)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(username, key) DO UPDATE SET value=excluded.value,
                   tags=excluded.tags, ts=excluded.ts""",
            (username, key.strip(), value.strip(), tags, time.time()),
        )
        self._conn.commit()

    def forget_fact(self, username: str, key: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM facts WHERE username = ? AND key = ?", (username, key.strip())
        )
        self._conn.commit()
        return cur.rowcount > 0

    def list_facts(self, username: str) -> list[Fact]:
        rows = self._conn.execute(
            "SELECT key, value, tags, ts FROM facts WHERE username = ? ORDER BY key",
            (username,),
        ).fetchall()
        return [Fact(**dict(r)) for r in rows]

    def recall_facts(self, username: str, query: str, limit: int = 5) -> list[Fact]:
        """Keyword recall over the user's stored facts."""
        terms = [t for t in _tokenize(query) if len(t) >= 2]
        rows = self._conn.execute(
            "SELECT key, value, tags, ts FROM facts WHERE username = ?", (username,)
        ).fetchall()
        scored: list[tuple[int, Fact]] = []
        for r in rows:
            fact = Fact(**dict(r))
            haystack = f"{fact.key} {fact.value} {fact.tags}".lower()
            score = sum(haystack.count(t) for t in terms)
            if score:
                scored.append((score, fact))
        scored.sort(key=lambda x: (-x[0], x[1].key))
        return [f for _, f in scored[:limit]]

    # -- projects -----------------------------------------------------------
    def upsert_project(self, project: Project) -> None:
        self._conn.execute(
            """INSERT INTO projects (name, owner, status, notes, data, ts)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET status=excluded.status,
                   notes=excluded.notes, data=excluded.data, ts=excluded.ts""",
            (
                project.name,
                project.owner,
                project.status,
                project.notes,
                json.dumps(project.data or {}, ensure_ascii=False),
                time.time(),
            ),
        )
        self._conn.commit()

    def get_project(self, name: str) -> Project | None:
        row = self._conn.execute(
            "SELECT name, owner, status, notes, data, ts FROM projects WHERE name = ?",
            (name,),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["data"] = json.loads(d["data"] or "{}")
        return Project(**d)

    def list_projects(self) -> list[Project]:
        rows = self._conn.execute(
            "SELECT name, owner, status, notes, data, ts FROM projects ORDER BY ts DESC"
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["data"] = json.loads(d["data"] or "{}")
            out.append(Project(**d))
        return out


def _tokenize(text: str) -> list[str]:
    out: list[str] = []
    token = []
    for ch in text.lower():
        if ch.isalnum() or ("가" <= ch <= "힣"):  # keep Hangul syllables
            token.append(ch)
        elif token:
            out.append("".join(token))
            token = []
    if token:
        out.append("".join(token))
    return out
