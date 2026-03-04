"""Tests for modules.banking_score.scoring.rating_scale.

Validates:
- Tier boundaries: no gaps in [0, 100]
- map_rating_tier covers edge cases
- get_tier_color returns valid hex for every tier
- get_all_tiers returns 10 entries
- check_boundary_proximity detection
"""
import pytest

from modules.banking_score.scoring.rating_scale import (
    RATING_SCALE,
    TIER_COLORS,
    check_boundary_proximity,
    get_all_tiers,
    get_tier_color,
    map_rating_tier,
)


class TestMapRatingTier:
    """map_rating_tier must cover [0, 100] without gaps."""

    @pytest.mark.parametrize("score,expected", [
        (100.0, "SDQ-AAA"),
        (95.0,  "SDQ-AAA"),
        (94.99, "SDQ-AA+"),
        (90.0,  "SDQ-AA+"),
        (89.99, "SDQ-AA"),
        (85.0,  "SDQ-AA"),
        (84.99, "SDQ-AA-"),
        (80.0,  "SDQ-AA-"),
        (79.99, "SDQ-A+"),
        (75.0,  "SDQ-A+"),
        (74.99, "SDQ-A"),
        (70.0,  "SDQ-A"),
        (69.99, "SDQ-A-"),
        (65.0,  "SDQ-A-"),
        (64.99, "SDQ-BBB+"),
        (55.0,  "SDQ-BBB+"),
        (54.99, "SDQ-BBB"),
        (45.0,  "SDQ-BBB"),
        (44.99, "SDQ-D"),
        (0.0,   "SDQ-D"),
    ])
    def test_boundary_values(self, score, expected):
        assert map_rating_tier(score) == expected

    def test_midpoints(self):
        """Each tier's midpoint must map to itself."""
        for tier, lo, hi in RATING_SCALE:
            mid = (lo + hi) / 2
            assert map_rating_tier(mid) == tier

    def test_full_range_no_gaps(self):
        """Every score from 0 to 100 in 0.01 steps must produce a valid tier."""
        valid_tiers = {t for t, _, _ in RATING_SCALE}
        score = 0.0
        while score <= 100.0:
            tier = map_rating_tier(score)
            assert tier in valid_tiers, f"Score {score} mapped to invalid tier '{tier}'"
            score = round(score + 0.01, 2)

    def test_negative_score_returns_d(self):
        assert map_rating_tier(-5.0) == "SDQ-D"

    def test_over_100_returns_aaa(self):
        assert map_rating_tier(100.0) == "SDQ-AAA"


class TestGetTierColor:
    def test_all_tiers_have_colors(self):
        for tier, _, _ in RATING_SCALE:
            color = get_tier_color(tier)
            assert color.startswith("#"), f"Color for {tier} is not hex: {color}"
            assert len(color) == 7, f"Color for {tier} has wrong length: {color}"

    def test_unknown_tier_returns_gray(self):
        assert get_tier_color("INVALID") == "#6B7280"


class TestGetAllTiers:
    def test_returns_10_tiers(self):
        tiers = get_all_tiers()
        assert len(tiers) == 10

    def test_tiers_are_ordered(self):
        tiers = get_all_tiers()
        for i, t in enumerate(tiers):
            assert t["index"] == i

    def test_each_tier_has_required_fields(self):
        for t in get_all_tiers():
            assert "tier" in t
            assert "lower" in t
            assert "upper" in t
            assert "color" in t
            assert "index" in t


class TestBoundaryProximity:
    def test_near_boundary_detected(self):
        # 45.0 is a boundary; 46.0 is within default threshold=2.0
        result = check_boundary_proximity(46.0)
        assert result is not None
        distance, direction = result
        assert distance == pytest.approx(1.0)
        assert direction == "downgrade"  # just above boundary

    def test_below_boundary(self):
        result = check_boundary_proximity(44.0)
        assert result is not None
        distance, direction = result
        assert distance == pytest.approx(1.0)
        assert direction == "upgrade"  # just below boundary

    def test_far_from_boundary(self):
        result = check_boundary_proximity(50.0)
        assert result is None

    def test_exact_boundary(self):
        result = check_boundary_proximity(75.0)
        assert result is not None
        assert result[0] == pytest.approx(0.0)
