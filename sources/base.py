from abc import ABC, abstractmethod
from processors.base import Content, Processor

class Source(ABC):
    """
        A base class for all sources.
    """
    @abstractmethod
    def fetch(self, logger) -> list[Content]:
        """
            Fetch items from the source.
        """
        return []

    @abstractmethod
    def processors(self) -> list[Processor]:
        """
            Return a list of processors.
        """
        return []
