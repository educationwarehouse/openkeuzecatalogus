"""Importer tests executed in the PGQ suite."""

import json
import typing as t
import uuid
import warnings
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from mimetypes import guess_type
from pathlib import Path
from threading import Thread

import pytest
from typedal import TypeDAL
from yayarl import URL

from shared_code.data_model import ImporterRun, ImporterRunEvent, Method, MethodEd, Product, ProductEd, SupplierEd
from shared_code.infra.database import database_context, rebuild_model
from shared_code.modules.auth import AuthAdapter
from shared_code.modules.scrapers.eduv import (
    EduVFileVersion,
    EduVImporter,
    EduVImporterV2,
    fetch_eduv_product_page,
    fetch_eduv_products,
)
from shared_code.modules.scrapers.eduv.generated import catalogue_v1_1_0, catalogue_v2_0_0
from shared_code.modules.scrapers.eduv.json_import import EduVFileImporter, default_eduv_file_version
from shared_code.modules.scrapers.errors import ImportErrorCode
from shared_code.modules.scrapers.kennisnet_catalogue import (
    KennisnetCatalogueLoadError,
    KennisnetCatalogueProduct,
    KennisnetCataloguePublisher,
    define_catalogue_tables,
    kennisnet_catalogue_status,
    refresh_kennisnet_catalogue_if_stale,
)
from shared_code.modules.scrapers.kennisnet_import import KennisnetCatalogueImporter
from shared_code.util import olid

FIXTURE_DIR = Path(__file__).parent / "data" / "eduv"
BASE_URL_V1 = (FIXTURE_DIR / "v1.1.0").resolve().as_uri()
BASE_URL_V2 = (FIXTURE_DIR / "v2.0.0").resolve().as_uri()

EDUV_PGQ_SUPPLIER_GID = "e6bbca64-cf76-46d6-a1a4-3a1d61010c66"  # fixed test gid

ERROR_UNUSED_FIELDS = "unused top-level fields"
STRICT_UNUSED = True


class FixtureFileHandler(BaseHTTPRequestHandler):
    """Serve files configured on a FixtureFileServer."""

    def do_GET(self) -> None:
        """Serve the fixture file requested by the client."""
        server = t.cast(FixtureFileServer, self.server)
        server.requested_paths.append(self.path)
        fixture_path = server.files.get(self.path)
        if fixture_path is None:
            self.send_error(404)
            return

        response = fixture_path.read_bytes()
        self.send_response(200)
        content_type, _ = guess_type(fixture_path.name)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format: str, *args: object) -> None:
        """Suppress request logging during fixture-server tests."""
        return


class FixtureFileServer(ThreadingHTTPServer):
    """HTTP server with explicit fixture-file routing state."""

    files: dict[str, Path]
    requested_paths: list[str]

    def __init__(self, files: dict[str, Path]) -> None:
        """Create a server that maps request paths to fixture files."""
        super().__init__(("127.0.0.1", 0), FixtureFileHandler)
        self.files = files
        self.requested_paths = []

    @property
    def base_url(self) -> str:
        """Return the server's local HTTP base URL."""
        host, port = self.server_address[0], self.server_address[1]
        return f"http://{host}:{port}/"


@contextmanager
def _serve_files(files: dict[str, Path]) -> Iterator[FixtureFileServer]:
    """Serve fixture files by request path, including their query string."""
    server = FixtureFileServer(files)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@contextmanager
def _serve_eduv_product_pages(
    tmp_path: Path,
    pages: dict[int, list[dict[str, str]]],
    page_size: int,
) -> Iterator[FixtureFileServer]:
    """Serve Edu-V product envelopes for each requested pagination offset."""
    response_files: dict[str, Path] = {}
    terminal_start = max(start + len(products) for start, products in pages.items())
    pages = {**pages, terminal_start: []}

    for start, products in pages.items():
        response_path = tmp_path / f"products-{start}.json"
        response_path.write_text(json.dumps({"products": products}), encoding="utf-8")
        response_files[f"/products?start={start}&limit={page_size}"] = response_path

    with _serve_files(response_files) as server:
        yield server


def _assert_no_unused_field_debug_output(output: str) -> None:
    matching_lines = [line for line in output.splitlines() if ERROR_UNUSED_FIELDS in line]
    if STRICT_UNUSED:
        assert not matching_lines, "\n".join(matching_lines)
    else:
        warnings.warn("\n".join(matching_lines), stacklevel=0)


def _eduv_clean(db: TypeDAL, supplier_gid: str = EDUV_PGQ_SUPPLIER_GID) -> None:
    ProductEd.where(supplier_gid=supplier_gid).delete()
    rebuild_model(db, "product")
    MethodEd.where(supplier_gid=supplier_gid).delete()
    rebuild_model(db, "method")
    SupplierEd.where(gid=supplier_gid).delete()
    rebuild_model(db, "supplier")


@pytest.fixture
def prepare_eduv_importer_data() -> Iterator[Callable[[str], None]]:
    """Clean registered supplier data before and after an importer integration test."""
    supplier_gids: set[str] = set()

    def prepare(supplier_gid: str) -> None:
        supplier_gids.add(supplier_gid)
        with database_context("pytest.pgq.scrapers.fixture_setup") as db:
            _eduv_clean(db, supplier_gid=supplier_gid)

    yield prepare

    with database_context("pytest.pgq.scrapers.fixture_cleanup") as db:
        for supplier_gid in supplier_gids:
            _eduv_clean(db, supplier_gid=supplier_gid)


@pytest.mark.parametrize(
    ("fixture_path", "product_model"),
    [
        (FIXTURE_DIR / "v1.1.0" / "products.json", catalogue_v1_1_0.Product),
        (FIXTURE_DIR / "v2.0.0" / "products.json", catalogue_v2_0_0.Product),
    ],
)
def test_eduv_products_fixtures_match_catalogue_schema(
    fixture_path: Path,
    product_model: type[catalogue_v1_1_0.Product | catalogue_v2_0_0.Product],
) -> None:
    """Fixture products must validate against the matching versioned catalogue schema."""
    payload = json.loads(fixture_path.read_text())

    assert isinstance(payload.get("products"), list)
    for row in payload["products"]:
        product_model.model_validate(row)


def test_eduv_v2_importer_filters_fixture_products_by_endpoint_publisher() -> None:
    """Edu-V v2 importer should drop products whose publisher does not match the configured filter."""
    importer = EduVImporter.with_injected(
        base_url=BASE_URL_V2,
        supplier_gid=EDUV_PGQ_SUPPLIER_GID,
        endpoint_publisher="Malmberg",
        auth_adapter=AuthAdapter.for_service("pytest.eduv_v2"),
    )

    products = importer.fetch_products()
    methods = importer.fetch_methods()

    assert len(products) == 1
    assert products[0]["isbn"] == "9789402054958"
    assert products[0]["name"] == "Biologie voor jou 4 havo/vwo leerboek"

    assert len(methods) == 1
    assert methods[0]["name"] == "Biologie voor jou"


def test_eduv_paginated_products_collects_enveloped_pages(tmp_path: Path) -> None:
    """Paginated endpoints collect every products envelope before stopping at an empty page."""
    pages = {
        0: [{"productId": "first"}, {"productId": "second"}],
        2: [{"productId": "third"}, {"productId": "fourth"}],
    }

    with _serve_eduv_product_pages(tmp_path, pages, page_size=2) as server:
        products = fetch_eduv_products(URL(server.base_url) / "products", uses_pagination=True, page_size=2)

    assert products == [product for page in pages.values() for product in page]
    assert server.requested_paths == [
        "/products?start=0&limit=2",
        "/products?start=2&limit=2",
        "/products?start=4&limit=2",
    ]


@pytest.mark.parametrize(
    ("pages", "expected_message"),
    [
        ({0: [{}]}, "page without a productId"),
        ({0: [{"productId": "first"}], 1: [{"productId": "first"}]}, "returned a repeated page"),
    ],
)
def test_eduv_paginated_products_reject_invalid_page_sequences(
    tmp_path: Path,
    pages: dict[int, list[dict[str, str]]],
    expected_message: str,
) -> None:
    """Pagination fails safely when a page cannot advance reliably."""
    with (
        _serve_eduv_product_pages(tmp_path, pages, page_size=1) as server,
        pytest.raises(ValueError, match=expected_message),
    ):
        fetch_eduv_products(URL(server.base_url) / "products", uses_pagination=True, page_size=1)


def test_eduv_product_page_and_helpers_handle_incomplete_payloads(tmp_path: Path) -> None:
    """Malformed endpoint responses and remaining helpers use explicit fallbacks."""
    malformed_object = tmp_path / "malformed-object.json"
    malformed_object.write_text("{}", encoding="utf-8")
    malformed_scalar = tmp_path / "malformed-scalar.json"
    malformed_scalar.write_text('"not a product list"', encoding="utf-8")

    with _serve_files({"/object": malformed_object, "/scalar": malformed_scalar}) as server:
        with pytest.raises(ValueError, match="must contain a 'products' key"):
            fetch_eduv_product_page(URL(server.base_url) / "object")
        with pytest.raises(ValueError, match="must return a JSON list"):
            fetch_eduv_product_page(URL(server.base_url) / "scalar")

    importer = EduVImporterV2(base_url="https://catalogus.edu-v.kennisnet.nl/v2/")
    assert importer._extract_version_from_text("not a version") is None
    assert importer._matches_endpoint_publisher({}) is False
    assert importer._extract_bouw(["vwo", "havo x", "havo 4"]) == ["bovenbouw"]

    importer.base_url = ""
    with pytest.raises(ValueError, match="base_url is not configured"):
        importer._fetch_products_payload()


def test_kennisnet_catalogue_refresh_prefers_v2_publishers_and_retains_stale_cache(tmp_path: Path) -> None:
    """The cache prefers v2 publishers and remains available when a later refresh fails."""
    responses = {
        "/v1/products?start=0&limit=100": {
            "products": [
                {
                    "publisher": "Shared",
                    "name": "Shared v1",
                    "productId": "shared-v1",
                    "status": "available",
                    "type": "book",
                },
                {
                    "publisher": "V1 only",
                    "name": "V1 product",
                    "productId": "v1",
                    "status": "available",
                    "type": "book",
                },
            ]
        },
        "/v1/products?start=2&limit=100": {"products": []},
        "/v2/products?start=0&limit=100": {
            "products": [
                {
                    "publisher": "Shared",
                    "name": "Shared v2",
                    "productId": "shared-v2",
                    "status": "available",
                    "type": "digital",
                },
                {
                    "publisher": "V2 only",
                    "name": "V2 product",
                    "productId": "v2",
                    "status": "available",
                    "type": "digital",
                },
            ]
        },
        "/v2/products?start=2&limit=100": {"products": []},
    }
    files: dict[str, Path] = {}
    for index, (request_path, response) in enumerate(responses.items()):
        response_path = tmp_path / f"response-{index}.json"
        response_path.write_text(json.dumps(response), encoding="utf-8")
        files[request_path] = response_path

    database_path = tmp_path / "catalogue.sqlite"
    with _serve_files(files) as server:
        refreshed = refresh_kennisnet_catalogue_if_stale(
            force=True, database_path=database_path, base_url=URL(server.base_url)
        )
        assert refreshed["is_stale"] is False
        with closing(TypeDAL(f"sqlite://{database_path}", migrate=True, use_pyproject=False)) as catalogue_db:
            define_catalogue_tables(catalogue_db)
            product_rows = KennisnetCatalogueProduct.select(orderby=KennisnetCatalogueProduct.publisher).collect()
            publisher_rows = KennisnetCataloguePublisher.select(orderby=KennisnetCataloguePublisher.publisher).collect()

            assert {(row.publisher, row.version, row.product_id) for row in product_rows} == {
                ("Shared", "v2", "shared-v2"),
                ("V1 only", "v1", "v1"),
                ("V2 only", "v2", "v2"),
            }
            assert {(row.publisher, row.version) for row in publisher_rows} == {
                ("Shared", "v2"),
                ("V1 only", "v1"),
                ("V2 only", "v2"),
            }
        assert kennisnet_catalogue_status(database_path=database_path)["is_stale"] is False

        requested_paths = list(server.requested_paths)
        cached = refresh_kennisnet_catalogue_if_stale(
            force=False, database_path=database_path, base_url=URL(server.base_url)
        )
        assert cached["is_stale"] is False
        assert server.requested_paths == requested_paths

        stale = refresh_kennisnet_catalogue_if_stale(
            force=True, database_path=database_path, base_url=URL(server.base_url) / "missing"
        )
        assert stale["is_stale"] is True

        with pytest.raises(KennisnetCatalogueLoadError):
            refresh_kennisnet_catalogue_if_stale(
                force=True, database_path=tmp_path / "missing.sqlite", base_url=URL(server.base_url) / "missing"
            )


@pytest.mark.parametrize(
    ("version", "fixture_directory", "base_url"),
    [
        ("v1", "v1.1.0", BASE_URL_V1),
        ("v2", "v2.0.0", BASE_URL_V2),
    ],
)
def test_eduv_file_importer_matches_endpoint_importer_for_valid_fixture(
    version: EduVFileVersion,
    fixture_directory: str,
    base_url: str,
) -> None:
    """Uploaded catalogues use the same schema validation and normalization as endpoints."""
    payload = json.loads((FIXTURE_DIR / fixture_directory / "products.json").read_text())
    endpoint_importer = EduVImporter.with_injected(
        base_url=base_url,
        supplier_gid=EDUV_PGQ_SUPPLIER_GID,
        auth_adapter=AuthAdapter.for_service(f"pytest.eduv_{version}"),
    )
    file_importer = EduVFileImporter(
        payload=payload,
        version=version,
        supplier_gid=EDUV_PGQ_SUPPLIER_GID,
    )

    file_products = [
        {key: value for key, value in product.items() if key not in {"_source_row", "_source_row_index"}}
        for product in file_importer.fetch_products()
    ]

    assert file_products == endpoint_importer.fetch_products()
    assert file_importer.fetch_methods() == endpoint_importer.fetch_methods()
    assert file_importer.validation_errors() == []


def test_eduv_file_importer_filters_products_by_endpoint_publisher() -> None:
    """Uploaded catalogues retain the endpoint publisher filter."""
    payload = json.loads((FIXTURE_DIR / "v2.0.0" / "products.json").read_text())
    importer = EduVFileImporter(
        payload=payload,
        version="v2",
        supplier_gid=EDUV_PGQ_SUPPLIER_GID,
        endpoint_publisher="Malmberg",
    )

    products = importer.fetch_products()
    methods = importer.fetch_methods()

    assert len(products) == 1
    assert products[0]["isbn"] == "9789402054958"
    assert len(methods) == 1
    assert methods[0]["name"] == "Biologie voor jou"


def test_eduv_file_importer_reports_invalid_rows_as_error_products() -> None:
    """An invalid uploaded row remains visible as a minimal error product."""
    payload = json.loads((FIXTURE_DIR / "v2.0.0" / "products.json").read_text())
    del payload["products"][0]["productId"]
    importer = EduVFileImporter(
        payload=payload,
        version="v2",
        supplier_gid=EDUV_PGQ_SUPPLIER_GID,
    )

    products = importer.fetch_products()
    errors = importer.validation_errors()

    assert len(products) == 2
    invalid_product = next(
        product for product in products if ImportErrorCode.ROW_VALIDATION_FAILED in product["_errors"]
    )
    assert "olid" not in invalid_product
    assert invalid_product["_source_row_index"] == 1
    assert len(errors) == 1
    assert errors[0].index == 1
    assert any(message.startswith("productId:") for message in errors[0].messages)


def test_eduv_file_importer_keeps_source_index_for_invalid_rows() -> None:
    """Schema errors must point to the original product row in an uploaded file."""
    payload = json.loads((FIXTURE_DIR / "v2.0.0" / "products.json").read_text())
    del payload["products"][1]["productId"]
    importer = EduVFileImporter(
        payload=payload,
        version="v2",
        supplier_gid=EDUV_PGQ_SUPPLIER_GID,
    )

    errors = importer.validation_errors()

    assert len(errors) == 1
    assert errors[0].index == 2


def test_eduv_file_importer_archives_items_omitted_from_a_later_file(
    prepare_eduv_importer_data: Callable[[str], None],
) -> None:
    """A later uploaded file marks its supplier's omitted products and methods as removed."""
    supplier_gid = str(uuid.uuid4())
    payload = json.loads((FIXTURE_DIR / "v2.0.0" / "products.json").read_text())
    retained_product_id = payload["products"][0]["productId"]
    removed_product_id = payload["products"][1]["productId"]
    retained_product_olid = olid.generate("product", retained_product_id)
    removed_product_olid = olid.generate("product", removed_product_id)
    removed_method_olid = olid.generate("method", "noordhoff:getal en ruimte")
    prepare_eduv_importer_data(supplier_gid)

    with database_context("pytest.pgq.eduv_file_import.setup") as db:
        SupplierEd.insert(
            gid=supplier_gid,
            name="Edu-V File Import Supplier",
            email_domains=[f"{uuid.uuid4().hex}.example.test"],
            endpoint_type="edu-v",
            status_visions="compleet",
        )

    with database_context("pytest.pgq.eduv_file_import.import") as db:
        full_importer = EduVFileImporter.with_injected(
            db=db,
            auth_adapter=AuthAdapter.for_service("pytest.eduv_file_import"),
            payload=payload,
            version="v2",
            supplier_gid=supplier_gid,
        )
        initial_stats = full_importer.import_methods_and_products(
            prio=full_importer.priority,
            last_saved_by="pytest.eduv_file_import",
        )

        subset_importer = EduVFileImporter.with_injected(
            db=db,
            auth_adapter=AuthAdapter.for_service("pytest.eduv_file_import"),
            payload={"products": [payload["products"][0]]},
            version="v2",
            supplier_gid=supplier_gid,
        )
        removal_stats = subset_importer.import_methods_and_products(
            prio=subset_importer.priority,
            last_saved_by="pytest.eduv_file_import",
        )

        retained_product = Product.where(Product.olid == retained_product_olid).first_or_fail()
        removed_product = Product.where(Product.olid == removed_product_olid).first_or_fail()
        removed_method = Method.where(Method.olid == removed_method_olid).first_or_fail()

    assert initial_stats.products.new == 2
    assert removal_stats.methods.removed == 1
    assert removal_stats.products.removed == 1
    assert retained_product.available == "leverbaar"
    assert removed_product.available == "verwijderd"
    assert removed_method.available == "verwijderd"


def test_automatic_eduv_import_keeps_unrelated_supplier_items_available(
    prepare_eduv_importer_data: Callable[[str], None],
) -> None:
    """Automatic imports only mark items from their own supplier as removed."""
    imported_supplier_gid = str(uuid.uuid4())
    unrelated_supplier_gid = str(uuid.uuid4())
    prepare_eduv_importer_data(imported_supplier_gid)
    prepare_eduv_importer_data(unrelated_supplier_gid)

    with database_context("pytest.pgq.eduv_supplier_scope.setup") as db:
        for supplier_gid, name in (
            (imported_supplier_gid, "Imported Edu-V Supplier"),
            (unrelated_supplier_gid, "Unrelated Edu-V Supplier"),
        ):
            SupplierEd.insert(
                gid=supplier_gid,
                name=name,
                email_domains=[f"{uuid.uuid4().hex}.example.test"],
                endpoint_type="edu-v",
                status_visions="compleet",
            )

    unrelated_payload = json.loads((FIXTURE_DIR / "v1.1.0" / "products.json").read_text())
    unrelated_product = unrelated_payload["products"][0]
    unrelated_product["productId"] = "9789402054996"
    unrelated_product["publisher"] = "Unrelated Publisher"
    unrelated_product["productFamilyName"] = "Unrelated Method"

    with database_context("pytest.pgq.eduv_supplier_scope.import") as db:
        unrelated_importer = EduVImporter.with_injected(
            db=db,
            auth_adapter=AuthAdapter.for_service("pytest.eduv_supplier_scope.v1"),
            base_url=BASE_URL_V1,
            supplier_gid=unrelated_supplier_gid,
        )
        unrelated_importer._products_cache = [unrelated_product]
        unrelated_importer.import_into_db()

        imported_importer = EduVImporter.with_injected(
            db=db,
            auth_adapter=AuthAdapter.for_service("pytest.eduv_supplier_scope.v2"),
            base_url=BASE_URL_V2,
            supplier_gid=imported_supplier_gid,
        )
        imported_importer.import_into_db()

        unrelated_products = Product.where(Product.supplier_gid == unrelated_supplier_gid).collect()
        unrelated_methods = Method.where(Method.supplier_gid == unrelated_supplier_gid).collect()

    assert len(unrelated_products) == 1
    assert len(unrelated_methods) == 1
    assert unrelated_products[0].available == "leverbaar"
    assert unrelated_methods[0].available == "leverbaar"


def test_kennisnet_import_fetches_each_version_once_and_routes_selected_publishers(
    tmp_path: Path,
    prepare_eduv_importer_data: Callable[[str], None],
) -> None:
    """One Kennisnet scan per version imports only the configured publisher suppliers."""
    v1_supplier_gid = str(uuid.uuid4())
    v2_supplier_gid = str(uuid.uuid4())
    prepare_eduv_importer_data(v1_supplier_gid)
    prepare_eduv_importer_data(v2_supplier_gid)

    with database_context("pytest.pgq.kennisnet_import.setup"):
        SupplierEd.insert(
            gid=v1_supplier_gid,
            name="Malmberg v1",
            email_domains=[f"{uuid.uuid4().hex}.example.test"],
            endpoint_type="edu-v-kennisnet-v1",
            endpoint_publisher="Malmberg",
            status_visions="compleet",
        )
        SupplierEd.insert(
            gid=v2_supplier_gid,
            name="Noordhoff v2",
            email_domains=[f"{uuid.uuid4().hex}.example.test"],
            endpoint_type="edu-v-kennisnet-v2",
            endpoint_publisher="Noordhoff",
            status_visions="compleet",
        )

    v1_products = FIXTURE_DIR / "v1.1.0" / "products.json"
    v2_products = FIXTURE_DIR / "v2.0.0" / "products.json"
    v1_count = len(json.loads(v1_products.read_text())["products"])
    v2_count = len(json.loads(v2_products.read_text())["products"])
    empty_page = tmp_path / "empty-products.json"
    empty_page.write_text('{"products": []}', encoding="utf-8")

    with _serve_files(
        {
            "/v1/products?start=0&limit=100": v1_products,
            f"/v1/products?start={v1_count}&limit=100": empty_page,
            "/v2/products?start=0&limit=100": v2_products,
            f"/v2/products?start={v2_count}&limit=100": empty_page,
        }
    ) as server:
        job_key = str(uuid.uuid4())
        KennisnetCatalogueImporter.run(base_url=server.base_url, job_key=job_key)
        requested_paths = server.requested_paths

    with database_context("pytest.pgq.kennisnet_import.assert"):
        v1_products_in_db = Product.where(Product.supplier_gid == v1_supplier_gid).collect()
        v2_products_in_db = Product.where(Product.supplier_gid == v2_supplier_gid).collect()
        run = ImporterRun.where(ImporterRun.job_key == job_key).first_or_fail()

    assert len(v1_products_in_db) == v1_count
    assert len(v2_products_in_db) == 1
    assert run.supplier_gid is None
    assert run.success is True
    assert requested_paths == [
        "/v1/products?start=0&limit=100",
        f"/v1/products?start={v1_count}&limit=100",
        "/v2/products?start=0&limit=100",
        f"/v2/products?start={v2_count}&limit=100",
    ]


def test_kennisnet_supplier_import_only_marks_that_supplier_removed(
    tmp_path: Path,
    prepare_eduv_importer_data: Callable[[str], None],
) -> None:
    """A supplier-scoped Kennisnet run does not reconcile another publisher's products."""
    malmberg_gid = str(uuid.uuid4())
    noordhoff_gid = str(uuid.uuid4())
    prepare_eduv_importer_data(malmberg_gid)
    prepare_eduv_importer_data(noordhoff_gid)

    with database_context("pytest.pgq.kennisnet_removal.setup"):
        for supplier_gid, publisher in ((malmberg_gid, "Malmberg"), (noordhoff_gid, "Noordhoff")):
            SupplierEd.insert(
                gid=supplier_gid,
                name=publisher,
                email_domains=[f"{uuid.uuid4().hex}.example.test"],
                endpoint_type="edu-v-kennisnet-v2",
                endpoint_publisher=publisher,
                status_visions="compleet",
            )

    products_file = FIXTURE_DIR / "v2.0.0" / "products.json"
    product_count = len(json.loads(products_file.read_text())["products"])
    empty_page = tmp_path / "empty-products.json"
    empty_page.write_text('{"products": []}', encoding="utf-8")
    malformed_products = json.loads(products_file.read_text())
    for product in malformed_products["products"]:
        if product["publisher"] == "Noordhoff":
            del product["name"]
    malformed_products_file = tmp_path / "malformed-products.json"
    malformed_products_file.write_text(json.dumps(malformed_products), encoding="utf-8")

    with _serve_files(
        {
            "/v2/products?start=0&limit=100": products_file,
            f"/v2/products?start={product_count}&limit=100": empty_page,
        }
    ) as server:
        KennisnetCatalogueImporter.run(base_url=server.base_url)

    with _serve_files(
        {
            "/v2/products?start=0&limit=100": malformed_products_file,
            f"/v2/products?start={product_count}&limit=100": empty_page,
        }
    ) as server:
        KennisnetCatalogueImporter.run(supplier_gid=noordhoff_gid, base_url=server.base_url)

    with database_context("pytest.pgq.kennisnet_malformed.assert"):
        noordhoff_product = Product.where(Product.supplier_gid == noordhoff_gid).first_or_fail()

    assert noordhoff_product.available == "leverbaar"
    noordhoff_product_gid = noordhoff_product.gid

    replacement_product = next(
        product for product in json.loads(products_file.read_text())["products"] if product["publisher"] == "Noordhoff"
    )
    replacement_product["productId"] = str(uuid.uuid4())
    replacement_products_file = tmp_path / "replacement-products.json"
    replacement_products_file.write_text(json.dumps({"products": [replacement_product]}), encoding="utf-8")

    with _serve_files(
        {
            "/v2/products?start=0&limit=100": replacement_products_file,
            "/v2/products?start=1&limit=100": empty_page,
        }
    ) as server:
        KennisnetCatalogueImporter.run(supplier_gid=noordhoff_gid, base_url=server.base_url)

    with database_context("pytest.pgq.kennisnet_removal.assert"):
        malmberg_product = Product.where(Product.supplier_gid == malmberg_gid).first_or_fail()
        noordhoff_product = Product.where(Product.gid == noordhoff_product_gid).first_or_fail()
        replacement = Product.where(
            (Product.supplier_gid == noordhoff_gid) & (Product.gid != noordhoff_product_gid)
        ).first_or_fail()

    assert malmberg_product.available == "leverbaar"
    assert noordhoff_product.available == "verwijderd"
    assert replacement.available == "leverbaar"


def test_kennisnet_import_rejects_duplicate_publisher_filters_before_download(
    prepare_eduv_importer_data: Callable[[str], None],
) -> None:
    """Duplicate publisher routing is rejected before an authoritative Kennisnet scan."""
    supplier_gids = [str(uuid.uuid4()), str(uuid.uuid4())]
    for supplier_gid in supplier_gids:
        prepare_eduv_importer_data(supplier_gid)

    with database_context("pytest.pgq.kennisnet_import_duplicates.setup"):
        for supplier_gid in supplier_gids:
            SupplierEd.insert(
                gid=supplier_gid,
                name=f"Duplicate {supplier_gid}",
                email_domains=[f"{uuid.uuid4().hex}.example.test"],
                endpoint_type="edu-v-kennisnet-v2",
                endpoint_publisher="Duplicate Publisher",
                status_visions="compleet",
            )

    with pytest.raises(ValueError, match="Duplicate Kennisnet publisher filters"):
        KennisnetCatalogueImporter.run()


@pytest.mark.parametrize(
    ("endpoint_base_url", "expected_version"),
    [
        ("https://catalogus.edu-v.kennisnet.nl/v1/", "v1"),
        ("https://catalogus.edu-v.kennisnet.nl/v2/", "v2"),
        (None, None),
    ],
)
def test_default_eduv_file_version_follows_supplier_endpoint(
    endpoint_base_url: str | None,
    expected_version: EduVFileVersion | None,
) -> None:
    """The upload form defaults to the version configured for the supplier endpoint."""
    assert default_eduv_file_version(endpoint_base_url) == expected_version


def test_eduv_importer_run_imports_fixture_into_database(capsys: pytest.CaptureFixture[str]) -> None:
    """Edu-V importer should read fixture data and persist methods, products, and run logs."""
    job_key = uuid.uuid7()

    # 1. Clean + set up; context closes before the importer runs
    with database_context("pytest.pgq.scrapers.setup") as db:
        _eduv_clean(db)
        SupplierEd.insert(
            gid=EDUV_PGQ_SUPPLIER_GID,
            name="Fixture Publisher",
            email_domains=[f"{uuid.uuid4().hex}.example.test"],
            endpoint_type="edu-v",
            endpoint_base_url=BASE_URL_V1,
            status_visions="compleet",
        )

    try:
        # 2. Importer opens its own database context, no outer context open here
        stats = EduVImporter.run(
            base_url=BASE_URL_V1,
            supplier_gid=EDUV_PGQ_SUPPLIER_GID,
            endpoint_type="edu-v",
            job_key=str(job_key),
        )

        with database_context("pytest.pgq.scrapers.error_rows") as db:
            run = ImporterRun.where(ImporterRun.job_key == job_key).first_or_fail()
            error_rows = ImporterRunEvent.where(
                (ImporterRunEvent.run_gid == run.gid) & (ImporterRunEvent.event_type == "error")
            ).collect()

        assert stats.products.issues == 0, f"product has issues: {error_rows.as_list()}"
        assert stats.methods.new == 1
        assert stats.products.new == 1

        stdio = capsys.readouterr()
        _assert_no_unused_field_debug_output(stdio.out)
        _assert_no_unused_field_debug_output(stdio.err)

        # 3. Assert in a fresh context
        with database_context("pytest.pgq.scrapers.assert") as db:
            run = ImporterRun.where(ImporterRun.job_key == job_key).first_or_fail()
            products = Product.where(Product.supplier_gid == EDUV_PGQ_SUPPLIER_GID).collect()
            methods = Method.where(Method.supplier_gid == EDUV_PGQ_SUPPLIER_GID).collect()
            error_rows = ImporterRunEvent.where(
                (ImporterRunEvent.run_gid == run.gid) & (ImporterRunEvent.event_type == "error")
            ).collect()

            assert run.success is True
            assert len(methods) == 1
            assert len(products) == 1
            assert len(error_rows) == 0

            happy_product = Product.where(Product.olid == olid.generate("isbn", "9789402054958")).first_or_fail()
            assert happy_product.available == "leverbaar"
            assert happy_product.recommended_price == 31.43
            assert happy_product.image_url.startswith("file:///shared_cache/image_uploads/")
            assert not happy_product.image_url.startswith("file:///pythonpath/")

            method = Method.where(Method.olid == olid.generate("method", "malmberg:biologie voor jou")).first_or_fail()
            assert method.physical_digital_mix == "mix"
            assert method.tto is False

    finally:
        # 4. Always clean up, even on assertion failure
        with database_context("pytest.pgq.scrapers.cleanup") as db:
            _eduv_clean(db)


def test_eduv_v2_importer_run_imports_fixture_into_database(capsys: pytest.CaptureFixture[str]) -> None:
    """Edu-V v2 importer should read fixture data and persist methods, products, and run logs."""
    job_key = uuid.uuid7()

    # 1. Clean + set up; context closes before the importer runs
    with database_context("pytest.pgq.scrapers.setup") as db:
        _eduv_clean(db)
        SupplierEd.insert(
            gid=EDUV_PGQ_SUPPLIER_GID,
            name="Fixture Publisher",
            email_domains=[f"{uuid.uuid4().hex}.example.test"],
            endpoint_type="edu-v",
            endpoint_base_url=BASE_URL_V2,
            status_visions="compleet",
        )

    try:
        # 2. Importer opens its own database context, no outer context open here
        stats = EduVImporter.run(
            base_url=BASE_URL_V2,
            supplier_gid=EDUV_PGQ_SUPPLIER_GID,
            endpoint_type="edu-v",
            job_key=str(job_key),
        )

        assert stats.methods.new == 2
        assert stats.products.new == 2
        assert stats.products.issues == 0

        stdio = capsys.readouterr()
        _assert_no_unused_field_debug_output(stdio.out)
        _assert_no_unused_field_debug_output(stdio.err)

        # 3. Assert in a fresh context
        with database_context("pytest.pgq.scrapers.assert") as db:
            run = ImporterRun.where(ImporterRun.job_key == job_key).first_or_fail()
            products = Product.where(Product.supplier_gid == EDUV_PGQ_SUPPLIER_GID).collect()
            methods = Method.where(Method.supplier_gid == EDUV_PGQ_SUPPLIER_GID).collect()
            error_rows = ImporterRunEvent.where(
                (ImporterRunEvent.run_gid == run.gid) & (ImporterRunEvent.event_type == "error")
            ).collect()

            assert run.success is True
            assert len(methods) == 2
            assert len(products) == 2

            happy_product = Product.where(Product.olid == olid.generate("isbn", "9789402054958")).first_or_fail()
            assert happy_product.available == "leverbaar"
            assert happy_product.recommended_price == 31.43

            method = Method.where(Method.olid == olid.generate("method", "malmberg:biologie voor jou")).first_or_fail()
            assert method.physical_digital_mix == "mix"
            assert method.tto is False

            assert len(error_rows) == 0

    finally:
        # 4. Always clean up, even on assertion failure
        with database_context("pytest.pgq.scrapers.cleanup") as db:
            _eduv_clean(db)
