from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any


CONTEXT_MATERIAL_VERSION = 1


@dataclass(frozen=True)
class ContextChangeThresholds:
    similarity_threshold: float = 0.92
    length_delta: int = 160
    length_ratio: float = 0.25


@dataclass(frozen=True)
class ContextChangeDecision:
    significant: bool
    reason: str
    basis: str = ""
    similarity: float = 1.0
    length_delta: int = 0
    length_ratio: float = 0.0
    previous_length: int = 0
    current_length: int = 0


def build_context_material_snapshot(
    *,
    official_context: str = "",
    mobile_context: str = "",
    has_mobile_context: bool = False,
) -> dict[str, Any]:
    official = normalize_context_material(official_context)
    mobile = normalize_context_material(mobile_context)
    return {
        "version": CONTEXT_MATERIAL_VERSION,
        "official_context": official,
        "mobile_context": mobile,
        "has_official_context": bool(official),
        "has_mobile_context": bool(has_mobile_context or mobile),
    }


def serialize_context_material_snapshot(snapshot: dict[str, Any]) -> str:
    normalized = parse_context_material_snapshot(snapshot) or {}
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_context_material_snapshot(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value or "{}")
        except json.JSONDecodeError:
            return None
    if not isinstance(value, dict) or value.get("version") != CONTEXT_MATERIAL_VERSION:
        return None
    official = normalize_context_material(str(value.get("official_context") or ""))
    mobile = normalize_context_material(str(value.get("mobile_context") or ""))
    return {
        "version": CONTEXT_MATERIAL_VERSION,
        "official_context": official,
        "mobile_context": mobile,
        "has_official_context": bool(value.get("has_official_context") or official),
        "has_mobile_context": bool(value.get("has_mobile_context") or mobile),
    }


def evaluate_context_material_change(
    previous: Any,
    current: dict[str, Any],
    thresholds: ContextChangeThresholds,
) -> ContextChangeDecision:
    previous_snapshot = parse_context_material_snapshot(previous)
    current_snapshot = parse_context_material_snapshot(current)
    if previous_snapshot is None or current_snapshot is None:
        return ContextChangeDecision(True, "missing_material_snapshot")

    previous_official = str(previous_snapshot.get("official_context") or "")
    current_official = str(current_snapshot.get("official_context") or "")
    if previous_official or current_official:
        return _evaluate_text_change(
            previous_official,
            current_official,
            thresholds,
            basis="official",
            became_available_reason="official_became_available",
            temporarily_missing_reason="official_temporarily_missing",
        )

    previous_mobile = str(previous_snapshot.get("mobile_context") or "")
    current_mobile = str(current_snapshot.get("mobile_context") or "")
    if previous_mobile or current_mobile:
        return _evaluate_text_change(
            previous_mobile,
            current_mobile,
            thresholds,
            basis="mobile",
            became_available_reason="mobile_became_available",
            temporarily_missing_reason="mobile_temporarily_missing",
        )

    previous_has_mobile = bool(previous_snapshot.get("has_mobile_context"))
    current_has_mobile = bool(current_snapshot.get("has_mobile_context"))
    if not previous_has_mobile and current_has_mobile:
        return ContextChangeDecision(True, "mobile_became_available", basis="mobile")
    if previous_has_mobile and not current_has_mobile:
        return ContextChangeDecision(False, "mobile_temporarily_missing", basis="mobile")
    return ContextChangeDecision(False, "no_context_material")


def normalize_context_material(value: str) -> str:
    text = html.unescape(str(value or ""))
    text = text.replace("\u200b", "").replace("\ufeff", "").replace("\u3000", " ")
    text = text.translate(
        str.maketrans(
            {
                "，": ",",
                "。": ".",
                "！": "!",
                "？": "?",
                "；": ";",
                "：": ":",
                "（": "(",
                "）": ")",
                "“": '"',
                "”": '"',
                "‘": "'",
                "’": "'",
            }
        )
    )
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(展开|收起|查看全文)(?=$|[\s,.;:!?])", "", text).strip()
    text = re.sub(r"\s*([,.;:!?])\s*", r"\1", text)
    return text.strip()


def _evaluate_text_change(
    previous: str,
    current: str,
    thresholds: ContextChangeThresholds,
    *,
    basis: str,
    became_available_reason: str,
    temporarily_missing_reason: str,
) -> ContextChangeDecision:
    previous_length = len(previous)
    current_length = len(current)
    length_delta = abs(current_length - previous_length)
    length_ratio = length_delta / max(previous_length, current_length, 1)

    if not previous and current:
        return ContextChangeDecision(
            True,
            became_available_reason,
            basis=basis,
            previous_length=previous_length,
            current_length=current_length,
            length_delta=length_delta,
            length_ratio=length_ratio,
        )
    if previous and not current:
        return ContextChangeDecision(
            False,
            temporarily_missing_reason,
            basis=basis,
            previous_length=previous_length,
            current_length=current_length,
            length_delta=length_delta,
            length_ratio=length_ratio,
        )

    similarity = SequenceMatcher(None, previous, current).ratio() if previous or current else 1.0
    decision_kwargs = {
        "basis": basis,
        "similarity": similarity,
        "previous_length": previous_length,
        "current_length": current_length,
        "length_delta": length_delta,
        "length_ratio": length_ratio,
    }
    if previous == current:
        return ContextChangeDecision(False, "same_context_material", **decision_kwargs)
    if similarity < thresholds.similarity_threshold:
        return ContextChangeDecision(True, "similarity_below_threshold", **decision_kwargs)
    if length_delta >= thresholds.length_delta:
        return ContextChangeDecision(True, "length_delta_exceeded", **decision_kwargs)
    if length_ratio >= thresholds.length_ratio:
        return ContextChangeDecision(True, "length_ratio_exceeded", **decision_kwargs)
    return ContextChangeDecision(False, "minor_context_change", **decision_kwargs)
