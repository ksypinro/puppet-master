# Evidence and query contract

## Minimum record for a manual investigation

An agent following direct CLI recipes can maintain this record in task-owned Markdown or JSON. No service is necessary for an initial investigation. A future automated backend should validate the same fields rather than rely on prose. Unknown values are null with a reason, not zero or empty success.

**Experiment:** question; expected lifetime/metric; explicit app/process/runtime domain; warm-up and repeat policy; completion predicates; permitted operations; comparison conditions; pause/disk/output limits.

**Target:** platform and UDID/device ID; bundle and executable; PID and launch identity; architecture; app binary/dSYM UUIDs; source revision if known; driver/debugger owner. A capture rechecks this binding. Imported artifacts may have incomplete identity, which constrains comparisons.

**Snapshot:** unique immutable ID; absolute local path; SHA-256; capture start/end; identity evidence; backend/executable/tool versions; logging mode requested and observed; content policy; artifact validation; scenario/checkpoint/UI evidence IDs. Keep raw artifacts immutable; derived indexes are replaceable.

**Command:** operation ID; argument array; start/end; exit code; timeout/cancellation; raw stdout/stderr paths; extraction line/byte ranges; warnings; process-state disposition. A timeout does not establish that the target is running.

**Finding:** question and conclusion; observed facts versus inference; units; snapshot/query IDs; scope; competing explanations; limitations; next discriminating query. A claimed source line also requires matching build/symbol provenance.

## Separate statuses

Do not collapse these into a single success flag:

| Dimension | Values and meaning |
|---|---|
| Capability | qualified, available_untested, documented, unavailable, unknown |
| Execution | completed, failed, denied, timed_out, cancelled, not_run |
| Parse | recognized, partial, unrecognized, not_attempted |
| Coverage | selected scope, known omissions, filters, history and metadata availability |
| Conclusion | observed, inferred, inconclusive, unsupported, not_captured |

Reason codes may include `target_unresolved`, `identity_conflict`, `history_not_recorded`, `possible_address_reuse`, `exact_retained_size_unavailable`, `blocked_by_existing_owner`, `invalid_input`, and `confounded_comparison`. They explain the outcome; they do not replace evidence.

A reader exiting 1 because it detected leaks is different from a permission failure. A positive summary with unrecognized detail grammar remains useful partial evidence. An empty parser result with no recognized summary is not a clean result. A scan reporting zero establishes only scanner-detected absence in the analyzed scope.

## Normalized objects and relationships

Use `(snapshot_id, address)` as the location key, not a global object identity. Record type/name and its recognition source, allocation bytes, optional logical instance bytes, image/region, optional stack, available fields, and raw evidence ranges. Explicit semantic identity or event history may support a cross-snapshot join; address equality alone does not.

Edges retain source/destination locations, field name and byte offset when known, original text label, normalized ownership kind, and classification provenance. Kinds: typed strong, typed weak, typed unowned, conservative pointer, unknown. Interior pointers and ambiguous targets require their own flags. A source selected by the reader is not automatically the only incoming owner.

Every bounded result records requested scope, matched count if known, returned count, row/byte limit, depth and path limit, truncation, omitted categories, parse warnings and continuation support. If a reader cannot supply total matches, use unknown. A controller pagination token must bind query, snapshot hash and parser version; this draft does not implement tokens.

## Proposed service interface

The following are logical operations for a future CLI/JSON/MCP adapter, not callable tools shipped with this skill:

| Logical operation | What it provides |
|---|---|
| capabilities and target.resolve | Versioned capability inventory and unambiguous target binding |
| capture and snapshot.inspect | Coordinated capture, provenance and artifact validation |
| heap.summary and heap.diff | Type/size/category summaries and compatible checkpoint differences |
| object.inspect | One allocation's layout, size, selected fields and references |
| graph.incoming and graph.paths | Bounded incoming relationships and paths to known roots |
| leaks.scan | Scanner totals and supported cycle details with independent parse status |
| history.query | Recorded allocation events/stacks, never reconstructed missing history |
| scenario.compare | Lifetime assertions, aligned checkpoints and per-iteration values |
| report.export | Evidence-linked conclusions and explicit limitations |

Keep the engine on the Mac beside the artifacts. An MCP server is an optional transport exposing these operations, not the collector itself. A shell-capable agent can use current Apple commands directly; a chat-only agent needs a human or tool adapter to execute them. A cloud agent should receive authorized, minimized exports rather than unrestricted Mac command execution.

## Example result shape

This is a schema example, not a new measurement:

```json
{
  "schema_version": "0.1",
  "query_id": "query-007",
  "snapshot_id": "snapshot-after-dismissal",
  "operation": "object.inspect",
  "execution_status": "completed",
  "parse_status": "partial",
  "coverage": {
    "scope": "one selected allocation",
    "complete_adjacency": false,
    "allocation_history": "not_captured",
    "truncated": false,
    "unknown_fields": ["swift_generic_payload"]
  },
  "facts": [],
  "conclusion_status": "inconclusive",
  "limitations": ["No claim about all owners or a historical writer"],
  "evidence_refs": ["query-007.stdout:12-28"]
}
```

In a real result, empty facts are permitted only as an explicit no-facts/inconclusive result; they are not default proof of absence. Prefer returning a small supported fact set over filling every schema property speculatively.

## Final answer contract

Lead with the answer and its scope. Then give the target/checkpoint, measured facts and units, retaining/lifetime explanation if supported, source attribution quality, evidence paths, uncertainty and the next experiment. State exactly which claim remains unresolved.

For repeated runs include all valid values or an artifact, invalid/missing counts and reasons, baseline-relative deltas, median/range, and measurement conditions. Keep survivors, leaked bytes, footprint and peak allocation series separate. A trend without comparable conditions is exploratory, not a regression verdict.

Never expose raw object contents, paths containing secrets, connection tokens or whole graphs by default. Stored raw evidence and a model-visible summary have different disclosure policies. Sanitization must be explicit; noContent is not a security boundary.
