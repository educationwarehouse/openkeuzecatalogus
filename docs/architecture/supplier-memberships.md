# Supplier Memberships and Access Control

This project uses supplier records as the source of truth for supplier-scoped access.
Supplier memberships are one part of the broader auth and RBAC model described in [Auth and RBAC](auth-rbac.md).

## Overview

- `supplier_ed.email_domains` stores the email domains that should map to a supplier.
- When a user logs in or verifies their email, auth refreshes memberships by matching the user's email domain to a supplier row.
- Supplier access is therefore data-driven: adding or updating a supplier row changes who can be matched, without introducing a dedicated environment-variable whitelist.
- The same auth refresh also checks organisation memberships separately; supplier membership is not the entire permissions model.

## RBAC Structure

- Each supplier gets an RBAC identity in the form `<supplier gid>@supplier`.
- All supplier identities inherit from `supplier@internal`.
- The seeded Education Warehouse and SIVON suppliers also inherit from `admin@internal`.
- Supplier RBAC identities are kept in sync with the latest active `supplier_ed` row, including name updates.
- Each supplier identity also gets a self-permission entry so members can read and write their own supplier row.

## Runtime Flow

1. Auth stores the user in session after login.
2. Auth re-checks supplier membership on login and after email verification.
3. `SupplierBackend` finds the supplier whose `email_domains` contain the user's email domain.
4. If a match exists, auth grants membership to that supplier identity.
5. `SupplierPolicy` uses membership inheritance to decide whether the current actor can read or manage supplier-scoped data.

## Supplier Self-Service

Users with `ROLE_SUPPLIER` enter the admin application through the shared
`admin_or_supplier()` fixture. Policy-scoped queries limit them to supplier rows and
catalogue data associated with their inherited supplier memberships.

Supplier users can:

- view and update their own supplier row
- inspect their own current and archived methods and products
- upload and validate an Edu-V test file and inspect its non-persistent preview

They cannot create or delete suppliers, restore archived catalogue rows, run JSON
imports, manage memberships, start endpoint imports, view retained import runs, apply
an uploaded test-file import, or enable the destructive `mark_removed` option. Those
operations remain guarded by `admin()`.

## Implementation Notes

- The backend wiring lives in [py4web/common/models/backend/auth_cls.py](../../py4web/common/models/backend/auth_cls.py).
- Supplier domain orchestration lives in [shared_code/modules/suppliers/module.py](../../shared_code/modules/suppliers/module.py).
- Supplier authorization rules live in [shared_code/modules/suppliers/policy.py](../../shared_code/modules/suppliers/policy.py).
- The broader auth abstraction lives in [shared_code/modules/auth/contract.py](../../shared_code/modules/auth/contract.py).
- Organisation memberships and org-to-org permissions are documented separately in [Auth and RBAC](auth-rbac.md).
- The seeding migration that creates the special supplier groups is documented in [Migrations](../development/migrations.md#supplier-rbac-seeding).
