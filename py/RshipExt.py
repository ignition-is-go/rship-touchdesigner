"""
Extension classes enhance TouchDesigner components with python. An
extension is accessed via ext.ExtensionClassName from any operator
within the extended component. If the extension is promoted via its
Promote Extension parameter, all its attributes with capitalized names
can be accessed externally, e.g. op('yourComp').PromotedFunction().

Help: search "Extensions" in wiki
"""
from typing import Dict
import TDFunctions as TDF
import socket
from exec import CLIENT, ExecClient, GetTargetsByServiceId, Instance, Machine, InstanceStatus, Status, Action, Emitter
from handle_webrtc import init as initWebRTC, handle_on_answer, handle_on_ice_candidate
from myko import QueryResponse
from op_target import OPTarget
import json

from target import TouchTarget
from util import makeEmitterChangeKey, makeServiceId

# region ExecInfo

class ExecInfo:
	connected: bool
	rshipUrl: str | None
	machineId: str
	

	def __init__(self, machineId: str, connected: bool, rshipUrl: str | None):
		self.machineId = machineId
		self.connected = connected
		self.rshipUrl = rshipUrl

# endregion ExecInfo

# region RshipExt

class RshipExt:

	def __init__(self, ownerComp):
		print("[RshipExt]: Initializing RshipExt...")
		self.ownerComp = ownerComp
		self.findTargetsOp = self.ownerComp.op('find_targets')
		

		self.websocketOp = self.ownerComp.op('websocket')
		self.execInfoOp = self.ownerComp.op('exec_info')

		self.targetsOp = self.ownerComp.op('path_and_pars')
		
		CLIENT.setSend(self.websocketOp.sendText)

		self.OnProjectPreSave()

		TDF.createProperty(self, 'MachineId', value=None, dependable=True,
						   readOnly=False)

		TDF.createProperty(self, "wsConnected", value=False, dependable=True, readOnly=False)
		
		self.execInfoRequests = {}

		self.opTargets: Dict[str, OPTarget] = {}
		self.allTouchTargets: Dict[str, TouchTarget] = {}

		self.instance: Instance | None = None

		self.emitterIndex: Dict[str, Emitter] = {}
		self.emitterHandlers: Dict[str, callable] = {}


	@property
	def ConnectionStatus(self):
		return "Connected" if self.wsConnected else "Disconnected"


	def OnProjectPreSave(self):
		self.cookTargetList()
		self.updateExecInfo()


# region exec info 
	def updateExecInfo(self):
		print("[RshipExt]: Updating Exec Info from Rship Link...")
		self.execInfoOp.par.request.pulse()

	def OnExecInfoClientConnect(self, requestId: str):
		print("[RshipExt]: Exec Info Client connected with request ID:", requestId)
		self.execInfoRequests[requestId] = True

	def OnExecInfoClientDisconnect(self, requestId: str):
		if requestId in self.execInfoRequests:
			del self.execInfoRequests[requestId]
			print("[RshipExt]: Failed to get Exec Info from Rship Link")
			self.handleLinkMachineId(None)
			self.handleLinkRshipUrl(None)

			print("[RshipExt]: Refreshing project data")
			self.refreshProjectData()

	def OnExecInfoUpdate(self, data: ExecInfo, requestId: str):
		if requestId in self.execInfoRequests:
			del self.execInfoRequests[requestId]

		print("[RshipExt]: Exec Info received:", data)

		data = json.loads(data)

		machineId = data.get('machineId', None)
		connection = data.get('connectionStatus', None)
		rshipUrl = connection.get('data', None) if connection else None

		self.handleLinkRshipUrl(rshipUrl)
		self.handleLinkMachineId(machineId)
		self.refreshProjectData()

# endregion exec info

# region WebSocket Callbacks

	def targetListUpdated(self, data: QueryResponse):

		allKeys = set(self.allTouchTargets.keys())
		remoteKeys = set([target.item['id'] for target in data.upserts])

		# Find targets that are in the local list but not in the remote list
		missingKeys = remoteKeys - allKeys

		for key in missingKeys:
			if key == "dbc230dc-aa08-47ff-a0a3-3a429f9ef081:A":
				print("SENDING SUBJECT OFFLINE")	
			print(f"[RshipExt]: Target {key} is missing from local list, setting offline")			
			CLIENT.setTargetOffline(key, self.instance.id)

		# for target in data.upserts:
			# if target.item['id'] not in self.allTouchTargets:
				# print(f"[RshipExt]: Remote target not found: {target.item['id']}")
				# CLIENT.setTargetOffline(target.item['id'], self.instance.id)


	def OnRshipConnect(self):
		self.wsConnected = True
		print("[RshipExt]: Connected to Rship Server at ", self.websocketOp.par.netaddress.eval())
		initWebRTC(self.client)
		self.refreshProjectData()
		CLIENT.sendQuery(GetTargetsByServiceId(makeServiceId()), "Target", self.targetListUpdated)


	def OnRshipDisconnect(self):
		self.wsConnected = False
		print("[RshipExt]: Disconnected from Rship Server")


	def OnRshipReceivePing(self):
		if self.wsConnected is False:
			self.wsConnected = True
			self.refreshProjectData()
			return
		pass

	def OnRshipReceiveText(self, text: str):
		
		CLIENT.parseMessage(text)

# endregion

# region exec info handlers

	def handleLinkMachineId(self, machineId: str | None):
		print("MACHINE", machineId)
		if machineId is None or machineId == "":
			hostname = socket.gethostname()
			print("[RshipExt]: Machine Id not provided, using fallback", hostname)
			self.MachineId = hostname  # Fallback to hostname if not set
			return
		
		self.MachineId = machineId

	def handleLinkRshipUrl(self, rship_host: str | None):

		port = 5155

		if rship_host is not None:

			sections = rship_host.split("://")

			protocol = sections[0]
			path = sections[1]

			path_sections = path.split(":")

			path = path_sections[0]

			after_colon = path_sections[1] if len(path_sections) > 1 else port

			after_colon_sections = after_colon.split("/")

			port = after_colon_sections[0] if after_colon_sections else port

			rship_host = f"{protocol}://{path}"


		port = int(port)

		if self.ownerComp.par.Port.eval() == port and self.ownerComp.par.Address.eval() == rship_host and self.wsConnected:
			print("[RshipExt]: Rship already connected to", rship_host, "on port", port)
			return

		self.ownerComp.par.Port = port
		self.ownerComp.par.Address = rship_host
		print("[RshipExt]: Setting Rship host to", rship_host, "on port", port)


		# since machineId is coming from the Rship Link, we need not send the machine info

	def refreshProjectData(self):
		self.updateLocalInstance()
		self.buildTargets()

		if self.wsConnected:
			self.sendProjectData()
		else:
			print("[RshipExt]: Not connected to Rship Server, cannot send project data")

# endregion


# region Project Management


	def cookTargetList(self):
		print("[RshipExt]: Finding OpTargets...")
		self.findTargetsOp.cook(force=True)
		

	def buildTargets(self):

		print("[RshipExt]: Building targets...")

		ops = [op(self.targetsOp[i, 0].val) for i in range(0, self.targetsOp.numRows)]

		print("[RshipExt]: Found", len(ops), "ops")

		foundOps: Dict[str, OPTarget] = {}

		for o in ops:
			opTarget = OPTarget(o, self.instance)

			if opTarget.id in foundOps:
				print(f"[RshipExt]: Target with ID {opTarget.id} already exists")
				opTarget.regenerateId()

			foundOps[opTarget.id] = opTarget

		self.opTargets = foundOps

		allTouchTargets = [child for target in self.opTargets.values() for child in target.collectChildren()]

		self.allTouchTargets = {target.id: target for target in allTouchTargets}
		print(f"[RshipExt]: Found {len(allTouchTargets)} TouchTargets in total")
		# print("all TouchTargets", self.allTouchTargets.keys())

	def updateLocalInstance(self): 

		serviceId = makeServiceId()

		print(f"[RshipExt]: Updating local instance with service ID: {serviceId}")
		print("machineId", self.MachineId)


		instance = Instance(
			id=self.MachineId+":"+serviceId, 
			name=serviceId, 
			serviceId=serviceId, 
			serviceTypeCode="touchdesigner", 
			status=InstanceStatus.Available, 
			machineId=self.MachineId, 
			color="#727e51"
		)

		self.instance = instance
		print(f"[RshipExt]: Local Instance updated:\n  ID: {instance.id},\n  Name: {instance.name}")


# endregion

# ws senders

	def sendProjectData(self):
		if self.instance is None:
			print("[RshipExt]: Instance is not set, cannot send project data")
			return
		
		# if self.wsConnected is False:
		# 	print("[RshipExt]: Not connected to Rship Server, cannot send project data")
		# 	return

		CLIENT.set(self.instance)


		allTouchTargets = [child for target in self.opTargets.values() for child in target.collectChildren()]

		allTargets = [target.getTarget() for target in allTouchTargets]
		allActions = [action for target in allTouchTargets for action in target.getActions()]
		allEmitters = [emitter for target in allTouchTargets for emitter in target.getEmitters()]


		for target in allTargets:
			# print(f"[RshipExt]: Sending target {target.id} to server")
			CLIENT.saveTarget(target)
			# print(f"[RshipExt]: Target {target.id} sent to server")
			if target.id == "dbc230dc-aa08-47ff-a0a3-3a429f9ef081:A":
				print("SENDING SUBJECT ONLINE")
			CLIENT.setTargetStatus(target.id, self.instance.id, Status.Online)
		
		for action in allActions:
			CLIENT.saveHandler(action.id, action.handler)
			
			del action.handler  # Remove handler from action to avoid circular references
			CLIENT.saveAction(action)

		for emitter in allEmitters:
			self.emitterIndex[emitter.changeKey] = emitter
			self.emitterHandlers[emitter.changeKey] = emitter.handler
			
			del emitter.handler  # Remove handler from emitter to avoid circular references
			del emitter.changeKey
			CLIENT.saveEmitter(emitter)
	

		

	def PulseEmitter(self, opPath: str, parName: str):
		changeKey = makeEmitterChangeKey(opPath, parName)

		emitter = self.emitterIndex.get(changeKey, None)
		if emitter is None:
			print(f"[RshipExt]: No emitter found for change key {changeKey}")
			return
		

		handler = self.emitterHandlers.get(changeKey, None)



		if handler is None:
			print(f"[RshipExt]: No handler found for emitter {changeKey}")
			return
		

		data = handler()

		if data is None:
			print(f"[RshipExt]: No data returned from emitter handler for {changeKey}")
			return
		
		CLIENT.pulseEmitter(emitter.id, data)

		# pulseEmitter(opPath, parName, self.client)

# region WebRTC Handlers

	def HandleWebRTCAnswer(self, connectionId: str, localSdp: str):
		handle_on_answer(connectionId, localSdp, self.client)


	def HandleWebRTCIceCandidate(self, connectionId: str, candidate: str, sdpMid: str, lineIndex: int):
		handle_on_ice_candidate(connectionId, candidate, sdpMid, lineIndex, self.client)

# endregion WebRTC Handlers

# endregion RshipExt