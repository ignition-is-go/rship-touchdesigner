from datetime import datetime, timezone
import json
from myko import MEvent, MEventType, MItem, MCommand, WSEvent
from enum import Enum
from typing import Dict


class Target(MItem) :
	def __init__(self, id: str, name: str, actionIds: [str], emitterIds: [str], subTargets: [str], serviceId: str, bgColor: str, fgColor: str, lastUpdated: str, category: str, rootLevel: bool):
		super().__init__(id, name)

		self.actionIds = actionIds
		self.emitterIds = emitterIds
		self.subTargets = subTargets
		self.serviceId = serviceId
		self.bgColor = bgColor
		self.fgColor = fgColor
		self.lastUpdated = lastUpdated
		self.category = category
		self.rootLevel = rootLevel

class Status(Enum): 
	Online = 'online'
	Offline ='offline'

class TargetStatus(MItem): 
	def __init__(self, id: str, name: str, targetId: str, status: Enum, lastUpdated: str, instanceId: str):
		super().__init__(id, name)

		self.targetId = targetId
		self.status = status.value
		self.lastUpdated = lastUpdated
		self.instanceId = instanceId

class Action(MItem): 
	def __init__(self, id: str, name: str, targetId: str, systemId: str, schema: str):
		super().__init__(id, name)

		self.schema = schema
		self.targetId = targetId
		self.systemId = systemId

class Emitter(MItem): 
	def __init__(self, id: str, name: str, targetId: str, serviceId: str, schema: any):
		super().__init__(id, name)

		self.targetId = targetId
		self.serviceId = serviceId
		self.schema = schema

class Pulse(MItem): 
	def __init__(self, id: str, name: str, emitterId: str, data: any):
		super().__init__(id, name)

		self.emitterId = emitterId
		self.data = data

class Exec(MItem): 

	def __init__(self, id: str, name: str, machineId: str):
		super().__init__(id, name)

		self.machineId = machineId

class InstanceStatus(Enum):
	Starting = 'Starting'
	Available = 'Available'
	Stopping = 'Stopping'
	Unavailable = 'Unavailable'
	Error = 'Error'


class Instance(MItem): 
	def __init__(self, id: str, name: str, serviceId: str, execId: str, serviceTypeCode: str, status: InstanceStatus, machineId: str, color: str):
		super().__init__(id, name)
		
		self.serviceId = serviceId
		self.execId = execId
		self.serviceTypeCode = serviceTypeCode
		self.status = status.value
		self.machineId = machineId
		self.color = color

class Machine(MItem):
	name: str
	dnsName: str
	execName: str
	address: str

	def __init__(self, name: str): 
		super().__init__(name, name)
		self.name = name
		self.dnsName = name
		self.execName = name
		self.address = 'fakeAddress'

class Service(MItem):
	def __init__(self, id: str, name: str, systemTypeCode: str):
		super().__init__(id, name)

		self.systemTypeCode = systemTypeCode


# Commands #######################

class ExecTargetAction(MCommand): 
	def __init__(self, tx: str, createdAt: str, action: Action, data: any):
		super().__init__(tx, createdAt)
		self.action = action
		self.data = data
		

# CLIENT

# class that handles the cached version of the touch targets, instances, actions, etc for rocketship. 
class ExecClient:
	def __init__(self) -> None:
		self.targets: Dict[str, Target] = {}
		self.targetStatuses: Dict[str, TargetStatus] = {}
		self.actions: Dict[str, Action] = {}
		self.emitters: Dict[str, Emitter] = {}
		self.handlers: Dict[str, callable] = {}
		self.clientId: str = None

	
	def setSend(self, send):
		self.send = send

	def onExecConnected(self, func): 
		self.onExecConnectedCallback: callable = func
		func()

	def log(self, message):
		print("RshipClient: " + message)

	def sendEvent(self, event: MEvent):
		if not hasattr(self, 'send'):
			self.log("Cant send, no socket")
			return
		text = json.dumps(WSEvent(event).__dict__)
		self.send(text)

	def set(self, item: MItem):
		event = MEvent(changeType=MEventType.SET, item=item)
		self.sendEvent(event)

	def parseMessage(self, message):
		d = json.loads(message)
		if d['event'] == 'ws:m:command':
			self.parseCommand(d['data'])

	def parseCommand(self, data):
		if data['commandId'] == 'target:action:exec': 
			action = self.actions[data['command']['action']['id']]
			c = ExecTargetAction(
				tx=data['command']['tx'], 
				createdAt=data['command']['createdAt'], 
				action=action, 
				data=data['command']['data']
			)
			self.handleExecTargetAction(c)

		if data['commandId'] == 'client:setId': 
			self.clientId = data['command']['clientId']
			self.log("Setting ID: " +  self.clientId)
			if hasattr(self, 'onExecConnectedCallback'):
				self.onExecConnectedCallback()


	def handleExecTargetAction(self, command: ExecTargetAction):
		handler = self.handlers[command.action.id]
		handler(command.action, command.data)

	def saveTarget(self, target: Target):
		self.targets[target.id] = target
		self.set(target)

	def setTargetOffline(self, target: Target, instance: Instance):
		self.setTargetStatus(target, instance, Status.Offline)

	def setTargetStatus(self, target: Target, instance: Instance, status: Status):
		
		ts = TargetStatus(
			id=target.id + ":status",
			name=target.name + " Status",
			targetId=target.id,
			instanceId=instance.id,
			status=status,
			lastUpdated=datetime.now(timezone.utc).isoformat()
		)

		self.targetStatuses[ts.id] = ts
		self.set(ts)
	
	def saveAction(self, action: Action):
		self.actions[action.id] = action
		self.set(action)

	def saveEmitter(self, emitter: Emitter):
		self.emitters[emitter.id] = emitter
		self.set(emitter)

	def pulseEmitter(self, emitterId: str, data: any):
		p = Pulse(
			id=emitterId,
			name="Pulse",
			emitterId=emitterId,
			data=data
		)
		self.set(p)

	def saveHandler(self, actionId: str, handler: callable):
		self.handlers[actionId] = handler

