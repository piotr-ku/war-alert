import os
import hashlib
import logging
from processors.base import Processor
from processors.base import Content

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
        # Check if the content has already been processed
        hash = calculate_md5_hash(str(content))
        if search_hash_in_file(hash):
            return None

        # Write the hash to the temporary file
        write_hash_to_file(hash)
        return content
