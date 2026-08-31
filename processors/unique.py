import os
import hashlib
import logging
import threading
from processors.base import Processor
from processors.base import Content

_hash_lock = threading.Lock()

def tmp_file_name():
    """
        Return a temporary file name using $TMPDIR environment variable.
    """
    return os.environ.get("TMPDIR", "/tmp") + "/war-alert.txt"

def search_hash_in_file(hash):
    """
        Search a hash in a temporary file. Create a temporary file if it
        doesn't exist.
    """
    # Create a temporary file
    if not os.path.exists(tmp_file_name()):
        with open(tmp_file_name(), "w") as file:
            file.write("")

    with open(tmp_file_name(), "r") as file:
        for line in file:
            if line.startswith(hash):
                return True
    return False

def write_hash_to_file(hash):
    """
        Write a hash to a temporary file.
    """
    with open(tmp_file_name(), "a") as file:
        file.write(hash + "\n")

def calculate_md5_hash(text):
    """
        Calculate the MD5 hash of a text.
    """
    return hashlib.md5(text.encode('utf-8')).hexdigest()

class ProcessorUnique(Processor):
    """
        A class to represent a unique processor.
    """
    def process(self, content: Content, logger: logging.Logger) -> Content|None:
        """
            Process a content.
        """
        content_hash = calculate_md5_hash(str(content))
        with _hash_lock:
            if search_hash_in_file(content_hash):
                return None
        content._unique_hash = content_hash
        return content

    def mark_seen(self, content: Content) -> None:
        """
            Mark a content as seen after successful notification.
        """
        content_hash = getattr(content, "_unique_hash", None)
        if content_hash is None:
            content_hash = calculate_md5_hash(str(content))
        with _hash_lock:
            if not search_hash_in_file(content_hash):
                write_hash_to_file(content_hash)
