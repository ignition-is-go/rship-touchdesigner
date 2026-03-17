from datetime import datetime, timezone
from par_group_target import ParGroupTarget
from sequence_target import SequenceTarget
from exec import Target, TargetStatus, Action, Emitter, Instance
from typing import Dict, List
from target import TouchTarget
from util import RS_TARGET_INFO_PAGE
import json

class PageTarget(TouchTarget):

    def __init__(self, parentId: str, ownerComp: OP, page: Page, instance: Instance):
        super().__init__(instance)
        self.ownerComp = ownerComp
        self.page = page
        self.parentId = parentId
        self.parGroupTargets: Dict[str, ParGroupTarget] = {}
        self.parGroupTargetsByName: Dict[str, ParGroupTarget] = {}
        self.sequenceTargets: Dict[str, SequenceTarget] = {}
        self.sequenceTargetsByName: Dict[str, SequenceTarget] = {}

        op.RS_LOG.Debug(f"[PageTarget]: Initializing PageTarget for {self.page.name} at {self.ownerComp.path}")

        self.buildParGroupTargets()
        self.bulkUpdatedName = f"Rship{self.page.name.replace(' ', '').lower()}updated"
        self.generateUtilPars()

    
    @property
    def id(self) -> str:
        return f"{self.parentId}:{self.page.name}"

    def getTarget(self) -> Target:
        return  Target(
            id=self.id,
            name=self.page.name,
            parentTargets=[self.parentId],
            category="Page",
            serviceId=self.instance.serviceId,
        )

    def collectChildren(self):
        children = [self]
        for t in self.parGroupTargets.values():
            children.extend(t.collectChildren())
        for t in self.sequenceTargets.values():
            children.extend(t.collectChildren())
        return children

    def getActions(self) -> List[Action]:
        """
        Returns a list of actions that can be performed on this target.
        """

        def bulk_set_action_handler(action: Action, data: Dict[str, any]):
            op.RS_LOG.Debug(f"[OPTarget]: Handling bulk set action for {self.id}")
            op.RS_LOG.Debug("Data received:", data)

            for par in self.parGroupTargets.values():
                if par.parShape is None:
                    continue

                if par.parGroup.name in data:
                    value = data.get(par.parGroup.name, None)
                    if value is None:
                        op.RS_LOG.Debug(f"Skipping {par.parGroup.name} on {self.page.name} as no value provided")
                        continue
                    par.parShape.setData(value)
                op.RS_LOG.Debug(f"Setting {par.parGroup.name} to {value} on {self.page.name}")
            for sequenceTarget in self.sequenceTargets.values():
                value = data.get(sequenceTarget.sequence.name, None)
                if value is None:
                    continue
                sequenceTarget.parShape.setData(value)
                op.RS_LOG.Debug(f"Setting sequence {sequenceTarget.sequence.name} on {self.page.name}")
            opCompletePulse = self.ownerComp.par[self.bulkUpdatedName]
            if not opCompletePulse.isPulse:
                op.RS_LOG.Warning(f"[PageTarget]: {self.bulkUpdatedName} is not a pulse parameter, cannot pulse.")
                return
            opCompletePulse.pulse()
            pass


        orderedEntries = self.buildBulkSchemaEntries()
        properties = {entry["path"]: entry["schema"] for entry in orderedEntries}
        schemaLayout = []
        for entry in orderedEntries:
            layoutEntry = {"path": entry["path"]}
            if entry["label"] is not None:
                layoutEntry["label"] = entry["label"]
            if entry["section"] is not None:
                layoutEntry["section"] = entry["section"]
            schemaLayout.append(layoutEntry)

        schema = {
            "type": "object",
            "properties": properties,
        }
        op.RS_LOG.Info(
            f"[PageTarget]: Bulk schema for {self.id}: {json.dumps({'schema': schema, 'schemaLayout': schemaLayout}, sort_keys=True)}"
        )


        bulk_set_action = Action(
            id=f"{self.id}:bulk_set",
            name="Bulk Set",
            handler=bulk_set_action_handler,
            targetId=self.id,
            schema=schema,
            schemaLayout=schemaLayout,
            serviceId=self.instance.serviceId
        )

        allActions = [bulk_set_action] 
        return allActions

    def getEmitters(self) -> List[Emitter]:
        """
        Returns a list of emitters that can be used with this target.
        """
        allEmitters = []
        return allEmitters
    
    def buildParGroupTargets(self):
        seenSequences = set()
        for par in self.page.parGroups:
            try:
                if par.sequence is not None:
                    sequenceName = par.sequence.name
                    if sequenceName in seenSequences:
                        continue
                    sequenceParGroups = [
                        pageParGroup
                        for pageParGroup in self.page.parGroups
                        if pageParGroup.sequence is not None and pageParGroup.sequence.name == sequenceName
                    ]
                    t = SequenceTarget(
                        self.id,
                        self.parentId,
                        self.ownerComp,
                        par,
                        self.instance,
                        sequenceParGroups=sequenceParGroups,
                    )
                    self.sequenceTargets[t.id] = t
                    self.sequenceTargetsByName[t.sequence.name] = t
                    seenSequences.add(sequenceName)
                    continue
                t = ParGroupTarget(self.id, self.parentId, self.ownerComp, par, self.instance)
                self.parGroupTargets[t.id] = t
                self.parGroupTargetsByName[par.name] = t
            except Exception as e:
                op.RS_LOG.Debug(f"Error building ParGroupTarget for {par.name}: {e}")

    def buildBulkSchemaEntries(self, sectionPrefix: str | None = None):
        entries = []
        seenPaths = set()
        currentSection = None

        for par in self.page.pars:
            parStyle = getattr(par, "style", None)
            if parStyle == "Header":
                currentSection = getattr(par, "label", None) or par.name
                continue

            parGroup = getattr(par, "parGroup", None)
            if parGroup is None:
                continue

            if getattr(parGroup, "sequence", None) is not None:
                path = parGroup.sequence.name
                target = self.sequenceTargetsByName.get(path, None)
                label = getattr(parGroup.sequence, "label", None) or path
                schemaNode = target.parShape.buildSchemaProperties() if target is not None else None
            else:
                path = parGroup.name
                target = self.parGroupTargetsByName.get(path, None)
                label = getattr(par, "label", None) or path
                if target is None:
                    schemaNode = None
                else:
                    schemaNode = {
                        "type": "object",
                        "properties": target.parShape.buildSchemaProperties(),
                    }

            if path in seenPaths or schemaNode is None:
                continue

            seenPaths.add(path)
            section = currentSection
            if sectionPrefix:
                section = f"{sectionPrefix} / {section}" if section else sectionPrefix

            entries.append(
                {
                    "path": path,
                    "label": label,
                    "section": section,
                    "schema": schemaNode,
                }
            )

        return entries


    def generateUtilPars(self):
        """
        Generates utility parameters for this page target.
        """
        if "COMP" not in self.ownerComp.OPType:
            op.RS_LOG.Debug(f"[OPTarget]: {self.ownerComp.path} [{self.ownerComp.OPType}] is not a COMP - skipping page util pars creation.")
            return
        
        page = self.ownerComp.customPages[RS_TARGET_INFO_PAGE]

        if not page:
            op.RS_LOG.Warning(f"[PageTarget]: Rship Target Config page not found in {self.ownerComp.path}")
            return
        

    
        page.appendPulse(self.bulkUpdatedName, label=f"{self.page.name} Page Updated")
        # Create utility parameters for the page
