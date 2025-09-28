from abc import ABC, abstractmethod
from processors.base import Content

class Notifier(ABC):
    """
        A base class for all notifiers.
    """
    @abstractmethod
    def notify(self, content: Content, logger) -> None:
        """
            Notify a content.
        """
        return
