# me - this DAT
# par - the Par object that has changed
# val - the current value
# prev - the previous value
# 
# Make sure the corresponding toggle is enabled in the Parameter Execute DAT.


def onValueChange(par, prev):
	# me.ext.RshipExt.PulseEmitter(par.owner, par.parGroup.name)
	return

# Called at end of frame with complete list of individual parameter changes.
# The changes are a list of named tuples, where each tuple is (Par, previous value)
def onValuesChanged(changes):

	parGroups = set()

	for c in changes:
		# use par.eval() to get current value
		par = c.par
		prev = c.prev
		parGroups.add(par.parGroup)
		
	
	for pg in parGroups:
		me.ext.RshipExt.PulseEmitter(pg.owner, pg.name)
	return

def onPulse(par):
	me.ext.RshipExt.PulseEmitter(par.owner, par.parGroup.name)
	return

def onExpressionChange(par, val, prev):
	return

def onExportChange(par, val, prev):
	return

def onEnableChange(par, val, prev):
	return

def onModeChange(par, val, prev):
	return


    
	