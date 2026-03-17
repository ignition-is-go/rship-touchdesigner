# me - this DAT
# par - the Par object that has changed
# val - the current value
# prev - the previous value
# 
# Make sure the corresponding toggle is enabled in the Parameter Execute DAT.


def onValueChange(par, prev):
	# me.ext.RshipExt.PulseEmitter(par.owner, _getEmitterParGroupName(par.parGroup))
	return


def _getEmitterParGroupName(parGroup):
	sequence = getattr(parGroup, 'sequence', None)
	if sequence is not None:
		return sequence.name
	return parGroup.name

# Called at end of frame with complete list of individual parameter changes.
# The changes are a list of named tuples, where each tuple is (Par, previous value)
def onValuesChanged(changes):

	parGroups = set()

	for c in changes:
		# use par.eval() to get current value
		par = c.par
		prev = c.prev
		parGroups.add((par.parGroup.owner, _getEmitterParGroupName(par.parGroup)))
		
	
	for owner, parGroupName in parGroups:
		me.ext.RshipExt.PulseEmitter(owner, parGroupName)
	return

def onPulse(par):
	me.ext.RshipExt.PulseEmitter(par.owner, _getEmitterParGroupName(par.parGroup))
	return

def onExpressionChange(par, val, prev):
	return

def onExportChange(par, val, prev):
	return

def onEnableChange(par, val, prev):
	return

def onModeChange(par, val, prev):
	return


    
	
