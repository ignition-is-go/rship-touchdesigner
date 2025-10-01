from datetime import datetime, timezone
from uuid import uuid4
from page_target import PageTarget
from typing import Dict, List
from target import TouchTarget
from exec import Action, Target,Instance,Stream
from util import RS_BUNDLE_COMPLETE_PAR, RS_TARGET_ID_PAR, RS_TARGET_ID_STORAGE_KEY, RS_TARGET_INFO_PAGE



class OPTarget(TouchTarget):

    def __init__ (self, ownerComp, instance: Instance):
        super().__init__(instance)
        self.ownerComp = ownerComp
        self.pageTargets: Dict[str, PageTarget] = {}
        self.streamInfo: Stream | None = None
        self.streamSource: str | None = None


        op.RS_LOG.Debug("[OPTarget]: Initializing OPTarget at " + ownerComp.path)
        self.ensureUtilPars()
        self.buildPageTargets()
        self.organizePars()
        self.buildStream()


    @property
    def id(self):
        id =  self.ownerComp.storage.get(RS_TARGET_ID_STORAGE_KEY, None)
        if id is None:
            op.RS_LOG.Debug("[OPTarget]: No target ID found, generating a new one...")
            id = str(uuid4())
            self.ownerComp.storage[RS_TARGET_ID_STORAGE_KEY] = id

        return id
    
    def regenerateId(self):
        op.RS_LOG.Debug("[OPTarget]: Regenerating target ID...")
        newId = str(uuid4())
        self.ownerComp.storage[RS_TARGET_ID_STORAGE_KEY] = newId
        self.pageTargets = {}
        self.buildPageTargets()
        self.buildStream()
        return newId
    

    def ensureUtilPars(self):

        op.RS_LOG.Debug("[OPTarget]: OpType is " + self.ownerComp.OPType)

        if "COMP" not in self.ownerComp.OPType:
            op.RS_LOG.Debug(f"[OPTarget]: {self.ownerComp.path} [{self.ownerComp.OPType}] is not a COMP - skipping util pars creation.")
            return

        if RS_TARGET_INFO_PAGE not in self.ownerComp.customPages:
            self.ownerComp.appendCustomPage(RS_TARGET_INFO_PAGE)

        page = self.ownerComp.customPages[RS_TARGET_INFO_PAGE]

        if RS_TARGET_ID_PAR not in page.pars:
            page.appendStr(RS_TARGET_ID_PAR, label="Target ID")

        if RS_BUNDLE_COMPLETE_PAR not in page.pars:
            page.appendPulse(RS_BUNDLE_COMPLETE_PAR, label="All Op Pars Updated")

        bundleCompletePar = self.ownerComp.par[RS_BUNDLE_COMPLETE_PAR]

        bundleCompletePar.startSection = True

        targetIdPar = self.ownerComp.par[RS_TARGET_ID_PAR]
        targetIdPar.startSection = True
        targetIdPar.readOnly = True
        targetIdPar.expr = f"me.storage['{RS_TARGET_ID_STORAGE_KEY}'] if '{RS_TARGET_ID_STORAGE_KEY}' in me.storage else ''"

    def organizePars(self):

        if "COMP" not in self.ownerComp.OPType:
            return

        page = self.ownerComp.customPages[RS_TARGET_INFO_PAGE]

        configParNames = [RS_TARGET_ID_PAR, RS_BUNDLE_COMPLETE_PAR, *[p.bulkUpdatedName for p in self.pageTargets.values() if p.page.name != RS_TARGET_INFO_PAGE]]

        for par in page.pars:
            if par.name not in configParNames:
                par.destroy()

        page.sort(*configParNames)

        if len(page.pars) > 2:
            page.pars[1].startSection = True
            page.pars[2].startSection = True

    def buildStream(self):

        if "rship_stream" not in self.ownerComp.tags:
            op.RS_LOG.Debug(f"[OPTarget]: {self.ownerComp.path} is not a rship_stream - skipping stream creation.")
            return

        op.RS_LOG.Debug("[OPTarget]: Building stream for target", self.id, self.ownerComp.opType)

        if "TOP" in self.ownerComp.opType:
            self.streamSource = self.ownerComp.path
        elif "COMP" in self.ownerComp.opType:
            self.streamSource = self.ownerComp.par.opviewer.eval()
    

        op.RS_LOG.Debug("[OPTarget]: Stream Source", self.streamSource)
        self.streamInfo = Stream(
            id=f"{self.id}-{self.instance.id.replace(':', '-').replace(' ', '_')}-stream",
            name=self.ownerComp.name,
        )
        op.RS_LOG.Debug("[OPTarget]: Stream Info", self.streamInfo.id)
        

        


    def buildPageTargets(self):
        """
        Builds the target page for this OPTarget.
        This is used to display the target information in the UI.
        """

        for page in self.ownerComp.customPages:
            if page.name == RS_TARGET_INFO_PAGE:
                continue
            
            t = PageTarget(self.id, self.ownerComp, page, self.instance)
            self.pageTargets[t.id] = t

        
        if "Notch" in self.ownerComp.pages:
            notchPage = self.ownerComp.pages["Notch"]
            t = PageTarget(self.id, self.ownerComp, notchPage, self.instance)
            self.pageTargets[t.id] = t

    def getActions(self):

        def bulk_set_action_handler(action: Action, data: Dict[str, any]):
            op.RS_LOG.Debug(f"[OPTarget]: Handling bulk set action for {self.id}")
            op.RS_LOG.Debug("Data received:", data)

            for page in self.pageTargets.values():
                for par in page.parGroupTargets.values():
                    if par.parShape is None:
                        continue

                    if par.parGroup.name in data:
                        value = data.get(par.parGroup.name, None)
                        if value is None:
                            op.RS_LOG.Debug(f"Skipping {par.parGroup.name} on {page.name} as no value provided")
                            continue
                        par.parShape.setData(value)
                    op.RS_LOG.Debug(f"Setting {par.parGroup.name} to {value} on {page.page.name}")
            opCompletePulse = self.ownerComp.par[RS_BUNDLE_COMPLETE_PAR]
            if not opCompletePulse.isPulse:
                op.RS_LOG.Debug(f"[OPTarget]: {RS_BUNDLE_COMPLETE_PAR} is not a pulse parameter, cannot pulse.")
                return
            opCompletePulse.pulse()
            pass


        properties = {}

        for page in self.pageTargets.values():
            for par in page.parGroupTargets.values():

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
    

    def getEmitters(self):
        allEmitters = []
        return allEmitters

    def getTarget(self):
        return Target(
            id=self.id,
            category=self.ownerComp.OPType,
            name=self.ownerComp.name,
            parentTargets=[],
            rootLevel=True,
            serviceId=self.instance.serviceId,
            fgColor="#ffffff",
            bgColor="#000000",
            lastUpdated=datetime.now(timezone.utc).isoformat(),
        )
    
    def getStreamInfo(self):
        return self.streamInfo
    
    def collectChildren(self) -> List[TouchTarget]:
        children = [self]
        for t in self.pageTargets.values():
            children.extend(t.collectChildren())
        return children


