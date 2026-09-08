from scripts.evaluate_memory import DEFAULT_CORPUS, evaluate


def test_release_memory_eval_meets_declared_thresholds() -> None:
    report = evaluate(DEFAULT_CORPUS)

    assert report["passed"] is True
    assert report["write"]["precision"] >= report["thresholds"]["write_precision"]
    assert report["write"]["recall"] >= report["thresholds"]["write_recall"]
    assert report["retrieval"]["recall_at_k"] >= report["thresholds"]["retrieval_recall_at_k"]
