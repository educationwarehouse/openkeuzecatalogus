# Public Release Mirroring

## Purpose

This project publishes a separate airgapped repository (for example `onzeleermiddelen-public`) from `onzeleermiddelen-private`.

The private repository is the source of truth.
The public repository receives one commit per release snapshot.

## Chosen Strategy

Use snapshot sync (implemented through a `tasks.py` release command), not patch-based transfer.

## Why Snapshot Sync

- Deterministic output: each release is a full, explicit filesystem snapshot.
- Simpler operations: fewer moving parts than generating and applying patch series.
- Lower drift risk: no patch-application conflicts or partial apply states.
- Easier validation: compare resulting tree directly against include/exclude policy.
- Fits release model: naturally produces a single commit per release in the public repo.

## Mirror Rules

- Never transfer `.git` from private to public.
- Exclude everything matched by `.gitignore` during transfer.
- Exclude all py4web apps listed in `PRIVATE_APPS`.
- Keep public repository history to one commit per release (no internal incremental history).

## Implemented Command (`edwh local.prepare-public`)

The release command is implemented as `prepare_public(...)` in `tasks.py`.
It performs snapshot sync using `rsync`.

Behavior:

1. Build a release snapshot from the private working tree.
2. Apply exclusion rules:
    - `.git`
    - all `.gitignore`-matched paths
    - py4web apps in `PRIVATE_APPS`
3. Sync snapshot into the airgapped public workspace.
4. Target directory defaults to sibling `../onzeleermiddelen-public` when `PUBLIC_TARGET` is unset.

Operational flags:

- `edwh local.prepare-public --test`: dry-run (`rsync -n`)
- `edwh local.prepare-public --files`: verbose copied file listing

Notes:

- The command syncs files only; it does not create commits in the public repository.
- Commit policy ("one commit per release") remains an operational convention around this command.

## Notes

- Excluding `.gitignore` paths is mainly for safe/clean testing behavior (for example preventing accidental overwrite of local `.env` files), even if those files would not normally be committed.
