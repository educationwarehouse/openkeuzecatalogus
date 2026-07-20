"""Concrete effective-dated table base class."""

from shared_code.data_model.tables.base import BaseTable

from .mixin import EffdtFields


class EffdtTable(EffdtFields, BaseTable):
    """Concrete table base class (protocol) for effective-dated models."""
