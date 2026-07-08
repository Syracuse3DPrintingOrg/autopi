"""Built-in example setups that load a complete working scenario in one click."""
from . import dt15  # noqa: F401

EXAMPLES = {
    "dt15": {
        "name": dt15.NAME,
        "description": dt15.DESCRIPTION,
        "load": dt15.load,
        "is_loaded": dt15.is_loaded,
    },
}
