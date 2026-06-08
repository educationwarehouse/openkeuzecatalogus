# Auth Integration

## Overview

Auth is implemented with py4web `Auth` and a project-specific wrapper in
`py4web/apps/_default/models/auth.py`.

Classes:
- `AppAuth(Auth)`: custom auth adapter.
- `LoggingAuthForms(DefaultAuthForms)`: logs auth actions to applog.

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

- Outbound auth mail uses `Mailer.from_env(db)` via `auth.sender`.
- Auth actions are logged through `Applogger.log_auth_action(...)`.
- Login failures are recorded as `invalid_login_attempt`.

Logged metadata includes:
- action
- success/failure
- user gid / email (if available)
- request IP
- user agent

## Password Reset Policy

- Password reset links expire after 72 hours.
- The expiry timestamp is stored on `auth_user.reset_password_expires_at`.
- `request_reset_password` writes the expiry when a reset token is created, and reset-token validation checks it before allowing the reset flow to continue.
