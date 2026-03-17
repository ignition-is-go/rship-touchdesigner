from exec import Action, CLIENT, Emitter, Instance, Target
from par_shape import SequenceParShape
from target import TouchTarget
from util import makeEmitterChangeKey


class SequenceTarget(TouchTarget):
    def __init__(self, parentId: str, opTargetId: str, ownerComp: OP, parGroup: ParGroup, instance: Instance, sequenceParGroups=None):
        super().__init__(instance)
        self.ownerComp = ownerComp
        self.parentId = parentId
        self.opTargetId = opTargetId
        self.parGroup = parGroup
        self.sequence = parGroup.sequence
        self.parShape = SequenceParShape(ownerComp, parGroup, sequenceParGroups=sequenceParGroups)

        if self.sequence is None:
            raise ValueError(f"{parGroup.name} is not part of a sequence")

        op.RS_LOG.Debug(f"[SequenceTarget]: Initializing SequenceTarget for {self.sequence.name} at {self.ownerComp.path}")

    @property
    def id(self) -> str:
        return f"{self.opTargetId}:{self.sequence.name}"

    def collectChildren(self):
        return [self]

    def getTarget(self) -> Target:
        return Target(
            id=self.id,
            name=self.sequence.name,
            parentTargets=[self.parentId],
            category="Sequence",
            serviceId=self.instance.serviceId,
        )

    def getActions(self):
        schema = self.parShape.buildSchemaProperties()

        def handleSetAction(action: Action, data):
            return self.parShape.setData(data)

        setAction = Action(
            id=f"{self.id}:set",
            name=f"Set {self.sequence.name}",
            targetId=self.id,
            schema=schema,
            serviceId=self.instance.serviceId,
            handler=handleSetAction,
        )

        def handleResendAction(action: Action, data):
            CLIENT.pulseEmitter(f"{self.id}:updated", self.parShape.buildData())
            return

        resendAction = Action(
            id=f"{self.id}:resend",
            name=f"Resend {self.sequence.name}",
            targetId=self.id,
            schema=None,
            serviceId=self.instance.serviceId,
            handler=handleResendAction,
        )

        return [setAction, resendAction]

    def _buildChangeKeys(self):
        changeKeys = [makeEmitterChangeKey(self.ownerComp, self.sequence.name)]
        for block in self.sequence.blocks:
            for blockParGroup in block:
                changeKeys.append(makeEmitterChangeKey(self.ownerComp, blockParGroup.name))
        return list(dict.fromkeys(changeKeys))

    def getEmitters(self):
        schema = self.parShape.buildSchemaProperties()

        setEmitter = Emitter(
            id=f"{self.id}:updated",
            name=f"{self.sequence.name} Updated",
            targetId=self.id,
            serviceId=self.instance.serviceId,
            schema=schema,
            changeKey=makeEmitterChangeKey(self.ownerComp, self.sequence.name),
            handler=self.parShape.buildData,
        )
        setEmitter.changeKeys = self._buildChangeKeys()

        return [setEmitter]
