"""Stage 2 — dedup across runs AND across pipelines.

Primary store is a local SQLite database (seen.db), merged on each run with:
  1. this pipeline's committed registry (data/processed.csv)
  2. the FUNDED pipeline's registry (local checkout or raw GitHub URL)
  3. both pipelines' Processed tabs on the Google Sheet (see sheets.py)

normalize_name / SeenStore / registry helpers are shared with the funded
pipeline (ic_pipeline/dedup.py in Rayanabid22/IC-Outreach) — keep in sync.
"""

import csv
import io
import os
import re
import sqlite3
from datetime import date

import config

# Text registry committed to the repo so dedup survives fresh clones.
PROCESSED_REGISTRY = os.path.join("data", "processed.csv")
REGISTRY_HEADERS = ["key", "company", "domain", "date", "outcome"]

# Legal-entity suffixes stripped when normalizing company names.
_LEGAL_SUFFIXES = (
    r"\b(incorporated|inc|llc|l\.l\.c|ltd|limited|corp|corporation|co|"
    r"plc|gmbh|s\.a|sa|bv|b\.v|ab|as|oy|pte|pty|lp|l\.p|llp|holdings|"
    r"technologies|technology|labs|group)\b\.?"
)


def normalize_name(name: str) -> str:
    """Normalize a company name into a dedup key."""
    key = (name or "").lower().strip()
    key = re.sub(r"[,\.]", " ", key)
    # Strip trailing legal suffixes repeatedly ("Acme Labs Inc" -> "acme").
    prev = None
    while prev != key:
        prev = key
        key = re.sub(_LEGAL_SUFFIXES + r"\s*$", "", key).strip()
    key = re.sub(r"[^a-z0-9]+", "", key)
    return key


class SeenStore:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS seen (
                key TEXT PRIMARY KEY,
                company TEXT,
                domain TEXT,
                first_seen TEXT,
                outcome TEXT
            )"""
        )
        self.conn.commit()

    def is_seen(self, key: str) -> bool:
        if not key:
            return True  # unparseable names are never processed
        row = self.conn.execute(
            "SELECT 1 FROM seen WHERE key = ?", (key,)
        ).fetchone()
        return row is not None

    def mark(self, key: str, company: str, domain: str, outcome: str):
        if not key:
            return
        self.conn.execute(
            "INSERT OR IGNORE INTO seen (key, company, domain, first_seen, outcome)"
            " VALUES (?, ?, ?, ?, ?)",
            (key, company, domain, date.today().isoformat(), outcome),
        )
        self.conn.commit()

    def import_keys(self, keys, note: str = "imported"):
        """Merge keys from a registry or Processed tab (cross-run/pipeline sync)."""
        for key in keys:
            if key:
                self.conn.execute(
                    "INSERT OR IGNORE INTO seen (key, company, domain, first_seen, outcome)"
                    " VALUES (?, '', '', '', ?)",
                    (key, note),
                )
        self.conn.commit()

    def close(self):
        self.conn.close()


def load_registry() -> dict[str, str]:
    """Read this pipeline's committed processed.csv registry: key -> outcome."""
    if not os.path.exists(PROCESSED_REGISTRY):
        return {}
    with open(PROCESSED_REGISTRY, newline="") as fh:
        return {row["key"]: row.get("outcome", "") for row in csv.DictReader(fh)}


def append_registry(rows: list[dict]):
    """Append rows ({key, company, domain, date, outcome}) to processed.csv."""
    os.makedirs(os.path.dirname(PROCESSED_REGISTRY), exist_ok=True)
    exists = os.path.exists(PROCESSED_REGISTRY)
    with open(PROCESSED_REGISTRY, "a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=REGISTRY_HEADERS)
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({h: row.get(h, "") for h in REGISTRY_HEADERS})


def load_funded_keys() -> set[str]:
    """Dedup keys from the FUNDED pipeline's committed registry.

    Tries local checkout paths first (fast, offline), then the raw GitHub
    URL. Best-effort — a miss just means the sheet's Processed tabs carry
    the cross-pipeline dedup on their own.
    """
    keys: set[str] = set()

    for path in config.FUNDED_REGISTRY_PATHS:
        if path and os.path.exists(path):
            try:
                with open(path, newline="") as fh:
                    keys.update(row["key"] for row in csv.DictReader(fh) if row.get("key"))
                print(f"[dedup] funded registry loaded from {path} ({len(keys)} keys)")
                return keys
            except Exception as exc:
                print(f"[dedup] warning: could not read {path}: {exc}")

    import requests

    for url in config.FUNDED_REGISTRY_URLS:
        try:
            resp = requests.get(url, timeout=20)
            if resp.status_code != 200:
                print(f"[dedup] warning: HTTP {resp.status_code} for funded registry {url}")
                continue
            reader = csv.DictReader(io.StringIO(resp.text))
            keys.update(row["key"] for row in reader if row.get("key"))
            print(f"[dedup] funded registry loaded from {url} ({len(keys)} keys)")
            return keys
        except Exception as exc:
            print(f"[dedup] warning: could not fetch funded registry {url}: {exc}")

    print("[dedup] warning: funded registry unavailable — relying on sheet Processed tabs")
    return keys
