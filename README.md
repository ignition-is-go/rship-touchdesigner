# Rship-TouchDesigner

Rocketship integrates naturally with TouchDesigner. Simply load the rship .tox into any TouchDesigner network to eastablish a connection with Rocketship, tag the Base COMPs whose parameters you wish to expose with 'rship', and their custom paramaters will appear as Targets in the rship GUI with Emitters and Actions that observe/set each parameter's value. 

The Base COMP itself is also a Target with an Action to activate/deactivate (turn cooking on/off).

Rocketship has first-class support for Notch TOPs, which can also be tagged 'rship' to expose the parameters of the 'Notch' page, as well as the 'Parameters' page of each Notch layer in the block.

## Installation and Setup

1. Download the rship.tox
2. Import the rship.tox into a TouchDesigner project
3. In the rship.tox, enter the address of a Rocketship Server

## Usage

1. Add an 'rship' tag to any Base COMP
    1. Pulse 'Reconnect' on the rship.tox and verify the COMP appears in the Rocketship GUI as a Target
2. Add the rship_buddy.tox container as a child component anywhere inside the rhsip-tagged Base COMP
    1. Activate the rship_buddy node (click the plus button in the bottom-right corner of the node)
3. Drag and drop parameters onto the rship_buddy
    1. Click on the name of the parameter to reveal the parameter's details, then middle-click and drag from the parameter's lower-case ID onto the rship_buddy
    2. Verify a new custom parameter is created on the rship-tagged Base COMP, on the corresponding Rship_Buddy parameter page
        1. Each instance of the RshipBuddy.tox is associated with a custom parameter page by the name of its parent
    3. Verify the original parameter is bound to the new custom parameter
4. Pulse 'Reconnect' on the rship.tox or save the .toe and verify the parameter appears in the Rocketship GUI as a Target

> NOTE: As of 2024/05/17 Rship-Touchdesigner currently supports float, int, bool, string, and pulse types. Additional types (RGB, XYZ, etc.) can be added upon request.

## Usage: Notch TOPs

1. Add an 'rship' tag to any Notch TOP
2. Pulse 'Reconnect' on the rship.tox or save the .toe and verify the parameter appears in the Rocketship GUI as a Target

> NOTE: When tagging a new OP 'rship', or adding a new custom parameter to a tagged Base COMP, you must pulse 'Reconnect' or save the .toe in order to register it. 

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
