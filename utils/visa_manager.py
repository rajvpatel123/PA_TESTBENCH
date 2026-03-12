# utils/visa_manager.py - COMPLETE FILE
import pyvisa
from utils.logger import get_logger

_logger = get_logger(__name__)
_rm = None

def get_visa_rm():
    """Return a singleton pyvisa ResourceManager."""
    global _rm
    if _rm is None:
        _rm = pyvisa.ResourceManager()
        _logger.info("Initialized VISA ResourceManager")
    return _rm
