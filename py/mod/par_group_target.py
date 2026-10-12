from datetime import datetime, timezone
from exec import Target, Action, Emitter, Instance, makeWriterRef
from typing import Dict, List
from par_shape import buildShape, makeExecTick
from uuid import uuid4
from target import TouchTarget
from util import makeEmitterChangeKey
from exec import CLIENT

def supportsProperties(ownerComp) -> bool:
    return "rship-no-properties" not in getattr(ownerComp, "tags", ())


class ParGroupTarget(TouchTarget):
    def __init__(self, parentId: str, opTargetId: str,  ownerComp: OP, parGroup: ParGroup, instance: Instance, allowProperties: bool = True):
        
        super().__init__(instance)
        self.ownerComp = ownerComp
        self.parentId = parentId
        self.opTargetId = opTargetId
        self.parGroup = parGroup
        self.isProperty = allowProperties and parGroup.style not in ("Pulse", "Momentary", "Sequence") and getattr(parGroup, "sequence", None) is None
        self.parShape = buildShape( ownerComp, parGroup)
        op.RS_LOG.Debug(f"[ParGroupTarget]: Initializing ParGroupTarget for {self.parGroup.name} at {self.ownerComp.path}")

        op.RS_LOG.Debug("SCHEMA", self.parShape.buildSchemaProperties())

    @property
    def id(self) -> str:
        return f"{self.opTargetId}:{self.parGroup.name}"
    

    def collectChildren(self) -> List[TouchTarget]:
        return [self]

    def getTarget(self) -> Target:
        return  Target(
            id=self.id,
            name=self.parGroup.name,
            parentTargets=[self.parentId],
            category=self.parGroup.style,
            serviceId=self.instance.serviceId,
        )


    def getActions(self) -> List[Action]:
        """
        Returns a list of actions that can be performed on this target.
        """

        schema = {
            "type": "object",
            "properties": self.parShape.buildSchemaProperties()
        }

        # Rship provides the GO exec pin separately. A null action schema
        # registers a trigger without any editable data pins.
        if self.parGroup.style in ("Pulse", "Momentary"):
            schema = None

        def handleSetAction(action: Action, data: Dict[str, any]):
            result = self.handleAction(action.id, data)
            if self.isProperty:
                CLIENT.pulseEmitter(f"{self.id}:updated", self.parShape.buildData())
            return result

        setAction = Action(
            id=f"{self.id}:set",
            name=f"Set {self.parGroup.name}",
            targetId=self.id,
            schema=schema,
            serviceId=self.instance.serviceId,
            handler=handleSetAction,
            writesTo=makeWriterRef(f"{self.id}:updated") if self.isProperty else None,
        )

        def handleResendAction(action: Action, data: Dict[str, any]):
            CLIENT.pulseEmitter(f"{self.id}:updated", self.parShape.buildData())
            return
        

        resendAction = Action(
            id=f"{self.id}:resend",
            name=f"Resend {self.parGroup.name}",
            targetId=self.id,
            schema=None,
            serviceId=self.instance.serviceId,
            handler=handleResendAction
        )

        return [setAction, resendAction]

    def getEmitters(self) -> List[Emitter]:
        """
        Returns a list of emitters that can be used with this target.
        """

        schema = {
            "type": "object",
            "properties": self.parShape.buildSchemaProperties()
        }

        if self.parGroup.style in ("Pulse", "Momentary"):
            schema = self.parShape.buildSchemaProperties()

        setEmitter = Emitter(
            id=f"{self.id}:updated",
            name=self.parGroup.name if self.isProperty else f"{self.parGroup.name} Updated",
            targetId=self.id,
            serviceId=self.instance.serviceId,
            schema=schema,
            changeKey=makeEmitterChangeKey(self.ownerComp, self.parGroup.name),
            handler=self.parShape.buildData
        )

        return [setEmitter]




    def handleAction(self, actionId, data):
        if self.parGroup.style in ("Pulse", "Momentary"):
            if data is not None:
                raise ValueError("Pulse action takes no data payload")
            data = makeExecTick(str(uuid4()))
        return self.parShape.setData(data)
