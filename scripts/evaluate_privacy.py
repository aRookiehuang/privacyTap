import json
import sys
import time
from pathlib import Path

from tokentap.privacy.detectors import detect_sensitive


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "tests" / "fixtures" / "privacy_cases.json"


def metrics(
    tp: int, fp: int, fn: int
) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return precision, recall, f1


def percentile(values: list[float], ratio: float) -> float:
    ordered = sorted(values)
    index = round((len(ordered) - 1) * ratio)
    return ordered[index]


def main() -> int:
    cases = json.loads(DATASET.read_text(encoding="utf-8"))
    tp = fp = fn = 0
    latencies_ms: list[float] = []

    for case in cases:
        expected = {
            (item["type"], item["value"])
            for item in case["expected"]
        }
        actual_findings = detect_sensitive(case["text"])
        actual = {
            (item.entity_type.value, item.value)
            for item in actual_findings
        }
        tp += len(actual & expected)
        fp += len(actual - expected)
        fn += len(expected - actual)

        for _ in range(100):
            started = time.perf_counter()
            detect_sensitive(case["text"])
            latencies_ms.append(
                (time.perf_counter() - started) * 1000
            )

    precision, recall, f1 = metrics(tp, fp, fn)
    p50 = percentile(latencies_ms, 0.50)
    p95 = percentile(latencies_ms, 0.95)
    print(f"TP={tp} FP={fp} FN={fn}")
    print(
        f"Precision={precision:.4f} "
        f"Recall={recall:.4f} F1={f1:.4f}"
    )
    print(f"Latency P50={p50:.4f}ms P95={p95:.4f}ms")
    return 0 if min(precision, recall, f1) >= 0.95 else 1


if __name__ == "__main__":
    sys.exit(main())
