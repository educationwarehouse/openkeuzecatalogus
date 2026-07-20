"""Class-level helper utilities."""

import typing as t
from copy import deepcopy


def _deepcopy_attributes[T](old_cls: type[T], new_cls: type[T]) -> None:
    for attr_name, attr_value in old_cls.__dict__.items():
        if attr_name.startswith("__"):
            continue

        # Copy methods and callable attributes directly
        if callable(attr_value):
            setattr(new_cls, attr_name, attr_value)
            continue

        try:
            # Try to deep copy data attributes
            if isinstance(attr_value, (dict, list, set)):
                setattr(new_cls, attr_name, deepcopy(attr_value))
            else:
                # For immutable values, just set directly
                setattr(new_cls, attr_name, attr_value)
        except Exception as e:
            print(f"Error copying {attr_name}: {e}")
            # If copying fails, just reference it
            setattr(new_cls, attr_name, attr_value)


def _deepcopy_inherited[T](old_cls: type[T], new_cls: type[T]) -> None:
    for attr_name in dir(old_cls):
        # Skip what we've already handled and special methods
        if attr_name in new_cls.__dict__ or attr_name.startswith("__"):
            continue

        # Get the attribute value
        attr_value = getattr(old_cls, attr_name)

        # Skip methods (they come from the base class anyway)
        if callable(attr_value):
            continue

        # Skip descriptors
        if hasattr(attr_value, "__get__") and not isinstance(attr_value, (dict, list, set)):
            continue

        try:
            # Try to deep copy mutable attributes
            if isinstance(attr_value, (dict, list, set)):
                setattr(new_cls, attr_name, deepcopy(attr_value))
            else:
                # For immutable values, just set directly if they're not already in the class
                if not hasattr(new_cls, attr_name):
                    setattr(new_cls, attr_name, attr_value)
        except Exception as e:
            print(f"Error copying inherited {attr_name}: {e}")


def class_deepcopy[T](old_cls: type[T]) -> type[T]:
    """Create a deep copy of a class including all its attributes and inherited attributes.

    Normal `deepcopy` only works on instances, not on (abstract) types with class properties.
    """
    # Create a new class with the same name and bases
    new_cls = t.cast(type[T], type(old_cls.__name__, old_cls.__bases__, {}))

    # Copy methods and class attributes from the current class (not inherited)
    _deepcopy_attributes(old_cls, new_cls)

    # Now handle inherited attributes that the class might be using
    _deepcopy_inherited(old_cls, new_cls)

    return new_cls
