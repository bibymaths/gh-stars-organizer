"""Non-destructive SQLite migration, offline full-text search, and rule-versioned results."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .models import ClassificationResult, Repository, SearchResult


def content_hash(repo: Repository) -> str:
    return hashlib.sha256(repo.model_dump_json(exclude={"stargazer_count"}).encode()).hexdigest()

class SQLiteCache:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.fts_enabled = False
        self._migrate()

    def _migrate(self):
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS repositories (
                repo_id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL,
                full_name TEXT NOT NULL, description TEXT NOT NULL, topics_json TEXT NOT NULL,
                primary_language TEXT NOT NULL, stargazer_count INTEGER NOT NULL,
                url TEXT NOT NULL, updated_at TEXT NOT NULL, archived INTEGER NOT NULL,
                is_fork INTEGER NOT NULL, last_seen_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS classification_v2 (
                repo_id TEXT NOT NULL, rule_hash TEXT NOT NULL, content_hash TEXT NOT NULL,
                result_json TEXT NOT NULL, PRIMARY KEY(repo_id,rule_hash));
            CREATE TABLE IF NOT EXISTS applied_operations (
                plan_id TEXT NOT NULL, repo_id TEXT NOT NULL, desired_json TEXT NOT NULL,
                applied_at TEXT NOT NULL, PRIMARY KEY(plan_id,repo_id));
        ''')
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(repositories)")}
        new_columns = {
            "languages_json": "TEXT NOT NULL DEFAULT '[]'",
            "readme": "TEXT NOT NULL DEFAULT ''",
            "starred_at": "TEXT",
            "private": "INTEGER NOT NULL DEFAULT 0",
            "is_starred": "INTEGER NOT NULL DEFAULT 1",
        }
        for name, declaration in new_columns.items():
            if name not in columns:
                self.conn.execute(f"ALTER TABLE repositories ADD COLUMN {name} {declaration}")
        try:
            self.conn.execute('''CREATE VIRTUAL TABLE IF NOT EXISTS repo_fts USING fts5(
                repo_id UNINDEXED, full_name, description, topics, languages, readme)''')
            self.fts_enabled = True
        except sqlite3.OperationalError:
            # SQLite installations built without FTS5 still support offline LIKE search.
            pass
        self.conn.commit()
        if self.fts_enabled:
            old_count = self.conn.execute("SELECT count(*) FROM repo_fts").fetchone()[0]
            if not old_count:
                self.reindex()

    def upsert_repositories(self, repos: list[Repository], complete: bool = False):
        now = datetime.now(UTC).isoformat()
        with self.conn:
            for repo in repos:
                self.conn.execute('''INSERT INTO repositories
                    (repo_id,owner,name,full_name,description,topics_json,primary_language,
                    stargazer_count,url,updated_at,archived,is_fork,last_seen_at,languages_json,readme,starred_at,private,is_starred)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
                    ON CONFLICT(repo_id) DO UPDATE SET
                    owner=excluded.owner,name=excluded.name,full_name=excluded.full_name,
                    description=excluded.description,topics_json=excluded.topics_json,
                    primary_language=excluded.primary_language,stargazer_count=excluded.stargazer_count,
                    url=excluded.url,updated_at=excluded.updated_at,archived=excluded.archived,
                    is_fork=excluded.is_fork,last_seen_at=excluded.last_seen_at,
                    languages_json=excluded.languages_json,readme=excluded.readme,
                    starred_at=excluded.starred_at,private=excluded.private,is_starred=1''',
                    (repo.id, repo.owner, repo.name, repo.full_name, repo.description,
                     json.dumps(repo.topics), repo.primary_language, repo.stargazer_count,
                     repo.url, repo.updated_at.isoformat(), int(repo.archived), int(repo.is_fork),
                     now, json.dumps(repo.languages), repo.readme, repo.starred_at.isoformat() if repo.starred_at else None, int(repo.private)))
                if self.fts_enabled:
                    self.conn.execute("DELETE FROM repo_fts WHERE repo_id=?", (repo.id,))
                    self.conn.execute("INSERT INTO repo_fts VALUES(?,?,?,?,?,?)", (
                        repo.id, repo.full_name, repo.description, " ".join(repo.topics),
                        " ".join(repo.languages + [repo.primary_language]), repo.readme))
            if complete:
                ids = [x.id for x in repos]
                if ids:
                    placeholders = ",".join("?" for _ in ids)
                    self.conn.execute(f"UPDATE repositories SET is_starred=0 WHERE repo_id NOT IN ({placeholders})", ids)
                else:
                    self.conn.execute("UPDATE repositories SET is_starred=0")
                self.set_metadata("last_sync", now, commit=False)

    def reindex(self):
        if not self.fts_enabled:
            return
        with self.conn:
            self.conn.execute("DELETE FROM repo_fts")
            self.conn.execute('''INSERT INTO repo_fts SELECT repo_id, full_name, description,
                topics_json, languages_json, readme FROM repositories''')

    def last_seen(self, repo_id: str) -> datetime | None:
        row = self.conn.execute("SELECT last_seen_at FROM repositories WHERE repo_id=?", (repo_id,)).fetchone()
        return datetime.fromisoformat(row["last_seen_at"]) if row else None

    def list_repositories(self, include_unstarred: bool = False) -> list[Repository]:
        query = "SELECT * FROM repositories" + ("" if include_unstarred else " WHERE is_starred=1") + " ORDER BY full_name COLLATE NOCASE"
        return [self._repo(row) for row in self.conn.execute(query)]

    @staticmethod
    def _repo(row: sqlite3.Row) -> Repository:
        return Repository(
            id=row["repo_id"], owner=row["owner"], name=row["name"], full_name=row["full_name"],
            description=row["description"], topics=json.loads(row["topics_json"]),
            primary_language=row["primary_language"], stargazer_count=row["stargazer_count"],
            url=row["url"], updated_at=datetime.fromisoformat(row["updated_at"]),
            archived=bool(row["archived"]), is_fork=bool(row["is_fork"]), private=bool(row["private"]),
            languages=json.loads(row["languages_json"]), readme=row["readme"],
            starred_at=datetime.fromisoformat(row["starred_at"]) if row["starred_at"] else None)

    def get_classification(self, repo: Repository, rule_hash: str) -> ClassificationResult | None:
        row = self.conn.execute('''SELECT result_json FROM classification_v2
            WHERE repo_id=? AND rule_hash=? AND content_hash=?''',
            (repo.id, rule_hash, content_hash(repo))).fetchone()
        return ClassificationResult.model_validate_json(row["result_json"]) if row else None

    def set_classification(self, repo: Repository, rule_hash: str, result: ClassificationResult):
        with self.conn:
            self.conn.execute('''INSERT INTO classification_v2 VALUES(?,?,?,?) ON CONFLICT(repo_id,rule_hash)
                DO UPDATE SET content_hash=excluded.content_hash,result_json=excluded.result_json''',
                (repo.id, rule_hash, content_hash(repo), result.model_dump_json()))

    def set_metadata(self, key: str, value: str, commit: bool = True):
        self.conn.execute('''INSERT INTO metadata(key,value) VALUES(?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value''', (key, value))
        if commit:
            self.conn.commit()

    def get_metadata(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def search(self, query: str, top_k: int = 10, *, category: str | None = None,
               language: str | None = None, topic: str | None = None, archived: bool | None = None,
               results: dict[str, ClassificationResult] | None = None) -> list[SearchResult]:
        results = results or {}
        if self.fts_enabled and query.strip():
            # Parameterized MATCH expression; every query word is a literal term.
            terms = [x for x in __import__("re").findall(r"\w+", query) if x]
            if not terms:
                return []
            expression = " OR ".join('"' + x.replace('"', '""') + '"' for x in terms)
            sql = '''SELECT r.*, bm25(repo_fts) AS rank FROM repo_fts
                JOIN repositories r ON repo_fts.repo_id=r.repo_id
                WHERE repo_fts MATCH ? AND r.is_starred=1 ORDER BY rank ASC LIMIT 10000'''
            try:
                rows = self.conn.execute(sql, (expression,)).fetchall()
            except sqlite3.OperationalError:
                rows = []
        else:
            rows = self.conn.execute("SELECT *,0.0 AS rank FROM repositories WHERE is_starred=1 LIMIT 10000").fetchall()
        found: list[SearchResult] = []
        for row in rows:
            repo = self._repo(row)
            labels = results.get(repo.id, ClassificationResult(repo_id=repo.id)).categories
            if category and category.casefold() not in {c.casefold() for c in labels}:
                continue
            if language and language.casefold() not in {x.casefold() for x in [repo.primary_language, *repo.languages]}:
                continue
            if topic and topic.casefold() not in {x.casefold() for x in repo.topics}:
                continue
            if archived is not None and repo.archived != archived:
                continue
            if query and not self.fts_enabled:
                if not all(q.casefold() in (repo.full_name + " " + repo.description + " " + " ".join(repo.topics)).casefold()
                           for q in query.split()):
                    continue
            found.append(SearchResult(repository=repo, score=-float(row["rank"]), categories=labels))
        return found[:top_k]

    def record_applied(self, plan_id: str, repo_id: str, desired: list[str]):
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO applied_operations VALUES(?,?,?,?)", (
                plan_id, repo_id, json.dumps(desired), datetime.now(UTC).isoformat()))

    def applied(self, plan_id: str) -> dict[str, list[str]]:
        return {x["repo_id"]: json.loads(x["desired_json"]) for x in self.conn.execute(
            "SELECT * FROM applied_operations WHERE plan_id=?", (plan_id,))}

    def close(self):
        self.conn.close()
