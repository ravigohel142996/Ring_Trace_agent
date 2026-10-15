"""Guard against reintroducing an unauthenticated Streamlit action bypass."""
from pathlib import Path


def test_legacy_streamlit_view_has_no_direct_action_executor():
    source = (Path(__file__).resolve().parents[1] / "app" / "dashboard.py").read_text()
    assert "execute_recommended_action" not in source
    assert "Execute recommended action (simulated)" not in source
    assert "Direct graph actions are disabled" in source
