"""
Extension classes enhance TouchDesigner components with python. An
extension is accessed via ext.ExtensionClassName from any operator
within the extended component. If the extension is promoted via its
Promote Extension parameter, all its attributes with capitalized names
can be accessed externally, e.g. op('yourComp').PromotedFunction().

Help: search "Extensions" in wiki
"""
from TDStoreTools import StorageManager
import TDFunctions as TDF
import socket
from exec import ExecClient, Instance, Machine, InstanceStatus
from touch import makeOpTarget, cleanDeleted, pulseEmitter
from handle_webrtc import init as initWebRTC, handle_on_answer, handle_on_ice_candidate

class RshipExt:

	def __init__(self, ownerComp):
		self.ownerComp = ownerComp
		self.findTargetsOp = self.ownerComp.op('find_targets')
		
		self.machineIdOp = self.ownerComp.op('machine_id')

		self.websocketOp = self.ownerComp.op('websocket')

		self.targetsOp = self.ownerComp.op('path_and_pars')
		
		


		self.client = ExecClient()
		self.client.setSend(self.websocketOp.sendText)


		self.OnProjectPreSave()

		TDF.createProperty(self, 'MachineId', value=None, dependable=True,
						   readOnly=False)


		TDF.createProperty(self, 'Connection', value="Disconnected", dependable=True, readOnly=False)
		self.clientIdRequests = {}

		self.ops = {}

		self.instance: Instance | None = None


	def OnProjectPreSave(self):
		self.findTargets()
		self.updateMachineId()


	def OnMachineIdClientConnect(self, requestId: str):
		self.clientIdRequests[requestId] = True

	
	def OnMachineIdClientDisconnect(self, requestId: str):
		if requestId in self.clientIdRequests:
			del self.clientIdRequests[requestId]
			print("[RshipExt]: Machine Id Request Failed, falling back to hostname")
			self.MachineId = socket.gethostname()
			# if the machine id not coming from the Rship Link, we need to provide Rship with our machine
			machine = Machine(self.MachineId, socket.gethostname())
			self.client.set(machine)
			self.afterMachineId()


	def OnMachineIdUpdate(self, machineId: str | None, requestId: str):
		if requestId in self.clientIdRequests:
			del self.clientIdRequests[requestId]
		
		print("[RshipExt]: Machine ID updated from Rship Link:", machineId)
		self.MachineId = machineId
		self.afterMachineId()
		# since machineId is coming from the Rship Link, we need not send the machine info


	def afterMachineId(self):
		self.buildInstance()
		self.client.set(self.instance)
		self.buildTargets()


	def OnRshipConnect(self):
		self.Connection = "Connected"
		print("[RshipExt]: Connected to Rship Server at ", self.websocketOp.par.netaddress.eval())
		self.findTargets()
		self.updateMachineId()
		initWebRTC(self.client)


	def OnRshipDisconnect(self):
		self.Connection = "Disconnected"
		print("[RshipExt]: Disconnected from Rship Server")
		pass

	def OnRshipReceiveText(self, text: str):
		self.client.parseMessage(text)
		pass


	def findTargets(self):
		print("[RshipExt]: Finding targets...")
		self.findTargetsOp.cook(force=True)
		

	def updateMachineId(self):
		print("[RshipExt]: Updating machine ID from Rship Link...")
		self.machineIdOp.par.request.pulse()



	def buildInstance(self): 
		projectfile = project.name
		sections = projectfile.split(".")
		
		
		serviceId = sections[0]

		instance = Instance(
			id=self.MachineId+":"+serviceId, 
			name=serviceId, 
			serviceId=serviceId, 
			serviceTypeCode="touchdesigner", 
			status=InstanceStatus.Available, 
			machineId=self.MachineId, color="#727e51"
		)

		self.instance = instance
		print(f"[RshipExt]: Instance created:\n  ID: {instance.id},\n  Name: {instance.name}")


	def buildTargets(self):

		print("[RshipExt]: Building targets...")

		ops = [op(self.targetsOp[i, 0].val) for i in range(0, self.targetsOp.numRows)]

		print("[RshipExt]: Found", len(ops), "targets")
		
		if self.instance is None:
			print("[RshipExt]: Instance is not set, cannot build targets")
			return

		if self.client is None:
			print("[RshipExt]: Client is not set, cannot build targets")
			return

		for o in ops: 
			makeOpTarget(self.client, self.instance, o)

		cleanDeleted(self.client, self.instance)

	def PulseEmitter(self, opPath: str, parName: str):
		pulseEmitter(opPath, parName, self.client)


	def HandleWebRTCAnswer(self, connectionId: str, localSdp: str):
		handle_on_answer(connectionId, localSdp, self.client)


	def HandleWebRTCIceCandidate(self, connectionId: str, candidate: str, sdpMid: str, lineIndex: int):
		handle_on_ice_candidate(connectionId, candidate, sdpMid, lineIndex, self.client)