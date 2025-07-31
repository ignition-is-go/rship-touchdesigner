# import socket
from exec import Instance, InstanceStatus, Machine,  Target, TargetStatus, Action, Emitter, Status, ExecClient
from datetime import datetime, timezone
from handle_webrtc import assertStream
import uuid

ops = {}

def makeParGroupTarget(client: ExecClient, instance: Instance, operator, parGroup, parentId, baseId) -> None:

	parTargetId = baseId + ":" + parGroup.name
	properties = None


	if parGroup.style == 'Float' or parGroup.style == 'Int':

		if parGroup.size > 1:
			properties = {}
			for i in parGroup.subLabel:
				properties[i] = {
					"type": "number",
					"minimum": parGroup.min,
					"maximum": parGroup.max,
				}
		else:
			properties = {
				"value": {
					"type": "number",
					"minimum": parGroup.min,
					"maximum": parGroup.max,
				}
			}

	elif parGroup.style == 'Str':
		properties = {
			"value": {
				"type": "string"
			}
		}
		

	elif parGroup.style == 'Toggle':

		properties = {
			"value": {
				"type": "boolean"
			}
		}

	elif parGroup.style == 'Pulse':
		properties = {
			"value": {
				"type": "null"
			}
		}

	elif parGroup.style == 'WH':
		properties = {
			"w": {
				"type": "number"
			},
			"h": {
				"type": "number"
			}
		}


	elif parGroup.style == 'XY':
		properties = {
			"x": {
				"type": "number"
			},
			"y": {
				"type": "number"	
			}
		}

	elif parGroup.style == 'XYZ':
		properties = {
			"x": {
				"type": "number"
			},
			"y": {
				"type": "number"
			},
			"z": {
				"type": "number"
			}
		}

	elif parGroup.style == 'XYZW':
		properties = {
			"x": {
				"type": "number"
			},
			"y": {
				"type": "number"
			},
			"z": {
				"type": "number"
			},
			"w": {
				"type": "number"
			}
		}

	elif parGroup.style == 'RGB':
		properties = {
			"r": {
				"type": "number",
				"minimum": 0,
				"maximum": 1
			},
			"g": {
				"type": "number",
				"minimum": 0,
				"maximum": 1
			},
			"b": {
				"type": "number",
				"minimum": 0,
				"maximum": 1
			}
		}

	elif parGroup.style == 'RGBA':
		properties = {
			"r": {
				"type": "number",
				"minimum": 0,
				"maximum": 1
			},
			"g": {
				"type": "number",
				"minimum": 0,
				"maximum": 1
			},
			"b": {
				"type": "number",
				"minimum": 0,
				"maximum": 1
			},
			"a": {
				"type": "number",
				"minimum": 0,
				"maximum": 1
			}
		}

	elif parGroup.style == 'UV':
		properties = {
			"u": {
				"type": "number",
				"minimum": 0,
				"maximum": 1
			},
			"v": {
				"type": "number",
				"minimum": 0,
				"maximum": 1
			}
		}

	elif parGroup.style == 'UVW':
		properties = {
			"u": {
				"type": "number",
				"minimum": 0,
				"maximum": 1
			},
			"v": {
				"type": "number",
				"minimum": 0,
				"maximum": 1
			},
			"w": {
				"type": "number",
				"minimum": 0,
				"maximum": 1
			}
		}

	
	if parGroup.style == 'Menu' or parGroup.style == 'StrMenu':
		oneOf = []

		for i in range(len(parGroup.menuNames[0])):
			oneOf.append({
				'const': parGroup.menuNames[0][i],
				'title': parGroup.menuLabels[0][i]
			})

		properties = {
			'value': {
				'type': 'string',
				'oneOf': oneOf
			}
		}


	if parGroup.style == 'File':
		properties = {
			"value": {
				"$ref": "asset-path",
			}
		}

	if parGroup.style == 'Sequence':
		makeSequenceActionEmitters(client, instance, operator, parGroup, parTargetId)

	if properties is not None: 

		schema = {
			"type": "object",
			"properties": properties,
		}

		setAction = Action(
			id=parTargetId + ":set",
			name="Set " + parGroup.label,
			targetId=parTargetId,
			serviceId=instance.serviceId,
			schema=schema,
		)

		def handle(action, data):

			try: 
				parGroup.name
			except: 
				print("Parameter not found, Deleting Action")
				client.removeHandler(action.id)
				return

			parName = parGroup.name

			if parGroup.style == 'WH' and 'w' in data.keys() and 'h' in data.keys():
				operator.par[parName + "w"] = data['w']
				operator.par[parName + "h"] = data['h']
				return

			if parGroup.style == 'XY' and 'x' in data.keys() and 'y' in data.keys():
				operator.par[parName + "x"] = data['x']
				operator.par[parName + "y"] = data['y']
				return
			
			
			if parGroup.style == 'XYZ' and 'x' in data.keys() and 'y' in data.keys() and 'z' in data.keys():
				operator.par[parName + "x"] = data['x']
				operator.par[parName + "y"] = data['y']
				operator.par[parName + "z"] = data['z']
				return
			
			if parGroup.style == 'XYZW' and 'x' in data.keys() and 'y' in data.keys() and 'z' in data.keys() and 'w' in data.keys():
				operator.par[parName + "x"] = data['x']
				operator.par[parName + "y"] = data['y']
				operator.par[parName + "z"] = data['z']
				operator.par[parName + "w"] = data['w']
				return
			
			if parGroup.style == 'RGB' and 'r' in data.keys() and 'g' in data.keys() and 'b' in data.keys():
				operator.par[parName + "r"] = data['r']
				operator.par[parName + "g"] = data['g']
				operator.par[parName + "b"] = data['b']
				return
			
			if parGroup.style == 'RGBA' and 'r' in data.keys() and 'g' in data.keys() and 'b' in data.keys() and 'a' in data.keys():
				operator.par[parName + "r"] = data['r']
				operator.par[parName + "g"] = data['g']
				operator.par[parName + "b"] = data['b']
				operator.par[parName + "a"] = data['a']
				return
			
			if parGroup.style == 'UV' and 'u' in data.keys() and 'v' in data.keys():
				operator.par[parName + "u"] = data['u']
				operator.par[parName + "v"] = data['v']
				return

			if parGroup.style == 'UVW' and 'u' in data.keys() and 'v' in data.keys() and 'w' in data.keys():
				operator.par[parName + "u"] = data['u']
				operator.par[parName + "v"] = data['v']
				operator.par[parName + "w"] = data['w']
				return
			
			if parGroup.style == 'Pulse':
				operator.par[parName].pulse()
				return
			if (parGroup.style == 'Float' or parGroup.style =='Int') and parGroup.size > 1:
				for i in parGroup.subLabel:
					operator.par[i] = data[i]
				return
					
			if 'value' in data.keys():
				operator.par[parName] = data['value']
				return

			
			print("sometimes data not is match", data, parGroup.style)

		client.saveHandler(setAction.id, handle)

		valueEmitter = Emitter(
			id=parTargetId + ":valueUpdated",
			name=parGroup.label + " Value Updated",
			targetId=parTargetId,
			serviceId=instance.serviceId,
			schema=schema
		)

		client.saveAction(setAction)

		# save emitters
		client.saveEmitter(valueEmitter)

	else: 
		print("no default properties for", parGroup.style, "par group", parGroup.name)

	clarification = ""
	if parGroup.name.lower() != parGroup.label.replace(" ", "").lower():
		clarification = " (" + parGroup.name + ")"

	# make target for each par
	t = Target(
		id=parTargetId,
		name=parGroup.label + clarification,
		parentTargets=[f"{parentId}:{parGroup.sequence.name}" if parGroup.sequence else parentId],
		serviceId=instance.serviceId,
		category="Parameter",
		bgColor="#727e51",
		fgColor="#727e51",
		lastUpdated=datetime.now(timezone.utc).isoformat(),
		rootLevel=False
	)

	print("Saving par target", t.id, "on", t.parentTargets)

	# save those targets
	client.saveTarget(t)
	client.setTargetStatus(t, instance, Status.Online)

	# save actions

def makeSequenceActionEmitters(client: ExecClient, instance: Instance, operator, sequencePar, targetId) -> None:

	targetId = targetId + ":" + sequencePar.name

	increaseAction = Action(
		 id=f"{targetId}:increase",
		 name=f"Add Block",
		 targetId=targetId,
		 serviceId=instance.serviceId,
		 schema=None
	 )
	
	def handle_increase(action, data):
		# handle the increase action
		print("Increase action triggered for", targetId)

		currentNumBlocks = len(sequencePar.blocks)

		sequencePar.insertBlock(currentNumBlocks)

		print(f"Added block {currentNumBlocks} to sequence {sequencePar.name}")

	client.saveHandler(increaseAction.id, handle_increase)
	client.saveAction(increaseAction)

	decreaseAction = Action(
		 id=f"{targetId}:decrease",
		 name=f"Remove Block",
		 targetId=targetId,
		 serviceId=instance.serviceId,
		 schema=None
	 )
	

	def handle_decrease(action, data):
		# handle the decrease action
		print("Decrease action triggered for", targetId)

		currentNumBlocks = len(sequencePar.blocks)

		if currentNumBlocks > 0:
			sequencePar.removeBlock(currentNumBlocks - 1)
			print(f"Removed block {currentNumBlocks - 1} from sequence {sequencePar.name}")
		else:
			print("No blocks to remove from sequence", sequencePar.name)

	client.saveHandler(decreaseAction.id, handle_decrease)
	client.saveAction(decreaseAction)


def makePageTarget(client: ExecClient, instance: Instance, operator, page, parentId) -> None:

	pageTargetId = parentId + ":" + page.name

	# make target for each page
	t = Target(
		id=pageTargetId,
		name=page.name,
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

	
	for par in page.parGroups:
		makeParGroupTarget(client, instance, operator, par, pageTargetId, parentId)
	
def makeOpTarget(client: ExecClient, instance: Instance, operator: OP) -> None:
		
	targetId = operator.fetch('rs_target_id', str(uuid.uuid4()), storeDefault=True) 
	# targetId = operator.fetch('rs_target_id', None)


	assertStream(targetId, operator, client)

	
	ops[targetId] = operator
		
	targetId = str(targetId)

	for page in operator.customPages:
		makePageTarget(client, instance, operator, page, targetId)

	# get pars
	#for par in operator.customPars:
		#makeParTarget(instance, operator, par, targetId)

	# has page named notch
	hasPageNamedNotch = False

	for page in operator.pages: 
		
		if page.name == "Notch":
			hasPageNamedNotch = True
			makePageTarget(client, instance, operator, page, targetId)
		if page.name == "Common":
			continue

		if not hasPageNamedNotch:
			continue
		
		makePageTarget(client, instance, operator, page, targetId)


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

def cleanDeleted(client: ExecClient, instance: Instance) -> None: 
	global ops
	
	targetsToRemove = []

	print("Cleaning deleted ops and targets")

	print(ops)

	for id, o in ops.items():
		operator = op(o.path)
		
		if operator == None:
			print("marking", o.path, "offline")
			if id not in client.targets:
				print("target not found for", o.path)
				continue
			target = client.targets[id]
		
			client.setTargetOffline(target, instance)
			targetsToRemove.append(target.id)
			continue
						
	print("Checking targets", [target.id for target in client.targets.values()])
	for target in client.targets.values():
		sections = target.id.split(":")
						
		if len(sections) < 2: 
			print("target", target.id, "has no sections - skipping")
			continue
			
		baseTargetId = sections[0]

		print("Checking base target", baseTargetId, "for", target.id)
		
		if baseTargetId not in ops:
			print(baseTargetId, "not found in ops - setting it offline")
			client.setTargetOffline(target, instance)
			targetsToRemove.append(target.id)
			continue
		
		operator: OP = ops[baseTargetId]
		
		if not operator.valid:
			print("marking op", target.id, "offline")
			client.setTargetOffline(target, instance);
			targetsToRemove.append(target.id)
			del ops[baseTargetId]
			
			continue
			
		slug = sections[1]
		if operator == None:
			print("op not found for", target.id)
			continue

		pageNames = [page.name for page in operator.customPages] + [page.name for page in operator.pages]

		isExistingPage = slug in pageNames
		
		isExistingPar = hasattr(operator.pars, slug) or hasattr(operator.parGroup, slug)

		if not isExistingPage and not isExistingPar:
			print("marking", target.id, "offline", slug)
			client.setTargetOffline(target, instance)
			targetsToRemove.append(target.id)
			continue

	for id in targetsToRemove:
		client.removeTarget(id)
	
	return

def pulseEmitter(opPath: str, par: Par, client: ExecClient):
	parGroup = par.parGroup

	parName = parGroup.name

	if parGroup is None:
		print("no par group found for", parName)
		return
	

	data = {}

	operator = op(opPath)

	if parGroup.style == 'Float' or parGroup.style == 'Int':
		if parGroup.size > 1:
			for i in parGroup.subLabel:
				data[i] = operator.par[i].eval()
		else:
			data['value'] = operator.par[parName].eval()
			
	elif parGroup.style == 'Str':
		data['value'] = operator.par[parName].eval()

	elif parGroup.style == 'Toggle':
		data['value'] = operator.par[parName].eval()

	elif parGroup.style == 'Pulse':
		data['value'] = "null"

	elif parGroup.style == 'WH':
		data['w'] = operator.par[parName + "w"].eval()
		data['h'] = operator.par[parName + "h"].eval()

	elif parGroup.style == 'XY':
		data['x'] = operator.par[parName + "x"].eval()
		data['y'] = operator.par[parName + "y"].eval()

	elif parGroup.style == 'XYZ':
		data['x'] = operator.par[parName + "x"].eval()
		data['y'] = operator.par[parName + "y"].eval()
		data['z'] = operator.par[parName + "z"].eval()


	elif parGroup.style == 'XYZW':
		data['x'] = operator.par[parName + "x"].eval()
		data['y'] = operator.par[parName + "y"].eval()
		data['z'] = operator.par[parName + "z"].eval()
		data['w'] = operator.par[parName + "w"].eval()


	elif parGroup.style == 'RGB':
		data['r'] = operator.par[parName + "r"].eval()
		data['g'] = operator.par[parName + "g"].eval()
		data['b'] = operator.par[parName + "b"].eval()

	
	elif parGroup.style == 'RGBA':
		data['r'] = operator.par[parName + "r"].eval()
		data['g'] = operator.par[parName + "g"].eval()
		data['b'] = operator.par[parName + "b"].eval()
		data['a'] = operator.par[parName + "a"].eval()

	
	elif parGroup.style == 'UV':
		data['u'] = operator.par[parName + "u"].eval()
		data['v'] = operator.par[parName + "v"].eval()

	
	elif parGroup.style == 'UVW':
		data['u'] = operator.par[parName + "u"].eval()
		data['v'] = operator.par[parName + "v"].eval()
		data['w'] = operator.par[parName + "w"].eval()
	
	elif parGroup.style == 'Menu' or parGroup.style == 'StrMenu': 
		data['value'] = operator.par[parName].eval()

	else:
		print("no data found for", parGroup.style)
		return
	
	targetId = operator.fetch('rs_target_id')
	
	emitterId = targetId + ":" + parName + ":valueUpdated"
	
	client.pulseEmitter(emitterId=emitterId,data=data)
	return
