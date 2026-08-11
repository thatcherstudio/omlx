# SPDX-License-Identifier: Apache-2.0
"""
Model pricing for cost tracking in the oMLX dashboard.

Stores per-model $/1M-token rates in a simple JSON file
alongside settings.json. This avoids modifying the GlobalSettings
hierarchy for what is essentially a dashboard overlay.

File location: ~/.omlx/pricing.json
Format:
{
    "models": {
        "model-id-here": {
            "prompt_price_per_m": 0.15,
            "completion_price_per_m": 0.60,
            "label": "Custom label (optional)"
        }
    },
    "default_prompt_price_per_m": 0.0,
    "default_completion_price_per_m": 0.0
}
"""

import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Default pricing file location
DEFAULT_PRICING_PATH = Path.home() / ".omlx" / "pricing.json"


class ModelPricing:
    """Per-model pricing for cost calculations.

    Thread-safe: uses a lock for reads/writes to the JSON file.
    """

    def __init__(self, pricing_path: Optional[Path] = None):
        self._path = pricing_path or DEFAULT_PRICING_PATH
        self._lock = threading.Lock()
        self._models: Dict[str, Dict[str, Any]] = {}
        self._default_prompt: float = 0.0
        self._default_completion: float = 0.0
        self._load()

    def _load(self) -> None:
        """Load pricing from disk."""
        if not self._path.exists():
            self._models = {}
            self._default_prompt = 0.0
            self._default_completion = 0.0
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            self._models = data.get("models", {})
            self._default_prompt = float(data.get("default_prompt_price_per_m", 0.0))
            self._default_completion = float(data.get("default_completion_price_per_m", 0.0))
        except (json.JSONDecodeError, TypeError, ValueError, OSError) as e:
            logger.warning("Failed to load pricing from %s: %s", self._path, e)
            self._models = {}
            self._default_prompt = 0.0
            self._default_completion = 0.0

    def _save(self) -> None:
        """Save pricing to disk."""
        data = {
            "models": self._models,
            "default_prompt_price_per_m": self._default_prompt,
            "default_completion_price_per_m": self._default_completion,
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._path.with_suffix(".json.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            tmp_path.replace(self._path)
        except OSError as e:
            logger.error("Failed to save pricing to %s: %s", self._path, e)

    def get_model_pricing(self, model_id: str) -> Dict[str, Any]:
        """Get pricing for a specific model, falling back to defaults.

        Returns dict with keys:
            prompt_price_per_m: float
            completion_price_per_m: float
            label: str (optional)
        """
        with self._lock:
            model_data = self._models.get(model_id, {})
            return {
                "model_id": model_id,
                "prompt_price_per_m": model_data.get(
                    "prompt_price_per_m", self._default_prompt
                ),
                "completion_price_per_m": model_data.get(
                    "completion_price_per_m", self._default_completion
                ),
                "label": model_data.get("label", model_id),
            }

    def get_all_pricing(self) -> Dict[str, Any]:
        """Get all pricing data including defaults."""
        with self._lock:
            return {
                "models": dict(self._models),
                "default_prompt_price_per_m": self._default_prompt,
                "default_completion_price_per_m": self._default_completion,
            }

    def update_pricing(self, data: Dict[str, Any]) -> None:
        """Update pricing data from a dict and save."""
        with self._lock:
            self._models = data.get("models", {})
            self._default_prompt = float(
                data.get("default_prompt_price_per_m", 0.0)
            )
            self._default_completion = float(
                data.get("default_completion_price_per_m", 0.0)
            )
            self._save()

    def update_model_pricing(
        self,
        model_id: str,
        prompt_price_per_m: Optional[float] = None,
        completion_price_per_m: Optional[float] = None,
        label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update pricing for a single model and save."""
        with self._lock:
            if model_id not in self._models:
                self._models[model_id] = {}
            entry = self._models[model_id]
            if prompt_price_per_m is not None:
                entry["prompt_price_per_m"] = prompt_price_per_m
            if completion_price_per_m is not None:
                entry["completion_price_per_m"] = completion_price_per_m
            if label is not None:
                entry["label"] = label
            self._save()
            return dict(entry)

    def calculate_cost(
        self,
        model_id: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> Dict[str, float]:
        """Calculate cost for a given model and token counts.

        Returns:
            Dict with prompt_cost, completion_cost, total_cost
        """
        pricing = self.get_model_pricing(model_id)
        prompt_cost = prompt_tokens * pricing["prompt_price_per_m"] / 1_000_000
        completion_cost = completion_tokens * pricing["completion_price_per_m"] / 1_000_000
        return {
            "prompt_cost": round(prompt_cost, 6),
            "completion_cost": round(completion_cost, 6),
            "total_cost": round(prompt_cost + completion_cost, 6),
        }


# Global singleton
_pricing: Optional[ModelPricing] = None


def get_model_pricing(pricing_path: Optional[Path] = None) -> ModelPricing:
    """Get the global ModelPricing singleton."""
    global _pricing
    if _pricing is None:
        _pricing = ModelPricing(pricing_path=pricing_path)
    return _pricing


def reset_model_pricing(pricing_path: Optional[Path] = None) -> ModelPricing:
    """Reset the pricing singleton (called on server start)."""
    global _pricing
    _pricing = ModelPricing(pricing_path=pricing_path)
    return _pricing