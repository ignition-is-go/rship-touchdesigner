# Rship-TouchDesigner

The TouchDesigner executor for Rocketship. Establishes a connection with a Rocketship server, scans the network for Base COMPs with an 'rship' tag, and exposes their custom parameters to rship as targets.

Notch TOPs also have first-class support. Similar to Base COMPs their parameters can be quickly turned into targets by tagging the Notch TOP 'rship'

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
