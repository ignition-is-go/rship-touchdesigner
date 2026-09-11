"""Run inside TouchDesigner to build the template comp-engine demo."""
import json
from td import baseCOMP, tableDAT, textDAT, constantCHOP, inCHOP, outCHOP, mathCHOP


root = op('/rship_source')
demo = root.op('comp_engine_demo')
if demo is not None:
    raise RuntimeError('comp_engine_demo already exists; inspect it before replacing it')
demo = root.create(baseCOMP, 'comp_engine_demo')
demo.nodeX = 600
demo.nodeY = 0
kinds = demo.create(baseCOMP, 'kinds')
instances = demo.create(baseCOMP, 'instances')
instances.nodeX = 300


def metadata(template, kind_id, rows):
    template.tags.add('rship-comp-kind')
    page = template.appendCustomPage('Rship Kind')
    page.appendStr('Kindid')[0].val = kind_id
    table = template.create(tableDAT, 'rship_kind_ports')
    table.clear()
    table.appendRow(['direction', 'id', 'index', 'schema', 'semantic', 'channel', 'accepts'])
    for row in rows:
        table.appendRow(row)


source = kinds.create(baseCOMP, 'source')
source.appendCustomPage('Controls').appendFloat('Value')[0].default = 1
source.par.Value = 1
signal = source.create(constantCHOP, 'signal')
signal.par.name0 = 'value'
signal.par.value0.expr = 'parent().par.Value'
source_out = source.create(outCHOP, 'out1')
source_out.inputConnectors[0].connect(signal)
source_out.nodeX = 200
metadata(source, 'source', [['out', 'value', 0, 'Signal', 'signal', '', '']])

layer = kinds.create(baseCOMP, 'layer')
layer.nodeX = 300
layer.appendCustomPage('Controls').appendFloat('Gain')[0].default = 1
layer.par.Gain = 1
layer_in = layer.create(inCHOP, 'in1')
multiply = layer.create(mathCHOP, 'multiply')
multiply.inputConnectors[0].connect(layer_in)
multiply.par.gain.expr = 'parent().par.Gain'
multiply.nodeX = 200
layer_out = layer.create(outCHOP, 'out1')
layer_out.inputConnectors[0].connect(multiply)
layer_out.nodeX = 400
metadata(layer, 'layer', [
    ['in', 'float', 0, '', '', 'value', 'source'],
    ['out', 'value', 0, 'Signal', 'signal', '', ''],
])

extension = demo.create(textDAT, 'compengine')
extension.par.file = 'py/example_comp_engine.py'
extension.par.syncfile = True
extension.par.loadonstartpulse.pulse()
demo.par.ext0object = "op('./compengine').module.DemoExt(me)"
demo.par.ext0promote = True
demo.par.initextonstart = True
demo.initializeExtensions(0)
result = json.dumps({'demo': demo.path, 'kinds': [source.path, layer.path]})
