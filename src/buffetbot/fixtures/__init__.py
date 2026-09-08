"""Packaged, explicitly synthetic source records for the offline dataset demonstration."""

import json
from importlib.resources import files

from buffetbot.contracts import MarketBar
from buffetbot.dataset_models import CorporateAction, SnapshotPlan

CASES = ("accounting", "missing_bar", "gap", "zero_volume", "incomplete_actions")


def load_fixture(case="accounting"):
    if case not in CASES:
        raise ValueError("Unknown synthetic fixture case")
    root = files(__package__)
    data = json.loads(root.joinpath("accounting.json").read_text(encoding="utf-8"))
    changes = json.loads(root.joinpath("cases.json").read_text(encoding="utf-8"))[case]
    data["plan"].update(changes.get("plan_overrides", {}))
    bars = []
    for row in data["bars"]:
        if row["session"] in changes.get("omit_sessions", []):
            continue
        row.update(changes.get("bar_overrides", {}).get(row["session"], {}))
        bars.append(MarketBar.model_validate(row))
    return (
        SnapshotPlan.model_validate(data["plan"]),
        tuple(bars),
        tuple(CorporateAction.model_validate(a) for a in data["actions"]),
    )
