"""
    Base notifier interface for war-alert.
"""

from abc import ABC, abstractmethod
from processors.base import Content

class Notifier(ABC):
    """
        A base class for all notifiers.
    """
    @abstractmethod
    def notify(self, content: Content, logger) -> bool:
        """
            Notify a content. Returns True on success.
        """
        return False
