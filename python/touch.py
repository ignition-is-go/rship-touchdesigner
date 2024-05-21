import socket
from exec import Instance, InstanceStatus, Machine,  Target, TargetStatus, Action, Emitter, Status
from registry import client
from datetime import datetime, timezone

ops = []


def scanTargets(instance: Instance): 
	ops.clear()
	root = op('/')
	scanOp(instance, root)

def scanOp(instance: Instance, operator):
	for child in operator.children:
		if "rship" in list(child.tags):
			makeTarget(instance, child)
		scanOp(instance, child)
	
def makeParTarget(instance: Instance, operator, par, parentId) -> None:
	parTargetId = parentId + ":" + par.name
	type = "string"

	if par.style == 'Float' or par.style == 'Int':
		type = "number"
	elif par.style == 'Toggle':
		type = "boolean"
	elif par.style == 'Pulse':
		type = "null"

	schema = {
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
		name="Set " + par.label,
		targetId=parTargetId,
		serviceId=instance.serviceId,
		schema=schema,
	)

	def handle(action, data):
		chunks = action.id.split(":")
		parName = chunks[2]
		if 'value' in data.keys():
			operator.par[parName] = data['value']
		else: 
			operator.par[parName].pulse()

	client.saveHandler(setAction.id, handle)

	valueEmitter = Emitter(
		id=parTargetId + ":valueUpdated",
		name=par.label + " Value Updated",
		targetId=parTargetId,
		serviceId=instance.serviceId,
		schema=schema
	)

	clarification = ""
	if par.name.lower() != par.label.replace(" ", "").lower():
		clarification = " (" + par.name + ")"

	# make target for each par
	t = Target(
		id=parTargetId,
		name=par.label + clarification,
		actionIds=[setAction.id],
		emitterIds=[valueEmitter.id],
		parentTargets=[parentId],
		serviceId=instance.serviceId,
		category="Parameter",
		bgColor="#727e51",
		fgColor="#727e51",
		lastUpdated=datetime.now(timezone.utc).isoformat(),
		rootLevel=False
	)

	# save those targets
	client.saveTarget(t)
	client.setTargetStatus(t, instance, Status.Online)

	# save actions

	client.saveAction(setAction)

	# save emitters
	client.saveEmitter(valueEmitter)

def makePageTarget(instance: Instance, operator, page, parentId) -> None:
	pageTargetId = instance.serviceId + ":" + operator.path + ":" + page.name

	# make target for each page
	t = Target(
		id=pageTargetId,
		name=page.name,
		actionIds=[],
		emitterIds=[],
		parentTargets=[parentId],
		serviceId=instance.serviceId,
		category="Page",
		bgColor="#727e51",
		fgColor="#727e51",
		lastUpdated=datetime.now(timezone.utc).isoformat(),
		rootLevel=False
	)

	# save those targets
	client.saveTarget(t)
	client.setTargetStatus(t, instance, Status.Online)

	for par in page.pars:
		makeParTarget(instance, operator, par, pageTargetId)
	
def makeTarget(instance: Instance, operator) -> None:

	targetId = instance.serviceId + ":" + operator.path
	ops.append(operator)

	# get pars
	for par in operator.customPars:
		makeParTarget(instance, operator, par, targetId)

	# has page named notch
	hasPageNamedNotch = False

	for page in operator.pages: 
		if page.name == "Notch":
			hasPageNamedNotch = True
			for par in page.pars:
				makeParTarget(instance, operator, par, targetId)
		if page.name == "Common":
			continue

		if not hasPageNamedNotch:
			continue
		
		makePageTarget(instance, operator, page, targetId)


	disableAction = Action(id=targetId+":disable", name="Disable", targetId=targetId, serviceId=instance.serviceId, schema=None)
	enableAction = Action(id=targetId+":enable", name="Enable", targetId=targetId, serviceId=instance.serviceId, schema=None)

	def handleDisable(action, data):
		operator.allowCooking = False

	def handleEnable(action, data):
		operator.allowCooking = True

	client.saveHandler(disableAction.id, handleDisable)
	client.saveHandler(enableAction.id, handleEnable)

	client.saveAction(enableAction)
	client.saveAction(disableAction)

	target = Target(
		id=targetId, 
		name=operator.name, 
		actionIds=[enableAction.id, disableAction.id], 
		emitterIds=[], 
		parentTargets=[],
		serviceId=instance.serviceId, 
		category="Base Comp",
		bgColor="#727e51", 
		fgColor="#727e51", 
		lastUpdated=datetime.now(timezone.utc).isoformat(),
		rootLevel=True
	)

	client.saveTarget(target)
	client.setTargetStatus(target, instance, Status.Online)

def handleConnect(dat):
	client.setSend(dat.sendText)
	op('../../..').par.Connected = True
	client.onExecConnected(refresh)
	return

def refresh(): 
	
	if not hasattr(client, 'clientId'):
		print("skipping refresh, no clientId")
		return
	client.log("refreshing...")


	op('../../emitters').cook(force=True)
	op('../../..').par.Clientid = client.clientId

	machine = makeMachine()
	instance = makeInstance(client.clientId)

	client.set(machine)
	client.set(instance)

	scanTargets(instance)

	targets = client.targets

	for target in targets.values():
		
		sections = target.id.split(":")
		opPath = sections[1]
		operator = op(opPath)
		if(type(operator) == type(None)):
			client.setTargetOffline(target, instance)
		else:
			if len(sections) > 2:
				parName = sections[-1]
				if not hasattr(operator.par, parName):
					client.setTargetOffline(target, instance)

	
	return

def pulseEmitter(opPath: str, parName: str, data: any):
	if(client.clientId == None):
		client.log("Cant pulse emitter without clientid")
		return

	instance = makeInstance(client.clientId)
	emitterId = instance.serviceId + ":" + opPath + ":" + parName + ":valueUpdated"
	
	client.pulseEmitter(emitterId=emitterId,data={'value': data})
	return

def makeMachine() -> Machine: 
	machine = Machine(socket.gethostname())
	return machine

def makeInstance(clientId: str) -> Instance:
	projectfile = project.name
	sections = projectfile.split(".")
	
	machine = makeMachine() 
	
	serviceId = sections[0]

	instance = Instance(
		id=machine.id+":"+serviceId, 
		name=serviceId, 
		serviceId=serviceId, 
		clientId=clientId, 
		serviceTypeCode="touchdesigner", 
		status=InstanceStatus.Available, 
		machineId=machine.id, color="#727e51"
	)
	return instance

def handleMessage(dat, message):
	client.parseMessage(message)

def handleDisconnect(dat): 
	op('../../..').par.Connected = False
	client.log("disconnected")

