import pytest

from backend.graph import _route_approval


def test_explicit_true_routes_to_manager_approval():
    assert _route_approval(
        {"requires_approval": True}
    ) == "approval"


def test_explicit_false_routes_to_draft_response():
    assert _route_approval(
        {"requires_approval": False}
    ) == "draft"


def test_missing_value_defaults_to_draft_response():
    assert _route_approval({}) == "draft"


@pytest.mark.parametrize(
    "invalid_value",
    ["True", "False", 1, 0, None, (False, [])],
)
def test_non_boolean_approval_values_are_rejected(invalid_value):
    with pytest.raises(TypeError):
        _route_approval(
            {"requires_approval": invalid_value}
        )
