from exec import Action, CLIENT, Emitter, Instance, Target, makeWriterRef
from par_group_target import supportsProperties
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
        self.stateShape = SequenceParShape(ownerComp, parGroup, sequenceParGroups=sequenceParGroups, stateOnly=True)
        self.isProperty = supportsProperties(ownerComp) and bool(self.stateShape.buildSchemaProperties()["items"]["properties"])

        if self.sequence is None:
            raise ValueError(f"{parGroup.name} is not part of a sequence")

        op.RS_LOG.Debug(f"[SequenceTarget]: Initializing SequenceTarget for {self.sequence.name} at {self.ownerComp.path}")

    @property
    def id(self) -> str:
        legacyId = f"{self.opTargetId}:{self.sequence.name}"

        # Sequence targets historically omitted their owning page from the ID.
        # Preserve that ID unless it would be identical to the PageTarget ID
        # (for example, a "Sampler" sequence on a "Sampler" page).  Identical
        # IDs make one target and its actions silently overwrite the other in
        # Rship's ID-indexed registries.
        if legacyId == self.parentId:
            return f"{self.opTargetId}:Sequence:{self.sequence.name}"

        return legacyId

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

        actions = [setAction, resendAction]
        if self.isProperty:
            def handleStateSetAction(action: Action, data):
                self.stateShape.setData(data)
                CLIENT.pulseEmitter(f"{self.id}:state_updated", self.stateShape.buildData())

            actions.append(Action(
                id=f"{self.id}:state_set",
                name=f"Set {self.sequence.name} State",
                targetId=self.id,
                schema=self.stateShape.buildSchemaProperties(),
                serviceId=self.instance.serviceId,
                handler=handleStateSetAction,
                writesTo=makeWriterRef(f"{self.id}:state_updated"),
            ))
        return actions

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

        emitters = [setEmitter]
        if self.isProperty:
            stateEmitter = Emitter(
                id=f"{self.id}:state_updated",
                name=f"{self.sequence.name} State",
                targetId=self.id,
                serviceId=self.instance.serviceId,
                schema=self.stateShape.buildSchemaProperties(),
                changeKey=makeEmitterChangeKey(self.ownerComp, self.sequence.name),
                handler=self.stateShape.buildData,
            )
            stateEmitter.changeKeys = list(setEmitter.changeKeys)
            emitters.append(stateEmitter)
        return emitters
