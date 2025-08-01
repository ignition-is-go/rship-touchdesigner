from enum import Enum
from typing import List
from uuid import uuid4

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


class MWrappedItem:
	def __init__(self, data: any):
		self.itemType = data.get('itemType', None)
		self.item = data.get('item', None)

class WSEvent: 
	def __init__(self, data: MEvent): 
		self.data = data.__dict__
		self.event = "ws:m:event"

class MQuery:
	def __init__(self) -> None:
		self.tx = str(uuid4())


class MWrappedQuery:
	def __init__(self, queryId: str, queryItemType: str, query: MQuery):
		self.queryId: str = queryId
		self.queryItemType: str = queryItemType
		self.query: MQuery = query.__dict__

class WSCommand: 
	def __init__(self, data: any):
		self.event = 'ws:m:command'
		self.data = data.__dict__

class WSQuery:
	def __init__(self, data: any):
		self.event = 'ws:m:query'
		self.data = data.__dict__

class MCommand: 
	def __init__(self, createdAt: str):
		self.tx = str(uuid4())
		self.createdAt = createdAt


class MWrappedCommand: 
	def __init__(self,  data: MCommand):
		self.command = data.__dict__
		self.commandId = type(data).__name__

class QueryResponse: 
	def __init__(self, data: any):
		self.tx: str = data['tx']
		self.upserts: List[MWrappedItem] = [MWrappedItem(item) for item in data.get('upserts', [])]
		self.deletes: List[str] = data.get('deletes', [])
		self.sequence: int = data.get('sequence', 0)
