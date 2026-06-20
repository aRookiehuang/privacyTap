from scripts.evaluate_privacy import evaluate_streaming_restoration


def test_streaming_evaluation_reports_perfect_restoration_and_no_leaks():
    result = evaluate_streaming_restoration()
    assert result["cases"] > 0
    assert result["accuracy"] == 1.0
    assert result["leakage_count"] == 0
    assert result["p95_ms"] < 20.0
