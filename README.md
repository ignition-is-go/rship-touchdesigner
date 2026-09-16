# Rship-TouchDesigner

The TouchDesigner executor for Rocketship. Establishes a connection with a Rocketship server, scans the network for Base COMPs with an 'rship' tag, and exposes their custom parameters to rship as targets.

Notch TOPs also have first-class support. Similar to Base COMPs, their parameters can be quickly turned into targets by tagging the Notch TOP 'rship'.

## Setup

1. Download the rship.tox and drag it into a network
> NOTE: When scanning the network for targets, the rship.tox recursively scans the directory it is in and all subdirectories. Place the rship .tox in the root of the network to ensure that the entire network is scanned (also to avoid cluttering the screen with reference lines).
2. In the rship .tox parameters page, enter the address and port of a Rocketship server (default 5155)
3. Save the project
4. Verify the TouchDesigner instance appears in the rship GUI, and activate the instance
5. Tag a Base COMP 'rship' and save the project
6. Verify the COMP appears as a target in the rship GUI

## Expose Parameters

1. Open the component editor window of a tagged COMP
2. Click and drag the par to be exposed onto the component editor window
3. See [Component Editor Dialogue](https://derivative.ca/UserGuide/Component_Editor_Dialog#:~:text=Bind%20New%20Par%20as%20Master,the%20parameter%20that%20was%20dragged.) to understand the different kinds of bindings/references in TouchDesigner
4. Save the project
5. Verify the parameter appears in the rship GUI as a target

> NOTE: As of 2025/03/21 Rship-Touchdesigner currently supports all primitive data types. COMPs/OPs and Python are currently unsupported.

> Note: The unique ID for a parameter is based on its **name**. Changing its **name** will break the connection and create a new target in rship. Prefer renaming labels.

## Use Notch TOPs

1. Tag a Notch TOP 'rship' and save the project
3. Verify the Notch layers and their parameters appear in the rship GUI as targets

## Targets, Actions, and Emitters

- Targets: Base COMPs
  - Emitters:
    - Publish custom par values
  - Actions:
    - Activate cooking
    - Deactivate cooking
    - Set custom par values

- Targets: Notch TOPs
  - Emitters:
    - Publish Notch par values
  - Actions:
    - Activate cooking
    - Deactivate cooking
    - Set Notch par values

- Targets: Notch Layers
  - Emitters:
    - Publish layer par values
  - Actions:
    - Set layer par values


## Legacy properties and loading

The Python source pairs supported ordinary parameter Set actions with their existing Updated emitters using legacy `Action.writesTo` metadata. It does not use the server Views schema. Parameter target IDs, Set and Resend action IDs, and Bulk Set payloads remain compatible with existing scenes.

A property setter publishes the parameter's actual value after assignment, including unchanged or normalized values. The executor also supplies current values on registration, reconnect, and server `ResendEmitterValue` requests. Menu values use `menuNames`; labels only control display. Scalar values keep the existing `{"value": ...}` shape, and vectors retain their component objects.

For chain scenes, select and elect the desired properties in Rship. The executor does not convert existing scenes or elect property nodes automatically.

Sequences expose a writable `<sequence name> State` property containing an array of blocks. The array length sets the block count within TouchDesigner's limits, with at least one block. Empty arrays and arrays above a sequence's maximum are rejected before assignment. Each block contains its persistent parameter values, including Pulse and Momentary members represented by the canonical `format: "exec-tick"` object (`id`, `prev`, and `next`). Nil and previously handled IDs do not fire, so property reconciliation cannot replay Emit or Clear events. A real local TouchDesigner pulse creates a fresh UUIDv4 and the most recent ID is retained for snapshots, resends, and unrelated value updates.

Ordinary controls on sequence-based operators also support properties. Add the `rship-no-properties` tag to an operator to disable writable pairing explicitly. Existing emitters remain registered, so the legacy server may still display them as read-only properties.

The executor publishes Starting before scanning and registering targets. It publishes definitions and current value seeds before target Online statuses and instance Available. Early action and Resend requests wait in arrival order while registration finishes. Failed scans or sends retry through the existing timer with delays capped at 30 seconds. Disconnect clears deferred commands and pending outbound pulses.

The loading queue accepts at most 1,024 command envelopes and 16 MiB of text. Overflow returns a command error. Queue draining yields after 16 envelopes or 4 milliseconds and resumes on the next frame. A single batch envelope executes as a whole, so an unusually large batch can exceed that frame budget.

The bundled `rship.tox` includes these changes. The development `RshipTox.toe` references that TOX. Automated behavior tests use simulated TouchDesigner parameters and real protocol serialization:

```sh
python -m unittest discover -s tests -v
```

Rebuild the package with the installed TouchDesigner utilities:

```powershell
python tools/build_tox.py --td-bin "C:/Program Files/Derivative/TouchDesigner.2025.33070/bin" --output rship.tox
```

Omit `--output` to check the existing package. The builder embeds UTF-8 source with LF newlines, re-expands the output, and verifies every embedded Python DAT against source. It also checks the table of contents and confirms that all other package data remains unchanged.

Validation on 2026-09-09 passed all 53 automated tests. Isolated TouchDesigner 2025.33070 checks covered loading, ordinary properties, and 17 sequence checks, including embedded-code reload, block resizing, minimum-block rejection, event filtering, current readback, and emitter fanout. Network output was captured locally. The installed production component registered 31 sequence properties and returned to Active without operator errors.

Production server scene reconciliation still requires an end-to-end check after installation. The protocol reference is the [pre-Views property implementation](https://github.com/ignition-is-go/rship/blob/2888e94b3ac801a83829ff9f0215d8208c792994/libs/entities/external/src/property.rs).
