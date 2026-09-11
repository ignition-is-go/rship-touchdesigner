# Properties and loading port

## Problem

The properties-loading branch had stronger registration and sequence behavior, but it predated the current Python target API, `reflect_comp`, connection manager, and comp engine. This port keeps those newer systems and moves the tested guarantees into their existing owners.

## Runtime shape

`ConnectionManager` remains the only owner of socket state and reconnect timing. `RegistrationCoordinator`, in the same embedded module, owns registration generations, retry timing, bounded command deferral, and FIFO draining. `RshipExt` builds and publishes the current target set. `ExecClient` validates inbound addressing and owns action and property-provider registries.

Registration follows this order:

1. Publish the instance as `Starting`.
2. Force target discovery and validate IDs.
3. Install handlers, property providers, and change-key fanout.
4. Publish generic and comp-engine definitions.
5. Publish current property values.
6. Publish Offline and Online target statuses.
7. Publish the instance as `Available`.
8. Drain deferred commands in arrival order.

Every registration send checks the connection generation before and after the operation. A disconnect invalidates queued commands and pending pulses. A failed scan or send leaves registration inactive and retries with a delay capped at 30 seconds.

## Sequence state

Both reflected and manual Python sequence properties validate the whole array before changing `numBlocks`. Persistent sequence state requires at least one block, respects `maxBlocks`, and omits Pulse and Momentary members. Those event parameters cannot be replayed by property reconciliation.

## Compatibility decisions

- Current sequence property IDs remain unchanged. The port does not restore the old parallel `state_set` and `state_updated` interface.
- `rship-no-properties` disables writable property pairing for reflected COMPs.
- The deleted legacy target classes remain deleted.
- Comp-engine topology and value handling remain unchanged. Registration only delays its initial seed and Online status.

## Verification

Run the behavioral suite with TouchDesigner's Python:

```powershell
& 'C:\Program Files\Derivative\TouchDesigner.2025.32898.99\bin\python.exe' -m unittest discover -v -s tests
```

Verify that embedded DATs match their source files:

```powershell
& 'C:\Program Files\Derivative\TouchDesigner.2025.32898.99\bin\python.exe' tools/build_tox.py --td-bin 'C:\Program Files\Derivative\TouchDesigner.2025.32898.99\bin'
```
