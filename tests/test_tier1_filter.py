"""Tests for Tier-1 keyword/regex filter."""

from src.pipeline.tier1_filter import Tier1Filter


def test_financial_keyword_passes():
    """Posts with financial keywords should pass the filter."""
    f = Tier1Filter()
    assert f.passes_filter("Where should I invest 5 lakh for long term?") is True
    assert f.passes_filter("Best mutual fund for beginners?") is True
    assert f.passes_filter("Looking for a good SIP plan") is True


def test_noise_rejected():
    """Posts without financial keywords should be dropped."""
    f = Tier1Filter()
    assert f.passes_filter("What a beautiful sunset today!") is False
    assert f.passes_filter("Just finished my morning jog") is False


def test_matched_keywords_returns_hits():
    """get_matched_keywords should return the specific matches."""
    f = Tier1Filter()
    matches = f.get_matched_keywords("I want to invest in mutual fund via SIP")
    assert "invest" in matches
    assert "mutual fund" in matches
    assert "sip" in matches
