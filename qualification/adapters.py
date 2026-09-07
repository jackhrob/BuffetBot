"""Small, version-specific corrections demonstrated by BB-002.

Keep these experiments out of the application until BB-009/017 integrate them.
Lumibot still owns orders, fills, positions, splits and cash storage.
"""

from datetime import date
from decimal import Decimal

from lumibot.brokers import Alpaca
from lumibot.entities import Order


def validate_order(order_type="market", time_in_force="day", extended_hours=False):
    if (order_type, time_in_force, extended_hours) != ("market", "day", False):
        raise ValueError("Qualified orders require market/day during regular hours")


def completed_features(features, now, splits):
    """Expose only available rows; normalize older features using splits effective by now.

    The fixture contains raw closes. Adjustment occurs only in this separate feature frame;
    executable OHLC and quantities remain in contemporaneous raw share units.
    """
    visible = features.loc[features.available_at < now].copy()
    for split_time, ratio in splits.items():
        if split_time <= now and ratio:
            older = visible.session < split_time.date().isoformat()
            visible.loc[older, "feature_close"] /= float(ratio)
    return visible


class ScheduledDividends:
    """Strategy mixin: capture ex-date entitlement and post cash on/after pay date once.

    Lumibot calls this before new session orders, after its native split adjustment. Native
    dividend posting is replaced, so an adjusted feature can never add dividend cash twice.
    Missing payment dates fail during fixture loading instead of assuming an ex-date payment.
    """

    def _update_cash_with_dividends(self):
        today = self.get_datetime().date()
        for action in self.dividends:
            key = action["id"]
            if today == date.fromisoformat(action["ex_date"]) and key not in self.entitlements:
                position = self.get_position(self.asset)
                quantity = Decimal(str(position.quantity if position else 0))
                self.entitlements[key] = quantity * Decimal(action["amount"])
            if key in self.entitlements and today >= date.fromisoformat(action["pay_date"]):
                if key in self.paid_dividends:
                    continue
                amount = self.entitlements[key]
                self._set_cash_position(float(Decimal(str(self.cash)) + amount))
                self._record_backtest_cash_event(
                    event_type="dividend",
                    amount=float(amount),
                    reason="dividend_payment",
                    description=key,
                    raw_type="dividend",
                    raw_subtype=self.asset.symbol,
                )
                self.paid_dividends.add(key)
        return self.cash

    @property
    def dividend_receivable(self):
        return float(sum(v for k, v in self.entitlements.items() if k not in self.paid_dividends))


class QualifiedAlpaca(Alpaca):
    """Correct partial-order import while retaining native synchronization and order trackers."""

    def _process_broker_synced_order(self, order):
        if order.status != Order.OrderStatus.PARTIALLY_FILLED:
            return super()._process_broker_synced_order(order)
        filled = Decimal(str(order._raw.filled_qty))
        if not 0 < filled < Decimal(str(order.quantity)):
            raise ValueError("Partial broker snapshot has invalid filled quantity")
        self._process_new_order(order)
        self._process_partially_filled_order(order, order.avg_fill_price, float(filled))
