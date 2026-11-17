import sqlite3
from gh_stars_organizer.cache import SQLiteCache
from gh_stars_organizer.classifier import RepositoryClassifier
from gh_stars_organizer.config import AppConfig


def test_upsert_search_cache(tmp_path, repo):
    cache = SQLiteCache(tmp_path / "cache.sqlite")
    cache.upsert_repositories([repo], complete=True)
    assert cache.list_repositories()[0].full_name == repo.full_name
    assert cache.get_metadata("last_sync")
    cfg = AppConfig(classification={"profile": "scientific"})
    classifier = RepositoryClassifier(cfg)
    actual = classifier.classify(repo)
    key = classifier.fingerprint()
    cache.set_classification(repo, key, actual)
    assert cache.get_classification(repo, key) == actual
    assert cache.get_classification(repo, "other") is None
    repo.description = "Major new update"
    assert cache.get_classification(repo, key) is None
    assert len(cache.search("num solver")) == 1
    cache.upsert_repositories([], complete=True)
    assert cache.list_repositories() == []
    cache.close()


def test_existing_sqlite_migrates_without_removing_old_tables(tmp_path, repo):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript('''CREATE TABLE repositories (repo_id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL,
       full_name TEXT NOT NULL, description TEXT NOT NULL, topics_json TEXT NOT NULL,
       primary_language TEXT NOT NULL, stargazer_count INTEGER NOT NULL, url TEXT NOT NULL,
       updated_at TEXT NOT NULL, archived INTEGER NOT NULL, is_fork INTEGER NOT NULL, last_seen_at TEXT NOT NULL);
       CREATE TABLE embeddings(repo_id TEXT, model TEXT, dim INTEGER, vector BLOB, updated_at TEXT);
       CREATE TABLE classifications(repo_id TEXT, model TEXT, category TEXT, created_at TEXT);
    ''')
    conn.commit()
    conn.close()
    cache = SQLiteCache(path)
    cache.upsert_repositories([repo], complete=True)
    assert cache.list_repositories()[0].languages == ["Rust"]
    assert {x[0] for x in cache.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")} >= {"embeddings", "classifications"}
    cache.close()


def test_like_fallback_when_fts_unavailable(tmp_path, repo):
    cache = SQLiteCache(tmp_path / "fallback.db")
    cache.upsert_repositories([repo], complete=True)
    cache.fts_enabled = False
    assert len(cache.search("differential equations")) == 1
    assert cache.search("missing-token") == []
    cache.close()
