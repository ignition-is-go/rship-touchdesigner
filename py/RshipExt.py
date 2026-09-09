"""
Extension classes enhance TouchDesigner components with python. An
extension is accessed via ext.ExtensionClassName from any operator
within the extended component. If the extension is promoted via its
Promote Extension parameter, all its attributes with capitalized names
can be accessed externally, e.g. op('yourComp').PromotedFunction().

Help: search "Extensions" in wiki
"""
import datetime
import time
from collections import deque
from typing import Dict, Set, Callable
from enum import Enum

import TDFunctions as TDF
import socket
from exec import CLIENT, ExecClient, GetActionsByQuery, GetEmittersByQuery, GetTargetsByQuery, Instance, Machine, InstanceStatus, Status, Action, Emitter, Pulse
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
	ACTIVE = "active"

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
	DEFERRED_COMMANDS = frozenset(('ExecTargetAction', 'BatchTargetAction', 'CompactBatchTargetAction', 'ResendEmitterValue'))
	MAX_DEFERRED_COMMANDS = 1024
	MAX_DEFERRED_BYTES = 16 * 1024 * 1024
	DRAIN_RUN_SOURCE = "args[0]._drainCommands()"
	DRAIN_COMMAND_LIMIT = 16
	DRAIN_TIME_SECONDS = 0.004
	TICK_RUN_SOURCE = "args[0].OnTickInterval()"
	PULSE_FLUSH_RUN_SOURCE = "args[0]._flushPulses()"
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

		self.emitterIndex: Dict[str, list[Emitter]] = {}
		self.emitterHandlers: Dict[str, Callable] = {}

		self._pendingPulses = {}
		self._pendingExplicitPulses = []
		self._pulseFlushScheduled = False
		self._deferredCommands = deque()
		self._deferredBytes = 0
		self._drainRun = None
		self._connectionGeneration = 0
		self._retryAt = 0.0
		self._retryDelay = 1.0

		self._tickInterval = 1.0  # seconds
		self._tickRun = None
		self._cancelScheduledRuns()
		self._scheduleTick()

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
		if self._machineId is None:
			return False
		expectedId = self._machineId + ":" + self.makeServiceId()
		if self.instance is None or self.instance.id != expectedId:
			self._createInstance()
		if self.state == RshipState.UNINITIALIZED:
			self._transitionState(RshipState.CONNECTED if self.wsConnected else RshipState.READY)
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
			status=InstanceStatus.Starting,
			machineId=self._machineId,
			color="#727e51"
		)

		# Keep MachineId property in sync for backwards compatibility
		self.MachineId = self._machineId
		CLIENT.instanceId = self.instance.id
		self.sentTargetStatuses.clear()

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

		offlineEvents = []
		for target in data.upserts:
			targetId = target.item['id']
			if targetId not in allLocalKeys:
				# Only send offline status if it's different from what we last sent
				if targetId not in self.sentTargetStatuses or self.sentTargetStatuses[targetId] != Status.Offline:
					offlineEvents.append(CLIENT.buildTargetStatusEvent(targetId, self.instance.id, Status.Offline))
					self.sentTargetStatuses[targetId] = Status.Offline

		if offlineEvents:
			CLIENT.sendEventBatch(offlineEvents)

		op.RS_LOG.Info(f"[RshipExt]: <<< targetListUpdated - set {len(offlineEvents)} targets offline")
		self.updateStatsPage(remoteTargets=len(remoteKeys))

	def actionListUpdated(self, data: QueryResponse):
		self.updateStatsPage(remoteActions=len(data.upserts))

	def emitterListUpdated(self, data: QueryResponse):
		self.updateStatsPage(remoteEmitters=len(data.upserts))


	def OnRshipConnect(self):
		CLIENT.setSend(self.websocketOp.sendText)
		if self._drainRun is not None:
			self._drainRun.kill()
			self._drainRun = None
		self._connectionGeneration += 1
		self._deferredCommands.clear()
		self._deferredBytes = 0
		self.wsConnected = True
		self.sentTargetStatuses.clear()
		self._retryAt = 0.0
		self._retryDelay = 1.0
		self._transitionState(RshipState.CONNECTED)
		self.refreshProjectData(sendEmitterValues=True)

	def OnRshipDisconnect(self):
		self.wsConnected = False
		if self._drainRun is not None:
			self._drainRun.kill()
			self._drainRun = None
		self._connectionGeneration += 1
		self._deferredCommands.clear()
		self._deferredBytes = 0
		self._pendingPulses.clear()
		self._pendingExplicitPulses.clear()
		CLIENT.emitterValueProviders.clear()
		if self.instance is not None:
			self.instance.status = InstanceStatus.Starting.value
		self._transitionState(RshipState.READY if self._machineId else RshipState.UNINITIALIZED)
		self.sentTargetStatuses.clear()
		self.updateStatsPage(remoteTargets=0, remoteActions=0, remoteEmitters=0)

	def OnRshipReceivePing(self):
		self.ownerComp.par.Lastping = datetime.datetime.now()
		if not self.wsConnected:
			self.OnRshipConnect()

	def OnRshipReceiveText(self, text: str):
		CLIENT.setSend(self.websocketOp.sendText)
		try:
			message = json.loads(text)
		except (ValueError, TypeError):
			CLIENT.parseMessage(text)
			return
		if isinstance(message, dict) and isinstance(message.get('event'), str) and not self.wsConnected:
			self.OnRshipConnect()
		data = message.get('data', {}) if isinstance(message, dict) else {}
		if isinstance(message, dict) and message.get('event') == 'ws:m:command' and isinstance(data, dict) and data.get('commandId') in self.DEFERRED_COMMANDS:
			if not self.wsConnected:
				return
			if self.state != RshipState.ACTIVE or self._deferredCommands or self._drainRun is not None:
				size = len(text.encode('utf-8'))
				if len(self._deferredCommands) >= self.MAX_DEFERRED_COMMANDS or self._deferredBytes + size > self.MAX_DEFERRED_BYTES:
					CLIENT.sendCommandError(data.get('command', {}).get('tx', ''), data['commandId'], 'Executor loading queue is full')
					return
				self._deferredCommands.append((text, size))
				self._deferredBytes += size
				return
		CLIENT.parseMessage(text)

	def _drainCommands(self):
		self._drainRun = None
		generation = self._connectionGeneration
		deadline = time.monotonic() + self.DRAIN_TIME_SECONDS
		processed = 0
		while self._deferredCommands and self.wsConnected and self.state == RshipState.ACTIVE and generation == self._connectionGeneration:
			text, size = self._deferredCommands.popleft()
			self._deferredBytes -= size
			try:
				CLIENT.parseMessage(text)
			except Exception as error:
				self._registrationFailed(error, generation)
				return
			processed += 1
			if processed >= self.DRAIN_COMMAND_LIMIT or time.monotonic() >= deadline:
				break
		if self._deferredCommands and self.wsConnected and self.state == RshipState.ACTIVE and generation == self._connectionGeneration:
			self._drainRun = run(self.DRAIN_RUN_SOURCE, self, delayFrames=1)


	def _cancelScheduledRuns(self):
		ownerPath = self.ownerComp.path
		for scheduledRun in tuple(runs):
			if not scheduledRun.isString:
				continue
			if scheduledRun.source not in (self.TICK_RUN_SOURCE, self.PULSE_FLUSH_RUN_SOURCE, self.DRAIN_RUN_SOURCE):
				continue
			if ownerPath not in str(scheduledRun.path):
				continue
			scheduledRun.kill()

	def _scheduleTick(self):
		if self._tickRun is not None and self._tickRun.active:
			return
		self._tickRun = run(
			self.TICK_RUN_SOURCE,
			self,
			delayMilliSeconds=int(self._tickInterval * 1000),
		)

	def OnTickInterval(self):
		self._tickRun = None
		self._scheduleTick()
		self.updateExecInfo()
		if self.wsConnected and self.state not in (RshipState.ACTIVE, RshipState.SYNCING) and time.monotonic() >= self._retryAt:
			self.refreshProjectData(sendEmitterValues=True)

# endregion WebSocket Callbacks

# region Project Management

	def refreshProjectData(self, sendEmitterValues=False):
		if self.state == RshipState.SYNCING or not self._ensureReady():
			return
		if not self.wsConnected:
			self.ownerComp.par.Reconnect.pulse()
			return
		generation = self._connectionGeneration
		self._transitionState(RshipState.SYNCING)
		CLIENT.setSend(self.websocketOp.sendText)
		try:
			self.instance.status = InstanceStatus.Starting.value
			self._sendRegistrationBatch([CLIENT.buildSetEvent(self.instance)], generation)
			self.cookTargetList()
			self.buildTargets()
			self.sendProjectData(sendEmitterValues=sendEmitterValues)
			if not self.wsConnected or generation != self._connectionGeneration:
				return
			self._retryDelay = 1.0
			self._retryAt = 0.0
			self._transitionState(RshipState.ACTIVE)
			self._drainCommands()
		except Exception as error:
			self._registrationFailed(error, generation)

	def _registrationFailed(self, error, generation):
		op.RS_LOG.Error(f"[RshipExt]: Registration failed: {error}")
		if generation != self._connectionGeneration:
			return
		self.sentTargetStatuses.clear()
		self.instance.status = InstanceStatus.Starting.value
		if self.wsConnected:
			try:
				self._sendRegistrationBatch([CLIENT.buildSetEvent(self.instance)], generation)
			except Exception:
				pass
		self._transitionState(RshipState.CONNECTED if self.wsConnected else RshipState.READY)
		self._retryAt = time.monotonic() + self._retryDelay
		self._retryDelay = min(self._retryDelay * 2, 30.0)



	def cookTargetList(self):
		# op.RS_LOG.Info("[RshipExt]: Finding OpTargets...")
		self.findTargetsOp.cook(force=True)
		
	def _indexTouchTargets(self, touchTargets):
		"""Build a stable ID index and report collisions instead of hiding them."""
		indexedTargets = {}
		for touchTarget in touchTargets:
			targetId = touchTarget.id
			if targetId in indexedTargets:
				existingTarget = indexedTargets[targetId]
				existingOwner = getattr(getattr(existingTarget, 'ownerComp', None), 'path', '<unknown>')
				duplicateOwner = getattr(getattr(touchTarget, 'ownerComp', None), 'path', '<unknown>')
				op.RS_LOG.Error(
					f"[RshipExt]: Duplicate TouchTarget ID {targetId}: "
					f"keeping {type(existingTarget).__name__} at {existingOwner}, "
					f"dropping {type(touchTarget).__name__} at {duplicateOwner}"
				)
				continue
			indexedTargets[targetId] = touchTarget
		return indexedTargets


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

		self.allTouchTargets = self._indexTouchTargets(allTouchTargets)

		# Find targets that were removed locally
		currentTargets = set(self.allTouchTargets.keys())
		removedTargets = previousTargets - currentTargets

		# Mark removed targets as offline if we're connected
		if self.wsConnected and self.instance:
			offlineEvents = []
			for targetId in removedTargets:
				op.RS_LOG.Debug(f"[RshipExt]: Target {targetId} removed locally, setting offline")
				if targetId not in self.sentTargetStatuses or self.sentTargetStatuses[targetId] != Status.Offline:
					offlineEvents.append(CLIENT.buildTargetStatusEvent(targetId, self.instance.id, Status.Offline))
					self.sentTargetStatuses[targetId] = Status.Offline
			if offlineEvents:
				CLIENT.sendEventBatch(offlineEvents)


# endregion Project Management

# region ws senders

	def _pruneClientActions(self, currentActionIds: Set[str]):
		serviceId = self.instance.serviceId
		staleActionIds = [
			actionId
			for actionId, action in tuple(CLIENT.actions.items())
			if getattr(action, 'serviceId', None) == serviceId
			and actionId not in currentActionIds
		]
		for actionId in staleActionIds:
			CLIENT.actions.pop(actionId, None)
			CLIENT.handlers.pop(actionId, None)

	def sendProjectData(self, sendEmitterValues=False):
		if self.instance is None:
			raise RuntimeError("Instance is not configured")
		generation = self._connectionGeneration
		CLIENT.setSend(self.websocketOp.sendText)
		allTouchTargetsById = self._indexTouchTargets(
			[child for target in self.opTargets.values() for child in target.collectChildren()]
		)
		allTouchTargets = list(allTouchTargetsById.values())
		allTargets = [target.getTarget() for target in allTouchTargets]
		allActions = [action for target in allTouchTargets for action in target.getActions()]
		allEmittersById = {}
		for target in allTouchTargets:
			for emitter in target.getEmitters():
				allEmittersById.setdefault(emitter.id, emitter)
		propertyEmitterIds = {action.writesTo['emitterId'] for action in allActions if hasattr(action, 'writesTo')}
		emitterIndex = {}
		emitterHandlers = {}
		providers = {}
		pulseEvents = []
		pulseTargetIds = {target.id for target in allTargets if target.category in ('Pulse', 'Momentary')}
		for emitter in allEmittersById.values():
			handler = emitter.handler
			for changeKey in getattr(emitter, 'changeKeys', [emitter.changeKey]):
				emitterIndex.setdefault(changeKey, []).append(emitter)
			emitterHandlers[emitter.id] = handler
			if emitter.id in propertyEmitterIds:
				providers[emitter.id] = handler
			if handler is not None and (emitter.id in propertyEmitterIds or (sendEmitterValues and emitter.targetId not in pulseTargetIds)):
				data = handler()
				if data is not None:
					pulseEvents.append(CLIENT.buildSetEvent(Pulse(id=emitter.id, emitterId=emitter.id, data=data)))
			del emitter.handler
			del emitter.changeKey
			if hasattr(emitter, 'changeKeys'):
				del emitter.changeKeys
		if propertyEmitterIds != set(providers):
			raise RuntimeError("Property writer has no value provider")
		self._pruneClientActions({action.id for action in allActions})
		for action in allActions:
			CLIENT.saveHandler(action.id, action.handler)
			del action.handler
			CLIENT.actions[action.id] = action
		CLIENT.instanceId = self.instance.id
		CLIENT.emitterValueProviders = providers
		self.allTouchTargets = allTouchTargetsById
		self.emitterIndex = emitterIndex
		self.emitterHandlers = emitterHandlers
		self.updateStatsPage(localTargets=len(allTargets), localActions=len(allActions), localEmitters=len(allEmittersById))
		events = []
		for opTarget in self.opTargets.values():
			streamInfo = opTarget.getStreamInfo()
			if streamInfo is not None:
				events.append(CLIENT.buildSetEvent(streamInfo))
		events.extend(CLIENT.buildSetEvent(item) for item in [*allTargets, *allActions, *allEmittersById.values()])
		self._sendRegistrationBatch(events, generation)
		self._sendRegistrationBatch(pulseEvents, generation)
		statusEvents = [CLIENT.buildTargetStatusEvent(target.id, self.instance.id, Status.Online) for target in allTargets]
		self.instance.status = InstanceStatus.Available.value
		statusEvents.append(CLIENT.buildSetEvent(self.instance))
		self._sendRegistrationBatch(statusEvents, generation)
		self.sentTargetStatuses.update({target.id: Status.Online for target in allTargets})

	def _sendRegistrationBatch(self, events, generation):
		if not self.wsConnected or generation != self._connectionGeneration:
			raise RuntimeError("Connection changed during registration")
		CLIENT.sendEventBatch(events)
		if not self.wsConnected or generation != self._connectionGeneration:
			raise RuntimeError("Connection changed during registration")


	def PulseEmitter(self, opPath: str, parName: str, preserveDuplicate: bool = False):
		changeKey = makeEmitterChangeKey(opPath, parName)

		emitters = self.emitterIndex.get(changeKey, ())
		for emitter in emitters:
			handler = self.emitterHandlers.get(emitter.id)
			if handler is None:
				continue
			data = handler()
			if data is None:
				continue
			pulseEvent = CLIENT.buildSetEvent(Pulse(
				id=emitter.id,
				emitterId=emitter.id,
				data=data,
			))
			if preserveDuplicate and emitter.id not in CLIENT.emitterValueProviders:
				self._pendingExplicitPulses.append(pulseEvent)
			else:
				self._pendingPulses[emitter.id] = pulseEvent
		if (self._pendingPulses or self._pendingExplicitPulses) and not self._pulseFlushScheduled:
			self._pulseFlushScheduled = True
			run(self.PULSE_FLUSH_RUN_SOURCE, self, delayFrames=0)

	def _flushPulses(self):
		self._pulseFlushScheduled = False
		pulseEvents = list(self._pendingPulses.values()) + self._pendingExplicitPulses
		if not pulseEvents or not self.wsConnected or self.state != RshipState.ACTIVE:
			self._pendingPulses.clear()
			self._pendingExplicitPulses.clear()
			return
		CLIENT.setSend(self.websocketOp.sendText)
		CLIENT.sendEventBatch(pulseEvents)
		self._pendingPulses.clear()
		self._pendingExplicitPulses.clear()

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
