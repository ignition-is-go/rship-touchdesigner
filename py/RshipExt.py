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
from enum import Enum

import TDFunctions as TDF
import socket
from exec import CLIENT, ExecClient, GetActionsByQuery, GetEmittersByQuery, GetTargetsByQuery, Instance, Machine, InstanceStatus, Status, Action, Emitter
from myko import QueryResponse
from op_target import OPTarget
import json

from target import TouchTarget
from util import makeEmitterChangeKey

# region State Management

class RshipState(Enum):
	UNINITIALIZED = "uninitialized"  # No machine ID yet
	READY = "ready"  # Machine ID set, can operate
	DISCONNECTED = "disconnected"  # Configured locally, but websocket is not connected
	CONNECTED = "connected"  # WebSocket connected
	SYNCING = "syncing"  # Currently syncing data to server

# endregion State Management

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
	STATS_PAGE = 'Rship Sync Stats'
	LOCAL_TARGETS_PAR = 'Localtargets'
	LOCAL_ACTIONS_PAR = 'Localactions'
	LOCAL_EMITTERS_PAR = 'Localemitters'
	REMOTE_TARGETS_PAR = 'Remotetargets'
	REMOTE_ACTIONS_PAR = 'Remoteactions'
	REMOTE_EMITTERS_PAR = 'Remoteemitters'

	def __init__(self, ownerComp):
		self.ownerComp = ownerComp
		self.findTargetsOp = self.ownerComp.op('find_targets')
		
		self.websocketOp = self.ownerComp.op('websocket')
		self.execInfoOp = self.ownerComp.op('exec_info')

		self.targetsOp = self.ownerComp.op('path_and_pars')

		self.streamSourcesOp = self.ownerComp.op('stream_sources')
		
		CLIENT.setSend(self.websocketOp.sendText)

		TDF.createProperty(self, 'MachineId', value=None, dependable=True,
						   readOnly=False)

		TDF.createProperty(self, "wsConnected", value=False, dependable=True, readOnly=False)
		TDF.createProperty(self, "ConnectionStatus", value="uninitialized", dependable=True, readOnly=False)
		
		# State management
		self.state = RshipState.UNINITIALIZED
		self._machineId: str | None = None
		self._rshipUrl: str | None = None
		self._rshipPort: int = 5155
		
		self.execInfoRequests = {}

		self.opTargets: Dict[str, OPTarget] = {}
		self.allTouchTargets: Dict[str, TouchTarget] = {}

		self.instance: Instance | None = None

		self.emitterIndex: Dict[str, Emitter] = {}
		self.emitterHandlers: Dict[str, Callable] = {}

		self.reconnectTimerOp = self.ownerComp.op('reconnect_timer')

		self.reconnectTimerOp.par.start.pulse()

		self.remoteKeys: Set[str] = set()
		self.sentTargetStatuses: Dict[str, Status] = {}  # Track which statuses we've sent
		self.execInfoFailureLogged = False
		self.remoteStats = {
			'targets': 0,
			'actions': 0,
			'emitters': 0,
		}

		self.ensureStatsPars()
		self.updateStatsPage(localTargets=0, localActions=0, localEmitters=0)

	
	def postInit(self):
		CLIENT.setSend(self.websocketOp.sendText)
		self.websocketOp.par.reset.pulse()

	def ensureStatsPars(self):
		if self.STATS_PAGE not in self.ownerComp.customPages:
			self.ownerComp.appendCustomPage(self.STATS_PAGE)

		page = self.ownerComp.customPages[self.STATS_PAGE]
		parNames = [
			(self.LOCAL_TARGETS_PAR, 'Local Targets'),
			(self.LOCAL_ACTIONS_PAR, 'Local Actions'),
			(self.LOCAL_EMITTERS_PAR, 'Local Emitters'),
			(self.REMOTE_TARGETS_PAR, 'Remote Targets'),
			(self.REMOTE_ACTIONS_PAR, 'Remote Actions'),
			(self.REMOTE_EMITTERS_PAR, 'Remote Emitters'),
		]

		for parName, label in parNames:
			if parName not in page.pars:
				page.appendInt(parName, label=label)
			par = self.ownerComp.par[parName]
			par.readOnly = True

		page.sort(
			self.LOCAL_TARGETS_PAR,
			self.LOCAL_ACTIONS_PAR,
			self.LOCAL_EMITTERS_PAR,
			self.REMOTE_TARGETS_PAR,
			self.REMOTE_ACTIONS_PAR,
			self.REMOTE_EMITTERS_PAR,
		)
		self.ownerComp.par[self.REMOTE_TARGETS_PAR].startSection = True

	def updateStatsPage(
		self,
		localTargets: int | None = None,
		localActions: int | None = None,
		localEmitters: int | None = None,
		remoteTargets: int | None = None,
		remoteActions: int | None = None,
		remoteEmitters: int | None = None,
	):
		if localTargets is not None:
			self.ownerComp.par[self.LOCAL_TARGETS_PAR] = int(localTargets)
		if localActions is not None:
			self.ownerComp.par[self.LOCAL_ACTIONS_PAR] = int(localActions)
		if localEmitters is not None:
			self.ownerComp.par[self.LOCAL_EMITTERS_PAR] = int(localEmitters)
		if remoteTargets is not None:
			self.remoteStats['targets'] = int(remoteTargets)
			self.ownerComp.par[self.REMOTE_TARGETS_PAR] = int(remoteTargets)
		if remoteActions is not None:
			self.remoteStats['actions'] = int(remoteActions)
			self.ownerComp.par[self.REMOTE_ACTIONS_PAR] = int(remoteActions)
		if remoteEmitters is not None:
			self.remoteStats['emitters'] = int(remoteEmitters)
			self.ownerComp.par[self.REMOTE_EMITTERS_PAR] = int(remoteEmitters)

	def _transitionState(self, newState: RshipState):
		"""Transition to a new state with logging"""
		if self.state != newState:
			op.RS_LOG.Info(f"[RshipExt]: State transition: {self.state.value} -> {newState.value}")
			self.state = newState
			if newState == RshipState.READY:
				self.ConnectionStatus = RshipState.DISCONNECTED.value
			else:
				self.ConnectionStatus = newState.value

	def _ensureReady(self) -> bool:
		"""Ensure we have minimum requirements to operate. Returns True if ready."""
		if self._machineId is None:
			return False
		
		if self.state == RshipState.UNINITIALIZED:
			self._transitionState(RshipState.READY)
			self._createInstance()
		
		return True

	def _createInstance(self):
		"""Create the local instance object"""
		if self._machineId is None:
			return
		
		serviceId = self.makeServiceId()
		
		self.instance = Instance(
			id=self._machineId + ":" + serviceId,
			name=serviceId,
			serviceId=serviceId,
			serviceTypeCode="touchdesigner",
			status=InstanceStatus.Available,
			machineId=self._machineId,
			color="#727e51"
		)
		
		# Keep MachineId property in sync for backwards compatibility
		self.MachineId = self._machineId
		
		op.RS_LOG.Debug(f"[RshipExt]: Instance created: {self.instance.id}")

	def OnProjectPreSave(self):
		# Always rescan and update local cache
		self.cookTargetList()
		self.updateExecInfo()
		
		# Only send to server if we're ready
		if self._ensureReady():
			self.refreshProjectData()


# region exec info 
	def updateExecInfo(self):
		#op.RS_LOG.Debug("[RshipExt]: Updating Exec Info from Rship Link...")
		self.execInfoOp.par.request.pulse()

	def OnExecInfoClientConnect(self, requestId: str):
		# op.RS_LOG.Debug("[RshipExt]: Exec Info Client connected with request ID:", requestId)
		self.execInfoRequests[requestId] = True

	def OnExecInfoClientDisconnect(self, requestId: str):
		if requestId in self.execInfoRequests:
			del self.execInfoRequests[requestId]
			if not self.execInfoFailureLogged:
				op.RS_LOG.Warning("[RshipExt]: Failed to get Exec Info from Rship Link")
				self.execInfoFailureLogged = True
			else:
				op.RS_LOG.Debug("[RshipExt]: Exec Info unavailable, continuing with local configuration")
			configChanged = self._updateConfiguration(None, None)

			if configChanged and self._ensureReady():
				op.RS_LOG.Debug("[RshipExt]: Refreshing project data")
				self.refreshProjectData()

	def OnExecInfoUpdate(self, data: ExecInfo, requestId: str):
		if requestId in self.execInfoRequests:
			del self.execInfoRequests[requestId]

		try:
			data = json.loads(data)
			self.execInfoFailureLogged = False

			machineId = data.get('machineId', None)
			connection = data.get('connectionStatus', None)
			rshipUrl = connection.get('data', None) if connection else None

			# Update configuration
			configChanged = self._updateConfiguration(machineId, rshipUrl)
			
			if configChanged and self._ensureReady():
				self.refreshProjectData()
				
		except Exception as e:
			op.RS_LOG.Warning("[RshipExt]: Error occurred while processing Exec Info:", e)
			self._updateConfiguration(None, None)

# endregion exec info

# region Configuration Management

	def _updateConfiguration(self, machineId: str | None, rshipUrl: str | None) -> bool:
		"""
		Update configuration from external source (like exec info).
		Returns True if anything changed.
		"""
		changed = False
		
		# Update machine ID
		if machineId is None or machineId == "":
			hostname = socket.gethostname()
			if self._machineId != hostname:
				op.RS_LOG.Warning("[RshipExt]: Machine Id not provided, using fallback", hostname)
			machineId = hostname
		
		if self._machineId != machineId:
			self._machineId = machineId
			changed = True
			# Recreate instance with new machine ID
			if self.state != RshipState.UNINITIALIZED:
				self._createInstance()
		
		# Update Rship URL. If exec info is unavailable, preserve any manually configured address.
		if rshipUrl is None or rshipUrl == "":
			manualAddress = self.ownerComp.par.Address.eval()
			if manualAddress not in (None, ""):
				rshipUrl = str(manualAddress)

		if rshipUrl is not None and rshipUrl != "":
			defaultPort = int(self.ownerComp.par.Port.eval()) if self.ownerComp.par.Port.eval() else 5155
			port = defaultPort
			rawUrl = str(rshipUrl).strip()
			protocol = None
			host = rawUrl

			if "://" in rawUrl:
				sections = rawUrl.split("://", 1)
				protocol = sections[0]
				host = sections[1]

			host = host.split("/", 1)[0]

			if ":" in host:
				hostSections = host.rsplit(":", 1)
				host = hostSections[0]
				try:
					port = int(hostSections[1])
				except ValueError:
					port = defaultPort

			rshipUrl = f"{protocol}://{host}" if protocol else host
			
			if self._rshipUrl != rshipUrl or self._rshipPort != port:
				self._rshipUrl = rshipUrl
				self._rshipPort = port
				
				# Don't reconnect if already connected to this address
				if not (self.wsConnected and 
						self.ownerComp.par.Port.eval() == port and 
						self.ownerComp.par.Address.eval() == rshipUrl):
					self.ownerComp.par.Port = port
					self.ownerComp.par.Address = rshipUrl
					op.RS_LOG.Debug("[RshipExt]: Setting Rship host to", rshipUrl, "on port", port)
					changed = True
		
		return changed

# endregion Configuration Management

# region WebSocket Callbacks

	def targetListUpdated(self, data: QueryResponse):
		"""
		Process query response for remote targets.
		Only set offline targets that are in THIS response's upserts but not in our local cache.
		"""
		op.RS_LOG.Info(f"[RshipExt]: >>> targetListUpdated - received {len(data.upserts)} upserts, {len(data.deletes)} deletes")
		
		# Update our tracking of all remote keys
		remoteKeys = set([target.item['id'] for target in data.upserts])
		
		for key in remoteKeys:
			self.remoteKeys.add(key)

		for key in data.deletes:
			self.remoteKeys.discard(key)

		# Only process the upserts in this specific response
		# If a target is in this response but not in our local cache, set it offline
		allLocalKeys = set(self.allTouchTargets.keys())
		
		offlineCount = 0
		for target in data.upserts:
			targetId = target.item['id']
			if targetId not in allLocalKeys:
				# Only send offline status if it's different from what we last sent
				if targetId not in self.sentTargetStatuses or self.sentTargetStatuses[targetId] != Status.Offline:
					CLIENT.setTargetOffline(targetId, self.instance.id)
					self.sentTargetStatuses[targetId] = Status.Offline
					offlineCount += 1
		
		op.RS_LOG.Info(f"[RshipExt]: <<< targetListUpdated - set {offlineCount} targets offline")
		self.updateStatsPage(remoteTargets=len(remoteKeys))

	def actionListUpdated(self, data: QueryResponse):
		self.updateStatsPage(remoteActions=len(data.upserts))

	def emitterListUpdated(self, data: QueryResponse):
		self.updateStatsPage(remoteEmitters=len(data.upserts))


	def OnRshipConnect(self):
		CLIENT.setSend(self.websocketOp.sendText)
		self.wsConnected = True
		self._transitionState(RshipState.CONNECTED)
		
		op.RS_LOG.Info("[RshipExt]: >>> OnRshipConnect START")
		op.RS_LOG.Info("[RshipExt]: Connected to Rship Server at ", self.websocketOp.par.netaddress.eval())
		
		if not self._ensureReady():
			op.RS_LOG.Warning("[RshipExt]: Connected but not ready - waiting for machine ID")
			return
		
		# Send our data first, then query to clean up any stale remote targets
		self._transitionState(RshipState.SYNCING)
		op.RS_LOG.Info("[RshipExt]: Sending project data...")
		self.refreshProjectData(sendEmitterValues=True)
		op.RS_LOG.Info("[RshipExt]: Sending query for remote targets...")
		# Query after sending to ensure our targets are registered before cleanup
		CLIENT.sendQuery(
			GetTargetsByQuery({
				"serviceId": self.makeServiceId(),
			}),
			"Target",
			self.targetListUpdated
		)
		CLIENT.sendQuery(
			GetActionsByQuery({
				"serviceId": self.makeServiceId(),
				"schema": None,
			}),
			"Action",
			self.actionListUpdated
		)
		CLIENT.sendQuery(
			GetEmittersByQuery({
				"serviceId": self.makeServiceId(),
				"schema": None,
			}),
			"Emitter",
			self.emitterListUpdated
		)
		self._transitionState(RshipState.CONNECTED)
		op.RS_LOG.Info("[RshipExt]: <<< OnRshipConnect END")


	def OnRshipDisconnect(self):
		self.wsConnected = False
		
		# Transition back to appropriate state
		if self._machineId:
			self._transitionState(RshipState.READY)
		else:
			self._transitionState(RshipState.UNINITIALIZED)
		
		self.sentTargetStatuses.clear()
		self.updateStatsPage(remoteTargets=0, remoteActions=0, remoteEmitters=0)


	def OnRshipReceivePing(self):
		self.ownerComp.par.Lastping = datetime.datetime.now()
		
		# Only refresh if we weren't already connected and not currently syncing
		if self.wsConnected is False and self.state != RshipState.SYNCING:
			self.wsConnected = True
			self._transitionState(RshipState.CONNECTED)
			
			if self._ensureReady():
				self.refreshProjectData()


	def OnRshipReceiveText(self, text: str):
		CLIENT.setSend(self.websocketOp.sendText)
		CLIENT.parseMessage(text)


	def OnTickInterval(self):
		self.updateExecInfo()

# endregion WebSocket Callbacks

# region Project Management

	def refreshProjectData(self, sendEmitterValues=False):
		op.RS_LOG.Info(f"[RshipExt]: >>> refreshProjectData (sendEmitterValues={sendEmitterValues})")
		if not self._ensureReady():
			op.RS_LOG.Warning("[RshipExt]: Not ready, skipping refresh")
			return

		self.buildTargets()

		if self.wsConnected:
			self.sendProjectData(sendEmitterValues=sendEmitterValues)
		else:
			op.RS_LOG.Warning("[RshipExt]: Not connected to Rship Server, Attempting to reconnect")
			self.ownerComp.par.Reconnect.pulse()
		
		op.RS_LOG.Info("[RshipExt]: <<< refreshProjectData complete")


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

		# Track previously known targets
		previousTargets = set(self.allTouchTargets.keys())
		
		self.allTouchTargets = {target.id: target for target in allTouchTargets}
		
		# Find targets that were removed locally
		currentTargets = set(self.allTouchTargets.keys())
		removedTargets = previousTargets - currentTargets
		
		# Mark removed targets as offline if we're connected
		if self.wsConnected and self.instance:
			for targetId in removedTargets:
				op.RS_LOG.Debug(f"[RshipExt]: Target {targetId} removed locally, setting offline")
				if targetId not in self.sentTargetStatuses or self.sentTargetStatuses[targetId] != Status.Offline:
					CLIENT.setTargetOffline(targetId, self.instance.id)
					self.sentTargetStatuses[targetId] = Status.Offline


# endregion Project Management

# region ws senders

	def sendProjectData(self, sendEmitterValues = False):
		if self.instance is None:
			op.RS_LOG.Error("[RshipExt]: Instance is not set, cannot send project data")
			return

		CLIENT.setSend(self.websocketOp.sendText)
		events = [CLIENT.buildSetEvent(self.instance)]

		for opTarget in self.opTargets.values():
			streamInfo = opTarget.getStreamInfo()
			if streamInfo is not None:
				events.append(CLIENT.buildSetEvent(streamInfo))

		allTouchTargets = [child for target in self.opTargets.values() for child in target.collectChildren()]

		allTargets = [target.getTarget() for target in allTouchTargets]
		allActions = [action for target in allTouchTargets for action in target.getActions()]
		allEmitters = [emitter for target in allTouchTargets for emitter in target.getEmitters()]

		self.allTouchTargets = {target.id: target for target in allTouchTargets}
		self.emitterIndex.clear()
		self.emitterHandlers.clear()

		op.RS_LOG.Info(f"[RshipExt]: Sending {len(allTargets)} targets, {len(allActions)} actions, {len(allEmitters)} emitters")
		self.updateStatsPage(
			localTargets=len(allTargets),
			localActions=len(allActions),
			localEmitters=len(allEmitters),
		)
		
		statusesToSend = 0
		for target in allTargets:
			events.append(CLIENT.buildSetEvent(target))
			
			# Only send status if it's changed or never been sent
			if target.id not in self.sentTargetStatuses or self.sentTargetStatuses[target.id] != Status.Online:
				events.append(CLIENT.buildTargetStatusEvent(target.id, self.instance.id, Status.Online))
				self.sentTargetStatuses[target.id] = Status.Online
				statusesToSend += 1
		
		op.RS_LOG.Info(f"[RshipExt]: Sent {statusesToSend} target status updates (Online)")
		
		for action in allActions:
			CLIENT.saveHandler(action.id, action.handler)
			
			del action.handler  # Remove handler from action to avoid circular references
			CLIENT.actions[action.id] = action
			events.append(CLIENT.buildSetEvent(action))

		for emitter in allEmitters:
			changeKeys = getattr(emitter, 'changeKeys', [emitter.changeKey])
			for changeKey in changeKeys:
				self.emitterIndex[changeKey] = emitter
				self.emitterHandlers[changeKey] = emitter.handler
			
			del emitter.handler  # Remove handler from emitter to avoid circular references
			del emitter.changeKey
			if hasattr(emitter, 'changeKeys'):
				del emitter.changeKeys
			events.append(CLIENT.buildSetEvent(emitter))

		CLIENT.sendEventBatch(events)

		if not sendEmitterValues:
			return

		for key, handler in self.emitterHandlers.items():
			emitter = self.emitterIndex.get(key, None)
			if (emitter is not None) and (handler is not None):
				data = handler()
				CLIENT.pulseEmitter(emitter.id, data)


	def PulseEmitter(self, opPath: str, parName: str):
		CLIENT.setSend(self.websocketOp.sendText)
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

# endregion ws senders

# endregion RshipExt
