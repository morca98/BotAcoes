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
        risk_eur = capital * self.config.RISK_PERCENT / 100
        size = risk_eur / risk_per_unit

        signal.update({
            "sl": round(sl, 4),
            "tp": round(tp, 4),
            "size": round(size, 2),
            "risk_eur": round(risk_eur, 2),
            "rr": self.config.RR_RATIO
        })
        return signal
