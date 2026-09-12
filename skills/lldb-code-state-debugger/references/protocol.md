# Local JSON debugger protocol (schema 1)

Entry point: `python3 /absolute/skill/scripts/debugger.py`. No third-party Python package is needed. `doctor` discovers the selected LLDB; `start NEW_DIRECTORY` launches a persistent LLDB worker; `status SESSION`, `call SESSION JSON`, and `wait SESSION --after TOKEN --timeout 10 --breakpoint ID` control it. For the first launch with no previous stop, `--after none` is a literal sentinel different from a real token. The global `--out NEW_ABSOLUTE_FILE` option must precede the subcommand; it writes private JSON and refuses overwrite. Omit the JSON argument to read one request from stdin. Quote through an argument vector whenever possible.

The worker listens only on loopback with a random token in a 0600 `connection.json` inside a 0700 session folder. The worker log can contain target data and bootstrap metadata: keep the **entire session private**, and exclude it from shared skill packages. This is trusted local automation, not a hostile-client sandbox. A local privileged process can still inspect it. Requests and responses are capped at 2 MiB. Never expose the listener directly to a network.

## Response/state contract

- Inspect `ok`; nonzero CLI exit is a failed/unknown operation, not necessarily rollback.
- `status` returns session UUID, PID, process unique ID, state, expression-inclusive stop ID, revision, stop token, actual stop reasons and breakpoint IDs. Context metadata supplied by a client is not independently verified by the worker.
- Typed stopped operations require the exact current `stop_token`. Default frame is the selected thread's frame 0; prefer explicit `thread_id` (OS thread ID, not index) and `frame_index` from `threads`/`stack`.
- `resume`/`step` acknowledge dispatch, not the next stop. Use `wait`; an early stop visible in the acknowledgment is valid and `wait` will also see it. A different breakpoint/exit is not the requested outcome.
- State-changing requests invalidate stored value references. The token combines session, process unique ID, expression-inclusive stop ID and a conservative revision. It is a freshness guard, not an event counter or global transaction.
- `wait` polls outside the worker. Its deadline does **not** stop, cancel or resume the process. `pause` can stop normal asynchronous execution, but cannot interrupt a worker already blocked inside a synchronous native expression/raw command.
- Client call deadlines are 0.1–60 seconds, default 12. A deadline, disconnect or oversized response can occur after an action happened. Query status; never replay a launch, UI action, expression or mutation blindly.

## Target and breakpoint operations

```json
{"op":"target","executable":"/absolute/program","context":{"source_revision":"verified-revision"}}
{"op":"breakpoint_add","file":"/absolute/source.c","line":18,"condition":"index == 2","allow_target_execution":true}
{"op":"breakpoint_add","name":"apply_debit"}
{"op":"breakpoint_add","regex":"FixtureLedger.*apply"}
{"op":"launch","arguments":[],"stop_at_entry":true,"cwd":"/absolute/workdir"}
{"op":"attach","executable":"/verified/Simulator/App.app/App","pid":12345,"context":{"udid":"verified-udid","bundle":"verified-bundle"}}
```

`target`/`attach` also accept optional `triple` and `platform`; do not invent them. `launch` is for an already-created compatible target and optionally accepts `environment` as `NAME=value` strings. Simulator lifecycle belongs to simctl. A physical-device attach must use the advanced native device route, **not** typed host `attach`.

`breakpoints` returns current resolution/hit counts. `breakpoint_update` takes owned `id` and optional `enabled`, `one_shot`, `ignore_count`, `condition`, `commands` (up to 20 raw LLDB commands) and `auto_continue`. Conditions/commands require `allow_target_execution:true`; callbacks can also execute host code. `breakpoint_delete` deletes only an owned ID. Source and symbol breakpoints may exist before launch without load-address resolution; check again after loading. Raw-created probes are not tracked as owned by this interface and must be explicitly removed.

## Execution and bounded inspection

All examples below use `STOP` as a placeholder for the exact returned token, never as a literal token.

```json
{"op":"resume","stop_token":"STOP"}
{"op":"pause"}
{"op":"step","mode":"over","stop_token":"STOP","thread_id":123}
{"op":"threads","stop_token":"STOP"}
{"op":"stack","stop_token":"STOP","thread_id":123,"start":0,"count":20}
{"op":"variables","stop_token":"STOP","thread_id":123,"frame_index":0,"path":["self","balance"],"depth":2,"count":10}
{"op":"children","stop_token":"STOP","reference":"v1","start":0,"count":10,"depth":1}
{"op":"memory_read","stop_token":"STOP","address":"0xVERIFIED","count":8}
{"op":"registers","stop_token":"STOP","thread_id":123}
{"op":"disassemble","stop_token":"STOP","thread_id":123,"count":12}
{"op":"modules"}
```

Step modes are `over`, `into`, `out`, `instruction`, `instruction_over`; use frame 0 for stepping. Step completion is confirmed separately. `variables` without a path returns bounded arguments/locals/statics of the frame. Paths are member-name/index arrays, **not expression syntax**. Raw Swift layout may contain storage wrappers and no pretty strings. Values carry availability, errors, address when available, bounded child counts and opaque references. `children` pages an existing reference from this stop. Missing values remain unavailable.

Limits: 100 threads, 100 frames per stack request, 200 modules, depth 5, 50 children per page, 200 value nodes per variables call, strings 4096 characters, memory 4096 bytes, disassembly 100 instructions. Follow `has_more`/`truncated`; lack of complete coverage is not absence. Register sets are separately bounded. Module listing while running is metadata, not a stopped-state snapshot.

Variable paths default to `"scope":"frame"`. Use `"scope":"global"` explicitly for a global; multiple matching globals are an ambiguity error. A missing local never silently becomes a global. Responses include lookup scope. `modules` supports `start` and `count` (maximum 200 per page). Status marks incomplete stop-reason coverage; a missing breakpoint ID in an incomplete scan is not a verified miss.

Raw target/process creation is **not adopted** into the managed typed session. After a raw target switch, restore the original target before typed operations. Raw-created device/core sessions use the expert console only and are not qualified structured-device support. Shutdown checks every debugger target for live processes, not merely the selected target. Cleanup of raw probes/processes remains explicit.

## Execution-capable and mutating operations

```json
{"op":"evaluate","stop_token":"STOP","thread_id":123,"frame_index":0,"language":"swift","expression":"ledger.description","timeout_us":500000,"allow_target_execution":true}
{"op":"watchpoint_add","stop_token":"STOP","address":"0xVERIFIED","size":4,"read":false,"write":true}
{"op":"watchpoint_delete","stop_token":"STOP","id":1}
{"op":"memory_write","stop_token":"STOP","address":"0xOWNED_FIXTURE","hex":"00112233","allow_mutation":true}
{"op":"raw","command":"po ledger","allow_unsafe":true}
```

Evaluation languages: `swift`, `objc` (ObjC++), `c`, `cpp`. Native target-expression timeout is clamped to 1,000–5,000,000 microseconds; options disable all-thread retry, ignore expression breakpoints, request unwind on error and no dynamic values. This is **not a hard end-to-end compiler deadline or rollback**. Always obtain the returned/new status token after any evaluation, including failures. An opt-in is a documented decision by an authorized agent, not proof the expression is pure.

Hardware watch sizes are 1/2/4/8 bytes, subject to target capacity/alignment. Use a live, verified storage address; retain unsupported errors. Watchpoints often stop after a write.

`raw` is an expert escape into LLDB and embedded Python, with host/target execution and potential process-control side effects. It has no typed stop-token guard and invalidates references even for a read command. It can block the worker; output is truncated at 65,536 characters per stream. Do not use it to bypass task authority, one-owner policy, or a denied protected-target attach. Record raw probe IDs and imported-helper resources for explicit cleanup. It does not provide an independently supervised emergency channel.

`events` optionally takes `after` sequence; `output` returns captured target stdout/stderr. Retention is lossy (256 events, 128 output chunks). Console/logpoint output can instead appear in private `worker.log`; inspect that file when necessary. These are not complete execution traces or durable telemetry.

## Cleanup

```json
{"op":"detach","keep_stopped":false}
{"op":"terminate","allow_mutation":true}
{"op":"shutdown"}
```

Choose detach **or** terminate, not both by habit. Detach removes typed owned probes and requests the app remain running unless explicitly told otherwise. Verify actual disposition externally; detached is debugger state, not proof the app is alive. Terminate is for an explicitly owned disposable process or separately authorized termination. Shutdown refuses a live attached/launched process. Raw-created targets/probes can bypass ownership accounting, so avoid them for routine host attachment and clean them deliberately.
