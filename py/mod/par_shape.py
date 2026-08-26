from abc import ABC, abstractmethod
from copy import deepcopy
from typing import Dict, List

from td import OP, ParGroup


SEQUENCE_VALUE_ENVELOPE_STYLES = frozenset({
    "Str",
    "Toggle",
    "Pulse",
    "Momentary",
    "Menu",
    "StrMenu",
    "File",
})


class ParShape(ABC):
    @abstractmethod
    def buildData(self) -> Dict[str, any]:
        """
        Returns a dictionary of data for this ParShape.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    @abstractmethod
    def buildSchemaProperties(self) -> Dict[str, any]:
        """
        Returns a dictionary of schema properties for this ParShape.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    @abstractmethod
    def setData(self, data: Dict[str, any]):
        """
        Sets the data for this ParShape.
        """
        raise NotImplementedError("Subclasses must implement this method.")


class FloatParShape(ParShape):
    def __init__(self, ownerComp: OP, parGroup: ParGroup):
        self.parGroup = parGroup
        self.ownerComp = ownerComp

    def buildData(self) -> Dict[str, any]:
        data = {}
        parName = self.parGroup.name
        if self.parGroup.size > 1:
            for i in self.parGroup.subLabel:
                data[i] = self.ownerComp.par[i].eval()
        else:
            data["value"] = self.ownerComp.par[parName].eval()

        return data

    def buildSchemaProperties(self) -> Dict[str, any]:
        properties = {}
        if self.parGroup.size > 1:
            for i in self.parGroup.subLabel:
                properties[i] = {
                    "type": "number",
                }

        else:
            properties["value"] = {
                "type": "number",
            }
        return properties

    def setData(self, data: Dict[str, any]):
        if self.parGroup.size > 1:
            for i in self.parGroup.subLabel:
                if i in data:
                    self.ownerComp.par[i] = data[i]
        else:
            if "value" in data:
                self.ownerComp.par[self.parGroup.name] = data["value"]


class IntParShape(ParShape):
    def __init__(self, ownerComp: OP, parGroup: ParGroup):
        self.parGroup = parGroup
        self.ownerComp = ownerComp

    def buildData(self) -> Dict[str, any]:
        data = {}
        parName = self.parGroup.name
        if self.parGroup.size > 1:
            for i in self.parGroup.subLabel:
                data[i] = self.ownerComp.par[i].eval()
        else:
            data["value"] = self.ownerComp.par[parName].eval()
        return data

    def buildSchemaProperties(self) -> Dict[str, any]:
        properties = {}
        if self.parGroup.size > 1:
            for i in self.parGroup.subLabel:
                properties[i] = {"type": "integer"}
        else:
            properties["value"] = {"type": "integer"}
        return properties

    def setData(self, data: Dict[str, any]):
        if self.parGroup.size > 1:
            for i in self.parGroup.subLabel:
                if i in data:
                    self.ownerComp.par[i] = data[i]
        else:
            if "value" in data:
                self.ownerComp.par[self.parGroup.name] = data["value"]


class StrParShape(ParShape):
    def __init__(self, ownerComp: OP, parGroup: ParGroup):
        self.parGroup = parGroup
        self.ownerComp = ownerComp

    def buildData(self) -> Dict[str, any]:
        return {"value": self.ownerComp.par[self.parGroup.name].eval()}

    def buildSchemaProperties(self) -> Dict[str, any]:
        return {"value": {"type": "string"}}

    def setData(self, data: Dict[str, any]):
        if "value" in data:
            self.ownerComp.par[self.parGroup.name] = data["value"]


class ToggleParShape(ParShape):
    def __init__(self, ownerComp: OP, parGroup: ParGroup):
        self.parGroup = parGroup
        self.ownerComp = ownerComp

    def buildData(self) -> Dict[str, any]:
        return {"value": self.ownerComp.par[self.parGroup.name].eval()}

    def buildSchemaProperties(self) -> Dict[str, any]:
        return {"value": {"type": "boolean"}}

    def setData(self, data: Dict[str, any]):
        if "value" in data:
            self.ownerComp.par[self.parGroup.name] = data["value"]


class PulseParShape(ParShape):
    def __init__(self, ownerComp: OP, parGroup: ParGroup):
        self.parGroup = parGroup
        self.ownerComp = ownerComp

    def buildData(self) -> Dict[str, any]:
        return {"value": None}

    def buildSchemaProperties(self) -> Dict[str, any]:
        return {"value": {"type": "null"}}

    def setData(self, data: Dict[str, any]):
        self.ownerComp.par[self.parGroup.name].pulse()


class WHParShape(ParShape):
    def __init__(self, ownerComp: OP, parGroup: ParGroup):
        self.parGroup = parGroup
        self.ownerComp = ownerComp

    def buildData(self) -> Dict[str, any]:
        parName = self.parGroup.name
        return {
            "w": self.ownerComp.par[parName + "w"].eval(),
            "h": self.ownerComp.par[parName + "h"].eval(),
        }

    def buildSchemaProperties(self) -> Dict[str, any]:
        return {"w": {"type": "number"}, "h": {"type": "number"}}

    def setData(self, data: Dict[str, any]):
        parName = self.parGroup.name
        if "w" in data:
            self.ownerComp.par[parName + "w"] = data["w"]
        if "h" in data:
            self.ownerComp.par[parName + "h"] = data["h"]


class XYParShape(ParShape):
    def __init__(self, ownerComp: OP, parGroup: ParGroup):
        self.parGroup = parGroup
        self.ownerComp = ownerComp

    def buildData(self) -> Dict[str, any]:
        parName = self.parGroup.name
        return {
            "x": self.ownerComp.par[parName + "x"].eval(),
            "y": self.ownerComp.par[parName + "y"].eval(),
        }

    def buildSchemaProperties(self) -> Dict[str, any]:
        return {"x": {"type": "number"}, "y": {"type": "number"}}

    def setData(self, data: Dict[str, any]):
        parName = self.parGroup.name
        if "x" in data:
            self.ownerComp.par[parName + "x"] = data["x"]
        if "y" in data:
            self.ownerComp.par[parName + "y"] = data["y"]


class XYZParShape(ParShape):
    def __init__(self, ownerComp: OP, parGroup: ParGroup):
        self.parGroup = parGroup
        self.ownerComp = ownerComp

    def buildData(self) -> Dict[str, any]:
        parName = self.parGroup.name
        return {
            "x": self.ownerComp.par[parName + "x"].eval(),
            "y": self.ownerComp.par[parName + "y"].eval(),
            "z": self.ownerComp.par[parName + "z"].eval(),
        }

    def buildSchemaProperties(self) -> Dict[str, any]:
        return {
            "x": {"type": "number"},
            "y": {"type": "number"},
            "z": {"type": "number"},
        }

    def setData(self, data: Dict[str, any]):
        parName = self.parGroup.name
        if "x" in data:
            self.ownerComp.par[parName + "x"] = data["x"]
        if "y" in data:
            self.ownerComp.par[parName + "y"] = data["y"]
        if "z" in data:
            self.ownerComp.par[parName + "z"] = data["z"]


class XYZWParShape(ParShape):
    def __init__(self, ownerComp: OP, parGroup: ParGroup):
        self.parGroup = parGroup
        self.ownerComp = ownerComp

    def buildData(self) -> Dict[str, any]:
        parName = self.parGroup.name

        if self.ownerComp.par[parName + "z"] is None:
            return {
                "x": self.ownerComp.par[parName + "x"].eval(),
                "y": self.ownerComp.par[parName + "y"].eval(),
            }
        

        if self.ownerComp.par[parName + "w"] is None:
            return {
                "x": self.ownerComp.par[parName + "x"].eval(),
                "y": self.ownerComp.par[parName + "y"].eval(),
                "z": self.ownerComp.par[parName + "z"].eval(),
            }


        return {
            "x": self.ownerComp.par[parName + "x"].eval(),
            "y": self.ownerComp.par[parName + "y"].eval(),
            "z": self.ownerComp.par[parName + "z"].eval(),
            "w": self.ownerComp.par[parName + "w"].eval(),
        }

    def buildSchemaProperties(self) -> Dict[str, any]:

        if self.ownerComp.par[self.parGroup.name + "z"] is None:
            return {
                "x": {"type": "number"},
                "y": {"type": "number"},
            }
        

        if self.ownerComp.par[self.parGroup.name + "w"] is None:
            return {
                "x": {"type": "number"},
                "y": {"type": "number"},
                "z": {"type": "number"},
            }


        return {
            "x": {"type": "number"},
            "y": {"type": "number"},
            "z": {"type": "number"},
            "w": {"type": "number"},
        }

    def setData(self, data: Dict[str, any]):
        parName = self.parGroup.name
        if "x" in data:
            self.ownerComp.par[parName + "x"] = data["x"]
        if "y" in data:
            self.ownerComp.par[parName + "y"] = data["y"]
        if "z" in data:
            self.ownerComp.par[parName + "z"] = data["z"]
        if "w" in data:
            self.ownerComp.par[parName + "w"] = data["w"]


class RGBParShape(ParShape):
    def __init__(self, ownerComp: OP, parGroup: ParGroup):
        self.parGroup = parGroup
        self.ownerComp = ownerComp

    def buildData(self) -> Dict[str, any]:
        parName = self.parGroup.name
        return {
            "r": self.ownerComp.par[parName + "r"].eval(),
            "g": self.ownerComp.par[parName + "g"].eval(),
            "b": self.ownerComp.par[parName + "b"].eval(),
        }

    def buildSchemaProperties(self) -> Dict[str, any]:
        return {
            "r": {"type": "number", "minimum": 0, "maximum": 1},
            "g": {"type": "number", "minimum": 0, "maximum": 1},
            "b": {"type": "number", "minimum": 0, "maximum": 1},
        }

    def setData(self, data: Dict[str, any]):
        parName = self.parGroup.name
        if "r" in data:
            self.ownerComp.par[parName + "r"] = data["r"]
        if "g" in data:
            self.ownerComp.par[parName + "g"] = data["g"]
        if "b" in data:
            self.ownerComp.par[parName + "b"] = data["b"]


class ColorParShape(ParShape):
    def __init__(self, ownerComp: OP, parGroup: ParGroup):
        self.parGroup = parGroup
        self.ownerComp = ownerComp

    def buildData(self) -> Dict[str, any]:
        parName = self.parGroup.name

        if self.ownerComp.par[parName + "a"] is None:
            return {
                "r": self.ownerComp.par[parName + "r"].eval(),
                "g": self.ownerComp.par[parName + "g"].eval(),
                "b": self.ownerComp.par[parName + "b"].eval(),
            }

        return {
            "r": self.ownerComp.par[parName + "r"].eval(),
            "g": self.ownerComp.par[parName + "g"].eval(),
            "b": self.ownerComp.par[parName + "b"].eval(),
            "a": self.ownerComp.par[parName + "a"].eval(),
        }

    def buildSchemaProperties(self) -> Dict[str, any]:
        if self.ownerComp.par[self.parGroup.name + "a"] is None:
            return {
                "r": {"type": "number", "minimum": 0, "maximum": 1},
                "g": {"type": "number", "minimum": 0, "maximum": 1},
                "b": {"type": "number", "minimum": 0, "maximum": 1},
            }

        return {
            "r": {"type": "number", "minimum": 0, "maximum": 1},
            "g": {"type": "number", "minimum": 0, "maximum": 1},
            "b": {"type": "number", "minimum": 0, "maximum": 1},
            "a": {"type": "number", "minimum": 0, "maximum": 1},
        }

    def setData(self, data: Dict[str, any]):
        parName = self.parGroup.name
        if "r" in data:
            self.ownerComp.par[parName + "r"] = data["r"]
        if "g" in data:
            self.ownerComp.par[parName + "g"] = data["g"]
        if "b" in data:
            self.ownerComp.par[parName + "b"] = data["b"]
        if "a" in data:
            self.ownerComp.par[parName + "a"] = data["a"]


class UVParShape(ParShape):
    def __init__(self, ownerComp: OP, parGroup: ParGroup):
        self.parGroup = parGroup
        self.ownerComp = ownerComp

    def buildData(self) -> Dict[str, any]:
        parName = self.parGroup.name
        return {
            "u": self.ownerComp.par[parName + "u"].eval(),
            "v": self.ownerComp.par[parName + "v"].eval(),
        }

    def buildSchemaProperties(self) -> Dict[str, any]:
        return {
            "u": {"type": "number", "minimum": 0, "maximum": 1},
            "v": {"type": "number", "minimum": 0, "maximum": 1},
        }

    def setData(self, data: Dict[str, any]):
        parName = self.parGroup.name
        if "u" in data:
            self.ownerComp.par[parName + "u"] = data["u"]
        if "v" in data:
            self.ownerComp.par[parName + "v"] = data["v"]


class UVWParShape(ParShape):
    def __init__(self, ownerComp: OP, parGroup: ParGroup):
        self.parGroup = parGroup
        self.ownerComp = ownerComp

    def buildData(self) -> Dict[str, any]:
        parName = self.parGroup.name

        if self.ownerComp.par[parName + "w"] is None:
            return {
                "u": self.ownerComp.par[parName + "u"].eval(),
                "v": self.ownerComp.par[parName + "v"].eval(),
            }


        return {
            "u": self.ownerComp.par[parName + "u"].eval(),
            "v": self.ownerComp.par[parName + "v"].eval(),
            "w": self.ownerComp.par[parName + "w"].eval(),
        }

    def buildSchemaProperties(self) -> Dict[str, any]:

        if self.ownerComp.par[self.parGroup.name + "w"] is None:
            return {
                "u": {"type": "number", "minimum": 0, "maximum": 1},
                "v": {"type": "number", "minimum": 0, "maximum": 1},
            }

        return {
            "u": {"type": "number", "minimum": 0, "maximum": 1},
            "v": {"type": "number", "minimum": 0, "maximum": 1},
            "w": {"type": "number", "minimum": 0, "maximum": 1},
        }

    def setData(self, data: Dict[str, any]):
        parName = self.parGroup.name
        if "u" in data:
            self.ownerComp.par[parName + "u"] = data["u"]
        if "v" in data:
            self.ownerComp.par[parName + "v"] = data["v"]
        if "w" in data:
            self.ownerComp.par[parName + "w"] = data["w"]


class MenuParShape(ParShape):
    def __init__(self, ownerComp: OP, parGroup: ParGroup):
        self.parGroup = parGroup
        self.ownerComp = ownerComp

    def buildData(self) -> Dict[str, any]:
        return {"value": self.ownerComp.par[self.parGroup.name].eval()}

    def buildSchemaProperties(self) -> Dict[str, any]:
        oneOf = []
        for i in range(len(self.parGroup.menuNames[0])):
            oneOf.append(
                {
                    "const": self.parGroup.menuNames[0][i],
                    "title": self.parGroup.menuLabels[0][i],
                }
            )
        return {"value": {"type": "string", "oneOf": oneOf}}

    def setData(self, data: Dict[str, any]):
        if "value" in data:
            self.ownerComp.par[self.parGroup.name] = data["value"]


class StrMenuParShape(MenuParShape):
    pass


class FileParShape(ParShape):
    def __init__(self, ownerComp: OP, parGroup: ParGroup):
        self.parGroup = parGroup
        self.ownerComp = ownerComp

    def buildData(self) -> Dict[str, any]:
        return {"value": self.ownerComp.par[self.parGroup.name].eval()}

    def buildSchemaProperties(self) -> Dict[str, any]:
        return {"value": {"$ref": "asset-path"}}

    def setData(self, data: Dict[str, any]):
        if "value" in data:
            self.ownerComp.par[self.parGroup.name] = data["value"]


def buildShape(ownerComp: OP, parGroup: ParGroup) -> ParShape:
    """
    Factory function to build the appropriate ParShape based on the parGroup style.
    """
    if parGroup.style == "Float":
        return FloatParShape(ownerComp, parGroup)
    elif parGroup.style == "Int":
        return IntParShape(ownerComp, parGroup)
    elif parGroup.style == "Str":
        return StrParShape(ownerComp, parGroup)
    elif parGroup.style == "Toggle":
        return ToggleParShape(ownerComp, parGroup)
    elif parGroup.style == "Pulse" or parGroup.style == "Momentary":
        return PulseParShape(ownerComp, parGroup)
    elif parGroup.style == "WH":
        return WHParShape(ownerComp, parGroup)
    elif parGroup.style == "XY":
        return XYParShape(ownerComp, parGroup)
    elif parGroup.style == "XYZ":
        return XYZParShape(ownerComp, parGroup)
    elif parGroup.style == "XYZW":
        return XYZWParShape(ownerComp, parGroup)
    elif parGroup.style == "RGB":
        return RGBParShape(ownerComp, parGroup)
    elif parGroup.style == "RGBA":
        return ColorParShape(ownerComp, parGroup)
    elif parGroup.style == "UV":
        return UVParShape(ownerComp, parGroup)
    elif parGroup.style == "UVW":
        return UVWParShape(ownerComp, parGroup)
    elif parGroup.style == "Menu":
        return MenuParShape(ownerComp, parGroup)
    elif parGroup.style == "StrMenu":
        return StrMenuParShape(ownerComp, parGroup)
    elif parGroup.style == "File":
        return FileParShape(ownerComp, parGroup)
    elif parGroup.style == "Sequence":
        return SequenceParShape(ownerComp, parGroup)

    raise ValueError(f"Unknown ParType: {parGroup.style}")


class SequenceParShape(ParShape):
    def __init__(self, ownerComp: OP, parGroup: ParGroup, sequenceParGroups: List[ParGroup] | None = None):
        self.parGroup = parGroup
        self.ownerComp = ownerComp
        self.sequenceParGroups = sequenceParGroups or [parGroup]
        self._cachedData = None
        self._blockCacheSequenceName = None
        self._blockCacheCount = -1
        self._blockMembers = []
        self._blockPulseMemberKeys = []

    def _invalidateBlockCache(self):
        self._blockCacheSequenceName = None
        self._blockCacheCount = -1
        self._blockMembers = []
        self._blockPulseMemberKeys = []

    def _ensureBlockCache(self, sequence):
        blockCount = sequence.numBlocks
        if (
            self._blockCacheSequenceName == sequence.name
            and self._blockCacheCount == blockCount
            and len(self._blockMembers) == blockCount
        ):
            return

        blockMembers = []
        blockPulseMemberKeys = []

        # Iterating a TouchDesigner SequenceBlock creates ParGroup/PageList
        # proxy objects.  Materialize those proxies once per sequence shape and
        # reuse them until the number of blocks changes.
        for block in sequence.blocks:
            members = []
            pulseMemberKeys = []
            for blockParGroup in block:
                try:
                    blockShape = buildShape(self.ownerComp, blockParGroup)
                except ValueError as e:
                    op.RS_LOG.Debug(
                        f"[SequenceParShape]: Skipping par '{blockParGroup.name}' while caching sequence members: {e}"
                    )
                    continue

                memberKey = self._getSequenceMemberKey(blockParGroup)
                members.append((blockParGroup, memberKey, blockShape))
                if blockParGroup.style in ("Pulse", "Momentary"):
                    pulseMemberKeys.append(memberKey)

            blockMembers.append(tuple(members))
            blockPulseMemberKeys.append(tuple(pulseMemberKeys))

        # TD may return a fresh Python proxy each time ParGroup.sequence is
        # accessed, so object identity is not a stable cache key.
        self._blockCacheSequenceName = sequence.name
        self._blockCacheCount = blockCount
        self._blockMembers = tuple(blockMembers)
        self._blockPulseMemberKeys = tuple(blockPulseMemberKeys)

    def _getSchemaParGroups(self) -> List[ParGroup]:
        schemaParGroups = []

        for parGroup in self.sequenceParGroups:
            if parGroup is None:
                continue
            if parGroup.style == "Sequence":
                continue
            if parGroup.name == self.parGroup.name:
                continue
            schemaParGroups.append(parGroup)

        if len(schemaParGroups) > 0:
            return schemaParGroups

        sequence = self.parGroup.sequence
        if sequence is None or sequence.numBlocks == 0:
            return []

        self._ensureBlockCache(sequence)
        if not self._blockMembers:
            return []
        return [member[0] for member in self._blockMembers[0]]

    def _getSequenceMemberKey(self, parGroup: ParGroup) -> str:
        sequence = getattr(parGroup, 'sequence', None)
        if sequence is None:
            return parGroup.name

        sequenceIndex = getattr(parGroup, 'sequenceIndex', None)
        if sequenceIndex is None:
            sequenceIndex = getattr(parGroup, 'blockIndex', None)

        if sequenceIndex is None:
            return parGroup.name

        prefix = f"{sequence.name}{sequenceIndex}"
        if parGroup.name.startswith(prefix):
            return parGroup.name[len(prefix):]

        return parGroup.name

    def _unwrapSequenceMemberData(self, value: any):
        if isinstance(value, dict):
            keys = list(value.keys())
            if keys == ["value"]:
                return value["value"]
        return value

    def _wrapSequenceMemberData(self, parGroup: ParGroup, value: any):
        # Scalar sequence members use the same {"value": ...} envelope as their
        # non-sequence ParShape counterparts.  Determine that from the parameter
        # shape instead of building its schema here.  Menu schema construction
        # reads menuNames/menuLabels, which can re-evaluate a dynamic menuSource
        # while TouchDesigner is resizing or populating the sequence.
        usesValueEnvelope = (
            parGroup.style in SEQUENCE_VALUE_ENVELOPE_STYLES
            or (parGroup.style in ("Float", "Int") and parGroup.size == 1)
        )
        if usesValueEnvelope and not isinstance(value, dict):
            return {"value": value}
        return value

    def _unwrapSequenceMemberSchema(self, schemaProperties: Dict[str, any]):
        if list(schemaProperties.keys()) == ["value"]:
            return schemaProperties["value"]
        return {
            "type": "object",
            "properties": schemaProperties,
        }

    def _blockHasActivePulse(self, blockIndex: int, blockData: Dict[str, any]) -> bool:
        if blockIndex >= len(self._blockPulseMemberKeys):
            return False
        return any(
            bool(blockData.get(memberKey, False))
            for memberKey in self._blockPulseMemberKeys[blockIndex]
        )

    def buildData(self) -> List[Dict[str, any]]:
        items = []
        sequence = self.parGroup.sequence
        if sequence is None:
            return items

        self._ensureBlockCache(sequence)
        for blockMembers in self._blockMembers:
            blockItem = {}
            for blockParGroup, memberKey, blockShape in blockMembers:
                blockItem[memberKey] = self._unwrapSequenceMemberData(
                    blockShape.buildData()
                )
            items.append(blockItem)

        # SequenceTarget keeps one SequenceParShape alive for actions and
        # emitters.  Retain the most recently observed state so a high-rate set
        # does not have to re-evaluate every member merely to find its delta.
        self._cachedData = deepcopy(items)
        return items

    def buildSchemaProperties(self) -> Dict[str, any]:
        itemProperties = {}
        seenParGroups = set()

        for blockParGroup in self._getSchemaParGroups():
            memberKey = self._getSequenceMemberKey(blockParGroup)
            if memberKey in seenParGroups:
                continue
            seenParGroups.add(memberKey)
            try:
                blockShape = buildShape(self.ownerComp, blockParGroup)
            except ValueError as e:
                op.RS_LOG.Debug(f"[SequenceParShape]: Skipping par '{blockParGroup.name}' in buildSchemaProperties: {e}")
                continue
            itemProperties[memberKey] = self._unwrapSequenceMemberSchema(
                blockShape.buildSchemaProperties()
            )

        return {
            "type": "array",
            "items": {
                "type": "object",
                "properties": itemProperties,
            },
        }

    def setData(self, data: List[Dict[str, any]]):
        sequence = self.parGroup.sequence
        if sequence is None:
            return

        if not isinstance(data, list):
            raise ValueError("Sequence data must be an array")

        # Validate the complete payload before resizing or assigning anything.
        for blockIndex, blockData in enumerate(data):
            if not isinstance(blockData, dict):
                raise ValueError(f"Sequence block {blockIndex} must be an object")

        # Assigning numBlocks rebuilds TouchDesigner's sequential parameters.
        # Avoid that churn when an action only updates values in existing blocks.
        if sequence.numBlocks != len(data):
            sequence.numBlocks = len(data)
            self._invalidateBlockCache()
        self._ensureBlockCache(sequence)

        for blockIndex, blockData in enumerate(data):
            blockMembers = self._blockMembers[blockIndex]
            for blockParGroup, memberKey, blockShape in blockMembers:
                blockValue = blockData.get(memberKey, None)
                if blockValue is None:
                    continue
                isActivePulse = (
                    blockParGroup.style in ("Pulse", "Momentary")
                    and bool(blockValue)
                )
                if blockParGroup.style in ("Pulse", "Momentary") and not blockValue:
                    continue
                if not isActivePulse:
                    # Parameters can be changed by TouchDesigner scene recalls,
                    # expressions, exports, or scripts without going through
                    # this action handler.  The last received payload is not a
                    # reliable snapshot of the live component, so compare the
                    # desired value with the actual parameter before skipping.
                    currentValue = self._unwrapSequenceMemberData(
                        blockShape.buildData()
                    )
                    if currentValue == blockValue:
                        continue
                blockShape.setData(self._wrapSequenceMemberData(blockParGroup, blockValue))

        self._cachedData = deepcopy(data)
