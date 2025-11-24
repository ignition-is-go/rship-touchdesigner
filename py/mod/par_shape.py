import uuid
from abc import ABC, abstractmethod
from typing import Dict, List

from td import OP, ParGroup


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
        return {"value": str(uuid.uuid4())}

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
        return {
            "x": self.ownerComp.par[parName + "x"].eval(),
            "y": self.ownerComp.par[parName + "y"].eval(),
            "z": self.ownerComp.par[parName + "z"].eval(),
            "w": self.ownerComp.par[parName + "w"].eval(),
        }

    def buildSchemaProperties(self) -> Dict[str, any]:
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


class RGBAParShape(ParShape):
    def __init__(self, ownerComp: OP, parGroup: ParGroup):
        self.parGroup = parGroup
        self.ownerComp = ownerComp

    def buildData(self) -> Dict[str, any]:
        parName = self.parGroup.name
        return {
            "r": self.ownerComp.par[parName + "r"].eval(),
            "g": self.ownerComp.par[parName + "g"].eval(),
            "b": self.ownerComp.par[parName + "b"].eval(),
            "a": self.ownerComp.par[parName + "a"].eval(),
        }

    def buildSchemaProperties(self) -> Dict[str, any]:
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
        return {
            "u": self.ownerComp.par[parName + "u"].eval(),
            "v": self.ownerComp.par[parName + "v"].eval(),
            "w": self.ownerComp.par[parName + "w"].eval(),
        }

    def buildSchemaProperties(self) -> Dict[str, any]:
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


class SequenceParShape(ParShape):
    def __init__(self, ownerComp: OP, parGroup: ParGroup):
        self.parGroup = parGroup
        self.ownerComp = ownerComp

    def buildData(self) -> Dict[str, any]:
        # Sequence data structure can be customized as needed
        return {"blocks": [self.parGroup.sequence.numBlocks]}

    def buildSchemaProperties(self) -> Dict[str, any]:
        # Schema for sequence can be customized as needed
        return {"blocks": {"type": "number"}}

    def setData(self, data: Dict[str, any]):
        self.parGroup.sequence.numBlocks = data.get("blocks", 1)
        # Implement logic to set sequence data if needed
        pass


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
    elif parGroup.style == "Pulse":
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
        return RGBAParShape(ownerComp, parGroup)
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
