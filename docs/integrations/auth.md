# Auth Integration

## Overview

Auth is implemented with py4web `Auth` and a project-specific wrapper in
`py4web/common/models/backend/auth_cls.py`.

Classes:
- `AppAuth(Auth)`: custom auth adapter.
- `LoggingAuthForms(DefaultAuthForms)`: logs auth actions to applog.

The web integration delegates shared authorization behavior to:

- `AuthAdapter`: runtime bridge from py4web to shared auth contracts
- `AuthContext`: framework-agnostic actor, membership, and permission API used by modules and policies

See [Auth and RBAC](../architecture/auth-rbac.md).

## Enabled Actions

Configured `allowed_actions`:
- `login`
- `logout`
- `request_reset_password`
- `reset_password`
- `change_password`
- `profile`
- `register`
- `verify_email`

## Mail + Logging Hooks

- Outbound auth mail is attached by `AppAuth.from_dependencies(...)` via `auth.sender = backend.mailer`.
- Auth actions are logged through `Applogger.log_auth_action(...)`.
- Login failures are recorded as `invalid_login_attempt`.

Logged metadata includes:
- action
- success/failure
- user gid / email (if available)
- request IP
- user agent

## Membership Refresh

Membership assignment is part of the auth flow:

- `store_user_in_session(...)` refreshes memberships after a successful login.
- `grant_roles_after_email_verification(...)` refreshes memberships after email verification.
- `SupplierBackend` matches the user's email domain against `supplier.email_domains` and grants membership to the matching supplier RBAC identity.
- `OrganisationBackend` matches the user's email domain against `organisation.email_domains` and grants membership to the matching organisation RBAC identity.
- Access checks use `AuthContext` membership plus RBAC inheritance and permissions, not an environment-variable whitelist.

See [Supplier memberships and access control](../architecture/supplier-memberships.md) and [Auth and RBAC](../architecture/auth-rbac.md).

## Password Reset Policy

- Password reset links expire after 72 hours.
- The expiry timestamp is stored on `auth_user.reset_password_expires_at`.
- `request_reset_password` writes the expiry when a reset token is created, and reset-token validation checks it before allowing the reset flow to continue.
