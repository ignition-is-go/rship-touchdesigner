# Properties and loading port

## Problem

The properties-loading branch had stronger registration and sequence behavior, but it predated the current Python target API, `reflect_comp`, connection manager, and comp engine. This port keeps those newer systems and moves the tested guarantees into their existing owners.

## Runtime shape

`ConnectionManager` remains the only owner of socket state and reconnect timing. `RegistrationCoordinator` owns registration generations, retry timing, bounded command deferral, and FIFO draining. `RshipExt` builds and publishes the current target set. `ExecClient` owns native Myko map subscriptions in addition to ordinary action dispatch.

The required-state contract is pinned to rship `b8a2739dd4` and Myko `def6643797`. It uses two independent native views:

- `ReconciledProperties`, scoped to the instance and the actual published root targets.
- `RequiredCompEngineState`, scoped to the instance and filtered by engine locally.

Each view keeps its own transaction, sequence, readiness, rows, and error. Sequence zero atomically replaces the map. Later sequences must be contiguous. Disconnect makes a view unready but retains its rows and applied local state; reconnect reuses the transaction and waits for a new sequence-zero snapshot.

### Design decision

We compared two shapes: independent domain controllers over reusable native maps, and one public instance-level coordinator wrapping both domains. The independent-controller design won because it mirrors the server's two unrelated subscriptions and leaves instance/socket lifecycle with `RshipExt`, where it already lives. A shared coordinator would duplicate readiness, cached rows, and registration ownership while making a failure in one domain easier to leak into the other.

The retained piece from the coordinator design is one private `_configureRequiredStateViews()` call in `RshipExt`. It makes registration ordering explicit without combining state. `myko.py` contains wire envelopes, `exec.py` contains generic map transport, `rship.py` contains property enforcement, and `comp_engine.py` contains comp row validation and materialization.

Registration follows this order:

1. Publish the instance as `Starting`.
2. Force target discovery and validate IDs.
3. Install handlers, property providers, and change-key fanout.
4. Publish generic targets and actions plus native comp-engine declarations.
5. Publish current property values.
6. Publish Offline and Online target statuses.
7. Publish the instance as `Available`.
8. Subscribe to both native required-state views.
9. Drain deferred commands in arrival order.

Every registration send checks the connection generation before and after the operation. A disconnect invalidates queued commands and pending pulses. A failed scan or send leaves registration inactive and retries with a delay capped at 30 seconds.

## Sequence state

Both reflected and manual Python sequence properties validate the whole array before changing `numBlocks`. Persistent sequence state requires at least one block and respects `maxBlocks`. Pulse and Momentary members use the canonical retained `exec-tick` value (`id`, `prev`, and `next`); nil and previously handled IDs do not fire, so reconciliation cannot replay an old event.

## Reconciled properties

Property rows are keyed by the genuine emitter ID. `RshipExt` captures the emitter readback and its canonical writer before publishing definitions. The reconciler validates the emitter, target, and schema, then invokes that local writer directly with the row value. It never synthesizes an `ExecTargetAction` and never adds a universal value wrapper. A deletion releases enforcement without writing null. Parameter-change readbacks trigger bounded drift correction.

## Comp-engine state

Comp engines no longer publish prepare, apply, cancel, or request-state actions, prep/committed emitters, or synthetic cap/presence properties. One instance-wide view carries Element, Cap, Presence, and Dependency rows. Structural changes rebuild affected engine assignments; cap and presence changes use the existing targeted value callback and do not rebuild topology.

The executor publishes `CompEngineObservedStateRow` with ordinary native SET/DEL events. Ready observations include the exact applied Element row value. `DeliverCompEngineTrigger` is a typed, one-shot command with bounded event-ID deduplication. Genuine output emitters remain and use `output:<nodeId>::<channel>` beneath the engine target. The empty segment is retained for address compatibility; it is not an instance tag.

## Compatibility decisions

- Current sequence property IDs remain unchanged. The port does not restore the old parallel `state_set` and `state_updated` interface.
- `rship-no-properties` disables writable property pairing for reflected COMPs.
- The deleted legacy target classes remain deleted.
- Required-row and observation IDs use UTF-8 byte lengths, matching Rust `str::len`.
- The two views deliberately do not share readiness or cached rows.

## Verification

Run the behavioral suite with TouchDesigner's Python:

```powershell
& 'C:\Program Files\Derivative\TouchDesigner.2025.32898.99\bin\python.exe' -m unittest discover -v -s tests
```

Verify that embedded DATs match their source files:

```powershell
& 'C:\Program Files\Derivative\TouchDesigner.2025.32898.99\bin\python.exe' tools/build_tox.py --td-bin 'C:\Program Files\Derivative\TouchDesigner.2025.32898.99\bin'
```
