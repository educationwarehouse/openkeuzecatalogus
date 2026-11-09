# Frontend validation

This document records the scope of frontend verification for PR 208. It is not a live test-results checklist.

## Automated tests

On 5 November 2026, Robin reported that the test suites passed with 81.23% coverage after the first review-fix round. That result predates the second-round changes to bundles and audit logging; those changes still need a new test run. The report did not identify a commit SHA.

## Browser and visual verification

Mike checked the frontend changes, including the htmx and Bootstrap upgrades, as confirmed by Robin. Earlier staging checks covered:

- Public landing, FAQ, catalogue filters, pagination, details and comparisons.
- Login, registration, profile and password-recovery rendering.
- Process overview, wizard navigation, material selection, assessment, criteria and priorities.
- Modal behaviour, navigation history and persistence after reload.
- Responsive layouts at mobile and desktop widths, and the generated vision PDF.

These are historical checks of representative flows, not verification of every record, role or subsequent change.

## Checks after bundle changes

Rebuild the default, private and admin JavaScript bundles. Verify direct loads and boosted navigation between public, private and admin pages, including browser back. Check wizard steps, material search, sortable priorities, admin grids and the public content editor. Public visitors should receive the shared bundle without the private or admin bundles.
