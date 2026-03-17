from datetime import datetime, timezone
from enum import Enum
from typing import List
from uuid import uuid4


def iso_now() -> str:
	return datetime.now(timezone.utc).isoformat()


class MEventType(Enum):
	SET = 'SET'
	DEL = 'DEL'


class MItem:
	def __init__(self, id: str, name: str):
		self.id = id
		self.name = name


class MEvent:
	def __init__(
		self,
		changeType: MEventType,
		item: MItem | dict,
		itemType: str | None = None,
		tx: str | None = None,
		createdAt: str | None = None,
		sourceId: str | None = None,
		options: dict | None = None,
	):
		self.changeType = changeType.value
		self.item = item if isinstance(item, dict) else item.__dict__
		self.itemType = itemType or type(item).__name__
		self.createdAt = createdAt or iso_now()
		self.tx = tx or str(uuid4())
		self.sourceId = sourceId
		if options is not None:
			self.options = options


class MWrappedItem:
	def __init__(self, data: any):
		self.itemType = data.get('itemType', None)
		self.item = data.get('item', None)


class QueryChange:
	def __init__(self, data: any):
		self.kind = data.get('kind', None)
		self.item = data.get('item', None)
		self.id = data.get('id', None)
		self.ids = data.get('ids', [])
		self.totalCount = data.get('totalCount', data.get('total_count', None))
		self.window = data.get('window', None)


class WSEvent:
	def __init__(self, data: MEvent):
		self.data = data.__dict__
		self.event = 'ws:m:event'


class WSEventBatch:
	def __init__(self, data: List[MEvent]):
		self.data = [event.__dict__ for event in data]
		self.event = 'ws:m:event-batch'


class MQuery:
	def __init__(self) -> None:
		self.tx = str(uuid4())
		self.createdAt = iso_now()


class MWrappedQuery:
	def __init__(self, queryId: str, queryItemType: str, query: MQuery):
		self.queryId: str = queryId
		self.queryItemType: str = queryItemType
		self.query: dict = query.__dict__


class MReport:
	def __init__(self) -> None:
		self.tx = str(uuid4())
		self.createdAt = iso_now()


class MWrappedReport:
	def __init__(self, reportId: str, report: MReport):
		self.reportId: str = reportId
		self.report: dict = report.__dict__


class WSCommand:
	def __init__(self, data: any):
		self.event = 'ws:m:command'
		self.data = data.__dict__ if hasattr(data, '__dict__') else data


class WSQuery:
	def __init__(self, data: any):
		self.event = 'ws:m:query'
		self.data = data.__dict__ if hasattr(data, '__dict__') else data


class WSReport:
	def __init__(self, data: any):
		self.event = 'ws:m:report'
		self.data = data.__dict__ if hasattr(data, '__dict__') else data


class MCommand:
	def __init__(self, createdAt: str | None = None, tx: str | None = None):
		self.tx = tx or str(uuid4())
		self.createdAt = createdAt or iso_now()


class MWrappedCommand:
	def __init__(self, data: MCommand):
		self.command = data.__dict__
		self.commandId = type(data).__name__


class QueryResponse:
	def __init__(self, data: any):
		self.tx: str = data['tx']
		self.upserts: List[MWrappedItem] = [
			MWrappedItem(item) for item in data.get('upserts', [])
		]
		self.deletes: List[str] = data.get('deletes', [])
		self.sequence: int = data.get('sequence', 0)
		self.changes: List[QueryChange] = [
			QueryChange(change) for change in data.get('changes', [])
		]
		self.totalCount: int | None = data.get('totalCount', data.get('total_count', None))
		self.window = data.get('window', None)


class QueryError:
	def __init__(self, data: any):
		self.tx: str = data.get('tx', '')
		self.queryId: str = data.get('queryId', '')
		self.message: str = data.get('message', '')


class ReportResponse:
	def __init__(self, data: any):
		self.tx: str = data.get('tx', '')
		self.response = data.get('response', None)


class ReportError:
	def __init__(self, data: any):
		self.tx: str = data.get('tx', '')
		self.reportId: str = data.get('reportId', '')
		self.message: str = data.get('message', '')


class CommandResponse:
	def __init__(self, tx: str, response: any = None):
		self.tx = tx
		self.response = response


class CommandError:
	def __init__(self, tx: str, commandId: str, message: str):
		self.tx = tx
		self.commandId = commandId
		self.message = message
