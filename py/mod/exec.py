from datetime import datetime, timezone
import json
from enum import Enum
from typing import Callable, Dict, List, Self

from myko import (
	CommandError,
	CommandResponse,
	MCommand,
	MEvent,
	MEventType,
	MItem,
	MQuery,
	MReport,
	MWrappedCommand,
	MWrappedQuery,
	MWrappedReport,
	QueryError,
	QueryResponse,
	ReportError,
	ReportResponse,
	WSCommand,
	WSEvent,
	WSEventBatch,
	WSQuery,
	WSReport,
)


class Target(MItem):
	def __init__(
		self,
		id: str,
		name: str,
		parentTargets: List[str],
		serviceId: str,
		category: str,
	):
		super().__init__(id, name)
		self.parentTargets = parentTargets
		self.serviceId = serviceId
		self.category = category


class Status(Enum):
	Online = 'online'
	Offline = 'offline'


class TargetStatus(MItem):
	def __init__(self, id: str, targetId: str, status: Enum, instanceId: str):
		super().__init__(id, id)
		self.targetId = targetId
		self.status = status.value
		self.instanceId = instanceId


class Action(MItem):
	def __init__(
		self,
		id: str,
		name: str,
		targetId: str,
		serviceId: str,
		schema: any,
		handler: Callable[[Self, Dict[str, any]], None],
		schemaLayout: any = None,
	):
		super().__init__(id, name)
		self.schema = schema
		self.schemaLayout = schemaLayout
		self.targetId = targetId
		self.serviceId = serviceId
		self.handler = handler


class Emitter(MItem):
	def __init__(
		self,
		id: str,
		name: str,
		targetId: str,
		serviceId: str,
		schema: any,
		changeKey: str,
		handler: Callable,
	):
		super().__init__(id, name)
		self.targetId = targetId
		self.serviceId = serviceId
		self.schema = schema
		self.changeKey = changeKey
		self.handler = handler


class Pulse(MItem):
	def __init__(self, id: str, emitterId: str, data: any):
		super().__init__(id, id)
		self.emitterId = emitterId
		self.data = data
		self.clientId = None


class InstanceStatus(Enum):
	Starting = 'Starting'
	Available = 'Available'
	Stopping = 'Stopping'
	Unavailable = 'Unavailable'
	Error = 'Error'


class Instance(MItem):
	def __init__(
		self,
		id: str,
		name: str,
		serviceId: str,
		serviceTypeCode: str,
		status: InstanceStatus,
		machineId: str,
		color: str,
		message: str | None = None,
		renderDomain: any = None,
		coordinateSpace: any = None,
		clusterId: str | None = None,
	):
		super().__init__(id, name)
		self.serviceId = serviceId
		self.serviceTypeCode = serviceTypeCode
		self.status = status.value
		self.machineId = machineId
		self.color = color
		self.clientId = None
		self.message = message
		self.renderDomain = renderDomain
		self.coordinateSpace = coordinateSpace or {
			'right': 'PositiveX',
			'up': 'PositiveY',
			'forward': 'NegativeZ',
			'unitsPerMeter': 1,
		}
		self.clusterId = clusterId


class Machine(MItem):
	def __init__(
		self,
		id: str,
		name: str | None = None,
		dnsName: str | None = None,
		execName: str | None = None,
		addresses: List[str] | None = None,
	):
		super().__init__(id, name or id)
		self.name = name
		self.dnsName = dnsName
		self.execName = execName
		self.addresses = addresses or []
		self.fileDownloadInfo = None


class Service(MItem):
	def __init__(self, id: str, name: str, systemTypeCode: str):
		super().__init__(id, name)
		self.systemTypeCode = systemTypeCode


class ActionStub:
	def __init__(self, id: str, targetId: str):
		self.id = id
		self.targetId = targetId


class ExecTargetAction:
	def __init__(
		self,
		tx: str,
		createdAt: str,
		instanceId: str | None,
		action: ActionStub,
		data: any,
	):
		self.tx = tx
		self.createdAt = createdAt
		self.instanceId = instanceId
		self.action = action
		self.data = data


class BatchTargetAction:
	def __init__(self, actions: List[ExecTargetAction]):
		self.actions = actions


class CompactBatchTargetActionAssignment:
	def __init__(self, instanceId: str, targetId: str, payloadIndex: int):
		self.instanceId = instanceId
		self.targetId = targetId
		self.payloadIndex = payloadIndex


class CompactBatchTargetActionGroup:
	def __init__(self, actionId: str, payloads: List[any], assignments: List[CompactBatchTargetActionAssignment]):
		self.actionId = actionId
		self.payloads = payloads
		self.assignments = assignments


class Stream(MItem):
	def __init__(self, id: str, name: str):
		super().__init__(id, name)
		self.clientId = None


class IceCandidate:
	def __init__(self, candidate: str, sdpMid: str, lineIndex: int):
		self.candidate = candidate
		self.sdpMid = sdpMid
		self.sdpMLineIndex = lineIndex


class WebRTCConnection(MItem):
	offerCandidates: List[IceCandidate]
	answerCandidates: List[IceCandidate]
	sdpOffer: str
	sdpAnswer: str
	streamId: str

	def __init__(self, id: str, streamId: str):
		super().__init__(id, id)
		self.streamId = streamId


class GetWebRTCConnections(MQuery):
	def __init__(self):
		super().__init__()


class GetTargetsByServiceId(MQuery):
	def __init__(self, serviceId: str):
		super().__init__()
		self.serviceId = serviceId


class GetTargetsByQuery(MQuery):
	def __init__(self, partialTarget: dict):
		super().__init__()
		self.category = partialTarget.get('category', None)
		self.name = partialTarget.get('name', None)
		self.parentTargets = partialTarget.get('parentTargets', None)
		self.serviceId = partialTarget.get('serviceId', None)


class GetActionsByQuery(MQuery):
	def __init__(self, partialAction: dict):
		super().__init__()
		self.name = partialAction.get('name', None)
		self.targetId = partialAction.get('targetId', None)
		self.serviceId = partialAction.get('serviceId', None)
		self.schema = partialAction.get('schema', None)


class GetEmittersByQuery(MQuery):
	def __init__(self, partialEmitter: dict):
		super().__init__()
		self.name = partialEmitter.get('name', None)
		self.targetId = partialEmitter.get('targetId', None)
		self.serviceId = partialEmitter.get('serviceId', None)
		self.schema = partialEmitter.get('schema', None)


class AddAnswerCandidate(MCommand):
	def __init__(self, id: str, candidate: IceCandidate):
		super().__init__(str(datetime.now(timezone.utc).isoformat()))
		self.candidate = candidate.__dict__
		self.id = id


class SetAnswer(MCommand):
	def __init__(self, id: str, sdpAnswer: str):
		super().__init__(str(datetime.now(timezone.utc).isoformat()))
		self.sdpAnswer = sdpAnswer
		self.id = id


class ExecClient:
	_shared_send = None

	def __init__(self) -> None:
		self.targetStatuses: Dict[str, TargetStatus] = {}
		self.actions: Dict[str, Action] = {}
		self.handlers: Dict[str, callable] = {}
		self.clientId: str = None
		self.webRtcConnections: Dict[str, str] = {}
		self.queryHandlers: Dict[str, callable] = {}
		self.reportHandlers: Dict[str, callable] = {}

	def setSend(self, send):
		self.send = send
		ExecClient._shared_send = send

	def log(self, message):
		op.RS_LOG.Info('RshipClient: ' + message)

	def _sendPayload(self, payload: dict):
		send = getattr(self, 'send', None) or ExecClient._shared_send
		if send is None:
			self.log('Cant send, no socket')
			return
		send(json.dumps(payload))

	def buildSetEvent(self, item: MItem | dict, itemType: str | None = None) -> MEvent:
		return MEvent(changeType=MEventType.SET, item=item, itemType=itemType)

	def sendEvent(self, event: MEvent):
		self._sendPayload(WSEvent(event).__dict__)

	def sendEventBatch(self, events: List[MEvent]):
		if len(events) == 0:
			return
		if len(events) == 1:
			self.sendEvent(events[0])
			return
		self._sendPayload(WSEventBatch(events).__dict__)

	def set(self, item: MItem, itemType: str | None = None):
		self.sendEvent(self.buildSetEvent(item, itemType=itemType))

	def parseMessage(self, message):
		try:
			d = json.loads(message)
			event = d.get('event', None)
			data = d.get('data', None)

			if event == 'ws:m:command':
				self.parseCommand(data)
			elif event == 'ws:m:query-response':
				self.parseQueryResponse(data)
			elif event == 'ws:m:query-error':
				self.parseQueryError(data)
			elif event == 'ws:m:report-response':
				self.parseReportResponse(data)
			elif event == 'ws:m:report-error':
				self.parseReportError(data)
			elif event == 'ws:m:command-response':
				self.log(f"Command acknowledged for tx={data.get('tx', 'unknown')}")
			elif event == 'ws:m:command-error':
				command_error = CommandError(
					tx=data.get('tx', ''),
					commandId=data.get('commandId', ''),
					message=data.get('message', 'Unknown command error'),
				)
				self.log(
					f"Command error [{command_error.commandId}] tx={command_error.tx}: {command_error.message}"
				)
		except json.JSONDecodeError as e:
			self.log('Error parsing message: ' + str(e))
			self.log('Message was: ' + message)

	def sendQuery(self, query: MQuery, queryItemType: str, handler: Callable[[QueryResponse], None]):
		wrappedQuery = MWrappedQuery(
			queryId=type(query).__name__,
			queryItemType=queryItemType,
			query=query,
		)
		self.queryHandlers[query.tx] = handler
		self._sendPayload(WSQuery(wrappedQuery).__dict__)

	def sendReport(self, report: MReport, handler: Callable[[ReportResponse], None]):
		wrappedReport = MWrappedReport(
			reportId=type(report).__name__,
			report=report,
		)
		self.reportHandlers[report.tx] = handler
		self._sendPayload(WSReport(wrappedReport).__dict__)

	def sendCommand(self, command: MCommand):
		wrappedCommand = MWrappedCommand(command)
		self._sendPayload(WSCommand(wrappedCommand).__dict__)

	def sendCommandResponse(self, tx: str, response: any = None):
		self._sendPayload(
			{
				'event': 'ws:m:command-response',
				'data': CommandResponse(tx=tx, response=response).__dict__,
			}
		)

	def sendCommandError(self, tx: str, commandId: str, message: str):
		self._sendPayload(
			{
				'event': 'ws:m:command-error',
				'data': CommandError(tx=tx, commandId=commandId, message=message).__dict__,
			}
		)

	def parseCommand(self, data):
		commandId = data.get('commandId', None)
		command = data.get('command', {})
		if commandId == 'ExecTargetAction':
			self.handleIncomingExecTargetAction(commandId, command)
		elif commandId == 'BatchTargetAction':
			for action_command in command.get('actions', []):
				wrapped_action_command = dict(action_command)
				if 'tx' not in wrapped_action_command:
					wrapped_action_command['tx'] = command.get('tx', '')
				if 'createdAt' not in wrapped_action_command:
					wrapped_action_command['createdAt'] = command.get(
						'createdAt', datetime.now(timezone.utc).isoformat()
					)
				self.handleIncomingExecTargetAction('ExecTargetAction', wrapped_action_command)
		elif commandId == 'CompactBatchTargetAction':
			self.handleCompactBatchTargetAction(commandId, command)
		else:
			self.log(f'Unhandled commandId: {commandId}')

	def handleCompactBatchTargetAction(self, commandId: str, command: dict):
		tx = command.get('tx', '')
		created_at = command.get('createdAt', datetime.now(timezone.utc).isoformat())
		groups = command.get('groups', [])
		errors = []

		for group in groups:
			action_id = group.get('actionId', None)
			payloads = group.get('payloads', [])
			assignments = group.get('assignments', [])

			if action_id is None:
				errors.append('Compact batch group missing actionId')
				continue

			for assignment in assignments:
				target_id = assignment.get('targetId', None)
				instance_id = assignment.get('instanceId', None)
				payload_index = assignment.get('payloadIndex', None)

				if target_id is None or payload_index is None:
					errors.append(f'Compact batch assignment missing targetId or payloadIndex for action {action_id}')
					continue

				if payload_index < 0 or payload_index >= len(payloads):
					errors.append(
						f'Compact batch payload missing for action {action_id} at index {payload_index}'
					)
					continue

				self.handleIncomingExecTargetAction(
					'ExecTargetAction',
					{
						'tx': tx,
						'createdAt': created_at,
						'instanceId': instance_id,
						'action': {
							'id': action_id,
							'targetId': target_id,
						},
						'data': payloads[payload_index],
					},
					respond=False,
				)

		if errors:
			self.sendCommandError(tx, commandId, '; '.join(errors))
		else:
			self.sendCommandResponse(tx)

	def handleIncomingExecTargetAction(self, commandId: str, command: dict, respond: bool = True):
		action_data = command.get('action', {})
		action_id = action_data.get('id', None)
		target_id = action_data.get('targetId', None)
		tx = command.get('tx', '')
		created_at = command.get('createdAt', datetime.now(timezone.utc).isoformat())
		instance_id = command.get('instanceId', None)

		if action_id is None or target_id is None:
			if respond:
				self.sendCommandError(tx, commandId, 'Command missing action.id or action.targetId')
			else:
				raise Exception('Command missing action.id or action.targetId')
			return

		if action_id not in self.actions:
			self.log('No action found for id: ' + action_id)
			if respond:
				self.sendCommandError(tx, commandId, 'No action found for id: ' + action_id)
			else:
				raise Exception('No action found for id: ' + action_id)
			return

		action = self.actions[action_id]
		c = ExecTargetAction(
			tx=tx,
			createdAt=created_at,
			instanceId=instance_id,
			action=ActionStub(id=action_id, targetId=target_id),
			data=command.get('data', None),
		)
		try:
			response = self.handleExecTargetAction(c)
			if respond:
				self.sendCommandResponse(tx, response=response)
		except Exception as e:
			self.log(f'ExecTargetAction failed for {action_id}: {e}')
			if respond:
				self.sendCommandError(tx, commandId, str(e))
			else:
				raise

	def parseQueryResponse(self, data):
		tx = data.get('tx', None)
		if not tx:
			self.log('No tx in query response data')
			return

		handler = self.queryHandlers.get(tx, None)
		if not handler:
			return
		handler(QueryResponse(data))

	def parseQueryError(self, data):
		error = QueryError(data)
		self.log(f"Query error [{error.queryId}] tx={error.tx}: {error.message}")

	def parseReportResponse(self, data):
		tx = data.get('tx', None)
		if not tx:
			self.log('No tx in report response data')
			return
		handler = self.reportHandlers.get(tx, None)
		if not handler:
			return
		handler(ReportResponse(data))

	def parseReportError(self, data):
		error = ReportError(data)
		self.log(f"Report error [{error.reportId}] tx={error.tx}: {error.message}")

	def handleExecTargetAction(self, command: ExecTargetAction):
		if command.action.id not in self.handlers:
			raise Exception('No handler found for action id: ' + command.action.id)
		handler = self.handlers[command.action.id]
		return handler(self.actions[command.action.id], command.data)

	def saveTarget(self, target: Target):
		self.set(target)

	def setTargetOffline(self, targetId: str, instanceId: str):
		self.setTargetStatus(targetId, instanceId, Status.Offline)

	def buildTargetStatusEvent(self, targetId: str, instanceId: str, status: Status) -> MEvent:
		ts = TargetStatus(
			id=instanceId + ':' + targetId,
			targetId=targetId,
			instanceId=instanceId,
			status=status,
		)
		return self.buildSetEvent(ts)

	def setTargetStatus(self, targetId: str, instanceId: str, status: Status):
		self.sendEvent(self.buildTargetStatusEvent(targetId, instanceId, status))

	def saveAction(self, action: Action):
		self.actions[action.id] = action
		self.set(action)

	def saveEmitter(self, emitter: Emitter):
		self.set(emitter)

	def pulseEmitter(self, emitterId: str, data: any):
		p = Pulse(
			id=emitterId,
			emitterId=emitterId,
			data=data,
		)
		self.set(p)

	def saveHandler(self, actionId: str, handler: Callable[[Action, Dict[str, any]], None]):
		self.handlers[actionId] = handler

	def removeHandler(self, actionId: str):
		if actionId in self.handlers:
			op.RS_LOG.Info('removing handler for', actionId)
			del self.handlers[actionId]


CLIENT = ExecClient()
