from datetime import datetime, timezone
from par_group_target import ParGroupTarget
from exec import Target, TargetStatus, Action, Emitter, Instance
from typing import Dict, List
from target import TouchTarget
from util import RS_TARGET_INFO_PAGE

class PageTarget(TouchTarget):

    def __init__(self, parentId: str, ownerComp: OP, page: Page, instance: Instance):
        super().__init__(instance)
        self.ownerComp = ownerComp
        self.page = page
        self.parentId = parentId
        self.parGroupTargets: Dict[str, ParGroupTarget] = {}

        # print(f"[PageTarget]: Initializing PageTarget for {self.page.name} at {self.ownerComp.path}")

        self.buildParGroupTargets()
        self.safeName = f"Rship{self.page.name.replace(' ', '').lower()}updated"
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

        def bulk_set_action_handler(action: Action, data: Dict[str, any]):
            # print(f"[OPTarget]: Handling bulk set action for {self.id}")
            # print("Data received:", data)

            for par in self.parGroupTargets.values():
                if par.parShape is None:
                    continue

                if par.parGroup.name in data:
                    value = data.get(par.parGroup.name, None)
                    if value is None:
                        print(f"Skipping {par.parGroup.name} on {self.page.name} as no value provided")
                        continue
                    par.parShape.setData(value)
                # print(f"Setting {par.parGroup.name} to {value} on {self.page.name}")
            opCompletePulse = self.ownerComp.par[self.safeName]
            if not opCompletePulse.isPulse:
                print(f"[PageTarget]: {self.safeName} is not a pulse parameter, cannot pulse.")
                return
            opCompletePulse.pulse()
            pass


        properties = {}

        for par in self.parGroupTargets.values():

            properties[par.parGroup.name] = {
                "type": "object",
                "properties": par.parShape.buildSchemaProperties(),
            }


        schema = {
            "type": "object",
            "properties": properties,
        }


        bulk_set_action = Action(
            id=f"{self.id}:bulk_set",
            name="Bulk Set",
            handler=bulk_set_action_handler,
            targetId=self.id,
            schema=schema,
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
        for par in self.page.parGroups:
            t = ParGroupTarget(self.id, self.parentId, self.ownerComp, par, self.instance)
            self.parGroupTargets[t.id] = t


    def generateUtilPars(self):
        """
        Generates utility parameters for this page target.
        """
        if "COMP" not in self.ownerComp.OPType:
            # print(f"[OPTarget]: {self.ownerComp.path} [{self.ownerComp.OPType}] is not a COMP - skipping page util pars creation.")
            return
        
        page = self.ownerComp.customPages[RS_TARGET_INFO_PAGE]

        if not page:
            print(f"[PageTarget]: Rship Target Config page not found in {self.ownerComp.path}")
            return
        

    
        page.appendPulse(self.safeName, label=f"{self.page.name} Page Updated")
        # Create utility parameters for the page
        
    