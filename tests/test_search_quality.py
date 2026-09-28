"""Search stays on-topic: query parsing, titles over bodies, aliases, the relevance gate, metrics."""

from __future__ import annotations

import pytest

from openatlas.kb import evaluate, retrieve, store


@pytest.fixture
def corpus(tmp_path):
    with store.use_path(tmp_path / "brain.sqlite"):
        evaluate.load_fixture_corpus()
        yield


def titles(q, k=5):
    return [h["title"] for h in retrieve.search(q, k=k, use_vectors=False)]


def test_parse_phrases_exclusions_and_stopwords():
    q = retrieve.parse('what is the "event horizon" of a black hole -film')
    assert q.terms == ["event", "horizon", "black", "hole"]
    assert q.phrases == ["event horizon"] and q.exclude == ["film"]
    assert retrieve.parse("the").terms == ["the"]  # only stopwords: keep them


def test_fixture_corpus_meets_thresholds_and_old_ranker_does_not():
    good = evaluate.eval_fixture()
    assert good["ok"], good["failures"]
    assert good["metrics"]["off_topic"] == 0.0
    bad = evaluate.eval_fixture(evaluate.legacy_or_search)
    assert not bad["ok"] and bad["metrics"]["off_topic"] > 0.3  # the drift the user saw


def test_no_single_word_drift(corpus):
    assert titles("second world war") == ["World War II"]  # not Pythonidae ("the world")
    assert "Black Death" not in titles("black hole event horizon")
    assert titles("quantum chromodynamics gluon") == []  # unknown topic: say nothing


def test_title_beats_body_and_question_words_are_ignored(corpus):
    assert titles("what is photosynthesis")[0] == "Photosynthesis"
    assert titles("tell me about the black death") == ["Black Death"]
    assert titles("roman empire")[0] == "Roman Empire"


def test_hyphen_is_part_of_the_word_not_an_exclusion(corpus):
    """Regression: 'Nil-Coxeter algebra' used to exclude 'coxeter' and miss its own article."""
    q = retrieve.parse("Nil-Coxeter algebra -film")
    assert q.terms == ["nil", "coxeter", "algebra"] and q.exclude == ["film"]
    assert titles("Nil-Coxeter algebra")[0] == "Nil-Coxeter algebra"
    assert titles("nil-coxeter algebra")[0] == "Nil-Coxeter algebra"


def test_symbols_and_single_letters_find_their_own_titles(tmp_path):
    with store.use_path(tmp_path / "sym.sqlite"):
        for t in ("C++", "C#", "C (programming language)", "R (programming language)"):
            store.upsert_document(key="wikipedia:" + t, source="wikipedia", title=t, text=f"{t} is a topic. " * 6)
        for t in ("C++", "C#", "C (programming language)", "R (programming language)"):
            assert titles(t)[0] == t, t


def test_old_title_norms_are_upgraded(tmp_path):
    with store.use_path(tmp_path / "old2.sqlite"):
        store.upsert_document(key="wikipedia:C++", source="wikipedia", title="C++", text="C++ is a language. " * 6)
        with store.connect() as con:  # a brain indexed with the old rule ("C++" -> "c")
            con.execute("UPDATE titles SET norm='c'")
        store.reset_init_cache()
        assert titles("C++")[0] == "C++"


def test_aliases_and_exclusions(corpus):
    assert titles("WWII") == ["World War II"]
    assert titles("ML") == ["Machine learning"]
    assert "Empire (film)" not in titles("empire -film")


def test_hits_explain_themselves(corpus):
    (hit,) = retrieve.search("WW2", use_vectors=False)
    assert "alias" in hit["why"] and hit["score"] > 0


def test_title_index_backfilled_for_old_brains(tmp_path):
    with store.use_path(tmp_path / "old.sqlite"):
        store.upsert_document(key="k", source="wikipedia", title="Group theory",
                              text="Group theory studies groups. " * 20)
        with store.connect() as con:  # simulate a brain made before the title index existed
            con.execute("DELETE FROM titles")
            con.execute("DELETE FROM titles_fts")
        store.reset_init_cache()
        assert titles("group theory") == ["Group theory"]


def test_metrics_on_a_known_ranking():
    queries = [{"q": "a", "expect": ["A"], "ok": []}, {"q": "b", "expect": ["B"], "ok": []},
               {"q": "none", "expect": [], "ok": []}]
    fake = {"a": ["A", "X"], "b": ["X", "B"], "none": []}
    r = evaluate.score(queries, lambda q, k=5: [{"title": t} for t in fake[q]])
    m = r["metrics"]
    assert m["p_at_1"] == 0.5 and m["mrr"] == 0.75 and m["off_topic"] == 0.5


def test_ask_refuses_rather_than_answering_off_topic(corpus, monkeypatch):
    from openatlas.kb import ask, ingest

    monkeypatch.setattr(ingest, "boost", lambda *a, **k: 0)
    r = ask.ask("quantum chromodynamics gluon")
    assert r["citations"] == [] and "nothing on this" in r["answer"]
    r = ask.ask("what is photosynthesis")
    assert r["citations"][0]["title"] == "Photosynthesis"


def test_brain_eval_uses_your_own_articles(corpus):
    r = evaluate.eval_brain(sample=50)
    assert r["ok"] and r["queries"] >= 16 and r["metrics"]["p_at_1"] >= 0.85
