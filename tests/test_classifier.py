from gh_stars_organizer.classifier import RepositoryClassifier, whole_phrase
from gh_stars_organizer.config import AppConfig, Category, Override


def config():
    return AppConfig(classification={"profile": "custom", "minimum_score": 3, "max_categories_per_repository": 3},
                     categories=[
                         Category(name="Numerics", keywords=["numerical solver", "differential equations"]),
                         Category(name="Workflow", keywords=["workflow", "pipeline"]),
                         Category(name="Rust", keywords=["rust"]),
                         Category(name="R", keywords=["r"]),
                     ])


def test_boundaries():
    assert whole_phrase("a language r computing", "R")
    assert not whole_phrase("computer and raster", "R")
    assert not whole_phrase("google", "GO")
    assert whole_phrase("golang go programming", "GO")
    assert whole_phrase("neural networks for research", "neural networks")


def test_multilabel_scores_and_provenance(repo):
    engine = RepositoryClassifier(config())
    actual = engine.classify(repo)
    assert actual.categories == ["Numerics"]
    assert actual.scores["Numerics"] == 3 + 3
    assert actual.scores["Rust"] == 1
    assert any(x.field == "description" for x in actual.matched_rules)
    assert not actual.review_required


def test_negation(repo):
    cfg = config()
    cfg.categories[0].exclude_keywords = ["ode"]
    assert RepositoryClassifier(cfg).classify(repo).categories == []


def test_override_survives_scoring(repo):
    cfg = config()
    cfg.overrides[repo.full_name] = Override(categories=["Workflow"])
    actual = RepositoryClassifier(cfg).classify(repo)
    assert actual.categories == ["Workflow"]
    assert actual.override_used
    cfg.overrides[repo.full_name] = Override(exclude=True)
    actual = RepositoryClassifier(cfg).classify(repo)
    assert actual.excluded and not actual.categories


def test_unclassified_review(repo):
    cfg = config()
    cfg.classification.minimum_score = 999
    actual = RepositoryClassifier(cfg).classify(repo)
    assert actual.categories == [] and actual.review_required


def test_fingerprint_and_repeatability(repo):
    cfg = config()
    engine = RepositoryClassifier(cfg)
    assert engine.classify(repo).model_dump() == engine.classify(repo).model_dump()
    first = engine.fingerprint()
    cfg.categories[0].keywords.append("scientific simulation")
    assert first != RepositoryClassifier(cfg).fingerprint()


def test_score_margin_and_priority(repo):
    cfg = AppConfig(classification={"profile": "custom", "minimum_score": 1, "score_margin": 1},
                    categories=[Category(name="A", keywords=["ode"], priority=0),
                                Category(name="B", keywords=["ode"], priority=1)])
    actual = RepositoryClassifier(cfg).classify(repo)
    assert actual.categories == ["B", "A"]


def test_no_repeat_keyword_inflation(repo):
    repo.description = "ode ode ode ode"
    cfg = AppConfig(classification={"profile": "custom", "minimum_score": 1},
                    categories=[Category(name="ODE", keywords=["ode"])])
    actual = RepositoryClassifier(cfg).classify(repo)
    assert actual.scores["ODE"] == 8  # one topic + one description hit
