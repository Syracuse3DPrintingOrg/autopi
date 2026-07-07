"""AutoPi Stream Deck controller.

Runs a physical Elgato Stream Deck as an AutoPi surface: it reads the shared
key layout from the app, renders each key face, and on a press calls the app's
``POST /actions/{id}/run`` so the deck and the web start menu trigger exactly
the same actions.
"""
__version__ = "0.1.0"
