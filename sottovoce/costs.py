"""What a run costs on AMD Token Factory, from its published list prices."""

from __future__ import annotations

# $ per million tokens (input, output), from Token Factory's /models on 2026-10-13,
# checked again on 2026-10-16 (unchanged; MiMo added). Gemma was removed on Oct 16;
# its price stays so the lessons it wrote still cost out.
PRICES = {
    "DeepSeek-V4-Flash-Vision-Exp": (0.14, 0.28),
    "DeepSeek-V4.1-Flash": (0.28, 0.56),
    "MiMo-V2.6-Flash": (0.14, 0.28),
    "Qwen3.8-27B": (0.035, 0.07),
    "Qwen3.8-Flash-Next": (0.14, 0.28),
    "Gemma-4-31B-IT": (0.035, 0.07),
    "MiniCPM-V-4.7-35B-A3B": (0.035, 0.07),
}


def cost(tokens: dict[str, list[int]], models: dict[str, str]) -> float:
    """Dollars for one line: `tokens` is {agent: [in, out]}, `models` is {agent: model}."""
    total = 0.0
    for agent, (tokens_in, tokens_out) in tokens.items():
        price_in, price_out = PRICES.get(models.get(agent, ""), (0.0, 0.0))
        total += tokens_in * price_in / 1e6 + tokens_out * price_out / 1e6
    return total
