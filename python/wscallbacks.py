import json
from enum import Enum
import socket
from datetime import datetime, timezone

##################################
# Helpers
##################################

def print_dict(d, indent=0):
	for key, value in d.items():
		if isinstance(value, dict):
			print("{}{}:".format(" " * indent, key))
			print_dict(value, indent + 2)
		else:
			print("{}{}: {}".format(" " * indent, key, value))


##################################
# Myko Api
##################################

class MEventType(Enum): 
	SET = 'SET'
	DEL = 'DEL'

class MItem: 
	def __init__(self, id: str, name: str):
		self.id = id
		self.name = name
		self.hash = "hash" # somehow make a hash of the object

class MEvent: 
	def __init__(self, changeType: MEventType, item: MItem):
		self.changeType = changeType.value
		self.item = item.__dict__
		self.itemType = type(item).__name__

class WSEvent: 
	def __init__(self, data: MEvent): 
		self.data = data.__dict__
		self.event = "ws:m:event"

class MQuery:
	id: str
	def __init__(self) -> None:
		pass


class MWrappedQuery:
	def __init__(self, queryId: str, queryItemType: str, query: MQuery, tx: str):
		self.queryId: str
		self.queryItemType: str
		self.query: MQuery
		self.tx: str

class WSCommand: 
	def __init__(self, data: any):
		self.event = 'ws:m:command'
		self.data = data

class MCommand: 
	def __init__(self, tx: str, createdAt: str ):
		self.tx = tx
		self.createdAt = createdAt


class MWrappedCommand: 
	def __init__(self, commandId: str, clientId: str, data: MCommand):
		self.commandId = commandId
		self.clientId = clientId
		self.data = data

##################################
# Rship Executor API
##################################

# Items ##########################

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
	def __init__(self, id: str, name: str, targetId: str, serviceId: str):
		super().__init__(id, name)

		self.targetId = targetId
		self.serviceId = serviceId

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
	def __init__(self, id: str, name: str, serviceId: str, execId: str, serviceTypeCode: str, status: InstanceStatus, machineId: str):
		super().__init__(id, name)
		
		self.serviceId = serviceId
		self.execId = execId
		self.serviceTypeCode = serviceTypeCode
		self.status = status.value
		self.machineId = machineId

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

##################################
# Websocket MykoClient
##################################

# class that handles the cached version of the touch targets, instances, actions, etc for rocketship. 
class MykoClient:
	
	def setSend(self, send):
		self.send = send

	def log(self, message):
		print("MykoClient: " + message)

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
			action = actions[data['command']['action']['id']]
			c = ExecTargetAction(
				tx=data['command']['tx'], 
				createdAt=data['command']['createdAt'], 
				action=action, 
				data=data['command']['data']
			)
			self.handleExecTargetAction(c)

	def handleExecTargetAction(self, command: ExecTargetAction):
		handler = handlers[command.action.id]
		handler(command.action, command.data)



##################################
# Globals
##################################

# me - this DAT
# dat - the WebSocket DAT
client = MykoClient()
targets: dict = {}
targetStatuses: dict = {}
actions: dict = {}
emitters: dict = {}
handlers: dict = {}

##################################
# Touch Designer Exec
##################################

def scanTargets(instance: Instance): 
	root = op('/')
	scanOp(instance, root)

def scanOp(instance: Instance, operator):
	for child in operator.children:
		if "rship" in list(child.tags):
			saveTarget(instance, child)
		scanOp(instance, child)
	
	
def saveTarget(instance: Instance, operator) -> None:

	parTargets: [Target] = []


	# get pars
	for par in operator.customPars:
		parTargetId = operator.path + ":" + par.name

		type = "string"

		if par.style == 'Float' or par.style == 'Int':
			type = "number"
		elif par.style == 'Toggle':
			type = "boolean"

		setSchema = {
			"type": "object",
			"properties": {
				"value": {
					"type": type
				}
			},
			"required": [
				"value"
			]
		}

		setAction = Action(
			id=parTargetId + ":set",
			name="Set " + par.name,
			targetId=parTargetId,
			systemId=instance.serviceId,
			schema=setSchema,
		)

		def handle(action, data):
			chunks = action.id.split(":")
			parName = chunks[1]
			operator.par[parName] = data['value']

		handlers[setAction.id] = handle
	
		valueEmitter = Emitter(
			id=parTargetId + ":valueUpdated",
			name=par.name + " Value Updated",
			targetId=parTargetId,
			serviceId=instance.serviceId
		)

		# make target for each par
		t = Target(
			id=parTargetId,
			name=par.name,
			actionIds=[setAction.id],
			emitterIds=[valueEmitter.id],
			subTargets=[],
			serviceId=instance.serviceId,
			category="Parameter",
			bgColor="#5d6448",
			fgColor="#5d6448",
			lastUpdated=datetime.now(timezone.utc).isoformat(),
			rootLevel=False
		)

		parTargets.append(t)
		# save those targets
		targets[t.id] = t
		targetStatuses[t.id] = TargetStatus(
			id=t.id + ":status",
			name=t.name + " Status",
			targetId=t.id,
			instanceId=instance.id,
			status=Status.Online,
			lastUpdated=datetime.now(timezone.utc).isoformat()
		)

		# save actions
		actions[setAction.id] = setAction

		# save emitters
		emitters[valueEmitter.id] = valueEmitter
		

	# include as subtargets of base node

	target = Target(
		id=operator.path, 
		name=operator.name, 
		actionIds=[], 
		emitterIds=[], 
		subTargets=list(map(lambda t: t.id, parTargets)),
		serviceId=instance.serviceId, 
		category="Base Comp",
		bgColor="#5d6448", 
		fgColor="#5d6448", 
		lastUpdated=datetime.now(timezone.utc).isoformat(),
		rootLevel=True
	)

	targets[target.id] = target
	targetStatuses[target.id] = TargetStatus(
		id=target.id + ":status",
		name=target.name + " Status",
		targetId=target.id,
		status=Status.Online,
		instanceId=instance.id,
		lastUpdated=datetime.now(timezone.utc).isoformat()
	)



##################################
# Websocket DAT Callbacks
##################################

def onConnect(dat):
	client.setSend(dat.sendText)
	machine = Machine(socket.gethostname())
	clientId = op('script1')[0, 0].val

	projectfile = project.name
	sections = projectfile.split(".")
	serviceId = ".".join(sections[:-2])

	instance = Instance(id=machine.id+":"+serviceId, name=serviceId, serviceId=serviceId, execId=clientId, serviceTypeCode="touchdesigner", status=InstanceStatus.Available, machineId=machine.id)
	client.set(machine)
	client.set(instance)

	scanTargets(instance)
	
	for target in targets.values():
		client.set(target)
	
	for targetStatus in targetStatuses.values():
		client.set(targetStatus)

	for action in actions.values():
		client.set(action)

	for emitter in emitters.values():
		client.set(emitter)

	return

# me - this DAT
# dat - the WebSocket DAT

def onDisconnect(dat):
	if client:
		client.log("disconnected")
	return

# me - this DAT
# dat - the DAT that received a message
# rowIndex - the row number the message was placed into
# message - a unicode representation of the text
# 
# Only text frame messages will be handled in this function.

def onReceiveText(dat, rowIndex, message):
	client.parseMessage(message)
	return

def onReceiveBinary(dat, contents):
	return

def onReceivePing(dat, contents):
	dat.sendPong(contents) # send a reply with same message
	return


def onReceivePong(dat, contents):
	return

def onMonitorMessage(dat, message):
	print(message)
	return