"""
Extension classes enhance TouchDesigner components with python. An
extension is accessed via ext.ExtensionClassName from any operator
within the extended component. If the extension is promoted via its
Promote Extension parameter, all its attributes with capitalized names
can be accessed externally, e.g. op('yourComp').PromotedFunction().

Help: search "Extensions" in wiki
"""
import uuid

from TDStoreTools import StorageManager
TDF = op.TDModules.mod.TDFunctions


class RshipSource:
    """
    RshipSource 

    id: ID
    dataSchema: JSONSchema
    channels: Channel[]
    // NOTE(kb): added this to allow for better UI options
    name?: string

    """

    def __init__(self, ownerComp):
        # The component to which this extension is attached
        self.ownerComp = ownerComp
        rship_id = str(uuid.uuid4())
        # properties
        TDF.createProperty(self, 'rship_dataSchema', value={}, dependable=True,
                           readOnly=True)
        TDF.createProperty(self, 'rship_channels', value=[], dependable=True,
                           readOnly=True)
        TDF.createProperty(self, 'SourcePath', value=self.ownerComp.parent(0).path, dependable=True,
                           readOnly=True)
        TDF.createProperty(self, 'RshipName', value=self.ownerComp.parent(1).name, dependable=True,
                           readOnly=True)
            
        
        # stored items (persistent across saves and re-initialization):
        storedItems = [
            # Only 'name' is required...
            {'name': 'RshipId', 'default':rship_id , 'readOnly': True,
             'property': True, 'dependable': True},
            {'name': 'RshipChannels', 'default': [], 'readOnly': False,
             'property': True, 'dependable': True},       
        ]
        # Uncomment the line below to store StoredProperty. To clear stored
        # 	items, use the Storage section of the Component Editor

        self.stored = StorageManager(self, ownerComp, storedItems)
        return

    # def myFunction(self, v):
    # 	debug(v)
    @property
    def RshipName(self):
        self.ownerComp.parent(1).name

    def Register(self):
        self._SourcePath.val= self.ownerComp.parent(0).path
        debug('Registering Self', self.RshipId, self.ownerComp.parent(0).path)
        op.RshipAdapter.RegisterSource(self.ownerComp)
        return

    def SetupCompPars(self):
        self.page = self.ownerComp.appendCustomPage('Rocketship')
        self.page.appendPulse('Doregister', label="Register Source")
    

    
    def GenerateDataSchema(self):
        pages = self.ownerComp.parent(1).customPages
        schema = {
            'definitions': {},
            '$schema': 'http://json-schema.org/draft-07/schema#',
            '$id': 'https://schemas.rship.io/systems/touchdesigner/NEEDS_A_SYSTEM_ID/sources/{}.schema.json'.format(self.SourcePath.replace('/','|')),
            'type': 'object',
            'title': 'Touchdesigner Source: {}'.format(self.RshipName),
            'required': [],
            'properties': [],
        }

        for page in pages: 

            groupPath = '#/properties/{}'.format(page.name)
            group = {
                '$id': groupPath,
                'title': page.name,
                'properties': [],
            }

            for par in page.pars: 
                if not self.getParType(par): continue

                group['properties'].append({
                    '$id': '{group}/properties/{name}'.format(group=groupPath, name=par.name),
                    'title': par.label,
                    'default': par.default,
                    'type' : self.getParType(par),
                })
            

            schema['properties'].append(group)

        return schema

    def getParType(self, par):
        if par.isFloat:
            return 'number'
        if par.isInt:
            return 'integer'
        if par.isString:
            return 'string'

        # TODO: implement menu types
        return False

    def GetRshipSource(self):

        return {
            "id": self.RshipId,
            "name": self.RshipName,
            "channels": [],
            "dataSchema": self.GenerateDataSchema()
        }