from datetime import datetime, timezone
from par_group_target import ParGroupTarget
from exec import Target, TargetStatus, Action, Emitter, Instance
from typing import Dict, List
from target import TouchTarget

class PageTarget(TouchTarget):

    def __init__(self, parentId: str, ownerComp: OP, page: Page, instance: Instance):
        super().__init__(instance)
        self.ownerComp = ownerComp
        self.page = page
        self.parentId = parentId
        self.parGroupTargets: Dict[str, ParGroupTarget] = {}

        # print(f"[PageTarget]: Initializing PageTarget for {self.page.name} at {self.ownerComp.path}")

        self.buildParGroupTargets()
    
    @property
    def id(self) -> str:
        return f"{self.parentId}:{self.page.name}"

    def getTarget(self) -> Target:
        return  Target(
            id=self.id,
            name=self.page.name,
            parentTargets=[self.parentId],
            category="Page",
            rootLevel=False,
            serviceId=self.instance.serviceId,
            fgColor="#ffffff",
            bgColor="#000000",
            lastUpdated=datetime.now(timezone.utc).isoformat(),
        )

    def collectChildren(self):
        children = [self]
        for t in self.parGroupTargets.values():
            children.extend(t.collectChildren())
        return children

    def getActions(self) -> List[Action]:
        """
        Returns a list of actions that can be performed on this target.
        """
        allActions = [action for parGroup in self.parGroupTargets.values() for action in parGroup.getActions()]
        return allActions

    def getEmitters(self) -> List[Emitter]:
        """
        Returns a list of emitters that can be used with this target.
        """
        allEmitters = [emitter for parGroup in self.parGroupTargets.values() for emitter in parGroup.getEmitters()]
        return allEmitters
    

    def buildParGroupTargets(self):
        for par in self.page.parGroups:
            t = ParGroupTarget(self.id, self.parentId, self.ownerComp, par, self.instance)
            self.parGroupTargets[t.id] = t


    