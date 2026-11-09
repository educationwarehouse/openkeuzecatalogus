"""SQLite-backed Kennisnet catalogue cache for the admin grid."""

import datetime as dt
import json
import typing as t
from pathlib import Path

from typedal import TypeDAL, TypedField, TypedTable
from yayarl import URL

from shared_code.data_model.tables.base import TableWithGid
from shared_code.modules.scrapers.eduv import fetch_eduv_products
from shared_code.modules.scrapers.kennisnet import KENNISNET_CATALOGUE_BASE_URL
from shared_code.util.time import ensure_utc, utcnow

KENNISNET_CATALOGUE_CACHE_DIR = Path("/shared_cache/kennisnet_catalogue")
KENNISNET_CATALOGUE_DB_PATH = KENNISNET_CATALOGUE_CACHE_DIR / "catalogue.sqlite"
KENNISNET_CATALOGUE_TTL = dt.timedelta(hours=1)
CATALOGUE_STATE_KEY = "catalogue"


class KennisnetCatalogueProduct(TableWithGid):
    """One Kennisnet product row and its complete source data for the admin grid."""

    publisher = TypedField(str, length=255, label="Uitgever")
    name = TypedField(str, length=1024, label="Product")
    product_id = TypedField(str, length=255, label="Product-ID")
    version = TypedField(str, length=10, label="Edu-V versie")
    status = TypedField(str, length=80, label="Beschikbaarheid")
    product_type = TypedField(str, length=80, label="Type")
    source_json = TypedField(str | None, type="text", default=None, readable=False)


class KennisnetCataloguePublisher(TableWithGid):
    """One Kennisnet publisher with its preferred available Edu-V version."""

    publisher = TypedField(str, length=255, label="Uitgever")
    version = TypedField(str, length=10, label="Edu-V versie")


class KennisnetCatalogueState(TypedTable):
    """Refresh metadata for the shared Kennisnet catalogue database."""

    cache_key = TypedField(str, length=80, unique=True)
    refreshed_at = TypedField(dt.datetime)


class KennisnetCatalogueRefresh(t.TypedDict):
    """State of the SQLite catalogue after a freshness check."""

    refreshed_at: dt.datetime
    is_stale: bool


class KennisnetCatalogueStatus(t.TypedDict):
    """The currently stored Kennisnet catalogue state."""

    refreshed_at: dt.datetime | None
    is_stale: bool


class KennisnetCatalogueRefreshRequest(t.TypedDict):
    """Payload for a queued Kennisnet catalogue refresh."""

    force: bool


class KennisnetCatalogueLoadError(RuntimeError):
    """Raised when the catalogue has not yet been loaded successfully."""


def refresh_kennisnet_catalogue_if_stale(
    force: bool = False,
    database_path: Path = KENNISNET_CATALOGUE_DB_PATH,
    base_url: URL = KENNISNET_CATALOGUE_BASE_URL,
) -> KennisnetCatalogueRefresh:
    """Refresh the shared SQLite catalogue when stale or explicitly requested."""
    catalogue_db = _catalogue_database(database_path=database_path)
    try:
        return _refresh_catalogue(catalogue_db, force=force, base_url=base_url)
    finally:
        catalogue_db.close()


def _refresh_catalogue(catalogue_db: TypeDAL, force: bool, base_url: URL) -> KennisnetCatalogueRefresh:
    state = _catalogue_state()
    if state and not force and _is_fresh(state.refreshed_at):
        return KennisnetCatalogueRefresh(refreshed_at=state.refreshed_at, is_stale=False)

    try:
        _replace_catalogue_rows(base_url=base_url)
    except Exception as error:
        catalogue_db.rollback()
        if state:
            return KennisnetCatalogueRefresh(refreshed_at=state.refreshed_at, is_stale=True)
        raise KennisnetCatalogueLoadError("Kennisnet-catalogus kon niet worden geladen.") from error

    refreshed_at = utcnow()
    if state:
        state.update_record(refreshed_at=refreshed_at)
    else:
        KennisnetCatalogueState.insert(cache_key=CATALOGUE_STATE_KEY, refreshed_at=refreshed_at)
    catalogue_db.commit()
    return KennisnetCatalogueRefresh(refreshed_at=refreshed_at, is_stale=False)


def kennisnet_catalogue_status(database_path: Path = KENNISNET_CATALOGUE_DB_PATH) -> KennisnetCatalogueStatus:
    """Return cache metadata without downloading Kennisnet data."""
    catalogue_db = _catalogue_database(database_path=database_path)
    try:
        return catalogue_status(catalogue_db)
    finally:
        catalogue_db.close()


def catalogue_status(database: TypeDAL) -> KennisnetCatalogueStatus:
    """Read cache metadata using a connection whose lifetime the caller owns."""
    state = database(KennisnetCatalogueState.cache_key == CATALOGUE_STATE_KEY).select().first()
    if not state:
        return KennisnetCatalogueStatus(refreshed_at=None, is_stale=True)
    return KennisnetCatalogueStatus(
        refreshed_at=state.refreshed_at,
        is_stale=not _is_fresh(state.refreshed_at),
    )


def _catalogue_database(database_path: Path = KENNISNET_CATALOGUE_DB_PATH) -> TypeDAL:
    """Open one catalogue connection; the caller owns its lifetime."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    database = TypeDAL(f"sqlite://{database_path}", migrate=True, use_pyproject=False)
    define_catalogue_tables(database)

    return database


def define_catalogue_tables(database: TypeDAL) -> None:
    """Bind the catalogue schema to a worker DAL or a web DAL fixture."""
    database.define(KennisnetCatalogueProduct, rname="kennisnet_catalogue_product", migrate=True)
    database.define(KennisnetCataloguePublisher, rname="kennisnet_catalogue_publisher", migrate=True)
    database.define(KennisnetCatalogueState, rname="kennisnet_catalogue_state", migrate=True)


def _catalogue_state() -> KennisnetCatalogueState | None:
    return KennisnetCatalogueState.where(KennisnetCatalogueState.cache_key == CATALOGUE_STATE_KEY).first()


def _is_fresh(refreshed_at: dt.datetime) -> bool:
    return utcnow() - ensure_utc(refreshed_at) < KENNISNET_CATALOGUE_TTL


def _replace_catalogue_rows(base_url: URL = KENNISNET_CATALOGUE_BASE_URL) -> None:
    v1_products = fetch_eduv_products(base_url / "v1/products", uses_pagination=True)
    v2_products = fetch_eduv_products(base_url / "v2/products", uses_pagination=True)
    v2_publishers = {_publisher(product) for product in v2_products}

    KennisnetCatalogueProduct.truncate()
    KennisnetCataloguePublisher.truncate()
    for product in v2_products:
        _insert_product(product, "v2")
    for product in v1_products:
        if _publisher(product) not in v2_publishers:
            _insert_product(product, "v1")

    for publisher in sorted(v2_publishers):
        _insert_publisher(publisher, "v2")
    for publisher in sorted({_publisher(product) for product in v1_products} - v2_publishers):
        _insert_publisher(publisher, "v1")


def _insert_product(product: dict[str, t.Any], version: str) -> None:
    KennisnetCatalogueProduct.insert(
        publisher=_publisher(product),
        name=_string(product.get("name")),
        product_id=_string(product.get("productId")),
        version=version,
        status=_string(product.get("status")),
        product_type=_string(product.get("type")),
        source_json=json.dumps(product, ensure_ascii=False),
    )


def _insert_publisher(publisher: str, version: str) -> None:
    if publisher:
        KennisnetCataloguePublisher.insert(publisher=publisher, version=version)


def _publisher(product: dict[str, t.Any]) -> str:
    return _string(product.get("publisher"))


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
