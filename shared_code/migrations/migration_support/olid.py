"""Backfill method OLIDs from stored publisher and family metadata."""

import hashlib
import json
import logging
from urllib.parse import urlencode, urlparse, urlunparse
from uuid import UUID

from is_isbn.is_isbn import is_isbn
from slugify import slugify
from typedal import TypeDAL

from shared_code.migrations.migration_support.core import no_triggers

logger = logging.getLogger(__name__)


class ReplacementCandidates:
    """Collect source-derived mappings and reject ambiguous identifiers."""

    def __init__(self, existing: set[str]) -> None:
        """Limit candidate replacements to identifiers present in the database."""
        self.existing = existing
        self.replacements: dict[str, str] = {}

    def add(self, prefix: str, key: str) -> None:
        """Record a source key using the frozen four-character hash algorithm."""
        # Freeze the unregistered identifier algorithm for this migration version.
        uri = urlparse(key)
        if uri.scheme in {"ean", "isbn", "http", "https"} or is_isbn(uri.path):
            return
        self._add_key(prefix, key)
        # The pre-slug generator kept the raw key in the path and also appended
        # URI params and fragment queries. Slugification used that expanded path
        # as its source key, so semicolon and hashtag titles have a second form.
        query = urlencode({"fragment": uri.fragment}) if uri.fragment else ""
        raw_identifier = urlunparse(("olid", "unregistered", f"{prefix}/{key}", uri.params, query, ""))
        normalized_key = raw_identifier.removeprefix(f"olid://unregistered/{prefix}/")
        if normalized_key != key:
            self._add_key(prefix, normalized_key)

    def _add_key(self, prefix: str, key: str) -> None:
        """Match both hash versions of one historically generated source key."""
        uri = urlparse(key)
        identifier = urlunparse(("olid", "unregistered", f"{prefix}/{slugify(key)}", uri.params, "", ""))
        legacy = identifier + "#" + hashlib.shake_256(identifier.encode()).hexdigest(2)
        hash_input = identifier
        if key != slugify(key):
            hash_input += "\0" + key
        new = identifier + "#" + hashlib.shake_256(hash_input.encode()).hexdigest(2)
        # Earlier migrations may already have generated the new OLID.
        for old in {legacy, new} & self.existing:
            previous = self.replacements.get(old)
            if previous is not None and previous != new:
                raise ValueError(f"Cannot reconstruct ambiguous OLID {old!r}: {previous!r}, {new!r}")
            self.replacements[old] = new


def _method_keys_v1(db: TypeDAL, candidates: ReplacementCandidates) -> None:
    methods = db.executesql("""
        SELECT DISTINCT m.name, s.name, s.endpoint_publisher
        FROM method_model m JOIN supplier_model s ON s.gid = m.supplier_gid;
    """)
    for name, supplier_name, publisher in methods:
        if not name:
            continue
        for publisher_name in {supplier_name, publisher} - {None, ""}:
            candidates.add("method", f"{publisher_name.strip().lower()}:{name.strip().lower()}")


def _source_keys_v1(db: TypeDAL, candidates: ReplacementCandidates) -> None:
    missing = ReplacementCandidates(candidates.existing - candidates.replacements.keys())
    sources = db.executesql("""
        SELECT DISTINCT (details -> 'error_details' -> 'source_row')::text
        FROM importer_run_event
        WHERE details -> 'error_details' -> 'source_row' IS NOT NULL;
    """)
    for (source_json,) in sources:
        source = json.loads(source_json)
        if not isinstance(source, dict):
            continue
        publisher = source.get("publisher")
        family = source.get("productFamilyName", source.get("product_family_name")) or source.get("name")
        if isinstance(publisher, str) and isinstance(family, str) and publisher.strip() and family.strip():
            missing.add("method", f"{publisher.strip().lower()}:{family.strip().lower()}")
    candidates.replacements.update(missing.replacements)


def replace_method_olid_v1(
    db: TypeDAL, old: str, new: str, last_saved_by: str = "migration.backfill_collision_resistant_olids_v1"
) -> None:
    """Append identifier corrections at every priority, preserving GIDs and history."""
    if old == new:
        return

    conflicts = db.executesql(
        "SELECT COUNT(DISTINCT gid) FROM method_ed WHERE olid IN (%(old)s, %(new)s);",
        placeholders={"old": old, "new": new},
    )
    if conflicts[0][0] > 1:
        raise ValueError(f"Cannot merge method identities for {old!r} and {new!r}")

    db.executesql(
        """
        INSERT INTO method_ed
        SELECT migrated.* FROM (
            SELECT DISTINCT ON (gid, prio) * FROM method_ed
            ORDER BY gid, prio, effdt DESC, id DESC
        ) latest CROSS JOIN LATERAL jsonb_populate_record(NULL::method_ed,
            to_jsonb(latest) || jsonb_build_object(
                'id', nextval('method_ed_id_seq'), 'olid', %(new)s,
                'effdt', utcnow(), 'sync_gid', uuidv7(),
                'created_at', utcnow(), 'updated_at', utcnow(),
                'last_saved_by', %(last_saved_by)s
            )
        ) migrated WHERE latest.olid = %(old)s;
        UPDATE decision_material_selection SET olid = %(new)s WHERE olid = %(old)s;
        """,
        placeholders={"old": old, "new": new, "last_saved_by": last_saved_by},
    )


def _log_unresolved_method_keys_v1(candidates: ReplacementCandidates) -> None:
    for old in sorted(candidates.existing - candidates.replacements.keys()):
        key = old.removeprefix("olid://unregistered/method/").rsplit("#", 1)[0]
        try:
            UUID(key)
        except ValueError:
            logger.warning("Preserving method OLID %r: original source key is unavailable", old)


def backfill_collision_resistant_olids_v1(db: TypeDAL) -> None:
    """Insert method versions from existing keys; ISBN and UUID product IDs stay stable."""
    rows = db.executesql("""
        SELECT olid FROM method_model
        UNION SELECT olid FROM decision_material_selection;
    """)
    candidates = ReplacementCandidates(
        {row[0] for row in rows if row[0] and row[0].startswith("olid://unregistered/method/")}
    )
    _method_keys_v1(db, candidates)
    _source_keys_v1(db, candidates)
    _log_unresolved_method_keys_v1(candidates)
    with no_triggers(db):
        for old, new in candidates.replacements.items():
            replace_method_olid_v1(db, old, new)
    db.executesql("SELECT rebuild_method_model();")
    db.executesql("REFRESH MATERIALIZED VIEW learning_material;")
    logger.info(
        "Backfilled %s method OLIDs with new effective-dated versions",
        sum(old != new for old, new in candidates.replacements.items()),
    )
