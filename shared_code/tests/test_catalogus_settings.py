"""Database-backed tests for reusable JSON catalogue settings."""

import datetime as dt
import typing as t
import uuid

import pytest

from shared_code.data_model import AuthUser, CatalogusSetting
from shared_code.infra.database import DatabaseContext
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.catalogus_settings import CatalogusSettings
from shared_code.modules.recommendations.similar_materials import SIMILAR_MATERIAL_LIMIT_KEY


@pytest.fixture()
def catalogus_settings(db_per_file: DatabaseContext) -> CatalogusSettings:
    """Use the shared settings domain against the migrated database."""
    return CatalogusSettings.with_injected(
        db=db_per_file, auth_adapter=AuthAdapter.for_service("catalogus-settings-tests")
    )


@pytest.fixture()
def setting_key(db_per_file: DatabaseContext) -> t.Iterator[str]:
    """Isolate and clean up a setting without touching the seeded configuration."""
    key = f"tests.{uuid.uuid4().hex}"
    try:
        yield key
    finally:
        CatalogusSetting.where(CatalogusSetting.key == key).delete()
        db_per_file.commit()


def _setting(key: str) -> CatalogusSetting:
    """Load a stored setting and fail clearly if it was not persisted."""
    row = CatalogusSetting.where(CatalogusSetting.key == key).first()
    assert row is not None
    return row


def test_migration_seeds_the_global_limit_as_a_json_integer(catalogus_settings: CatalogusSettings) -> None:
    """The migration supplies the default and standard base-table metadata."""
    row = _setting(SIMILAR_MATERIAL_LIMIT_KEY)

    assert catalogus_settings.get(SIMILAR_MATERIAL_LIMIT_KEY) == 9
    assert type(row.value) is int
    assert str(uuid.UUID(str(row.gid))) == str(row.gid)
    assert isinstance(row.created_at, dt.datetime)
    assert isinstance(row.updated_at, dt.datetime)
    assert CatalogusSetting.where(CatalogusSetting.key == SIMILAR_MATERIAL_LIMIT_KEY).count() == 1


def test_missing_setting_uses_the_callers_default_without_inserting_a_row(
    catalogus_settings: CatalogusSettings, setting_key: str
) -> None:
    """Reading a missing key leaves the database unchanged."""
    assert catalogus_settings.get(setting_key, default=9) == 9
    assert catalogus_settings.get(setting_key, default={"enabled": True}) == {"enabled": True}
    assert catalogus_settings.get(setting_key) is None
    assert CatalogusSetting.where(CatalogusSetting.key == setting_key).count() == 0


@pytest.mark.parametrize(
    "value",
    [
        9,
        0,
        1.5,
        True,
        False,
        "plain text",
        "9",
        "true",
        "null",
        "[1, 2]",
        '{"looks": "like JSON"}',
        [],
        [1, "two", False],
        {"enabled": True, "levels": ["Havo"], "limit": 9},
        None,
    ],
)
def test_json_values_round_trip_without_coercing_their_types(
    value: object, db_per_file: DatabaseContext, catalogus_settings: CatalogusSettings, setting_key: str
) -> None:
    """The reusable table preserves scalars, strings, lists, objects, and null."""
    catalogus_settings.set(setting_key, value=value)
    reader = CatalogusSettings.with_injected(
        db=db_per_file, auth_adapter=AuthAdapter.for_service("catalogus-settings-reader")
    )

    restored = reader.get(setting_key, default="Missing")

    assert restored == value
    assert type(restored) is type(value)
    assert _setting(setting_key).value == value


def test_updating_a_setting_preserves_identity_and_creation_time_and_updates_timestamp(
    db_per_file: DatabaseContext, catalogus_settings: CatalogusSettings, setting_key: str
) -> None:
    """Saving an existing key updates its value and metadata without adding a row."""
    catalogus_settings.set(setting_key, value=9)
    initial = _setting(setting_key)
    old_timestamp = dt.datetime(2000, 1, 1)
    db_per_file.executesql(
        "UPDATE catalogus_setting SET updated_at = %(timestamp)s WHERE key = %(key)s;",
        placeholders={"timestamp": old_timestamp, "key": setting_key},
    )
    db_per_file.commit()

    catalogus_settings.set(setting_key, value={"enabled": True, "limit": 3})
    updated = _setting(setting_key)

    assert updated.id == initial.id
    assert updated.gid == initial.gid
    assert updated.created_at == initial.created_at
    assert updated.updated_at > old_timestamp
    assert updated.value == {"enabled": True, "limit": 3}
    assert CatalogusSetting.where(CatalogusSetting.key == setting_key).count() == 1


def test_setting_keys_are_independent(catalogus_settings: CatalogusSettings, setting_key: str) -> None:
    """An unrelated setting cannot change the catalogue suggestion limit."""
    original_limit = catalogus_settings.get(SIMILAR_MATERIAL_LIMIT_KEY)

    catalogus_settings.set(setting_key, value=27)

    assert catalogus_settings.get(setting_key) == 27
    assert catalogus_settings.get(SIMILAR_MATERIAL_LIMIT_KEY) == original_limit


def test_admin_can_persist_settings(
    db_per_file: DatabaseContext,
    admin_user: AuthUser,
    auth_adapter_factory: t.Callable[..., AuthAdapter],
    setting_key: str,
) -> None:
    """Client administrators can use the shared writer with real RBAC membership."""
    settings = CatalogusSettings.with_injected(db=db_per_file, auth_adapter=auth_adapter_factory(admin_user))

    settings.set(setting_key, value=3)

    assert _setting(setting_key).value == 3


def test_non_admin_cannot_create_or_overwrite_settings(
    db_per_file: DatabaseContext,
    normal_user: AuthUser,
    auth_adapter_factory: t.Callable[..., AuthAdapter],
    catalogus_settings: CatalogusSettings,
    setting_key: str,
) -> None:
    """Ordinary users cannot insert settings or change existing values."""
    visitor = CatalogusSettings.with_injected(db=db_per_file, auth_adapter=auth_adapter_factory(normal_user))

    with pytest.raises(PermissionError):
        visitor.set(setting_key, value=2)
    assert CatalogusSetting.where(CatalogusSetting.key == setting_key).count() == 0

    catalogus_settings.set(setting_key, value=9)
    original = _setting(setting_key)
    with pytest.raises(PermissionError):
        visitor.set(setting_key, value=2)

    current = _setting(setting_key)
    assert current.value == 9
    assert current.gid == original.gid
    assert current.updated_at == original.updated_at


@pytest.mark.parametrize("value", [float("nan"), float("inf"), {"nested": float("nan")}])
def test_non_json_numbers_cannot_overwrite_existing_values(
    value: object, catalogus_settings: CatalogusSettings, setting_key: str
) -> None:
    """JSON serialization errors leave the last successfully saved value intact."""
    catalogus_settings.set(setting_key, value=9)

    with pytest.raises(ValueError):
        catalogus_settings.set(setting_key, value=value)

    assert catalogus_settings.get(setting_key) == 9
