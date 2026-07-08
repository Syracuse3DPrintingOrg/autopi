"""Built-in example setups that load a complete working scenario in one click."""
from . import dt15  # noqa: F401
from . import ram1500  # noqa: F401
from . import giorgio  # noqa: F401

EXAMPLES = {
    "dt15": {
        "name": dt15.NAME,
        "description": dt15.DESCRIPTION,
        "load": dt15.load,
        "is_loaded": dt15.is_loaded,
    },
    "ram1500": {
        "name": ram1500.NAME,
        "description": ram1500.DESCRIPTION,
        "load": ram1500.load,
        "is_loaded": ram1500.is_loaded,
    },
    "giorgio": {
        "name": giorgio.NAME,
        "description": giorgio.DESCRIPTION,
        "load": giorgio.load,
        "is_loaded": giorgio.is_loaded,
    },
}
