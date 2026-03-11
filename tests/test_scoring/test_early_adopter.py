from gyn_kol.models.clinician import MasterClinician
from gyn_kol.scoring.early_adopter import calculate_early_adopter_score


def _make_clinician(**kwargs) -> MasterClinician:
    defaults = {
        "clinician_id": "test-id",
        "pub_count": 0,
        "trial_count": 0,
        "grant_count": 0,
        "review_count": 0,
        "source_flags": [],
        "specialty": None,
    }
    defaults.update(kwargs)
    c = MasterClinician()
    for k, v in defaults.items():
        setattr(c, k, v)
    return c


def test_zero_score():
    c = _make_clinician()
    assert calculate_early_adopter_score(c) == 0.0


def test_specialty_flag():
    c = _make_clinician(specialty="Minimally Invasive Surgery")
    assert calculate_early_adopter_score(c) >= 2.0


def test_multiple_sources():
    c = _make_clinician(source_flags=["pubmed", "ranzcog", "hospital"])
    assert calculate_early_adopter_score(c) >= 2.0


def test_tech_pubs():
    c = _make_clinician(pub_count=10)
    assert calculate_early_adopter_score(c) >= 2.0


def test_max_score():
    c = _make_clinician(
        specialty="oncology",
        source_flags=["pubmed", "ranzcog", "hospital", "university", "ages"],
        pub_count=20,
        review_count=50,
    )
    score = calculate_early_adopter_score(c)
    assert score == 10.0


def test_combination():
    c = _make_clinician(
        specialty="MIS",
        source_flags=["pubmed", "ranzcog", "hospital"],
        pub_count=5,
    )
    score = calculate_early_adopter_score(c)
    # MIS specialty: +2, 3 sources: +2, hospital+ranzcog: +1, 5 pubs: +2 = 7
    assert score == 7.0
