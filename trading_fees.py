"""Trading fee model for A-share order planning and research backtests."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeeModel:
    commission_rate: float = 0.0003
    min_commission: float = 5.0
    platform_fee: float = 15.0
    tiny_fee_rate: float = 0.00004
    sell_stamp_duty_rate: float = 0.0005


DEFAULT_FEE_MODEL = FeeModel()


def transaction_fee(side: str, notional: float, model: FeeModel = DEFAULT_FEE_MODEL) -> float:
    """Return estimated RMB transaction fee for one buy or sell order."""
    trade_notional = max(float(notional), 0.0)
    if trade_notional <= 0:
        return 0.0
    normalized_side = str(side).strip().upper()
    if normalized_side not in {"BUY", "SELL"}:
        raise ValueError(f"unsupported transaction side: {side!r}")

    fee = max(model.commission_rate * trade_notional, model.min_commission)
    fee += model.platform_fee
    fee += model.tiny_fee_rate * trade_notional
    if normalized_side == "SELL":
        fee += model.sell_stamp_duty_rate * trade_notional
    return float(fee)
