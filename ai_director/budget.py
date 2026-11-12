"""Local spend ledger for the AI chart director.

Every API call is checked BEFORE it is sent: the worst case (counted input tokens at full
price + max_tokens of output) must fit in what is left of the limit, otherwise the call is
refused. After the call, the real cost from response.usage is recorded.

This is a client-side guard. For a hard server-side cap, also set a monthly spend limit
for the API key's workspace in the Claude Console (Settings > Limits).
"""
import json
import os
import time

# USD per 1M tokens: (input, output). Cache writes bill 1.25x input, cache reads 0.1x input.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}
FALLBACK_PRICE = (5.00, 25.00)  # unknown/fallback model: assume the pricier tier


class BudgetExceeded(RuntimeError):
    pass


class Ledger:
    def __init__(self, path, limit_usd):
        self.path = path
        self.data = {"limit_usd": limit_usd, "spent_usd": 0.0, "calls": []}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                self.data.update(json.load(fh))
        self.data["limit_usd"] = limit_usd  # the CLI flag wins, so the limit can be raised/lowered explicitly

    @property
    def remaining(self):
        return max(0.0, self.data["limit_usd"] - self.data["spent_usd"])

    def check(self, model, input_tokens, max_output_tokens):
        price_in, price_out = PRICES.get(model, FALLBACK_PRICE)
        worst = (input_tokens * 1.25 * price_in + max_output_tokens * price_out) / 1e6
        if worst > self.remaining:
            raise BudgetExceeded(
                f"Worst-case cost ${worst:.2f} exceeds remaining budget ${self.remaining:.2f} "
                f"(spent ${self.data['spent_usd']:.2f} of ${self.data['limit_usd']:.2f})."
            )
        return worst

    def record(self, model, usage, note=""):
        price_in, price_out = PRICES.get(model, FALLBACK_PRICE)
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cost = (
            usage.input_tokens * price_in
            + cache_write * price_in * 1.25
            + cache_read * price_in * 0.10
            + usage.output_tokens * price_out
        ) / 1e6
        self.data["spent_usd"] = round(self.data["spent_usd"] + cost, 6)
        self.data["calls"].append({
            "time": time.strftime("%Y-%m-%d %H:%M:%S"), "model": model, "note": note,
            "input_tokens": usage.input_tokens, "cache_write": cache_write, "cache_read": cache_read,
            "output_tokens": usage.output_tokens, "cost_usd": round(cost, 4),
        })
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=1)
        os.replace(tmp, self.path)
        return cost
