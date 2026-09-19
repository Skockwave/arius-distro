"""Persistent memory & learning for ARIUS.

Backed by SQLite (standard library) so it survives restarts with zero setup.

Stores:
  * conversation log   - rolling dialogue history (for context windows)
  * facts              - things the user explicitly teaches the assistant
  * projects           - long-lived initiatives (e.g. a build/"suit" project)
  * knowledge          - web pages the assistant has read (see web.py)
  * vectors            - embeddings of facts and knowledge passages, so recall
                         can rank by *meaning* (cosine similarity), not just
                         exact keywords. See embeddings.py.

Recall is hybrid: semantic similarity when an embedder is attached, boosted
by keyword hits; pure keyword matching otherwise. "Learning" here is durable
recall that gets fed back into the model's context — not model fine-tuning
(impractical on a personal machine; see the README).

A Memory may be used from any thread: the heartbeat runs on a background
thread while the REPL (`/agent run`) can touch the same object from the main
thread. The SQLite connection is opened with check_same_thread=False and every
operation is serialised behind a reentrant lock.
"""

from __future__ import annotations

import functools
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from arius.embeddings import Embedder, chunk_text, cosine, from_blob, to_blob
from arius.privacy import redact

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
CREATE TABLE IF NOT EXISTS knowledge (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    url      TEXT NOT NULL,
    title    TEXT NOT NULL,
    content  TEXT NOT NULL,
    ts       REAL NOT NULL,
    UNIQUE(username, url)
);
CREATE TABLE IF NOT EXISTS policies (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    text     TEXT NOT NULL,
    enabled  INTEGER NOT NULL DEFAULT 1,
    ts       REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       REAL NOT NULL,
    kind     TEXT NOT NULL,           -- 'heartbeat' | 'task' | 'action' | 'denied' | 'error'
    summary  TEXT NOT NULL,
    detail   TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS approvals (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       REAL NOT NULL,
    tool     TEXT NOT NULL,
    args_key TEXT NOT NULL DEFAULT '',  -- a short, stable rendering of the arguments
    approved INTEGER NOT NULL           -- 1 = the user said yes, 0 = no
);
CREATE TABLE IF NOT EXISTS vectors (
    kind     TEXT NOT NULL,          -- 'fact' | 'knowledge'
    username TEXT NOT NULL,
    ref      TEXT NOT NULL,          -- fact key, or knowledge url
    idx      INTEGER NOT NULL DEFAULT 0,
    text     TEXT NOT NULL,          -- the passage that was embedded
    model    TEXT NOT NULL,          -- embedder name; mismatched rows are ignored
    vec      BLOB NOT NULL,
    PRIMARY KEY (kind, username, ref, idx, model)
);
"""

# Columns added after the first release; created on open when missing.
_FACT_MIGRATIONS = (
    ("source", "TEXT NOT NULL DEFAULT 'user'"),      # who told us: user | agent | web | system
    ("confidence", "REAL NOT NULL DEFAULT 1.0"),     # 0..1
    ("confirmed_ts", "REAL NOT NULL DEFAULT 0"),     # last time the user re-confirmed it
)

# Cosine below this is treated as "unrelated" for the hashing embedder.
DEFAULT_MIN_SCORE = 0.12
_FACT_KW_BOOST = 0.15
_KNOWLEDGE_KW_BOOST = 0.05


@dataclass
class Fact:
    key: str
    value: str
    tags: str = ""
    ts: float = 0.0
    score: float = 0.0
    source: str = "user"
    confidence: float = 1.0
    confirmed_ts: float = 0.0

    def meta(self) -> str:
        """'저장 2026-09-19 · 출처 사용자 · 신뢰도 100% · 확인 2026-09-19'"""
        src = {"user": "사용자", "agent": "에이전트", "web": "웹", "system": "시스템"}.get(self.source, self.source)
        parts = [f"저장 {_date(self.ts)}", f"출처 {src}", f"신뢰도 {round(self.confidence * 100)}%"]
        if self.confirmed_ts:
            parts.append(f"확인 {_date(self.confirmed_ts)}")
        return " · ".join(parts)


@dataclass
class Project:
    name: str
    owner: str
    status: str = "active"
    notes: str = ""
    data: dict | None = None
    ts: float = 0.0


@dataclass
class Knowledge:
    url: str
    title: str
    content: str
    ts: float = 0.0
    best_chunk: str = ""  # the passage that matched best (semantic recall)
    score: float = 0.0

    def snippet(self, limit: int = 200) -> str:
        body = " ".join((self.best_chunk or self.content).split())
        return body if len(body) <= limit else body[: limit - 1] + "…"


def _locked(method):
    """Run `method` under the Memory's lock so one connection can be shared across threads."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class Memory:
    def __init__(self, db_path: str | Path = ":memory:", embedder: Embedder | None = None) -> None:
        self.db_path = str(db_path)
        self.embedder = embedder
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        # check_same_thread=False: the heartbeat thread uses a Memory built on the
        # main thread. Cross-thread use is made safe by _locked, not by SQLite.
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        have = {r["name"] for r in self._conn.execute("PRAGMA table_info(facts)").fetchall()}
        for col, decl in _FACT_MIGRATIONS:
            if col not in have:
                self._conn.execute(f"ALTER TABLE facts ADD COLUMN {col} {decl}")

    @_locked
    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Memory":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- conversation log ---------------------------------------------------
    @_locked
    def add_message(self, username: str, role: str, content: str) -> None:
        self._conn.execute(
            "INSERT INTO messages (username, role, content, ts) VALUES (?, ?, ?, ?)",
            (username, role, content, time.time()),
        )
        self._conn.commit()

    @_locked
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
    @_locked
    def learn_fact(
        self, username: str, key: str, value: str, tags: str = "", *, source: str = "user", confidence: float = 1.0
    ) -> None:
        key, value = key.strip(), value.strip()
        now = time.time()
        self._conn.execute(
            """INSERT INTO facts (username, key, value, tags, ts, source, confidence, confirmed_ts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(username, key) DO UPDATE SET value=excluded.value,
                   tags=excluded.tags, ts=excluded.ts, source=excluded.source,
                   confidence=excluded.confidence, confirmed_ts=excluded.confirmed_ts""",
            (username, key, value, tags, now, source, max(0.0, min(1.0, float(confidence))), now),
        )
        self._index_fact(username, key, value)
        self._conn.commit()

    @_locked
    def confirm_fact(self, username: str, key: str) -> bool:
        """The user re-confirmed a stored fact: bump its confirmation date and confidence."""
        cur = self._conn.execute(
            "UPDATE facts SET confirmed_ts = ?, confidence = 1.0 WHERE username = ? AND key = ?",
            (time.time(), username, key.strip()),
        )
        self._conn.commit()
        return cur.rowcount > 0

    @_locked
    def forget_fact(self, username: str, key: str) -> bool:
        key = key.strip()
        cur = self._conn.execute("DELETE FROM facts WHERE username = ? AND key = ?", (username, key))
        self._conn.execute("DELETE FROM vectors WHERE kind='fact' AND username = ? AND ref = ?", (username, key))
        self._conn.commit()
        return cur.rowcount > 0

    @_locked
    def forget_all(self, username: str) -> dict[str, int]:
        """'내 정보를 모두 잊어': facts, learned web pages, and the conversation log of one user."""
        counts = {}
        for table in ("facts", "knowledge", "messages"):
            cur = self._conn.execute(f"DELETE FROM {table} WHERE username = ?", (username,))
            counts[table] = cur.rowcount
        self._conn.execute("DELETE FROM vectors WHERE username = ?", (username,))
        self._conn.commit()
        return counts

    @_locked
    def list_facts(self, username: str) -> list[Fact]:
        rows = self._conn.execute(
            "SELECT key, value, tags, ts, source, confidence, confirmed_ts FROM facts WHERE username = ? ORDER BY key",
            (username,),
        ).fetchall()
        return [Fact(**dict(r)) for r in rows]

    @_locked
    def recall_facts(
        self, username: str, query: str, limit: int = 5, min_score: float = DEFAULT_MIN_SCORE
    ) -> list[Fact]:
        """Hybrid recall: semantic similarity (if available) boosted by keyword hits."""
        facts = self.list_facts(username)
        if not facts:
            return []
        terms = [t for t in _tokenize(query) if len(t) >= 2]
        semantic = self._semantic_scores("fact", username, query)
        ranked: list[Fact] = []
        for fact in facts:
            haystack = f"{fact.key} {fact.value} {fact.tags}".lower()
            kw = sum(haystack.count(t) for t in terms)
            score = semantic.get(fact.key, (0.0, ""))[0] + _FACT_KW_BOOST * min(kw, 3)
            if kw > 0 or score >= min_score:
                fact.score = round(score, 4)
                ranked.append(fact)
        ranked.sort(key=lambda f: (-f.score, f.key))
        return ranked[:limit]

    # -- projects -----------------------------------------------------------
    @_locked
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

    @_locked
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

    @_locked
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

    # -- knowledge (web learning) ------------------------------------------
    @_locked
    def add_knowledge(self, username: str, url: str, title: str, content: str) -> None:
        self._conn.execute(
            """INSERT INTO knowledge (username, url, title, content, ts)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(username, url) DO UPDATE SET title=excluded.title,
                   content=excluded.content, ts=excluded.ts""",
            (username, url, title, content, time.time()),
        )
        self._index_knowledge(username, url, title, content)
        self._conn.commit()

    @_locked
    def list_knowledge(self, username: str) -> list[Knowledge]:
        rows = self._conn.execute(
            "SELECT url, title, content, ts FROM knowledge WHERE username = ? ORDER BY ts DESC",
            (username,),
        ).fetchall()
        return [Knowledge(**dict(r)) for r in rows]

    @_locked
    def search_knowledge(
        self, username: str, query: str, limit: int = 5, min_score: float = DEFAULT_MIN_SCORE
    ) -> list[Knowledge]:
        """Hybrid search over learned web content; returns the best-matching passage."""
        docs = self.list_knowledge(username)
        if not docs:
            return []
        terms = [t for t in _tokenize(query) if len(t) >= 2]
        semantic = self._semantic_scores("knowledge", username, query)
        ranked: list[Knowledge] = []
        for doc in docs:
            haystack = f"{doc.title}\n{doc.content}".lower()
            kw = sum(haystack.count(t) for t in terms)
            cos, passage = semantic.get(doc.url, (0.0, ""))
            score = cos + _KNOWLEDGE_KW_BOOST * min(kw, 5)
            if kw > 0 or score >= min_score:
                doc.score = round(score, 4)
                doc.best_chunk = passage or _keyword_passage(doc.content, terms)
                ranked.append(doc)
        ranked.sort(key=lambda d: (-d.score, -d.ts))
        return ranked[:limit]

    # -- agent: policies & log --------------------------------------------
    @_locked
    def add_policy(self, text: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO policies (text, enabled, ts) VALUES (?, 1, ?)", (text.strip(), time.time())
        )
        self._conn.commit()
        return int(cur.lastrowid)

    @_locked
    def list_policies(self, enabled_only: bool = False) -> list[dict]:
        sql = "SELECT id, text, enabled, ts FROM policies"
        if enabled_only:
            sql += " WHERE enabled = 1"
        rows = self._conn.execute(sql + " ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    @_locked
    def set_policy_enabled(self, policy_id: int, enabled: bool) -> bool:
        cur = self._conn.execute("UPDATE policies SET enabled = ? WHERE id = ?", (1 if enabled else 0, policy_id))
        self._conn.commit()
        return cur.rowcount > 0

    @_locked
    def remove_policy(self, policy_id: int) -> bool:
        cur = self._conn.execute("DELETE FROM policies WHERE id = ?", (policy_id,))
        self._conn.commit()
        return cur.rowcount > 0

    @_locked
    def seed_policies(self, texts: list[str]) -> int:
        """Insert config policies that are not stored yet. Returns how many were added."""
        existing = {p["text"] for p in self.list_policies()}
        added = 0
        for t in texts:
            t = t.strip()
            if t and t not in existing:
                self.add_policy(t)
                added += 1
        return added

    @_locked
    def log_agent(self, kind: str, summary: str, detail: str = "") -> None:
        self._conn.execute(
            "INSERT INTO agent_log (ts, kind, summary, detail) VALUES (?, ?, ?, ?)",
            (time.time(), kind, redact(summary), redact(detail)),
        )
        self._conn.commit()

    @_locked
    def agent_log(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT ts, kind, summary, detail FROM agent_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    # -- behaviour learning: what the user approves / refuses -----------------
    @_locked
    def record_approval(self, tool: str, args_key: str, approved: bool) -> None:
        self._conn.execute(
            "INSERT INTO approvals (ts, tool, args_key, approved) VALUES (?, ?, ?, ?)",
            (time.time(), tool, redact(args_key)[:200], 1 if approved else 0),
        )
        self._conn.commit()

    @_locked
    def approval_stats(self, tool: str) -> tuple[int, int]:
        """(approved, refused) counts for a tool."""
        row = self._conn.execute(
            "SELECT SUM(approved) AS yes, SUM(1 - approved) AS no FROM approvals WHERE tool = ?", (tool,)
        ).fetchone()
        return int(row["yes"] or 0), int(row["no"] or 0)

    @_locked
    def approval_candidates(self, min_approvals: int = 3) -> list[dict]:
        """Tools the user keeps approving and never refused — candidates for auto_allow."""
        rows = self._conn.execute(
            """SELECT tool, SUM(approved) AS yes, SUM(1 - approved) AS no, MAX(ts) AS last
               FROM approvals GROUP BY tool HAVING yes >= ? AND no = 0 ORDER BY yes DESC""",
            (min_approvals,),
        ).fetchall()
        return [dict(r) for r in rows]

    @_locked
    def recent_approvals(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT ts, tool, args_key, approved FROM approvals ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    # -- vector index -------------------------------------------------------
    def _index_fact(self, username: str, key: str, value: str) -> None:
        if self.embedder is None:
            return
        self._conn.execute(
            "DELETE FROM vectors WHERE kind='fact' AND username = ? AND ref = ?", (username, key)
        )
        vec = self.embedder.embed(f"{key}: {value}")
        self._conn.execute(
            "INSERT INTO vectors (kind, username, ref, idx, text, model, vec) VALUES ('fact', ?, ?, 0, ?, ?, ?)",
            (username, key, f"{key}: {value}", self.embedder.name, to_blob(vec)),
        )

    def _index_knowledge(self, username: str, url: str, title: str, content: str) -> None:
        if self.embedder is None:
            return
        self._conn.execute(
            "DELETE FROM vectors WHERE kind='knowledge' AND username = ? AND ref = ?", (username, url)
        )
        chunks = chunk_text(content)
        if not chunks:
            return
        vecs = self.embedder.embed_many([f"{title}\n{c}" for c in chunks])
        self._conn.executemany(
            "INSERT INTO vectors (kind, username, ref, idx, text, model, vec) VALUES ('knowledge', ?, ?, ?, ?, ?, ?)",
            [
                (username, url, i, chunk, self.embedder.name, to_blob(vec))
                for i, (chunk, vec) in enumerate(zip(chunks, vecs))
            ],
        )

    def _semantic_scores(self, kind: str, username: str, query: str) -> dict[str, tuple[float, str]]:
        """Best cosine per ref (and the passage that achieved it)."""
        if self.embedder is None or not query.strip():
            return {}
        qv = self.embedder.embed(query)
        rows = self._conn.execute(
            "SELECT ref, text, vec FROM vectors WHERE kind = ? AND username = ? AND model = ?",
            (kind, username, self.embedder.name),
        ).fetchall()
        best: dict[str, tuple[float, str]] = {}
        for r in rows:
            score = cosine(qv, from_blob(r["vec"]))
            if score > best.get(r["ref"], (-1.0, ""))[0]:
                best[r["ref"]] = (score, r["text"])
        return best

    @_locked
    def index_size(self) -> int:
        if self.embedder is None:
            return 0
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM vectors WHERE model = ?", (self.embedder.name,)
        ).fetchone()
        return int(row["n"])

    @_locked
    def reindex(self) -> int:
        """Rebuild all vectors with the current embedder. Returns rows embedded."""
        if self.embedder is None:
            return 0
        self._conn.execute("DELETE FROM vectors WHERE model = ?", (self.embedder.name,))
        for r in self._conn.execute("SELECT username, key, value FROM facts").fetchall():
            self._index_fact(r["username"], r["key"], r["value"])
        for r in self._conn.execute("SELECT username, url, title, content FROM knowledge").fetchall():
            self._index_knowledge(r["username"], r["url"], r["title"], r["content"])
        self._conn.commit()
        return self.index_size()

    @_locked
    def ensure_index(self) -> int:
        """Embed existing data if this embedder has never indexed it (e.g. after upgrade)."""
        if self.embedder is None or self.index_size() > 0:
            return 0
        has_data = self._conn.execute(
            "SELECT (SELECT COUNT(*) FROM facts) + (SELECT COUNT(*) FROM knowledge) AS n"
        ).fetchone()["n"]
        return self.reindex() if has_data else 0


def _date(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts)) if ts else "?"


def _keyword_passage(content: str, terms: list[str], width: int = 200) -> str:
    """Fallback snippet: the region around the first keyword hit."""
    low = content.lower()
    for t in terms:
        pos = low.find(t)
        if pos != -1:
            start = max(0, pos - width // 3)
            return content[start : start + width]
    return content[:width]


def _tokenize(text: str) -> list[str]:
    out: list[str] = []
    token: list[str] = []
    for ch in text.lower():
        if ch.isalnum() or ("가" <= ch <= "힣"):  # keep Hangul syllables
            token.append(ch)
        elif token:
            out.append("".join(token))
            token = []
    if token:
        out.append("".join(token))
    return out
