"""Built-in example setups that load a complete working scenario in one click."""
from . import dt15  # noqa: F401
from . import ram1500  # noqa: F401
from . import giorgio  # noqa: F401
from . import ford_f150  # noqa: F401
from . import toyota_rav4  # noqa: F401
from . import honda_civic  # noqa: F401
from . import hyundai_elantra  # noqa: F401

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
    "ford_f150": {
        "name": ford_f150.NAME,
        "description": ford_f150.DESCRIPTION,
        "load": ford_f150.load,
        "is_loaded": ford_f150.is_loaded,
    },
    "toyota_rav4": {
        "name": toyota_rav4.NAME,
        "description": toyota_rav4.DESCRIPTION,
        "load": toyota_rav4.load,
        "is_loaded": toyota_rav4.is_loaded,
    },
    "honda_civic": {
        "name": honda_civic.NAME,
        "description": honda_civic.DESCRIPTION,
        "load": honda_civic.load,
        "is_loaded": honda_civic.is_loaded,
    },
    "hyundai_elantra": {
        "name": hyundai_elantra.NAME,
        "description": hyundai_elantra.DESCRIPTION,
        "load": hyundai_elantra.load,
        "is_loaded": hyundai_elantra.is_loaded,
    },
}
