import socket
from exec import Instance, InstanceStatus, Machine,  Target, TargetStatus, Action, Emitter, Status
from registry import client
from datetime import datetime, timezone

ops = []

def scanTargets(instance: Instance): 
	ops.clear()
	root = op('/')
	scanOp(instance, root)

	parexec = op("../../parexec1")

def scanOp(instance: Instance, operator):
	for child in operator.children:
		if "rship" in list(child.tags):
			makeTarget(instance, child)
		scanOp(instance, child)
	
	
def makeTarget(instance: Instance, operator) -> None:
	targetId = instance.serviceId + ":" + operator.path
	ops.append(operator)
	parTargets: [Target] = []

	# get pars
	for par in operator.customPars:
		parTargetId = targetId + ":" + par.name


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
			parName = chunks[2]
			operator.par[parName] = data['value']

		client.saveHandler(setAction.id, handle)
	
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
		client.saveTarget(t)
		client.setTargetStatus(t, instance, Status.Online)

		# save actions

		client.saveAction(setAction)

		# save emitters
		client.saveEmitter(valueEmitter)		

	# include as subtargets of base node

	target = Target(
		id=targetId, 
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

	client.saveTarget(target)
	client.setTargetStatus(target, instance, Status.Online)

def handleConnect(dat):
	client.setSend(dat.sendText)
	refresh()
	return

def refresh(): 
	client.log("refreshing")

	op('../../parexec1').cook(force=True)

	machine = makeMachine()
	instance = makeInstance()

	client.set(machine)
	client.set(instance)

	scanTargets(instance)

	targets = client.targets

	for target in targets.values():
		
		sections = targetId.split(":")
		opPath = sections[1]
		operator = op(opPath)
		if(type(operator) == type(None)):
			client.setTargetOffline(target, instance)
	
	return

def pulseEmitter(opPath: str, parName: str, data: any):
	instance = makeInstance()
	emitterId = instance.serviceId + ":" + opPath + ":" + parName + ":valueUpdated"
	
	client.pulseEmitter(emitterId=emitterId,data=data)
	return

def makeMachine() -> Machine: 
	machine = Machine(socket.gethostname())
	return machine

def makeInstance() -> Instance:
	projectfile = project.name
	sections = projectfile.split(".")
	
	machine = makeMachine() 
	
	serviceId = sections[0]
	clientId = op('../../script1')[0, 0].val

	instance = Instance(id=machine.id+":"+serviceId, name=serviceId, serviceId=serviceId, execId=clientId, serviceTypeCode="touchdesigner", status=InstanceStatus.Available, machineId=machine.id)
	return instance

def handleMessage(dat, message):
	client.parseMessage(message)

def handleDisconnect(dat): 
	client.log("disconnected")