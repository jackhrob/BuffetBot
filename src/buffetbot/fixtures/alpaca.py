"""Explicitly synthetic Alpaca wire responses for the offline ingestion demonstration."""

import csv
import io
import json
from datetime import datetime, timedelta
from importlib.resources import files

from buffetbot.ingestion_models import HistoricalRequest
from buffetbot.market_http import Response

CAPTURE_TIME = datetime.fromisoformat("2026-09-08T00:00:00+00:00")


def history_request():
    return HistoricalRequest.model_validate_json(
        files(__package__).joinpath("alpaca-request.json").read_text()
    )


class SyntheticAlpaca:
    origin = "synthetic"

    def __init__(self):
        self.calls = []
        root = files(__package__)
        self.actions = json.loads(root.joinpath("alpaca-actions.json").read_text())
        self.bars = {}
        for row in csv.DictReader(io.StringIO(root.joinpath("alpaca-bars.csv").read_text())):
            opened = datetime.fromisoformat(row["open_time"])
            bars = self.bars.setdefault(row["session"], {}).setdefault(row["symbol"], [])
            for n in range(int(row["minutes"])):
                prices = {
                    key: int(row[name]) if n == 0 else int(row["close"])
                    for key, name in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"))
                }
                bars.append(
                    dict(
                        t=(opened + timedelta(minutes=n)).isoformat(),
                        **prices,
                        v=int(row["minute_volume"]),
                        n=1,
                        vw=int(row["close"]),
                    )
                )

    def get(self, path, params):
        self.calls.append((path, dict(params)))
        offset = int(params.get("page_token", "0"))
        if path == "/v2/stocks/bars":
            group = "bars"
            records = [
                (symbol, row)
                for symbol, bars in sorted(self.bars[params["start"][:10]].items())
                for row in bars
            ]
            count = 400  # Intentionally shorter than the requested 10,000-row limit.
        else:
            assert path == "/v1/corporate-actions"
            group = "corporate_actions"
            records = [(kind, row) for kind, actions in self.actions.items() for row in actions]
            count = 1
        payload = {}
        for key, row in records[offset : offset + count]:
            payload.setdefault(key, []).append(row)
        token = str(offset + count) if offset + count < len(records) else None
        body = json.dumps(
            {group: payload, "next_page_token": token}, separators=(",", ":")
        ).encode()
        return Response(body, CAPTURE_TIME, "synthetic-request")
