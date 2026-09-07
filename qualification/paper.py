"""Actual Lumibot/Alpaca SDK code with synthetic responses at the SDK transport boundary."""

from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from alpaca.trading.client import TradingClient
from lumibot.brokers import Alpaca
from lumibot.entities import Order

from qualification.adapters import QualifiedAlpaca
from qualification.backtest import ASSET, QUOTE

ORDER_ID = "00000000-0000-4000-8000-000000000001"
CLIENT_ID = "bb002-fixture-cycle1-BBTEST-buy"
RAW_ORDER = {
    "id": ORDER_ID,
    "client_order_id": CLIENT_ID,
    "created_at": "2024-07-02T13:30:00Z",
    "updated_at": "2024-07-02T13:30:01Z",
    "submitted_at": "2024-07-02T13:30:00Z",
    "asset_id": ORDER_ID,
    "symbol": "BBTEST",
    "asset_class": "us_equity",
    "qty": "10",
    "filled_qty": "0",
    "filled_avg_price": None,
    "order_class": "simple",
    "order_type": "market",
    "type": "market",
    "side": "buy",
    "time_in_force": "day",
    "status": "new",
    "extended_hours": False,
    "legs": None,
}
RAW_POSITION = {
    "asset_id": ORDER_ID,
    "symbol": "BBTEST",
    "exchange": "NYSE",
    "asset_class": "us_equity",
    "asset_marginable": True,
    "avg_entry_price": "110.11",
    "qty": "4",
    "side": "long",
    "market_value": "440.44",
    "cost_basis": "440.44",
    "unrealized_pl": "0",
    "unrealized_plpc": "0",
    "unrealized_intraday_pl": "0",
    "unrealized_intraday_plpc": "0",
    "current_price": "110.11",
    "lastday_price": "105",
    "change_today": "0.0486667",
}
RAW_ACCOUNT = {
    "id": ORDER_ID,
    "account_number": "SYNTHETIC",
    "status": "ACTIVE",
    "currency": "USD",
    "cash": "9559.56",
    "portfolio_value": "10000",
    "long_market_value": "440.44",
    "short_market_value": "0",
    "buying_power": "9559.56",
    "regt_buying_power": "9559.56",
    "daytrading_buying_power": "9559.56",
    "non_marginable_buying_power": "9559.56",
    "pattern_day_trader": False,
    "trading_blocked": False,
    "transfers_blocked": False,
    "account_blocked": False,
    "created_at": "2024-07-01T00:00:00Z",
    "trade_suspended_by_user": False,
    "multiplier": "1",
    "shorting_enabled": False,
    "equity": "10000",
    "last_equity": "10000",
    "initial_margin": "0",
    "maintenance_margin": "0",
    "last_maintenance_margin": "0",
    "sma": "0",
    "daytrade_count": 0,
}


def broker_instance(cls=QualifiedAlpaca):
    broker = cls(
        {"API_KEY": "qualification-dummy", "API_SECRET": "qualification-dummy", "PAPER": True},
        connect_stream=False,
        start_orders_thread=False,
    )
    broker._add_subscriber(
        SimpleNamespace(
            name="BB002",
            NEW_ORDER="new",
            PARTIALLY_FILLED_ORDER="partial_fill",
            FILLED_ORDER="fill",
            add_event=lambda event, payload: None,
        )
    )
    return broker


def qualify_paper():
    calls = []
    state = {"order": deepcopy(RAW_ORDER)}

    def snapshot(quantity):
        value = Decimal("110.11") * quantity
        state["position"] = dict(
            RAW_POSITION, qty=str(quantity), market_value=str(value), cost_basis=str(value)
        )
        state["account"] = dict(RAW_ACCOUNT, cash=str(10000 - value), long_market_value=str(value))

    snapshot(0)

    def request(client, method, path, data=None, **kwargs):
        assert client._base_url.value == "https://paper-api.alpaca.markets"
        calls.append({"method": method, "path": path, "data": data})
        if method == "POST" and path == "/orders":
            assert data["client_order_id"] == CLIENT_ID
            assert data["type"] == "market" and data["time_in_force"] == "day"
            assert data["qty"] == "10"
            return deepcopy(state["order"])
        if method == "GET":
            if path == "/account":
                return state["account"]
            if path == "/positions":
                return [state["position"]] if state["position"]["qty"] != "0" else []
            if path == "/orders":
                return [deepcopy(state["order"])]
            if path in (f"/orders/{ORDER_ID}", "/orders:by_client_order_id"):
                if path.endswith("by_client_order_id"):
                    assert data["client_order_id"] == CLIENT_ID
                return deepcopy(state["order"])
        raise AssertionError(f"Unexpected transport request: {method} {path}")

    with patch.object(TradingClient, "_request", request):
        broker = broker_instance()
        order = Order(
            "BB002",
            ASSET,
            10,
            "buy",
            order_type="market",
            time_in_force="day",
            custom_params={"client_order_id": CLIENT_ID},
        )
        broker._submit_order(order)
        assert str(order.identifier) == ORDER_ID
        by_id = broker._pull_broker_order(order.identifier)
        by_client = broker.api.get_order_by_client_id(CLIENT_ID)
        assert by_id.id == by_client.id
        assert by_client.client_order_id == CLIENT_ID
        balances = broker._get_balances_at_broker(QUOTE, None)
        assert balances == (10000.0, 0.0, 10000.0)

        # Native event lifecycle: two partial executions followed by the remainder.
        broker._process_trade_event(order, "new")
        strategy = SimpleNamespace(name="BB002")
        total = 0
        for quantity, event in [(4, "partial_fill"), (2, "partial_fill"), (4, "fill")]:
            total += quantity
            snapshot(total)
            broker._process_trade_event(order, event, price=110.11, filled_quantity=quantity)
            broker.sync_positions(strategy)
            assert broker.get_tracked_position("BB002", ASSET).quantity == total
        assert order.is_filled()
        assert [t.quantity for t in order.transactions] == [4, 2, 4]
        final_balances = broker._get_balances_at_broker(QUOTE, None)
        assert final_balances == (8898.9, 1101.1, 10000.0)

        # Independent restart scenario begins from a four-share partial broker snapshot.
        state["order"].update(status="partially_filled", filled_qty="4", filled_avg_price="110.11")
        snapshot(4)
        native = broker_instance(Alpaca)
        native.sync_positions(strategy)
        native.sync_orders(strategy)
        native_order = native.get_tracked_order(by_id.id)
        native_filled = sum(t.quantity for t in native_order.transactions)
        assert native_filled == 10  # Reproduced upstream partial-import bug, not accepted behavior.

        restarted = broker_instance()
        restarted.sync_positions(strategy)
        restarted.sync_orders(strategy)
        recovered = restarted.get_tracked_order(by_id.id)
        assert sum(t.quantity for t in recovered.transactions) == 4
        assert recovered.quantity == 10 and recovered.is_active()
        assert restarted.get_tracked_position("BB002", ASSET).quantity == 4
        restarted.sync_positions(strategy)
        restarted.sync_orders(strategy)
        assert sum(t.quantity for t in recovered.transactions) == 4
        snapshot(10)
        restarted._process_trade_event(recovered, "fill", price=110.11, filled_quantity=6)
        restarted.sync_positions(strategy)
        assert sum(t.quantity for t in recovered.transactions) == 10
        assert restarted.get_tracked_position("BB002", ASSET).quantity == 10
        assert recovered.is_filled()
        assert len([c for c in calls if c["method"] == "POST"]) == 1
    return {
        "evidence_type": "synthetic SDK transport; no broker connection",
        "endpoint": "https://paper-api.alpaca.markets",
        "client_order_id": CLIENT_ID,
        "balances": list(balances),
        "final_balances": list(final_balances),
        "partial_execution_quantities": [4, 2, 4],
        "native_startup_filled_quantity": native_filled,
        "corrected_startup_filled_quantity": 4,
        "after_remaining_fill_quantity": 10,
        "post_count": 1,
        "calls": calls,
        "actual_paper": "Not run",
    }
