from datetime import datetime, timezone
from uuid import uuid4
from page_target import PageTarget
from typing import Dict, List, Optional
from target import TouchTarget
from exec import Target,Instance
from util import makeServiceId

RS_TARGET_INFO_PAGE = "Rship Target Config"
RS_BUNDLE_COMPLETE_PAR = "Rsbundlecomplete"
RS_TARGET_ID_PAR = "Rstargetid"
RS_TARGET_ID_STORAGE_KEY = 'rs_target_id'

class OPTarget(TouchTarget):

    def __init__ (self, ownerComp, instance: Instance):
        super().__init__(instance)
        self.ownerComp = ownerComp
        self.pageTargets: Dict[str, PageTarget] = {}


        # print("[OPTarget]: Initializing OPTarget at " + ownerComp.path)
        self.ensureUtilPars()
        self.buildPageTargets()

    @property
    def id(self):
        id =  self.ownerComp.storage.get(RS_TARGET_ID_STORAGE_KEY, None)
        if id is None:
            print("[OPTarget]: No target ID found, generating a new one...")
            id = str(uuid4())
            self.ownerComp.storage[RS_TARGET_ID_STORAGE_KEY] = id

        return id
    
    def regenerateId(self):
        print("[OPTarget]: Regenerating target ID...")
        newId = str(uuid4())
        self.ownerComp.storage[RS_TARGET_ID_STORAGE_KEY] = newId
        return newId
    

    def ensureUtilPars(self):

        # print("[OPTarget]: OpType is " + self.ownerComp.OPType)

        if "COMP" not in self.ownerComp.OPType:
            print(f"[OPTarget]: {self.ownerComp.path} [{self.ownerComp.OPType}] is not a COMP - skipping util pars creation.")
            return

        if RS_TARGET_INFO_PAGE not in self.ownerComp.customPages:
            self.ownerComp.appendCustomPage(RS_TARGET_INFO_PAGE)

        page = self.ownerComp.customPages[RS_TARGET_INFO_PAGE]

        if RS_BUNDLE_COMPLETE_PAR not in page.pars:
            page.appendPulse(RS_BUNDLE_COMPLETE_PAR, label="Bundle Complete")


        if RS_TARGET_ID_PAR not in page.pars:
            page.appendStr(RS_TARGET_ID_PAR, label="Target ID")

        # bundleCompletePar = self.ownerComp.par[RS_BUNDLE_COMPLETE_PAR]
        # bundleCompletePar.readOnly = False

        targetIdPar = self.ownerComp.par[RS_TARGET_ID_PAR]
        targetIdPar.startSection = True
        targetIdPar.readOnly = True
        targetIdPar.expr = f"me.storage['{RS_TARGET_ID_STORAGE_KEY}'] if '{RS_TARGET_ID_STORAGE_KEY}' in me.storage else ''"

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
        allActions = [actions for target in self.pageTargets.values() for actions in target.getActions()]
        return allActions
    

    def getEmitters(self):
        allEmitters = [emitters for target in self.pageTargets.values() for emitters in target.getEmitters()]
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
    
    def collectChildren(self) -> List[TouchTarget]:
        children = [self]
        for t in self.pageTargets.values():
            children.extend(t.collectChildren())
        return children


