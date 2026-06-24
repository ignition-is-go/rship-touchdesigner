"""
Extension classes enhance TouchDesigner components with python. An
extension is accessed via ext.ExtensionClassName from any operator
within the extended component. If the extension is promoted via its
Promote Extension parameter, all its attributes with capitalized names
can be accessed externally, e.g. op('yourComp').PromotedFunction().

Help: search "Extensions" in wiki

RshipExt is the entrypoint/coordinator. It owns the rship data model (targets,
actions, emitters) and the TD-facing properties, and it forwards the WebSocket /
Web Client / Timer DAT callbacks. The connection lifecycle itself lives in
mod/connection.py (ConnectionManager); this class only feeds it signals and
provides two coordination hooks (_onConnected, _publishConnectionState).
"""
import datetime
from typing import Dict, Set, Callable

import TDFunctions as TDF
import socket
import json

from exec import CLIENT, Instance, InstanceStatus, Status, Action, Emitter
from target import TouchTarget
from util import makeEmitterChangeKey
from connection import ConnectionManager, ConnState
import rship
import comp_engine

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
		# Expose the user-facing API module globally as op.RSHIP.Api so extensions
		# anywhere in the project can use it (bare `import rship` only resolves for
		# DATs inside this comp). Same module instance we use -> shares CLIENT/registry.
		self.Api = rship
		self.CompEngine = comp_engine     # op.RSHIP.CompEngine — the comp-engine API
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

		# Configuration
		self._machineId: str | None = None
		self._rshipUrl: str | None = None
		self._rshipPort: int = 5155

		# Connection lifecycle is owned by ConnectionManager (mod/connection.py).
		# We feed it signals from the callbacks and it calls back through these
		# two hooks: _onConnected (push data) and _publishConnectionState (mirror state).
		self.conn = ConnectionManager(
			self.ownerComp,
			onConnect=self._onConnected,
			publishState=self._publishConnectionState,
			sendPing=self._sendWsPing,
		)

		self.execInfoRequests = {}

		self.opTargets: Dict[str, TouchTarget] = {}
		self.allTouchTargets: Dict[str, TouchTarget] = {}

		self.instance: Instance | None = None

		self.emitterIndex: Dict[str, Emitter] = {}
		self.emitterHandlers: Dict[str, Callable] = {}

		self.reconnectTimerOp = self.ownerComp.op('reconnect_timer')

		self.reconnectTimerOp.par.start.pulse()

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

# region Connection coordination hooks
#
# These are the only points where the connection state machine touches the
# extension. Everything connection-related otherwise lives in mod/connection.py.

	def _publishConnectionState(self, state: ConnState):
		"""Mirror connection state onto the TD-facing properties. The 'Connected'
		UI par follows ConnectionStatus through its own expression.

		Compare by .value, not enum identity: after a DAT reload / reinit the
		ConnState class RshipExt imported and the one the ConnectionManager carries
		can be distinct module copies, so identity comparison would wrongly fail."""
		self.ConnectionStatus = state.value
		self.wsConnected = (state.value == ConnState.CONNECTED.value)

	def _onConnected(self):
		"""Edge action: runs once each time the socket becomes healthy
		(DISCONNECTED -> CONNECTED). Re-registers the project, then seeds property
		values so the server has fresh reconciliation ground-truth."""
		CLIENT.setSend(self.websocketOp.sendText)
		op.RS_LOG.Info("[RshipExt]: Connected to Rship Server at " + str(self.websocketOp.par.netaddress.eval()))
		self.refreshProjectData()
		self.seedProperties()

	def seedProperties(self):
		"""Pulse every property emitter's current value. This is the property seed
		(reconciliation ground-truth), run on every (re)connect. Distinct from the
		retired 'send all emitter values' flag; the server can also pull individual
		values on demand via the inbound ResendEmitterValue command."""
		CLIENT.setSend(self.websocketOp.sendText)
		CLIENT.seedEmitterValues()

	def _sendWsPing(self):
		"""Send a websocket ping frame. The server's pong routes back through
		onReceivePong -> OnRshipReceivePing -> conn.noteBeat(), refreshing the heartbeat."""
		self.websocketOp.sendPing()

	def _ensureInstance(self) -> bool:
		"""Ensure the local Instance object exists. Returns True if we have identity."""
		if self._machineId is None:
			return False
		if self.instance is None:
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

# endregion Connection coordination hooks

# region DAT callback entrypoints

	def OnProjectPreSave(self):
		# Always rescan and update local cache, refresh identity from the link.
		self.cookTargetList()
		self.updateExecInfo()
		# Push if we can; if not connected, refreshProjectData -> reconcile drives reconnect.
		if self._ensureInstance():
			self.refreshProjectData()

	# --- websocket DAT ---

	def OnRshipConnect(self):
		self.conn.noteSocketOpen()

	def OnRshipDisconnect(self):
		self.sentTargetStatuses.clear()
		self.updateStatsPage(remoteTargets=0, remoteActions=0, remoteEmitters=0)
		self.conn.noteSocketClosed()

	def OnRshipReceivePing(self):
		self.ownerComp.par.Lastping = datetime.datetime.now()
		self.conn.noteBeat()

	def OnRshipReceiveText(self, text: str):
		CLIENT.setSend(self.websocketOp.sendText)
		self.conn.noteBeat()
		CLIENT.parseMessage(text)

	# --- reconnect_timer (~1Hz) ---

	def OnTickInterval(self):
		# Refresh identity/url from the link, then ping + re-derive connection
		# health. This keeps the heartbeat fresh, detects silent drops, and drives
		# reconnect.
		self.updateExecInfo()
		self.conn.tick()

		# Pick up Python targets registered after connect (e.g. late extension init).
		if self.conn.isConnected and rship.consume_dirty():
			op.RS_LOG.Debug("[RshipExt]: rship registry changed, re-publishing")
			self.refreshProjectData()
			self.seedProperties()

	# --- resend_all par ---

	def ResendAll(self):
		"""Force a full re-publish: forget what we've already sent, rescan the
		network, and push every target/action/emitter plus current values."""
		op.RS_LOG.Info("[RshipExt]: >>> ResendAll requested")
		self.sentTargetStatuses.clear()
		self.cookTargetList()
		if self._ensureInstance() and self.conn.isConnected:
			self.refreshProjectData()
			self.seedProperties()
		else:
			op.RS_LOG.Warning("[RshipExt]: ResendAll while not connected - reconnecting")
			self.conn.reconcile()

# endregion DAT callback entrypoints

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
			self.conn.reconcile()
			if configChanged and self.conn.isConnected:
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

			configChanged = self._updateConfiguration(machineId, rshipUrl)
			self.conn.reconcile()
			if configChanged and self.conn.isConnected:
				self.refreshProjectData()

		except Exception as e:
			op.RS_LOG.Warning("[RshipExt]: Error occurred while processing Exec Info:", e)
			self._updateConfiguration(None, None)
			self.conn.reconcile()

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
			self.conn.setMachineId(machineId)
			changed = True
			# Recreate instance with new machine ID if we already had one
			if self.instance is not None:
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

# region Project Management

	def refreshProjectData(self):
		op.RS_LOG.Info("[RshipExt]: >>> refreshProjectData")
		if not self._ensureInstance():
			op.RS_LOG.Warning("[RshipExt]: No machine id yet, skipping refresh")
			return

		self.buildTargets()

		if self.conn.isConnected:
			self.sendProjectData()
		else:
			op.RS_LOG.Warning("[RshipExt]: Not connected to Rship Server, will reconnect")
			self.conn.reconcile()

		op.RS_LOG.Info("[RshipExt]: <<< refreshProjectData complete")


	def cookTargetList(self):
		# op.RS_LOG.Info("[RshipExt]: Finding OpTargets...")
		self.findTargetsOp.cook(force=True)


	def buildTargets(self):

		# op.RS_LOG.Info("[RshipExt]: Building targets...")

		ops = [op(self.targetsOp[i, 0].val) for i in range(0, self.targetsOp.numRows)]

		# op.RS_LOG.Info("[RshipExt]: Found", len(ops), "ops")

		foundOps: Dict[str, TouchTarget] = {}

		# Reflect each tagged COMP through the consolidated rship.reflect_comp — one function
		# that replaced the old OPTarget/PageTarget/ParGroupTarget/SequenceTarget classes. Ids
		# come from the COMP's stored UUID (survives restarts); schemas via par_shape. Verified
		# byte-identical (20/20 wire-diff) + server-confirmed before the legacy classes were cut.
		for o in ops:
			opTarget = rship.reflect_comp(o, self.instance)
			foundOps[opTarget.id] = opTarget

		self.opTargets = foundOps

		# Merge user-registered Python targets (the rship.target(...) API). They
		# implement the TouchTarget interface so they flow through the normal
		# send/seed lifecycle; inject the instance so their ids can resolve.
		# First: a deleted base leaves a stale td-anchored registration — mark its
		# target OFFLINE and drop it, so it isn't re-published as online on connect.
		for proxy in rship.prune_dead():
			proxy.instance = self.instance
			CLIENT.setTargetOffline(proxy.id, self.instance.id)
			op.RS_LOG.Info("[RshipExt]: removed target (base deleted) ->", proxy.id, "offline")
		for proxy in rship.get_targets():
			proxy.instance = self.instance
			self.opTargets[proxy.id] = proxy

		# Drive the parexec's monitored ops: every tag-based target COMP plus every op backing
		# a Python-API par() property. (This list used to be a static par in the .toe; RshipExt
		# now manages it so par-backed properties AND reflected COMPs get TD-side change
		# detection — a par change fires onValuesChanged -> PulseEmitter -> the matching emitter.)
		monitor = set()
		for t in self.opTargets.values():
			mo = getattr(t, 'monitored_ops', None)
			if callable(mo):
				monitor |= mo()
			else:
				oc = getattr(t, 'ownerComp', None)
				if oc is not None and oc.valid:
					monitor.add(oc.path)
		emittersDat = self.ownerComp.op('emitters')
		if emittersDat is not None and emittersDat.par['ops'] is not None:
			emittersDat.par.ops = ' '.join(sorted(monitor))

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
		if self.conn.isConnected and self.instance:
			for targetId in removedTargets:
				op.RS_LOG.Debug(f"[RshipExt]: Target {targetId} removed locally, setting offline")
				if targetId not in self.sentTargetStatuses or self.sentTargetStatuses[targetId] != Status.Offline:
					CLIENT.setTargetOffline(targetId, self.instance.id)
					self.sentTargetStatuses[targetId] = Status.Offline


# endregion Project Management

# region ws senders

	def sendProjectData(self):
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
		CLIENT.clearEmitterValueProviders()

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

			# Register the value provider by emitter id for property seeding and
			# server-driven ResendEmitterValue.
			CLIENT.saveEmitterValueProvider(emitter.id, emitter.handler)

			del emitter.handler  # Remove handler from emitter to avoid circular references
			del emitter.changeKey
			if hasattr(emitter, 'changeKeys'):
				del emitter.changeKeys
			events.append(CLIENT.buildSetEvent(emitter))

		CLIENT.sendEventBatch(events)

		# Stand up opt-in comp engines via their ordered publish sequence (target ->
		# emitters -> actions -> CompEngine entity -> initial pulse) — not part of the
		# generic target batch above. First mark engines whose base was deleted offline.
		for dead in comp_engine.prune_dead_engines():
			dead.instance = self.instance
			dead.offline()
			op.RS_LOG.Info("[RshipExt]: removed comp engine (base deleted) ->", dead.id, "offline")
		for engine in comp_engine.get_engines():
			engine.instance = self.instance
			engine.publish()

		# Property seeding (pulsing current values) is now an explicit step done by
		# the caller via seedProperties(), not a flag on this send path.


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
