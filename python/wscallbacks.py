import json
from enum import Enum
import socket


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


##################################
# Rship Executor API
##################################

class Target(MItem) :
	def __init__(self, id: str, name: str, actionIds: [str], emitterIds: [str], subTargets: [str], serviceId: str, bgColor: str, fgColor: str, lastUpdated: str):
		super().__init__(id, name)

		self.actionIds = actionIds
		self.emitterIds = emitterIds
		self.subTargets = subTargets
		self.serviceId = serviceId
		self.bgColor = bgColor
		self.fgColor = fgColor
		self.lastUpdated = lastUpdated

class Action(MItem): 
	def __init__(self, id: str, name: str, targetId: str, systemId: str, schema: str =  None):
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

##################################
# Websocket MykoClient
##################################

# class that handles the cached version of the touch targets, instances, actions, etc for rocketship. 
class MykoClient:
	
	def __init__(self, send):
		self.send = send

	def log(self, message):
		print("MykoClient: " + message)

	def sendEvent(self, event: MEvent):

		text = json.dumps(WSEvent(event).__dict__)
		print("sending event", text)
		self.send(text)

	def set(self, item: MItem):
		event = MEvent(changeType=MEventType.SET, item=item)
		self.sendEvent(event)


##################################
# Websocket DAT Callbacks
##################################

# me - this DAT
# dat - the WebSocket DAT
client: MykoClient = None

def onConnect(dat):
	client = MykoClient(dat.sendText)
	client.log("connected")
	machine = Machine(socket.gethostname())
	clientId = op('script1')[0, 0].val

	projectfile = project.name
	sections = projectfile.split(".")
	serviceId = ".".join(sections[:-2])

	instance = Instance(id=machine.id+":"+serviceId, name=serviceId, serviceId=serviceId, execId=clientId, serviceTypeCode="touchdesigner", status=InstanceStatus.Available, machineId=machine.id)
	client.set(machine)
	client.set(instance)
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
	print("onReceiveText", rowIndex, message)
	return


# me - this DAT
# dat - the DAT that received a message
# contents - a byte array of the message contents
# 
# Only binary frame messages will be handled in this function.

def onReceiveBinary(dat, contents):
	print("receive binary")
	return

# me - this DAT
# dat - the DAT that received a message
# contents - a byte array of the message contents
# 
# Only ping messages will be handled in this function.

def onReceivePing(dat, contents):
	print("receivePing")
	dat.sendPong(contents) # send a reply with same message
	return

# me - this DAT
# dat - the DAT that received a message
# contents - a byte array of the message content
# 
# Only pong messages will be handled in this function.

def onReceivePong(dat, contents):
	print("receive pong")
	return


# me - this DAT
# dat - the DAT that received a message
# message - a unicode representation of the message
#
# Use this method to monitor the websocket status messages

def onMonitorMessage(dat, message):
	print(message)
	return

	
