from exec import Action, CLIENT, Emitter, Instance, Target, makeWriterRef
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
            self.parShape.setData(data)
            # Sequence block edits don't reliably trigger the emitters parexec, so
            # the Deferred readback never fires and the server stays diverged.
            # Pulse the applied value explicitly (Applied mode) to converge.
            CLIENT.pulseEmitter(f"{self.id}:updated", self.parShape.buildData())
            return

        # Canonical writer of the {id}:updated property emitter.
        setAction = Action(
            id=f"{self.id}:set",
            name=f"Set {self.sequence.name}",
            targetId=self.id,
            schema=schema,
            serviceId=self.instance.serviceId,
            handler=handleSetAction,
            writesTo=makeWriterRef(f"{self.id}:updated"),
        )

        # Resend is server-driven now (inbound ResendEmitterValue), not an action.
        return [setAction]

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
            name=self.sequence.name,
            targetId=self.id,
            serviceId=self.instance.serviceId,
            schema=schema,
            changeKey=makeEmitterChangeKey(self.ownerComp, self.sequence.name),
            handler=self.parShape.buildData,
        )
        setEmitter.changeKeys = self._buildChangeKeys()

        return [setEmitter]
