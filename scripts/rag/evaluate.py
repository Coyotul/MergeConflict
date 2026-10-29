"""Evaluate retrieval on a labelled split (config/rag/eval/); validation is a hold-out gate."""
import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg  # noqa: E402

from scripts.rag import CONNECT_TIMEOUT_S, run_cli  # noqa: E402
from src.core.errors import KnowledgeStoreUnavailable  # noqa: E402
from src.core.settings import load_rag_settings  # noqa: E402
from src.integrations.llm.embeddings import PrecomputedQueryEmbedder  # noqa: E402
from src.services.retrieval.evaluation import EvalReport, check_labels, evaluate, load_eval_split  # noqa: E402
from src.services.retrieval.factory import build_retrieval_service  # noqa: E402

EVAL_DIR = Path("config/rag/eval")
GATE = {"recall_at_k": 0.8, "refusal_accuracy": 0.8, "false_refusal_rate": 0.1}
WORST = 15


def passes_gate(report: EvalReport) -> bool:
    """Validation gate: recall@k >= 0.8, refusal accuracy >= 0.8 and false-refusal rate <= 0.1."""
    return (report.recall_at_k >= GATE["recall_at_k"] and report.refusal_accuracy >= GATE["refusal_accuracy"]
            and report.false_refusal_rate <= GATE["false_refusal_rate"])


def print_report(report: EvalReport) -> None:
    print(f"recall@{report.k}={report.recall_at_k:.3f} mrr={report.mrr:.3f} ndcg@10={report.ndcg_at_10:.3f} "
          f"refusals={report.refusals_correct}/{report.refusals_total} ({report.refusal_accuracy:.3f}) "
          f"false_refusals={report.false_refusals}/{report.answerable_total} ({report.false_refusal_rate:.3f})")
    for dimension, groups in report.breakdowns.items():
        print(f"\nby {dimension}:")
        for value, b in sorted(groups.items(), key=lambda item: item[1].rate):
            print(f"  {value:<28} {b.correct:>4}/{b.n:<4} {b.rate:.3f}")

    def badness(row: dict) -> tuple:
        if row["answerable"]:
            return (row["hit_rank"] is not None and row["hit_rank"] <= report.k, row["ndcg"])
        return (row["status"] == "insufficient_evidence", 1.0)

    print(f"\nworst {WORST}:")
    for row in sorted(report.per_question, key=badness)[:WORST]:
        print(f"  {row['id']} [{row['status']}, hit_rank={row['hit_rank']}] {row['question']}")
        for t in row["top"][:3]:
            print(f"      {t['fused']:.4f} {t['canonical_key']} :: {t['section_path'][:90]}")


def main() -> int:
    settings = load_rag_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["tune", "validation"], required=True)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--check-labels", action="store_true",
                        help="only check that every label matches an indexed chunk")
    parser.add_argument("--query-vectors", type=Path,
                        help="precomputed question vectors (scripts/rag/embed_eval_queries.py); no model is loaded")
    args = parser.parse_args()

    questions = load_eval_split(EVAL_DIR / f"{args.split}.yaml")
    if args.check_labels:
        try:
            with psycopg.connect(settings.database_url, connect_timeout=CONNECT_TIMEOUT_S) as conn:
                unmatched = check_labels(conn, questions, args.as_of)
        except psycopg.OperationalError as exc:
            raise KnowledgeStoreUnavailable(f"knowledge store unreachable: {exc}") from exc
        labels = sum(len(q.expected) for q in questions)
        for line in unmatched:
            print(f"unmatched: {line}")
        print(f"labels: {labels} unmatched: {len(unmatched)}")
        return 0

    embedder = PrecomputedQueryEmbedder(args.query_vectors) if args.query_vectors else None
    report = evaluate(build_retrieval_service(settings, embedder).search, questions, k=args.k, as_of=args.as_of)
    print_report(report)
    if args.split == "validation":
        passed = passes_gate(report)
        print(f"\nvalidation gate: {'PASS' if passed else 'FAIL'} {GATE}")
        return 0 if passed else 1
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    run_cli(main)
