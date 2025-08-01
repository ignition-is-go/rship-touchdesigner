from abc import ABC, abstractmethod
from typing import Dict, List, Self
from exec import Target, Action, Emitter, Instance

class TouchTarget(ABC):


    def __init__(self, instance: Instance):
        super().__init__()
        self.instance = instance


    @abstractmethod
    def collectChildren(self) -> List[Self]:
        """
        Returns the base instance of this TouchTarget.
        """
        raise NotImplementedError("Subclasses must implement this method.") 

    @abstractmethod
    def getTarget(Self) -> Target:
        """
        Returns the target associated with this TouchTarget.
        """
        raise NotImplementedError("Subclasses must implement this method.")
    
    @abstractmethod
    def getActions(Self) -> List[Action]:
        """
        Returns a list of actions that can be performed on this target.
        """
        raise NotImplementedError("Subclasses must implement this method.")
    
    @abstractmethod
    def getEmitters(Self) -> List[Emitter]:
        """
        Returns a list of emitters associated with this target.
        """
        raise NotImplementedError("Subclasses must implement this method.")
    

    def handleAction(self, action: Action, data: Dict[str, any]) -> None:
        """
        Handles an action for this target.
        This method can be overridden by subclasses to provide custom action handling.
        """
        print(f"[TouchTarget]: HandleAction not implemented for {self.__class__.__name__}.")