"""Stage 7 — Google Sheets output via a service account (gspread).

Same auth pattern and write shape as ic_pipeline/sheets.py in the funded
pipeline (Rayanabid22/IC-Outreach), but writing to this pipeline's own tabs
("Bootstrapped Leads" / "Bootstrapped Processed" / "Bootstrapped Rejected")
and additionally READING the funded pipeline's Processed tab so the two
pipelines never overlap.
"""

import json
import os

import gspread

import config
from .dedup import normalize_name
from .models import LEADS_HEADERS, PROCESSED_HEADERS, REJECTED_HEADERS


def _service_account():
    """credentials.json on disk, or the GOOGLE_CREDENTIALS_JSON env var."""
    if os.path.exists(config.CREDENTIALS_FILE):
        return gspread.service_account(filename=config.CREDENTIALS_FILE)
    raw = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
    if raw:
        return gspread.service_account_from_dict(json.loads(raw))
    raise SystemExit(
        "No Google credentials found: place the service-account key at "
        f"{config.CREDENTIALS_FILE} or set GOOGLE_CREDENTIALS_JSON to its "
        "full JSON contents (see README)."
    )


class SheetWriter:
    def __init__(self):
        if not config.SHEET_ID:
            raise SystemExit(
                "SHEET_ID is not set. Export SHEET_ID=<your sheet id> or set it "
                "in config.py (see README for setup)."
            )
        self._gc = _service_account()
        self.sheet = self._gc.open_by_key(config.SHEET_ID)
        self.leads = self._ensure_tab(config.LEADS_TAB, LEADS_HEADERS)
        self.processed = self._ensure_tab(config.PROCESSED_TAB, PROCESSED_HEADERS)
        self.rejected = self._ensure_tab(config.REJECTED_TAB, REJECTED_HEADERS)

    def _ensure_tab(self, title: str, headers: list[str]):
        try:
            ws = self.sheet.worksheet(title)
        except gspread.WorksheetNotFound:
            ws = self.sheet.add_worksheet(title=title, rows=1000, cols=len(headers) + 2)
        first_row = ws.row_values(1)
        if not first_row:
            ws.append_row(headers, value_input_option="RAW")
        return ws

    def load_processed_keys(self) -> set[str]:
        """Keys already recorded in THIS pipeline's Processed tab (column A)."""
        values = self.processed.col_values(1)
        return set(values[1:])  # skip header

    def load_funded_processed_keys(self) -> set[str]:
        """Keys from the FUNDED pipeline's Processed tab (cross-pipeline dedup).

        Best-effort: the funded tab may live in the same spreadsheet or in
        FUNDED_SHEET_ID; a missing tab just returns an empty set. The funded
        tab stores raw keys in column A and company names in column B — we
        take both (normalized) to be safe.
        """
        try:
            if config.FUNDED_SHEET_ID and config.FUNDED_SHEET_ID != config.SHEET_ID:
                sheet = self._gc.open_by_key(config.FUNDED_SHEET_ID)
            else:
                sheet = self.sheet
            ws = sheet.worksheet(config.FUNDED_PROCESSED_TAB)
        except gspread.WorksheetNotFound:
            print(f"[dedup] funded tab '{config.FUNDED_PROCESSED_TAB}' not found — skipping")
            return set()
        keys = set(ws.col_values(1)[1:])
        keys |= {normalize_name(name) for name in ws.col_values(2)[1:]}
        keys.discard("")
        return keys

    def append_leads(self, rows: list[list]):
        if rows:
            self.leads.append_rows(rows, value_input_option="RAW")

    def append_processed(self, rows: list[list]):
        if rows:
            self.processed.append_rows(rows, value_input_option="RAW")

    def append_rejected(self, rows: list[list]):
        if rows:
            self.rejected.append_rows(rows, value_input_option="RAW")
