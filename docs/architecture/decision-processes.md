# Decision Processes and Keuzecanvas

Keuzecanvas supports a teaching team in selecting learning materials and recording the resulting
vision. The web interface in `py4web/apps/private` is deliberately thin: the workflow, access
rules, and persistence live in `shared_code/modules/decision_processes`.

## Structure and Access

A `DecisionTeam` belongs to a location. Each `DecisionProcess` belongs to one team and is
registered as an RBAC object below that team. As a result, permissions granted to the team,
location, school, or board reach the process through the existing membership graph.

- Users with `read` access can view reachable processes.
- Users with `write` access can work in the process.
- Creating a team or process requires `write` access to its location.
- A project leader must be a direct or inherited member of the team. Only that leader, an admin,
  or a service actor may change the process criteria.
- Board and school guidance notes are editable by their respective members while the process is
  active. The notes themselves belong to the organisation, so they are shared by all processes
  below that board or school.

Archiving preserves the process and its audit trail while making it inactive. An authorised user
can reopen it to continue at a workflow step.

## Workflow

1. The team starts a process for a school year. It inherits the team's courses, levels, and years,
   which the project leader can refine for this process.
2. In phase 1, participants set the project leader and select the candidate products and methods.
3. In phase 3, each participant records pros and cons for the selected materials.
4. In phase 4, the team assigns those assessments to decision themes, writes theme summaries, and
   consults organisation-level guidance.
5. In phase 5, the theme summaries are prioritised and saved as the process vision.

The completed vision page combines the saved theme summaries with catalogue recommendations for
the process criteria and selected materials. Methods match the selected subject areas and levels.
Products use those same criteria, with exact level-and-year matches ranked ahead of broader matches.

The vision page reuses the public catalogue's search, filters and sort options.
Subject and level filters supplied by the process, falling back to the team's
criteria, are locked: request parameters cannot override them, and **Wis overige
filters** clears only the additional filters. Methods and products have separate
counts and previews. Links to the full catalogue retain the process criteria,
additional filters and valid sort choice. An explicit product sort replaces the
default preference for exact level-and-year matches.

## AI Assistance

Where an LLM service is configured, phase 4 can queue an enhancement for a theme summary. The
service receives the authorised process context and the current summary, then returns an improved
draft for the user to review. AI is optional: unavailable services do not block the manual flow,
and each process has a bounded usage count.

Admins compare models and saved prompts at `/admin/llm-playground` using one editable
scenario, production JSON context and the same response schema. A successful comparison
can be activated globally; activation freezes its model and prompt text for live requests.
Editing a draft does not change that snapshot. Active prompts cannot be deleted.

Configuration and scenario storage support optional `scope_gid` overrides with global
fallback; production currently uses global settings. Comparisons allow at most 16
combinations and use admin-owned signed result tokens valid for ten minutes.

The picker loads the provider's `list_models()` catalogue, cached for one hour.
OpenRouter lists only paid JSON-capable ZDR endpoints and rechecks privacy before every
completion with `data_collection: "deny"`, `zdr: true` and `require_parameters: true`.
Missing privacy metadata blocks generation. Compatible gateways use `AI_HOST` without
OpenRouter routing options and offer manual model entry; their own policies govern privacy.

Prices are USD per million input/output tokens. Suggestions use price, intelligence scores
or Dutch token usage. Dutch usage measures popularity over `dutch_usage_period`, not
language quality. Its undocumented OpenRouter ranking API falls back to intelligence
scores when unavailable.

## Vision PDF

The completed vision can be exported as a PDF. The web tier builds self-contained HTML with CSS
and recommendation cover images inlined. It obtains covers from configured image storage or an
external HTTP(S) URL, stages the HTML on the shared storage volume, and queues the render.
`pgq-pdf` performs the WeasyPrint conversion asynchronously. See
[Storage integration](../integrations/storage.md#pdf-worker) and
[Queue processing](queue-processing.md#pdf-consumer) for the runtime contract.

## Related Docs

- [Auth and RBAC](auth-rbac.md): shared permission model.
- [Catalogue filtering](catalog-filters.md): the matching rules used by catalogue selection.
- [Storage integration](../integrations/storage.md): staging, caching, and PDF retries.
