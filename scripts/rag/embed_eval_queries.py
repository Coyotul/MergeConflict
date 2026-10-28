"""Embed every eval question once with BGE-M3 and save the vectors, so evaluation can run without the model.

Writes data/local/rag/eval_query_vectors.npz (git-ignored): ids, texts, float32 vectors, model_name.
Use it with: scripts/rag/evaluate.py --split tune --query-vectors data/local/rag/eval_query_vectors.npz
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402

from scripts.rag import run_cli  # noqa: E402
from src.core.settings import load_rag_settings  # noqa: E402
from src.integrations.llm.embeddings import BgeM3Embedder  # noqa: E402
from src.services.retrieval.evaluation import load_eval_split  # noqa: E402

EVAL_DIR = Path("config/rag/eval")
SPLITS = ("tune", "validation")


def main() -> int:
    settings = load_rag_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data/local/rag/eval_query_vectors.npz"))
    args = parser.parse_args()

    questions = [q for split in SPLITS for q in load_eval_split(EVAL_DIR / f"{split}.yaml")]
    embedder = BgeM3Embedder(settings.embedding_model, settings.embedding_device, batch_size=4)
    # One embed_query call per question: exactly the call RetrievalService makes at search time.
    vectors = np.array([embedder.embed_query(q.question) for q in questions], dtype=np.float32)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez(args.out, ids=np.array([q.id for q in questions]), texts=np.array([q.question for q in questions]),
             vectors=vectors, model_name=np.array(embedder.model_name))
    print(f"questions={len(questions)} distinct_texts={len({q.question for q in questions})} "
          f"dimension={vectors.shape[1]} model={embedder.model_name} -> {args.out}")
    return 0


if __name__ == "__main__":
    run_cli(main)
