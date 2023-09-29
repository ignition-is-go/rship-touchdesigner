from enum import Enum

class MEventType(Enum): 
	SET = 'SET'
	DEL = 'DEL'

class MItem: 
	def __init__(self, id: str, name: str):
		self.id = id
		self.name = name

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

