# Rship-TouchDesigner

The TouchDesigner executor for Rocketship. Establishes a connection with a Rocketship server, scans the network for tagged Base COMPs and exposes their custom parameters to rship as targets.

A buddy .tox is also included, which makes it easier to turn existing parameters in the network into rship targets.

Notch TOPs have first-class support. Similar to Base COMPs they can be tagged 'rship' to expose the parameters of the 'Notch' page, as well as the 'Parameters' page for each layer in the block.

## Setup

1. Download the rship.tox and drag it into a network
> NOTE: When scanning the network for targets, the rship.tox recursively scans the directory it is in and all subdirectories. We recommend placing the rship.tox in the root of the network in order to be sure that the entire network is scanned, as well as to avoid cluttering the screen with grey reference lines.
2. In the rship.tox parameters page, enter the address and port of a Rocketship server
3. Save the project
4. Verify the TouchDesigner instance appears in the rship GUI, and activate the instance
5. Add a tag to a Base COMP and name the tag 'rship' (using the small pencil icon in the parameters window)
6. Save the project
7. Verify the COMP appears as a target in the rship GUI
> NOTE: If the Base COMP is renamed, it will automatically track through to the rship GUI
8. Add parameters to the Base COMP and bind them to other parameters in the network, manually or by using the buddy

## Using the Buddy

1. Download the rship_buddy.tox and drag it into the network (wherever you would like to quickly expose parameters)
2. Activate the OP (using the small plus symbol in the bottom-right corner)
3. Select an OP and drag one of its parameters onto the rship_buddy
> NOTE: When a parameter is dropped onto the rship_buddy, it recursively scans parent directories until it finds a Base COMP tagged 'rship', creates a custom parameter page (named the source OP) and parameter (named the source parameter), and binds the source parameter to the custom parameter. 
4. Save the project
5. Verify the parameter appears as a target in the rship GUI
> NOTE: Because TouchDesigner uses network paths for binding parameters, renaming a source OP will cause the bindings to break and the Base COMP will error.
> NOTE: As of 2024/05/17 Rship-Touchdesigner currently supports float, int, bool, string, and pulse types. Support for other types (RGB, XYZ, enum, etc.) may be added as necessary.

## Using Notch TOPs

1. Add an 'rship' tag to any Notch TOP
2. Save the project
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
