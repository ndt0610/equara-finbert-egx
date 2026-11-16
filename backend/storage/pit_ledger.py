"""Append-only local observations. Capture time is evidence; source dates are metadata."""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "artifacts/pit_ledger/equara_us_pit.sqlite3"


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PitLedger:
    def __init__(self, path: str | Path = DEFAULT_PATH):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self._create()

    def close(self):
        self.db.close()

    def _create(self):
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS ingestion_runs (
            run_id TEXT PRIMARY KEY, source_name TEXT NOT NULL, provenance_tier TEXT NOT NULL,
            license_tag TEXT NOT NULL, started_at_utc TEXT NOT NULL, completed_at_utc TEXT NOT NULL,
            raw_hash_sha256 TEXT NOT NULL, config_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS raw_news_events (
            observation_id TEXT PRIMARY KEY, item_id TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES ingestion_runs(run_id),
            ticker TEXT NOT NULL, cik TEXT, headline TEXT NOT NULL, summary TEXT,
            source_name TEXT NOT NULL, source_url TEXT, external_event_key TEXT,
            item_type TEXT NOT NULL, sec_form_type TEXT, sec_items_json TEXT NOT NULL,
            published_at_utc TEXT, provider_accepted_at_utc TEXT, ingested_at_utc TEXT NOT NULL,
            effective_nyse_session_date TEXT, available_for_post_close_decision_date TEXT,
            provenance_tier TEXT NOT NULL, license_tag TEXT NOT NULL,
            provider_accepted_raw TEXT, publication_time_basis TEXT, source_filing_date TEXT
        );
        CREATE TABLE IF NOT EXISTS sentiment_scores (
            score_id TEXT PRIMARY KEY, observation_id TEXT NOT NULL REFERENCES raw_news_events(observation_id),
            item_id TEXT NOT NULL, model_id TEXT NOT NULL, model_revision TEXT NOT NULL,
            scored_at_utc TEXT NOT NULL, scoring_status TEXT NOT NULL,
            p_pos REAL, p_neu REAL, p_neg REAL, net_score REAL
        );
        CREATE TABLE IF NOT EXISTS eod_price_bars (
            bar_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES ingestion_runs(run_id),
            ticker TEXT NOT NULL, session_date TEXT NOT NULL, open_raw REAL NOT NULL,
            high_raw REAL, low_raw REAL, close_raw REAL NOT NULL, open_adj REAL,
            close_adj REAL, volume REAL, split_factor REAL, dividend_cash REAL,
            as_of_ingested_utc TEXT NOT NULL, provenance_tier TEXT NOT NULL,
            license_tag TEXT NOT NULL, adjustment_asof_utc TEXT,
            data_feed TEXT NOT NULL DEFAULT 'UNSPECIFIED'
        );
        """)
        if "data_feed" not in {row["name"] for row in self.db.execute("PRAGMA table_info(eod_price_bars)")}:
            self.db.execute("ALTER TABLE eod_price_bars ADD COLUMN data_feed TEXT NOT NULL DEFAULT 'UNSPECIFIED'")
        news_columns = {row["name"] for row in self.db.execute("PRAGMA table_info(raw_news_events)")}
        for name in ("provider_accepted_raw", "publication_time_basis", "source_filing_date"):
            if name not in news_columns:
                self.db.execute(f"ALTER TABLE raw_news_events ADD COLUMN {name} TEXT")
        for table in ("ingestion_runs", "raw_news_events", "sentiment_scores", "eod_price_bars"):
            for operation in ("UPDATE", "DELETE"):
                self.db.execute(f"CREATE TRIGGER IF NOT EXISTS no_{operation.lower()}_{table} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY'); END")
        self.db.commit()

    def record_run(self, source: str, tier: str, license_tag: str, payload: object,
                   started_at: str, completed_at: str, config: dict | None = None,
                   raw_hash_sha256: str | None = None) -> str:
        run_id = uuid4().hex
        raw_hash_sha256 = raw_hash_sha256 or digest(payload)
        if len(raw_hash_sha256) != 64 or any(c not in "0123456789abcdef" for c in raw_hash_sha256):
            raise ValueError("INVALID_RAW_HASH")
        self.db.execute("INSERT INTO ingestion_runs VALUES (?,?,?,?,?,?,?,?)", (
            run_id, source, tier, license_tag, started_at, completed_at, raw_hash_sha256, canonical(config or {})))
        self.db.commit()
        return run_id

    def add_news(self, run_id: str, item: dict) -> str:
        observation_id = uuid4().hex
        run = self.db.execute("SELECT provenance_tier,license_tag FROM ingestion_runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None:
            raise ValueError("UNKNOWN_RUN")
        self.db.execute("""INSERT INTO raw_news_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            observation_id, item["item_id"], run_id, item["ticker"], item.get("cik"),
            item["headline"], item.get("summary"), item["source_name"], item.get("source_url"),
            item.get("external_event_key"), item["item_type"], item.get("sec_form_type"),
            canonical(item.get("sec_items", [])), item.get("published_at_utc"),
            item.get("provider_accepted_at_utc"), item["ingested_at_utc"],
            item.get("effective_nyse_session_date"), item.get("available_for_post_close_decision_date"),
            run["provenance_tier"], run["license_tag"], item.get("provider_accepted_raw"),
            item.get("publication_time_basis", "SOURCE_PUBLISHED_AT"), item.get("source_filing_date")))
        self.db.commit()
        return observation_id

    def add_score(self, observation_id: str, item_id: str, model_id: str, revision: str,
                  scored_at: str, status: str, probabilities: dict | None = None) -> str:
        p = probabilities or {}
        if status == "SCORED":
            if (set(p) != {"positive", "neutral", "negative"}
                    or any(not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or value > 1 for value in p.values())
                    or abs(sum(p.values()) - 1) > 1e-5):
                raise ValueError("INVALID_PROBABILITIES")
        elif p:
            raise ValueError("UNSCORED_HAS_PROBABILITIES")
        score_id = uuid4().hex
        self.db.execute("INSERT INTO sentiment_scores VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
            score_id, observation_id, item_id, model_id, revision, scored_at, status,
            p.get("positive"), p.get("neutral"), p.get("negative"),
            p.get("positive", 0) - p.get("negative", 0) if status == "SCORED" else None))
        self.db.commit()
        return score_id

    def add_bar(self, run_id: str, bar: dict) -> str:
        run = self.db.execute("SELECT provenance_tier,license_tag FROM ingestion_runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None:
            raise ValueError("UNKNOWN_RUN")
        bar_id = uuid4().hex
        self.db.execute("INSERT INTO eod_price_bars VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            bar_id, run_id, bar["ticker"], bar["session_date"], bar["open_raw"],
            bar.get("high_raw"), bar.get("low_raw"), bar["close_raw"], bar.get("open_adj"),
            bar.get("close_adj"), bar.get("volume"), bar.get("split_factor"),
            bar.get("dividend_cash"), bar["as_of_ingested_utc"], run["provenance_tier"],
            run["license_tag"], bar.get("adjustment_asof_utc"), bar.get("data_feed", "UNSPECIFIED")))
        self.db.commit()
        return bar_id

    def rows(self, table: str) -> list[dict]:
        if table not in {"ingestion_runs", "raw_news_events", "sentiment_scores", "eod_price_bars"}:
            raise ValueError("UNKNOWN_TABLE")
        return [dict(row) for row in self.db.execute(f"SELECT * FROM {table}")]

    def export_run_jsonl(self, run_id: str, destination: str | Path) -> str:
        run = self.db.execute("SELECT * FROM ingestion_runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None:
            raise ValueError("UNKNOWN_RUN")
        lines = [canonical({"table": "ingestion_runs", "row": dict(run)})]
        for table in ("raw_news_events", "eod_price_bars"):
            lines.extend(canonical({"table": table, "row": dict(row)}) for row in
                         self.db.execute(f"SELECT * FROM {table} WHERE run_id=? ORDER BY rowid", (run_id,)))
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return hashlib.sha256(target.read_bytes()).hexdigest()
