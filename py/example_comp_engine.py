"""One comp-engine BASE owns both kind templates and their generated instances."""


class DemoExt:
    def __init__(self, ownerComp):
        self.ownerComp = ownerComp
        ce = op.RSHIP.CompEngine
        registry = ce.KindRegistryBuilder().register_children(ownerComp.op('kinds')).build()
        self.engine = ce.comp_engine(ownerComp, ce.CompEngineArgs(
            short_id='demo-engine',
            display_name='Template Demo',
            kind_registry=registry,
            host_target=op.RSHIP.Api.target(ownerComp, 'Template Demo'),
            replica_parent=ownerComp.op('instances'),
        ))

    def Republish(self):
        self.__init__(self.ownerComp)

    def Preview(self):
        """Create a local source/layer preview until RShip sends an assignment."""
        assignment = {'slotStates': [
            {'kind': 'source', 'boundInstance': {'compElementId': 'demo-source'},
             'capValues': [{'capId': 'Value', 'value': 2.0}],
             'presence': 1.0, 'wireInputValues': []},
            {'kind': 'layer', 'boundInstance': {'compElementId': 'demo-layer'},
             'capValues': [{'capId': 'Gain', 'value': 3.0}],
             'presence': 1.0, 'wireInputValues': [{
                 'pinId': 'float', 'source': {
                     'sourceEngineId': self.engine.id,
                     'sourceInstance': {'compElementId': 'demo-source'},
                     'outputChannelId': 'value'}}]},
        ], 'overflow': [], 'generation': 0}
        self.engine._render(assignment, None)
        self.engine._template_materializer.connect_wires()
        self.engine._committed = assignment
        replicas = self.engine._template_materializer.replicas
        for element_id, x in [('demo-source', 0), ('demo-layer', 300)]:
            replicas[element_id]['op'].nodeX = x
