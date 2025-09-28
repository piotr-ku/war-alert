from abc import ABC, abstractmethod

class Content(ABC):
    """
        A base class for all contents.
    """
    @abstractmethod
    def __str__(self) -> str:
        """
            Return a string representation of a content.
        """
        return ""

class Processor(ABC):
    """
        A base class for all processors.
    """
    @abstractmethod
    def process(self, content: Content, logger) -> Content|None:
        """
            Process a content.
        """
        return None
