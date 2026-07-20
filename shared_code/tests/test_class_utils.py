"""Tests for class-level utility helpers."""

from shared_code.util.class_utils import class_deepcopy


class _BaseConfig:
    """Base class providing inherited attributes for deepcopy coverage."""

    shared_state = {"nested": {"count": 1}}
    labels = ["alpha", "beta"]
    tags = {"first"}
    number = 41

    @property
    def computed(self) -> int:
        """Return a derived value from the inherited class state."""
        return self.number + 1


class _ChildConfig(_BaseConfig):
    """Subclass with its own mutable class attributes and methods."""

    own_state = {"numbers": [1, 2]}

    def describe(self) -> str:
        """Use both inherited and local class attributes."""
        return f"{self.computed}:{self.own_state['numbers'][-1]}"


def test_class_deepcopy_creates_independent_copy_with_inherited_behavior() -> None:
    """Copied classes should preserve behavior without sharing mutable state."""
    copied = class_deepcopy(_ChildConfig)

    assert copied is not _ChildConfig
    assert copied.__name__ == _ChildConfig.__name__
    assert copied.__bases__ == _ChildConfig.__bases__

    copied_instance = copied()
    assert copied_instance.computed == 42
    assert copied_instance.describe() == "42:2"

    assert copied.shared_state == _ChildConfig.shared_state
    assert copied.labels == _ChildConfig.labels
    assert copied.tags == _ChildConfig.tags
    assert copied.own_state == _ChildConfig.own_state
    assert copied.shared_state is not _ChildConfig.shared_state
    assert copied.labels is not _ChildConfig.labels
    assert copied.tags is not _ChildConfig.tags
    assert copied.own_state is not _ChildConfig.own_state

    copied.shared_state["nested"]["count"] = 9
    copied.labels.append("gamma")
    copied.tags.add("second")
    copied.own_state["numbers"].append(3)

    assert _ChildConfig.shared_state == {"nested": {"count": 1}}
    assert _ChildConfig.labels == ["alpha", "beta"]
    assert _ChildConfig.tags == {"first"}
    assert _ChildConfig.own_state == {"numbers": [1, 2]}
