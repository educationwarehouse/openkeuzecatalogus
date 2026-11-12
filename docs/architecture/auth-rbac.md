# Auth and RBAC

This project uses py4web auth for web-facing login flows, but authorization inside the application is built around a shared `AuthContext` abstraction and RBAC-backed policies.

## Layers

- `AppAuth` in `py4web/common/models/backend/auth_cls.py` handles login, logout, registration, email verification, and password reset flows.
- `AuthAdapter` in `shared_code/modules/auth/contract.py` connects a runtime to the shared auth contract by providing:
    - the current actor
    - membership checks
    - permission-scoped object identifiers
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
- teaching-team rows create `<team gid>@team` groups below their location

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

## Membership Invitations

Administrators can invite people to supplier, organisation, or teaching-team memberships. The
shared invitation flow first normalizes the email address and looks for an exact or similar
existing user or pending identity.

- An existing identity receives a direct membership after confirmation. A user who already has
  inherited access may still receive a direct membership, because this makes the membership
  explicit in the target's member list.
- A new person receives an invited identity, a direct membership, and an email with the login or
  registration link. Registration or SSO with that email claims the pending identity.
- Pending invitations can be retracted by removing that direct membership.

The flow rejects duplicate direct memberships and rechecks the selected candidate before granting
access, so a stale form submission cannot grant membership to a different identity.

## Policy Layer

Shared read and update authorization is implemented through reusable policies in
`shared_code/infra/database/policy.py`.

`ReusablePolicy._request_read_from_recursive_memberships(...)` builds a read scope from recursive RBAC memberships:

- admins and services get an unrestricted read scope
- normal users are limited to rows whose `gid` appears in their recursive memberships

This is the mechanism used by:

- `SupplierPolicy.request_read()` for `supplier_model`
- `OrganisationPolicy.request_read()` for `organisation_model`
- `MethodPolicy` and `ProductPolicy` for rows belonging to suppliers in the actor's
  recursive memberships, including archived effective-dated rows

`ReusablePolicy._request_update_from_permissions(...)` limits update queries to row
identities for which the actor inherits the requested RBAC permission. It is used by
`SupplierPolicy.request_update()` so supplier users can update their own supplier row.
Admins and service actors receive unrestricted policy scopes.

The result is that access is enforced through policy-scoped query builders rather than
ad-hoc row checks in controllers.

## Route Guards

Py4web route guards are thin wrappers around the same auth model:

- `requires_login()` ensures an authenticated user exists
- `requires_membership(...)` checks `auth_context.has_membership(...)`

Most admin routes use the `ROLE_ADMIN`-based `admin()` fixture. Supplier self-service
routes use `admin_or_supplier()`, which accepts either `ROLE_ADMIN` or `ROLE_SUPPLIER`
and then relies on policy-scoped queries to restrict the visible rows.

## Mutation Rules

- Membership mutation goes through `AuthContext.add_membership(...)` and `AuthContext.remove_membership(...)` when available.
- Some internal code uses `auth.raw_rbac` directly for lower-level RBAC operations such as `add_group(...)` and `update_identity(...)`.
- Supplier users can update their own supplier record and inspect their own current or
  archived methods and products. Creation, deletion, archive restoration, JSON import,
  membership administration, and destructive import options remain admin-only.
- Organisation relation mutations are intentionally restricted: only admins and services may create board-school or school-location relations.

## Related Docs

- [Supplier memberships and access control](supplier-memberships.md)
- [Effective-dated models](effective-dated-models.md)
- [OLID identifiers](olid.md)
