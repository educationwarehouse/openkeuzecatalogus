"""Reusable JSON import support for EddieGrid."""

import datetime as dt
import json
import typing as t
import uuid
from dataclasses import dataclass, field

import pyjson5
from typedal import TypeDAL
from typedal.types import Query, Row
from yatl.helpers import TABLE, TBODY, TD, TH, THEAD, TR, XML

from common.controllers.error import yatl_render
from py4web import HTTP, URL, request, response
from shared_code.data_model.constants import JSON_IMPORT_EXCLUDED_FIELD_NAMES
from shared_code.data_model.mixins.effdt import model_to_ed, update_effectivedated
from shared_code.data_model.tables.base import TableWithGid
from shared_code.util.strings import format_preview_value


@dataclass(frozen=True)
class JsonImportConfig:
    """Describe a table that may be imported through an EddieGrid."""

    table_name: str
    defaults: dict[str, t.Any] = field(default_factory=dict)


class ImportRow(t.TypedDict, total=False):
    """One parsed JSON row and its preview result."""

    index: int
    values: dict[str, t.Any]
    preview_values: dict[str, t.Any]
    status: str
    errors: dict[str, str]


class JsonImport[T: TableWithGid]:
    """Parse, validate, preview, and apply one grid-bound JSON import."""

    def __init__(
        self,
        db: TypeDAL,
        *,
        table: type[T],
        config: JsonImportConfig,
        endpoint: str,
        actor: str,
        query: Query,
        after_insert: t.Iterable[t.Callable[[Row], None]] = (),
        after_update: t.Iterable[t.Callable[[Row], None]] = (),
        after_delete: t.Iterable[t.Callable[[Row], None]] = (),
    ) -> None:
        """Initialize an import workflow for a table and its HTTP endpoint."""
        self.db = db
        self.table = table
        self.config = config
        self.endpoint = endpoint
        self.actor = actor
        self.query = query
        self.after_insert = tuple(after_insert)
        self.after_update = tuple(after_update)
        self.after_delete = tuple(after_delete)
        self.filename = ""
        self.rows: list[ImportRow] = []
        self.payload_json = ""
        self.phase = "upload"

    @property
    def import_url(self) -> str:
        """Return the URL that handles JSON imports for this grid."""
        return URL(self.endpoint, "import")

    @property
    def template_url(self) -> str:
        """Return the URL that downloads an import template for this grid."""
        return URL(self.endpoint, "import", "template")

    def process(self, is_template: bool) -> None:
        """Handle template, upload preview, and confirmed write requests."""
        if is_template:
            self.download_template()
            return
        if request.method != "POST":
            return

        self.filename = str(request.forms.get("filename") or "import.json")
        submitted = request.forms.get("payload_json")
        if submitted:
            self.payload_json = str(submitted)
            self.rows = self.validate_payload(self.payload_json)
            if request.forms.get("confirm") == "1" and not self.has_errors:
                self.apply()
                self.phase = "complete"
            else:
                self.phase = "preview"
            return

        uploaded = request.files.get("json_file")
        if not uploaded:
            raise HTTP(400, "Kies een JSON-bestand om te importeren.")
        self.filename = uploaded.filename or "import.json"
        try:
            self.payload_json = uploaded.file.read().decode("utf-8")
        except UnicodeDecodeError as error:
            raise HTTP(400, "Het bestand moet UTF-8 JSON bevatten.") from error
        self.rows = self.validate_payload(self.payload_json)
        self.phase = "preview"

    def download_template(self) -> None:
        """Return an empty, self-documenting template for this grid."""
        example = dict.fromkeys(sorted(self.importable_fields()), None)
        response.headers["Content-Type"] = "application/json"
        response.headers["Content-Disposition"] = f'attachment; filename="{self.config.table_name}-template.json"'
        raise HTTP(200, json.dumps({self.config.table_name: [example]}, indent=2))

    def importable_fields(self) -> set[str]:
        """Return client-controlled fields, including effective date/status."""
        return {field.name for field in self.table if field.name not in JSON_IMPORT_EXCLUDED_FIELD_NAMES}

    def validate_payload(self, payload_json: str) -> list[ImportRow]:
        """Validate a JSON5 file and return one preview result per row."""
        try:
            rows = self._parse_rows(payload_json)
        except pyjson5.Json5DecoderException as error:
            return [{"index": 0, "status": "invalid", "errors": {"json": str(error)}}]
        except ValueError as error:
            return [{"index": 0, "status": "invalid", "errors": {"json": str(error)}}]
        return self._validate_rows(rows)

    def _parse_rows(self, payload_json: str) -> list[t.Any]:
        """Decode JSON5 and normalize the supported top-level file shapes."""
        payload = pyjson5.loads(payload_json)
        if isinstance(payload, dict):
            if len(payload) != 1 or self.config.table_name not in payload:
                raise ValueError(f"Verwacht sleutel '{self.config.table_name}'.")
            payload = payload[self.config.table_name]
        if not isinstance(payload, list):
            raise ValueError("Verwacht een lijst met rijen.")
        return payload

    def _validate_rows(self, rows: list[t.Any]) -> list[ImportRow]:
        """Validate each row while detecting duplicate update identifiers."""
        allowed_fields = self.importable_fields()
        incoming_gids: set[str] = set()
        results: list[ImportRow] = []
        for index, raw_values in enumerate(rows, start=1):
            results.append(self._validate_row(index, raw_values, allowed_fields, incoming_gids))
        return results

    def _validate_row(
        self,
        index: int,
        raw_values: t.Any,
        allowed_fields: set[str],
        incoming_gids: set[str],
    ) -> ImportRow:
        """Validate one row against table fields and current database rows."""
        if not isinstance(raw_values, dict):
            return {"index": index, "status": "invalid", "errors": {"row": "Rij moet een object zijn."}}
        values = dict(self.config.defaults, **raw_values)
        errors = {field: "Onbekend of niet importeerbaar veld." for field in values if field not in allowed_fields}
        self._validate_gid(values, incoming_gids, errors)
        business_values = {key: value for key, value in values.items() if key in allowed_fields and key != "gid"}
        validation_errors, _ = self.table._validate_fields(business_values)  # type: ignore
        errors.update({str(key): str(value) for key, value in validation_errors.items()})
        return {
            "index": index,
            "values": values,
            "preview_values": self._project_values(values),
            "status": self._status(values) if not errors else "invalid",
            "errors": errors,
        }

    def _validate_gid(self, values: dict[str, t.Any], incoming_gids: set[str], errors: dict[str, str]) -> None:
        """Require update GIDs to be unique within the file and to exist."""
        gid = values.get("gid")
        if not gid:
            return
        gid = str(gid)
        if gid in incoming_gids:
            errors["gid"] = "GID komt meerdere keren in dit bestand voor."
        incoming_gids.add(gid)
        if not self._existing_row(gid):
            errors["gid"] = "Geen bestaande rij met deze GID. Laat gid weg voor een nieuwe rij."

    def _existing_row(self, gid: str) -> T | None:
        """Return an existing row only when it belongs to this grid's scope."""
        return self.table.where(self.query).where(self.table.gid == gid).first()

    def _project_values(self, values: dict[str, t.Any]) -> dict[str, t.Any]:
        """Build the effective-dated row that confirmation will write."""
        gid = values.get("gid")
        existing = self._existing_row(str(gid)) if gid else None
        projected = existing.as_dict() if existing else self._default_values()
        projected.update(values)
        projected["gid"] = gid or "wordt gegenereerd bij bevestiging"
        projected["effstatus"] = values.get("effstatus", True)
        projected["effdt"] = values.get("effdt") or "bij bevestiging"
        projected["last_saved_by"] = f"{self.actor} (JSON import: {self.filename})"
        projected.setdefault("prio", 0)
        return projected

    def _default_values(self) -> dict[str, t.Any]:
        """Evaluate static table defaults for a new-row preview."""
        defaults: dict[str, t.Any] = {}
        for table_field in self.table:
            if table_field.name in JSON_IMPORT_EXCLUDED_FIELD_NAMES or table_field.name == "gid":
                continue
            default = getattr(table_field, "default", None)
            if callable(default):
                default = default()
            defaults[table_field.name] = default
        return defaults

    def _status(self, values: dict[str, t.Any]) -> str:
        gid = values.get("gid")
        if not gid:
            return "nieuw"
        if values.get("effstatus") is False:
            return "archiveren"
        existing = self._existing_row(str(gid))
        if existing and all(getattr(existing, key, None) == value for key, value in values.items() if key != "gid"):
            return "ongewijzigd"
        return "wijzigen"

    @property
    def has_errors(self) -> bool:
        """Return whether any validated import row contains errors."""
        return any(row.get("errors") for row in self.rows)

    def apply(self) -> None:
        """Apply revalidated rows as one effective-dated transaction."""
        last_saved_by = f"{self.actor} (JSON import: {self.filename})"
        try:
            for row in self.rows:
                values = dict(row.get("values", {}))
                gid = values.pop("gid", None)
                effstatus = values.pop("effstatus", True)
                effdt_value = values.pop("effdt", None)
                effdt = dt.datetime.fromisoformat(effdt_value) if isinstance(effdt_value, str) else effdt_value
                table_ed = model_to_ed(self.table)
                if not table_ed:
                    raise HTTP(400, "JSON import ondersteunt alleen effectieve tabellen.")
                is_insert = not gid
                gid = gid or str(uuid.uuid4())
                inserted_id = update_effectivedated(
                    self.db,
                    table_ed,
                    table_ed.gid == gid,
                    None if effstatus is False else values | {"gid": gid},
                    effdt=effdt,
                    last_saved_by=last_saved_by,
                    delete=effstatus is False,
                )
                if inserted_row := table_ed(inserted_id):
                    if is_insert:
                        callbacks = self.after_insert
                    elif effstatus is False:
                        callbacks = self.after_delete
                    else:
                        callbacks = self.after_update

                    for callback in callbacks:
                        callback(t.cast(Row, inserted_row))

            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def render(self) -> XML:
        """Render the current import state with its YATL template."""
        if self.phase == "complete":
            return self._render_complete()
        elif self.phase == "upload":
            return self._render_upload()
        else:
            return self._render_preview_phase()

    def _render_complete(self) -> XML:
        """Render the state after a confirmed import."""
        return XML(yatl_render("json_import_complete.html", endpoint=self.endpoint))

    def _render_upload(self) -> XML:
        """Render the initial JSON5 upload form."""
        return XML(yatl_render("json_import_upload.html", template_url=self.template_url))

    def _render_preview_phase(self) -> XML:
        """Render the validated preview and its confirmation controls."""
        return XML(
            yatl_render(
                "json_import_preview.html",
                endpoint=self.endpoint,
                filename=self.filename,
                has_errors=self.has_errors,
                payload_json=self.payload_json,
                preview=self._render_preview(),
            )
        )

    def _render_preview(self) -> TABLE:
        """Render every supplied field so confirmation is informed."""
        fields = sorted({field for row in self.rows for field in row.get("preview_values", {})})
        headings = [TH("Rij"), TH("Actie"), *(TH(field) for field in fields)]
        if self.has_errors:
            headings.append(TH("Fouten"))

        rows = []
        for row in self.rows:
            cells = [TD(row.get("index")), TD(row.get("status"))]
            values = row.get("preview_values", {})
            cells.extend(TD(format_preview_value(values.get(field))) for field in fields)
            if self.has_errors:
                cells.append(TD(format_preview_value(row.get("errors"))))
            rows.append(TR(*cells))
        return TABLE(THEAD(TR(*headings)), TBODY(*rows), _class="table table-sm table-striped")
