# Rship-TouchDesigner

The TouchDesigner Executor integrates naturally and easily with Rocketship. Simply load the rship .tox into any TouchDesigner network to eastablish a connection with Rocketship, tag the Base COMPs whose parameters you wish to expose with 'rship', and their custom paramaters will appear as Targets in the rship GUI with Emitters and Actions to observe/set each parameter's values.

The Base COMP itself is also a Target and can be activated/deactivated with an Action.

Notch TOPs can also be tagged 'rship' to expose the parameters of the Notch page, as well as the parameter pages of every layer of the Notch block.

## Installation

> 1. Download the rship.tox
> 2. Import the rship.tox into your TouchDesigner project

## Usage

> 1. Add an 'rship' tag to every Base COMP you wish to expose to Rocketship as a Target.
> 2. Custom parameters of tagged Base COMPs will appear in Rocketship as Targets.
> 3. Bind any parameter in the network to a custom parameter on a tagged Base COMP
>    1. Right-click on an 'rship'-labeled BaseCOMP and choose 'Customize Component'
>    2. Enter a 'Par Name' and choose the parameter's data type and number of values
>    3. Identify the parameter in your TouchDesigner patch you wish to expose to Rocketship
>       1. Right-click on the parameter and click 'Copy Parameter'
>       2. Navigate back to the tagged Base COMP, right-click on the custom parameter, and select 'Paste Bind'
> 4. Save the project
> 5. Verify that the custom parameter appears in the Rocketship GUI as a Target
> 6. To export the output of a node to a custom parameter, drag the node onto the parameter name and select 'Export'

> NOTE: If Targets do not appear immediately in Rocketship, navigate to the rship.tox and pulse Reconnect.

## Targets, Actions, and Emitters

| Targets          | Emitters                    | Actions                 |
| ---------------- | --------------------------- | ----------------------- |
| **Base COMPs**   |                             | - Activate cooking      |
|                  |                             | - Deactivate cooking    |
|                  | - Publish custom par values | - Set custom par values |
| **Notch TOPs**   |                             | - Activate cooking      |
|                  |                             | - Deactivate cooking    |
|                  | - Publish Notch par values  | - Set Notch par values  |
| **Notch Layers** | - Publish layer par values  | - Set layer par values  |
