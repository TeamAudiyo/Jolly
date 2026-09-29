class JollyError(Exception):
    """Base error that can be safely returned to CLI clients."""


class ConfigurationError(JollyError):
    """Raised for an invalid robot or scene configuration."""


class MotionError(JollyError):
    """Raised when a requested motion is invalid or unsafe."""
