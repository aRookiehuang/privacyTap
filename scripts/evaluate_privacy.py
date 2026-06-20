import json
import sys
import time
from pathlib import Path

from privacytap.privacy.detectors import detect_sensitive
from privacytap.privacy.models import EntityType, SensitiveCredentialError
from privacytap.privacy.streaming import StreamingRestorer
from privacytap.privacy.transformer import sanitize_payload
from privacytap.privacy.vault import RequestVault


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


def evaluate_streaming_restoration() -> dict[str, float | int]:
    vault = RequestVault()
    originals = {
        EntityType.PHONE: "13800138000",
        EntityType.CN_ID: "11010519491231002X",
        EntityType.EMAIL: "alice@example.com",
        EntityType.BANK_CARD: "4111111111111111",
        EntityType.STUDENT_ID: "2023123456",
        EntityType.CREDENTIAL: "sk-proj-examplecredential123456",
    }
    placeholders = {
        vault.get_or_create(entity_type, value): value
        for entity_type, value in originals.items()
    }
    cases = correct = leakage_count = 0
    latencies_ms: list[float] = []
    for placeholder, original in placeholders.items():
        leakage_count += sum(
            secret in placeholder for secret in originals.values()
        )
        for split_at in range(1, len(placeholder)):
            restorer = StreamingRestorer(vault)
            started = time.perf_counter()
            output = (
                restorer.feed("stream", placeholder[:split_at])
                + restorer.feed("stream", placeholder[split_at:])
                + restorer.finish("stream")
            )
            latencies_ms.append(
                (time.perf_counter() - started) * 1000
            )
            cases += 1
            correct += int(output == original)
    return {
        "cases": cases,
        "accuracy": correct / cases if cases else 1.0,
        "leakage_count": leakage_count,
        "p95_ms": percentile(latencies_ms, 0.95),
    }


def main() -> int:
    cases = json.loads(DATASET.read_text(encoding="utf-8"))
    tp = fp = fn = 0
    detection_latencies_ms: list[float] = []
    transform_latencies_ms: list[float] = []

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
            detection_latencies_ms.append(
                (time.perf_counter() - started) * 1000
            )
            started = time.perf_counter()
            try:
                sanitize_payload(
                    {
                        "model": "benchmark",
                        "messages": [
                            {
                                "role": "user",
                                "content": case["text"],
                            }
                        ],
                    }
                )
            except SensitiveCredentialError:
                pass
            transform_latencies_ms.append(
                (time.perf_counter() - started) * 1000
            )

    precision, recall, f1 = metrics(tp, fp, fn)
    detection_p50 = percentile(detection_latencies_ms, 0.50)
    detection_p95 = percentile(detection_latencies_ms, 0.95)
    transform_p50 = percentile(transform_latencies_ms, 0.50)
    transform_p95 = percentile(transform_latencies_ms, 0.95)
    print(f"TP={tp} FP={fp} FN={fn}")
    print(
        f"Precision={precision:.4f} "
        f"Recall={recall:.4f} F1={f1:.4f}"
    )
    print(
        f"Detection P50={detection_p50:.4f}ms "
        f"P95={detection_p95:.4f}ms"
    )
    print(
        f"Transform P50={transform_p50:.4f}ms "
        f"P95={transform_p95:.4f}ms"
    )
    streaming = evaluate_streaming_restoration()
    print(f"Streaming cases: {streaming['cases']}")
    print(
        "Streaming restore accuracy: "
        f"{streaming['accuracy']:.4f}"
    )
    print(
        f"Raw secret leakage count: {streaming['leakage_count']}"
    )
    print(
        "Streaming transform P95: "
        f"{streaming['p95_ms']:.4f}ms"
    )
    meets_quality = min(precision, recall, f1) >= 0.95
    meets_latency = (
        transform_p95 < 20.0
        and float(streaming["p95_ms"]) < 20.0
    )
    meets_streaming = (
        streaming["accuracy"] == 1.0
        and streaming["leakage_count"] == 0
    )
    return 0 if meets_quality and meets_latency and meets_streaming else 1


if __name__ == "__main__":
    sys.exit(main())
