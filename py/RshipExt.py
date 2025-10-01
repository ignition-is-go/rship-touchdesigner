"""
Extension classes enhance TouchDesigner components with python. An
extension is accessed via ext.ExtensionClassName from any operator
within the extended component. If the extension is promoted via its
Promote Extension parameter, all its attributes with capitalized names
can be accessed externally, e.g. op('yourComp').PromotedFunction().

Help: search "Extensions" in wiki
"""
import datetime
from typing import Dict, Set, Callable

import TDFunctions as TDF
import socket
from exec import CLIENT, ExecClient, GetTargetsByServiceId, Instance, Machine, InstanceStatus, Status, Action, Emitter
from myko import QueryResponse
from op_target import OPTarget
import json

from target import TouchTarget
from util import makeEmitterChangeKey

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
		self.ownerComp = ownerComp
		self.findTargetsOp = self.ownerComp.op('find_targets')
		

		self.websocketOp = self.ownerComp.op('websocket')
		self.execInfoOp = self.ownerComp.op('exec_info')

		self.targetsOp = self.ownerComp.op('path_and_pars')

		self.streamSourcesOp = self.ownerComp.op('stream_sources')
		
		CLIENT.setSend(self.websocketOp.sendText)

		# self.OnProjectPreSave()

		TDF.createProperty(self, 'MachineId', value=None, dependable=True,
						   readOnly=False)

		TDF.createProperty(self, "wsConnected", value=False, dependable=True, readOnly=False)
		
		self.execInfoRequests = {}

		self.opTargets: Dict[str, OPTarget] = {}
		self.allTouchTargets: Dict[str, TouchTarget] = {}

		self.instance: Instance | None = None

		self.emitterIndex: Dict[str, Emitter] = {}
		self.emitterHandlers: Dict[str, Callable] = {}

		self.reconnectTimerOp = self.ownerComp.op('reconnect_timer')

		self.reconnectTimerOp.par.start.pulse()

		self.remoteKeys: Set[str] = set()

	
	def postInit(self):
		self.websocketOp.par.reset.pulse()


	@property
	def ConnectionStatus(self):
		return "Connected" if self.wsConnected else "Disconnected"


	def OnProjectPreSave(self):
		self.cookTargetList()
		self.updateExecInfo()
		self.refreshProjectData()


# region exec info 
	def updateExecInfo(self):
		op.RS_LOG.Debug("[RshipExt]: Updating Exec Info from Rship Link...")
		self.execInfoOp.par.request.pulse()

	def OnExecInfoClientConnect(self, requestId: str):
		op.RS_LOG.Debug("[RshipExt]: Exec Info Client connected with request ID:", requestId)
		self.execInfoRequests[requestId] = True

	def OnExecInfoClientDisconnect(self, requestId: str):
		if requestId in self.execInfoRequests:
			del self.execInfoRequests[requestId]
			op.RS_LOG.Warning("[RshipExt]: Failed to get Exec Info from Rship Link")
			self.handleLinkMachineId(None)
			self.handleLinkRshipUrl(None)

			op.RS_LOG.Debug("[RshipExt]: Refreshing project data")
			self.refreshProjectData()

	def OnExecInfoUpdate(self, data: ExecInfo, requestId: str):
		if requestId in self.execInfoRequests:
			del self.execInfoRequests[requestId]

		op.RS_LOG.Debug("[RshipExt]: Exec Info received:", data)

		try:
			data = json.loads(data)

			machineId = data.get('machineId', None)
			connection = data.get('connectionStatus', None)
			rshipUrl = connection.get('data', None) if connection else None

			changed = self.handleLinkRshipUrl(rshipUrl)
			changed |= self.handleLinkMachineId(machineId)
			if changed:
				self.refreshProjectData()
		except Exception as e:
			op.RS_LOG.Warning("[RshipExt]: Error occurred while processing Exec Info:", e)
			self.handleLinkMachineId(None)
			self.handleLinkRshipUrl(None)


# endregion exec info

# region WebSocket Callbacks

	def targetListUpdated(self, data: QueryResponse):

		

		remoteKeys = set([target.item['id'] for target in data.upserts])

		for key in remoteKeys:
			self.remoteKeys.add(key)


		for key in data.deletes:
			self.remoteKeys.discard(key)


		self.setMissingOffline()

		# Find targets that are in the local list but not in the remote list

		# for target in data.upserts:
			# if target.item['id'] not in self.allTouchTargets:
				# op.RS_LOG.Info(f"[RshipExt]: Remote target not found: {target.item['id']}")
				# CLIENT.setTargetOffline(target.item['id'], self.instance.id)
	
	def setMissingOffline(self):
		allKeys = set(self.allTouchTargets.keys())
		missingKeys = self.remoteKeys - allKeys

		for key in missingKeys:
			op.RS_LOG.Debug(f"[RshipExt]: Target {key} is missing from local list, setting offline")			
			CLIENT.setTargetOffline(key, self.instance.id)


	def OnRshipConnect(self):
		self.wsConnected = True
		op.RS_LOG.Info("[RshipExt]: Connected to Rship Server at ", self.websocketOp.par.netaddress.eval())
		self.refreshProjectData(sendEmitterValues=True)
		CLIENT.sendQuery(GetTargetsByServiceId(self.makeServiceId()), "Target", self.targetListUpdated)


	def OnRshipDisconnect(self):
		self.wsConnected = False
		op.RS_LOG.Warning("[RshipExt]: Disconnected from Rship Server")


	def OnRshipReceivePing(self):
		self.ownerComp.par.Lastping = datetime.datetime.now()
		
		if self.wsConnected is False:
			self.wsConnected = True
			self.refreshProjectData()

			return
		
		pass

	def OnRshipReceiveText(self, text: str):
		CLIENT.parseMessage(text)


	def OnTickInterval(self):
		self.updateExecInfo()		


# endregion

# region exec info handlers

	def handleLinkMachineId(self, machineId: str | None) -> bool:
		if machineId is None or machineId == "":
			hostname = socket.gethostname()
			op.RS_LOG.Warning("[RshipExt]: Machine Id not provided, using fallback", hostname)
			self.MachineId = hostname  # Fallback to hostname if not set
			return
		

		changed = self.MachineId != machineId
		self.MachineId = machineId
		return changed

	def handleLinkRshipUrl(self, rship_host: str | None) -> bool:

		port = 5155

		#TODO: handle empty string here
		if rship_host is not None and rship_host != "":

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
		changed = self.ownerComp.par.Port.eval() != port or self.ownerComp.par.Address.eval() != rship_host

		if not changed and self.wsConnected:
			# op.RS_LOG.Info("[RshipExt]: Rship already connected to", rship_host, "on port", port)
			return False


		self.ownerComp.par.Port = port
		self.ownerComp.par.Address = rship_host
		op.RS_LOG.Debug("[RshipExt]: Setting Rship host to", rship_host, "on port", port)

		return True
		# since machineId is coming from the Rship Link, we need not send the machine info

	def refreshProjectData(self, sendEmitterValues=False):

		if self.MachineId is None:
			op.RS_LOG.Error("[RshipExt]: MachineId is not set, cannot refresh project data")
			return

		self.updateLocalInstance()
		self.buildTargets()

		if self.wsConnected:
			self.sendProjectData(sendEmitterValues=sendEmitterValues)
		else:
			op.RS_LOG.Warning("[RshipExt]: Not connected to Rship Server, Attempting to reconnect")
			self.ownerComp.par.Reconnect.pulse()

# endregion


# region Project Management


	def cookTargetList(self):
		# op.RS_LOG.Info("[RshipExt]: Finding OpTargets...")
		self.findTargetsOp.cook(force=True)
		

	def buildTargets(self):

		# op.RS_LOG.Info("[RshipExt]: Building targets...")

		ops = [op(self.targetsOp[i, 0].val) for i in range(0, self.targetsOp.numRows)]

		# op.RS_LOG.Info("[RshipExt]: Found", len(ops), "ops")

		foundOps: Dict[str, OPTarget] = {}

		for o in ops:
			opTarget = OPTarget(o, self.instance)

			if opTarget.id in foundOps:
				op.RS_LOG.Warning(f"[RshipExt]: Target with ID {opTarget.id} already exists")
				opTarget.regenerateId()

			foundOps[opTarget.id] = opTarget

		self.opTargets = foundOps

		self.streamSourcesOp.clear()
		for opTarget in self.opTargets.values():
			if opTarget.getStreamInfo() is not None and opTarget.streamSource is not None:
				self.streamSourcesOp.appendRow([opTarget.getStreamInfo().id, opTarget.streamSource])

		allTouchTargets = [child for target in self.opTargets.values() for child in target.collectChildren()]

		self.allTouchTargets = {target.id: target for target in allTouchTargets}
		# op.RS_LOG.Info(f"[RshipExt]: Found {len(allTouchTargets)} TouchTargets in total")
		# op.RS_LOG.Info("all TouchTargets", self.allTouchTargets.keys())

	def updateLocalInstance(self): 

		serviceId = self.makeServiceId()

		op.RS_LOG.Debug(f"[RshipExt]: Updating local instance with service ID: {serviceId}")
		op.RS_LOG.Debug("machineId", self.MachineId)

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
		# op.RS_LOG.Info(f"[RshipExt]: Local Instance updated:\n  ID: {instance.id},\n  Name: {instance.name}")


# endregion

# ws senders

	def sendProjectData(self, sendEmitterValues = False):
		if self.instance is None:
			op.RS_LOG.Error("[RshipExt]: Instance is not set, cannot send project data")
			return
		
		# if self.wsConnected is False:
		# 	op.RS_LOG.Info("[RshipExt]: Not connected to Rship Server, cannot send project data")
		# 	return

		CLIENT.set(self.instance)


		# self.streamSourcesOp.clear()
		# for opTarget in self.opTargets.values():
		# 	self.assertStream()
			# assertStream(opTarget.id, self.instance.id, opTarget.ownerComp, CLIENT)

		for opTarget in self.opTargets.values():
			streamInfo = opTarget.getStreamInfo()
			if streamInfo is not None:
				CLIENT.set(streamInfo)

		allTouchTargets = [child for target in self.opTargets.values() for child in target.collectChildren()]


		allTargets = [target.getTarget() for target in allTouchTargets]
		allActions = [action for target in allTouchTargets for action in target.getActions()]
		allEmitters = [emitter for target in allTouchTargets for emitter in target.getEmitters()]

		self.allTouchTargets = {target.id: target for target in allTouchTargets}


		for target in allTargets:
			op.RS_LOG.Debug(f"[RshipExt]: Sending target {target.id} to server")
			CLIENT.saveTarget(target)
			# op.RS_LOG.Info(f"[RshipExt]: Target {target.id} sent to server")
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

		self.setMissingOffline()

		if not sendEmitterValues:
			return

		for key, handler in self.emitterHandlers.items():
			emitter = self.emitterIndex.get(key, None)
			if (emitter is not None) and (handler is not None):
				data = handler()
				CLIENT.pulseEmitter(emitter.id, data)


	def PulseEmitter(self, opPath: str, parName: str):
		changeKey = makeEmitterChangeKey(opPath, parName)

		emitter = self.emitterIndex.get(changeKey, None)
		if emitter is None:
			op.RS_LOG.Debug(f"[RshipExt]: No emitter found for change key {changeKey}")
			return
		

		handler = self.emitterHandlers.get(changeKey, None)



		if handler is None:
			op.RS_LOG.Debug(f"[RshipExt]: No handler found for emitter {changeKey}")
			return
		

		data = handler()

		if data is None:
			op.RS_LOG.Debug(f"[RshipExt]: No data returned from emitter handler for {changeKey}")
			return
		
		CLIENT.pulseEmitter(emitter.id, data)

	def makeServiceId(self):

		override = self.ownerComp.par.Serviceidoverride.eval()
		if(override is not None and override != ""):
			return override

		projectfile = project.name
		sections = projectfile.split(".")
		
		serviceId = sections[0]

		return serviceId

# endregion RshipExt