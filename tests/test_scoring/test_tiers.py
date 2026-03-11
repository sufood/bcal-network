from gyn_kol.scoring.tiers import assign_tier


def test_tier_1():
    assert assign_tier(80.0, 5.0, None) == 1
    assert assign_tier(75.0, 5.0, None) == 1
    assert assign_tier(100.0, 10.0, None) == 1


def test_tier_2():
    assert assign_tier(50.0, 5.0, None) == 2
    assert assign_tier(74.9, 5.0, None) == 2


def test_tier_3():
    assert assign_tier(25.0, 5.0, None) == 3
    assert assign_tier(49.9, 5.0, None) == 3
    assert assign_tier(10.0, 2.0, None) == 3


def test_tier_4_centrality_override():
    # High centrality overrides regardless of score
    assert assign_tier(20.0, 2.0, 0.2) == 4
    assert assign_tier(90.0, 9.0, 0.2) == 4


def test_tier_4_threshold():
    # Below threshold, normal tier assignment
    assert assign_tier(80.0, 5.0, 0.10) == 1
    assert assign_tier(50.0, 5.0, 0.14) == 2
