from datetime import datetime, timezone
import json
from myko import MEvent, MEventType, MItem, MCommand, QueryResponse, WSEvent, MQuery, MWrappedQuery, WSQuery, WSCommand, MWrappedCommand
from uuid import uuid4
from enum import Enum
from typing import Dict, List, Callable, Self



class Target(MItem):
    def __init__(self, id: str, name: str,  parentTargets: List[str], serviceId: str, bgColor: str, fgColor: str, lastUpdated: str, category: str, rootLevel: bool):
        super().__init__(id, name)

        self.subTargets = []
        self.serviceId = serviceId
        self.bgColor = bgColor
        self.fgColor = fgColor
        self.lastUpdated = lastUpdated
        self.category = category
        self.rootLevel = rootLevel
        self.parentTargets = parentTargets


class Status(Enum):
    Online = 'online'
    Offline = 'offline'


class TargetStatus(MItem):
    def __init__(self, id: str, name: str, targetId: str, status: Enum, lastUpdated: str, instanceId: str):
        super().__init__(id, name)

        self.targetId = targetId
        self.status = status.value
        self.lastUpdated = lastUpdated
        self.instanceId = instanceId


class Action(MItem):
    def __init__(self, id: str, name: str, targetId: str, serviceId: str, schema: str, handler: Callable[[Self, Dict[str, any]], None]):
        super().__init__(id, name)

        self.schema = schema
        self.targetId = targetId
        self.serviceId = serviceId
        self.handler = handler


class Emitter(MItem):
    def __init__(self, id: str, name: str, targetId: str, serviceId: str, schema: any, changeKey: str, handler: Callable):
        super().__init__(id, name)

        self.targetId = targetId
        self.serviceId = serviceId
        self.schema = schema
        self.changeKey = changeKey
        self.handler = handler          
        


class Pulse(MItem):
    def __init__(self, id: str, name: str, emitterId: str, data: any):
        super().__init__(id, name)

        self.emitterId = emitterId
        self.data = data
        self.hash = str(uuid4())


class InstanceStatus(Enum):
    Starting = 'Starting'
    Available = 'Available'
    Stopping = 'Stopping'
    Unavailable = 'Unavailable'
    Error = 'Error'


class Instance(MItem):
    def __init__(self, id: str, name: str, serviceId: str, serviceTypeCode: str, status: InstanceStatus, machineId: str, color: str):
        super().__init__(id, name)

        self.serviceId = serviceId
        self.serviceTypeCode = serviceTypeCode
        self.status = status.value
        self.machineId = machineId
        self.color = color


class Machine(MItem):
    name: str
    dnsName: str
    execName: str
    address: str

    def __init__(self, id: str, name: str):
        super().__init__(id, name)
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
        super().__init__(createdAt)
        self.action = action
        self.data = data

class Stream(MItem):
    id: str
    name: str

    def __init__(self, id: str, name: str):
        super().__init__(id, name)
        self.id = id


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


class AddAnswerCandidate(MCommand):
    def __init__(self, id: str, candidate: IceCandidate):
        super().__init__(str(datetime.now(timezone.utc).isoformat()))
        self.candidate = candidate.__dict__
        self.id = id

class SetAnswer(MCommand):
    def __init__(self, id: str,  sdpAnswer: str):
        super().__init__(str(datetime.now(timezone.utc).isoformat()))
        self.sdpAnswer = sdpAnswer
        self.id = id
    

# CLIENT

# class that handles the cached version of the touch targets, instances, actions, etc for rocketship.
class ExecClient:
    def __init__(self) -> None:
        # self.targets: Dict[str, Target] = {}
        self.targetStatuses: Dict[str, TargetStatus] = {}
        self.actions: Dict[str, Action] = {}
        # self.emitters: Dict[str, Emitter] = {}
        self.handlers: Dict[str, callable] = {}
        self.clientId: str = None
        self.webRtcConnections: Dict[str, str] = {} # localConnectionId: remoteConnectionId

        self.queryHandlers: Dict[str, callable] = {}

    def setSend(self, send):
        self.send = send

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
        try:
            d = json.loads(message)

            if d['event'] == 'ws:m:command':
                self.parseCommand(d['data'])
            if d['event'] == 'ws:m:query-response':
                self.parseQueryResponse(d['data'])
        except json.JSONDecodeError as e:
            self.log("Error parsing message: " + str(e))
            self.log("Message was: " + message)
            

    def sendQuery(self, query: MQuery, queryItemType: str, handler: Callable[[QueryResponse], None]):
        wrappedQuery = MWrappedQuery(
            queryId=type(query).__name__,
            queryItemType=queryItemType,
            query=query,
        )
        self.queryHandlers[query.tx] = handler

        text = json.dumps(WSQuery(wrappedQuery).__dict__)
        self.send(text)

    def sendCommand(self, command: MCommand):
        wrappedCommand = MWrappedCommand(command)
        text = json.dumps(WSCommand(wrappedCommand).__dict__)
        self.send(text)


    def parseCommand(self, data):
        if data['commandId'] == 'ExecTargetAction':

            commandId = data['command']['action']['id']

            if not commandId in self.actions:
                self.log("No action found for id: " + commandId)
                return

            action = self.actions[data['command']['action']['id']]
            c = ExecTargetAction(
                tx=data['command']['tx'],
                createdAt=data['command']['createdAt'],
                action=action,
                data=data['command']['data']
            )
            self.handleExecTargetAction(c)

    def parseQueryResponse(self, data):

        tx = data.get('tx', None)
        if not tx:
            self.log("No tx in query response data")
            return
        


        handler = self.queryHandlers.get(tx, None)
        if not handler:
            # self.log("No handler found for query tx: " + tx)
            return
        handler(QueryResponse(data))

    def handleExecTargetAction(self, command: ExecTargetAction):
        if command.action.id in self.handlers:
            handler = self.handlers[command.action.id]
            handler(command.action, command.data)

    def saveTarget(self, target: Target):
        # self.targets[target.id] = target
        self.set(target)

    def setTargetOffline(self, targetId: str, instanceId: str):
        self.setTargetStatus(targetId, instanceId, Status.Offline)

    def setTargetStatus(self, targetId: str, instanceId: str, status: Status):

        ts = TargetStatus(
            id=targetId + ":status",
            name=targetId + " Status",
            targetId=targetId,
            instanceId=instanceId,
            status=status,
            lastUpdated=datetime.now(timezone.utc).isoformat()
        )

        # self.targetStatuses[ts.id] = ts
        self.set(ts)

    def saveAction(self, action: Action):
        self.actions[action.id] = action
        self.set(action)

    def saveEmitter(self, emitter: Emitter):
        # self.emitters[emitter.id] = emitter
        self.set(emitter)

    def pulseEmitter(self, emitterId: str, data: any):
        p = Pulse(
            id=emitterId,
            name="Pulse",
            emitterId=emitterId,
            data=data
        )
        self.set(p)

    # def removeTarget(self, targetId: str):
    #     pass
        # if targetId not in self.targets:
        #     return

        # del self.targets[targetId]

		# # find all actions related to this targetId
        # for actionId, action in self.actions.items():
        #     if action.targetId == targetId:
        #         self.removeHandler(actionId)

    def saveHandler(self, actionId: str, handler: Callable[[Action, Dict[str, any]], None]):
        self.handlers[actionId] = handler

    def removeHandler(self, actionId: str):
        if actionId in self.handlers:
            print("removing handler for", actionId)
            del self.handlers[actionId]







CLIENT = ExecClient()