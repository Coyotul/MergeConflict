from src.core.settings import load_rag_settings


def test_defaults_and_env_override():
    s = load_rag_settings(env={})
    assert s.database_url == "postgresql://rag:rag@127.0.0.1:5433/rag"
    assert s.rrf_k == 20 and s.candidate_k == 30
    s2 = load_rag_settings(env={"RAG_DENSE_FLOOR": "0.6", "RAG_DENSE_MARGIN_WEIGHT": "2.5", "RAG_DENSE_MARGIN_RANK": "5",
                                "RAG_KEYWORD_WEIGHT": "0.5",
                                "RAG_DATABASE_URL": "postgresql://x/y"})
    assert s2.dense_floor == 0.6 and s2.database_url == "postgresql://x/y"
    assert s2.dense_margin_weight == 2.5 and s2.dense_margin_rank == 5 and s2.keyword_weight == 0.5
