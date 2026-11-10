# OLID Identifiers

This project uses OLIDs as stable domain identifiers for imported and synchronized entities such as suppliers, products, methods, and visions.

The shared generator lives in `shared_code/util/olid/__init__.py`.

## Purpose

An OLID gives the application one canonical identifier format even when source systems use different kinds of keys.

In practice, OLIDs are used to:

- preserve meaningful external identifiers where possible
- normalize different input shapes into one project-wide format
- give imported rows a stable identifier even when the source only provides a local key

## Format

OLIDs are URIs with the `olid://` scheme plus a short hash fragment.

Examples:

- `olid://https/example.test/path/to/item?a=1&b=2&fragment=frag#ea6b`
- `olid://isbn/9781402894626#91b6`
- `olid://unregistered/supplier/gid-123#6a6b`

The fragment is deterministic. Standard identifiers use a short integrity suffix derived from the normalized URI.
Unregistered keys changed by slugification also include the original key in the four-character hash, preserving identity
distinctions that the readable slug cannot express.

## Normalization Rules

`generate(prefix, key)` currently handles three main cases.

### HTTP or HTTPS URLs

If the input is an HTTP(S) URL:

- the original host and path are preserved
- the hierarchy becomes `https`
- query parameters are preserved
- URL fragments are moved into a `fragment=` query parameter before hashing

This keeps the source URL visible while still producing a canonical `olid://...` value.

### ISBN or EAN-like input

If the input already uses an `isbn:` or `ean:` scheme, or the input string parses as an ISBN:

- the hierarchy becomes `isbn` or the original explicit scheme
- the path is normalized to digits for bare ISBN input

### Fallback / unregistered values

If the input is not a recognized URL or ISBN-like value:

- the hierarchy becomes `unregistered`
- the path becomes `<prefix>/<slug>`
- `slug` is generated with `slugify`: it is lowercase ASCII, transliterates accents, and replaces whitespace and punctuation with hyphens

This is the default for internal or source-local identifiers that do not yet have a standard external namespace.
Keys that differ by case, accents, punctuation, or whitespace can share the readable path but have different fragments.
Keys already equal to their slug, including supplier UUIDs, retain their existing identifiers.

Edu-V product identifiers are ISBNs or UUID GIDs, so their OLIDs stay unchanged. Method source keys combine
the lowercased publisher and product-family name, and their OLIDs need a backfill.

The `backfill_collision_resistant_olids_20261005_001` migration reconstructs method keys from existing
method and supplier metadata and stored importer source rows. It appends new
effective-dated method versions at each existing priority without changing GIDs or historical rows,
updates saved selections, then rebuilds the current method model and learning-material view.
Historical importer events keep their original identifiers. Unavailable source keys produce warnings;
their existing OLIDs stay unchanged. Ambiguous mappings still abort. UUID-based method keys stay unchanged.

Deploy the migration before starting the updated importer workers. Imports also check the legacy hash
of each incoming method URI. A matching legacy method is upgraded using the same effective-dated
correction helper, preserving its GID, history and saved selections. Competing incoming identifiers
abort the import. A legacy method is left untouched when the incoming OLID already belongs to
another method. No external catalogue snapshot or replacement table is needed.
The four-character hash has a finite collision space; hashing the original key fixes
normalization-induced collisions without changing the OLID format.

## Supplier Behavior

Suppliers have special convenience handling:

- `generate_supplier_olid(gid)` creates a supplier OLID from the supplier `gid`
- `SupplierEd.before_insert(...)` auto-generates an OLID when a supplier insert does not provide one
- the seeded special suppliers in migrations also use this helper

That means supplier rows always end up with an OLID even when the caller only knows the `gid`.

## Practical Guidance

- Treat OLID as a stable domain identifier, not display text.
- Use the shared helper instead of constructing OLID strings by hand.
- Preserve the generated value as-is; downstream code may rely on its normalized shape.
- When querying by OLID, treat it like any other persisted identifier and bind it safely in SQL or ORM filters.

## Related Docs

- [Effective-dated models](effective-dated-models.md)
- [Auth and RBAC](auth-rbac.md)
