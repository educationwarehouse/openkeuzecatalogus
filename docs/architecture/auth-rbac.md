# Auth and RBAC

This project uses py4web auth for web-facing login flows, but authorization inside the application is built around a shared `AuthContext` abstraction and RBAC-backed policies.

## Layers

- `AppAuth` in `py4web/common/models/backend/auth_cls.py` handles login, logout, registration, email verification, and password reset flows.
- `AuthAdapter` in `shared_code/modules/auth/contract.py` connects a runtime to the shared auth contract by providing:
  - the current actor
  - membership checks
  - optional membership mutation hooks
- `AuthContext` wraps the adapter and exposes framework-agnostic auth behavior to modules, policies, and table hooks.
- `edwh_auth_rbac` is the low-level RBAC store used for groups, memberships, recursive memberships, and permissions.

## Actors

`AuthContext` exposes three actor kinds:

- `user`: a logged-in end user
- `service`: an internal caller such as migrations, background jobs, or backend maintenance code
- `anonymous`: a request without an authenticated user

Service callers are created with `AuthContext.for_service(...)` or `AuthAdapter.for_service(...)`.
They get a synthetic identity such as `service:supplier-sync`.

## Memberships and Permissions

The project treats RBAC memberships as the main source of authorization truth.

- Memberships answer "which identities does this actor belong to?"
- Permissions answer "what may this identity do to another identity?"

Current group families include:

- `users@internal`
- `admin@internal`
- `supplier@internal`
- `organisation@internal`
- `board@internal`
- `school@internal`
- `location@internal`

Domain rows then get their own RBAC identities:

- supplier rows create `<supplier gid>@supplier` groups
- organisation rows create `<organisation gid>@organisation` groups

Those row-level groups also receive self-permissions so members can read and write their own entity.

## Runtime Flow

In the py4web app, `py4web/common/models/backend/__init__.py` wires `AuthAdapter` to the active py4web user session.

At login and after email verification:

- `AppAuth.store_user_in_session(...)` refreshes memberships
- `AppAuth.grant_roles_after_email_verification(...)` refreshes memberships
- the refresh currently includes:
  - supplier memberships via `SupplierBackend.grant_memberships(...)`
  - organisation memberships via `OrganisationBackend.grant_memberships(...)`

Membership assignment is data-driven:

- supplier membership comes from matching the user's email domain against `supplier.email_domains`
- organisation membership comes from matching the user's email domain against `organisation.email_domains`

## Policy Layer

Shared read authorization is implemented through reusable policies in `shared_code/infra/database/policy.py`.

`ReusablePolicy._request_read_from_recursive_memberships(...)` builds a read scope from recursive RBAC memberships:

- admins and services get an unrestricted read scope
- normal users are limited to rows whose `gid` appears in their recursive memberships

This is the mechanism used by:

- `SupplierPolicy.request_read()` for `supplier_model`
- `OrganisationPolicy.request_read()` for `organisation_model`

The result is that read access is enforced through policy-scoped query builders rather than ad-hoc checks in controllers.

## Route Guards

Py4web route guards are thin wrappers around the same auth model:

- `requires_login()` ensures an authenticated user exists
- `requires_membership(...)` checks `auth_context.has_membership(...)`

Admin routes currently rely on `ROLE_ADMIN`-based guards in app fixtures under `py4web/apps/admin`.

## Mutation Rules

- Membership mutation goes through `AuthContext.add_membership(...)` and `AuthContext.remove_membership(...)` when available.
- Some internal code uses `auth.raw_rbac` directly for lower-level RBAC operations such as `add_group(...)` and `update_identity(...)`.
- Organisation relation mutations are intentionally restricted: only admins and services may create board-school or school-location relations.

## Related Docs

- [Supplier memberships and access control](supplier-memberships.md)
- [Effective-dated models](effective-dated-models.md)
- [OLID identifiers](olid.md)
