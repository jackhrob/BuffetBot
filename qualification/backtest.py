"""Supplied-data strategy and independently checked accounting experiments."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import joblib
import pandas as pd
import pandas_market_calendars as calendars
from lumibot.backtesting import BacktestingBroker, PandasDataBacktesting
from lumibot.entities import Asset, Data, TradingFee
from lumibot.strategies import Strategy
from lumibot.traders import Trader
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from qualification.adapters import ScheduledDividends, completed_features, validate_order

FIXTURES = Path(__file__).parent / "fixtures"
ASSET = Asset("BBTEST")
QUOTE = Asset("USD", "forex")


def load_fixture():
    bars = pd.read_csv(FIXTURES / "daily.csv")
    schedule = calendars.get_calendar("NYSE").schedule("2024-07-01", "2024-07-09")
    if bars.session.tolist() != schedule.index.strftime("%Y-%m-%d").tolist():
        raise ValueError("Daily data must contain exactly the declared exchange sessions")
    bars.index = pd.DatetimeIndex(schedule.market_open).tz_convert("America/New_York")
    bars = bars.drop(columns="session")
    features = pd.read_csv(FIXTURES / "features.csv")
    features["feature_close"] = features.feature_close.astype(float)
    features["available_at"] = pd.to_datetime(features.available_at)
    for row, close in zip(features.itertuples(), schedule.market_close, strict=True):
        if row.available_at <= close:
            raise ValueError("Features must arrive after their completed session")
    dividends = json.loads((FIXTURES / "dividends.json").read_text())
    for action in dividends:
        if date.fromisoformat(action["pay_date"]) < date.fromisoformat(action["ex_date"]):
            raise ValueError("Dividend pay date precedes ex date")
    return bars, features, dividends, schedule


def save_model(path):
    # A deterministic serialization probe, not a trained trading signal or performance claim.
    pipeline = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
    pipeline.fit([[50.0], [75.0], [100.0], [125.0]], [0.0, 0.25, 0.5, 0.75])
    joblib.dump(pipeline, path)
    return joblib.load(path)


class ProbeStrategy(Strategy):
    def initialize(self, features, dividends, model_path, splits, raw_opens):
        self.asset = ASSET
        self.features = features
        self.dividends = dividends
        self.entitlements = {}
        self.paid_dividends = set()
        self.splits = splits
        self.raw_opens = raw_opens
        self.model = joblib.load(model_path)
        self.sleeptime = "1D"
        self.snapshots = []
        self.decisions = []
        self.callback_times = []
        self.crash = None

    def on_trading_iteration(self):
        now = self.get_datetime()
        # The engine already called these hooks. Repeat on the actual split/ex/pay sessions
        # to verify idempotency while inventory and entitlements still exist.
        self._update_positions_with_splits()
        self._update_cash_with_dividends()
        position = self.get_position(ASSET)
        shares = float(position.quantity) if position else 0.0
        receivable = getattr(self, "dividend_receivable", 0.0)
        mark = float(self.raw_opens.loc[now])
        self.snapshots.append(
            {
                "time": now.isoformat(),
                "cash": float(self.cash),
                "quantity": shares,
                "average_fill_price": float(position.avg_fill_price) if position else None,
                "receivable": receivable,
                "raw_open_mark": mark,
                "equity_including_receivable": float(self.cash) + shares * mark + receivable,
                # Record the hazardous default as evidence; do not feed it to the policy.
                "native_last_price": float(self.get_last_price(ASSET)),
                "native_history_close": float(
                    self.get_historical_prices(ASSET, 1, timestep="day").df.close.iloc[-1]
                ),
            }
        )
        visible = completed_features(self.features, now, self.splits)
        if visible.empty:
            return
        observation = visible.iloc[-1]
        prediction = float(self.model.predict([[observation.feature_close]])[0])
        self.decisions.append(
            {
                "time": now.isoformat(),
                "observation_session": observation.session,
                "available_at": observation.available_at.isoformat(),
                "feature_close": float(observation.feature_close),
                "prediction": prediction,
                "instruction": observation.instruction,
            }
        )
        # Fixed fixture actions, deliberately independent of toy model predictions.
        if observation.instruction in ("buy", "sell"):
            validate_order()
            quantity = 10 if observation.instruction == "buy" else position.quantity
            self.submit_order(
                self.create_order(
                    ASSET,
                    quantity,
                    observation.instruction,
                    order_type="market",
                    time_in_force="day",
                )
            )

    def on_filled_order(self, position, order, price, quantity, multiplier):
        self.callback_times.append(
            {"side": str(order.side), "time": self.get_datetime().isoformat()}
        )

    def on_bot_crash(self, error):
        self.crash = error


class CorrectedProbe(ScheduledDividends, ProbeStrategy):
    pass


def run_backtest(model_path, *, corrected=True, spread=True, feature_override=None):
    bars, features, dividends, _ = load_fixture()
    if feature_override is not None:
        features = feature_override
    if spread:
        # Synthetic execution quotes: 10 bps adverse price per side, representing spread plus
        # slippage together. No claim that these are historical NBBO quotes.
        bars["bid"] = bars.open * 0.999
        bars["ask"] = bars.open * 1.001
    data = Data(ASSET, bars, timestep="day", quote=QUOTE)
    source = PandasDataBacktesting(
        bars.index[0].to_pydatetime() - pd.Timedelta(days=1),
        bars.index[-1].to_pydatetime() + pd.Timedelta(hours=7),
        pandas_data=[data],
        auto_adjust=False,
        show_progress_bar=False,
    )
    broker = BacktestingBroker(source)
    strategy_type = CorrectedProbe if corrected else ProbeStrategy
    # Preflight avoids an engine-thread exception being mistaken for a completed experiment.
    joblib.load(model_path)
    strategy = strategy_type(
        broker,
        name="BB002",
        budget=10000,
        risk_free_rate=0,
        benchmark_asset=None,
        analyze_backtest=False,
        buy_trading_fees=[TradingFee(flat_fee=1)],
        sell_trading_fees=[TradingFee(flat_fee=1)],
        parameters={
            "features": features,
            "dividends": dividends,
            "model_path": model_path,
            "splits": bars.stock_splits,
            "raw_opens": bars.open,
        },
    )
    trader = Trader(logfile="", backtest=True)
    trader.add_strategy(strategy)
    trader.run_all(
        show_plot=False, show_tearsheet=False, save_tearsheet=False, show_indicators=False
    )
    if strategy.crash:
        raise RuntimeError("Qualification strategy crashed") from strategy.crash
    events = []
    for row in broker._trade_event_log_df.to_dict("records"):
        if row["status"] == "new":
            continue
        event = {"time": row["time"].isoformat(), "status": row["status"]}
        if row["status"] == "fill":
            event.update(
                side=str(row["side"]),
                price=float(row["price"]),
                quantity=float(row["filled_quantity"]),
                commission=float(row["trade_cost"]),
            )
        elif row["status"] == "stock_split":
            event.update(ratio=float(row["price"]), quantity=float(row["filled_quantity"]))
        elif row["status"] == "dividend":
            event.update(amount=float(row["cash_event_amount"]))
        events.append(event)
    result = {
        "cash": float(strategy.cash),
        "quantity": sum(float(p.quantity) for p in strategy.get_positions() if p.asset == ASSET),
        "receivable": getattr(strategy, "dividend_receivable", 0.0),
        "events": events,
        "snapshots": strategy.snapshots,
        "decisions": strategy.decisions,
        "callback_times": strategy.callback_times,
    }
    # Both hooks can be called more than once by the engine. Test the same session again.
    before = (result["cash"], result["quantity"], len(broker._trade_event_log_df))
    strategy._update_cash_with_dividends()
    strategy._update_positions_with_splits()
    actual_quantity = sum(float(p.quantity) for p in strategy.get_positions() if p.asset == ASSET)
    assert before == (float(strategy.cash), actual_quantity, len(broker._trade_event_log_df))
    return result


def check_ledger(result):
    """Constants are hand-worked from the CSV, independent of engine calculations."""
    expected = json.loads((FIXTURES / "expected.json").read_text())
    assert result["events"] == expected["events"], (result["events"], expected["events"])
    for key in ("cash", "quantity", "receivable"):
        assert abs(Decimal(str(result[key])) - Decimal(str(expected[key]))) < Decimal("0.000001")
    for row, cash, shares, receivable in zip(
        result["snapshots"],
        [10000, 10000, 8897.90, 8897.90, 8897.90, 10115.70],
        [0, 0, 20, 20, 20, 0],
        [0, 0, 0, 20, 20, 0],
        strict=True,
    ):
        assert abs(row["cash"] - cash) < 1e-6
        assert row["quantity"] == shares
        assert row["receivable"] == receivable
    assert abs(result["snapshots"][2]["average_fill_price"] - 55.055) < 1e-6
    for row, expected_equity in zip(
        result["snapshots"],
        [10000, 10000, 10017.90, 10037.90, 10117.90, 10115.70],
        strict=True,
    ):
        assert abs(row["equity_including_receivable"] - expected_equity) < 1e-6
    for decision in result["decisions"]:
        assert pd.Timestamp(decision["available_at"]) < pd.Timestamp(decision["time"])
