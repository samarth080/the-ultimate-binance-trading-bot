import pytest
from src.signal_engine import Tier, _classify_tier

def test_tier1_minimum_boundary():
    assert _classify_tier(80.0, True, "TRENDING") == Tier.TIER_1

def test_tier2_just_below_tier1():
    assert _classify_tier(79.0, True, "TRENDING") == Tier.TIER_2

def test_tier1_requires_htf_confirm():
    assert _classify_tier(80.0, False, "TRENDING") == Tier.TIER_2

def test_tier1_requires_trending_or_neutral():
    assert _classify_tier(80.0, True, "VOLATILE") == Tier.TIER_2

def test_tier1_neutral_regime_ok():
    assert _classify_tier(80.0, True, "NEUTRAL") == Tier.TIER_1

def test_tier2_minimum_boundary():
    assert _classify_tier(65.0, False, "RANGING") == Tier.TIER_2

def test_tier3_just_below_tier2():
    assert _classify_tier(64.0, False, "RANGING") == Tier.TIER_3

def test_tier3_low_score():
    assert _classify_tier(50.0, False, "VOLATILE") == Tier.TIER_3
