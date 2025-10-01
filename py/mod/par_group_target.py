from datetime import datetime, timezone
from exec import Target, Action, Emitter, Instance
from typing import Dict, List
from par_shape import buildShape
from target import TouchTarget
from util import makeEmitterChangeKey
from exec import CLIENT

class ParGroupTarget(TouchTarget):
    def __init__(self, parentId: str, opTargetId: str,  ownerComp: OP, parGroup: ParGroup, instance: Instance):
        
        super().__init__(instance)
        self.ownerComp = ownerComp
        self.parentId = parentId
        self.opTargetId = opTargetId
        self.parGroup = parGroup
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
            rootLevel=False,
            serviceId=self.instance.serviceId,
            fgColor="#ffffff",
            bgColor="#000000",
            lastUpdated=datetime.now(timezone.utc).isoformat(),
        )


    def getActions(self) -> List[Action]:
        """
        Returns a list of actions that can be performed on this target.
        """

        schema = {
            "type": "object",
            "properties": self.parShape.buildSchemaProperties()
        }

        def handleSetAction(action: Action, data: Dict[str, any]):
            return self.parShape.setData(data)

        setAction = Action(
            id=f"{self.id}:set",
            name=f"Set {self.parGroup.name}",
            targetId=self.id,
            schema=schema,
            serviceId=self.instance.serviceId,
            handler=handleSetAction
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

        setEmitter = Emitter(
            id=f"{self.id}:updated",
            name=f"{self.parGroup.name} Updated",
            targetId=self.id,
            serviceId=self.instance.serviceId,
            schema=schema,
            changeKey=makeEmitterChangeKey(self.ownerComp, self.parGroup.name),
            handler=self.parShape.buildData
        )

        return [setEmitter]




    def handleAction(self, actionId, data):
        return self.parShape.setData(data)