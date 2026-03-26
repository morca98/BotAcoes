"""Risk Manager — Stock Signal Bot MTF V3"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(self, config):
        self.config = config

    def calculate_levels(self, signal: Dict[str, Any], capital: float) -> Dict[str, Any]:
        entry = signal["price"]
        sl = signal.get("h4_low", entry * 0.98)
        sl = min(sl, entry * 0.99)
        risk_per_unit = max(entry - sl, entry * 0.005)
        tp = entry + risk_per_unit * self.config.RR_RATIO
        risk_eur = capital * self.config.RISK_PCT
        size = risk_eur / risk_per_unit

        signal.update({
            "sl": round(sl, 4),
            "tp": round(tp, 4),
            "size": round(size, 2),
            "risk_eur": round(risk_eur, 2),
            "rr": self.config.RR_RATIO,
            "breakeven_price": round(entry * (1 + self.config.BREAKEVEN_PCT), 4),
            "trailing_price":  round(entry * (1 + self.config.TRAILING_PCT), 4),
        })
        return signal

    def update_trailing(self, entry: float, current_price: float, sl: float) -> Dict[str, float]:
        pct_gain = (current_price - entry) / entry
        if pct_gain >= self.config.TRAILING_PCT:
            new_sl = max(current_price * (1 - self.config.RISK_PCT), entry)
            return {"sl": round(new_sl, 4), "mode": "trailing"}
        elif pct_gain >= self.config.BREAKEVEN_PCT:
            return {"sl": round(entry, 4), "mode": "breakeven"}
        return {"sl": round(sl, 4), "mode": "original"}
