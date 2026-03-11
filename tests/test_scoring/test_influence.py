from gyn_kol.models.clinician import MasterClinician
from gyn_kol.scoring.influence import (
    calculate_influence_score,
    score_clinical_leadership,
    score_digital_presence,
    score_network_centrality,
    score_research_output,
)


def _make_clinician(**kwargs) -> MasterClinician:
    defaults = {
        "clinician_id": "test-id",
        "pub_count": 0,
        "trial_count": 0,
        "grant_count": 0,
        "review_count": 0,
        "h_index_proxy": None,
        "source_flags": [],
        "betweenness_centrality": None,
        "degree_centrality": None,
    }
    defaults.update(kwargs)
    c = MasterClinician()
    for k, v in defaults.items():
        setattr(c, k, v)
    return c


def test_research_output_zero():
    c = _make_clinician(pub_count=0, trial_count=0)
    assert score_research_output(c, 100, 10) == 0.0


def test_research_output_max():
    c = _make_clinician(pub_count=100, trial_count=10, h_index_proxy=30)
    score = score_research_output(c, 100, 10)
    assert score == 30.0


def test_research_output_partial():
    c = _make_clinician(pub_count=50, h_index_proxy=15)
    score = score_research_output(c, 100, 10)
    assert 0 < score < 30


def test_clinical_leadership():
    c = _make_clinician(source_flags=["ranzcog", "ages"], grant_count=3)
    score = score_clinical_leadership(c)
    assert score == 24.0  # 10 + 8 + min(6, 7)


def test_network_centrality_no_data():
    c = _make_clinician()
    assert score_network_centrality(c) == 0.0


def test_network_centrality_with_data():
    c = _make_clinician(betweenness_centrality=0.1, degree_centrality=0.3)
    score = score_network_centrality(c)
    assert score > 0


def test_digital_presence():
    c = _make_clinician(review_count=100, source_flags=["hospital", "linkedin"])
    score = score_digital_presence(c)
    assert score > 0


def test_composite_deterministic():
    c = _make_clinician(
        pub_count=20, trial_count=3, grant_count=2,
        source_flags=["pubmed", "ranzcog"], h_index_proxy=10,
    )
    score1 = calculate_influence_score(c, 50, 10)
    score2 = calculate_influence_score(c, 50, 10)
    assert score1 == score2
    assert 0 <= score1 <= 100
