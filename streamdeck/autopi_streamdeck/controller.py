"""The controller loop.

Skeleton implementation: open the deck, poll the app for the shared surface
layout plus the action catalog, paint one page of key faces, and on a press
POST to the app's run endpoint. Paging across a layout larger than the deck
reuses the app's pure ``deck_layout`` math, so the deck and the web grid agree
on where keys land. Kept intentionally lean; the source project's richer
behavior (idle blanking, live faces, kiosk navigation) layers on top later.
"""
from __future__ import annotations

import logging
import time

import httpx

from .config import Config
from .render import render_key

log = logging.getLogger(__name__)


def _key_count(deck) -> int:
    return deck.key_count()


def paging_for(count: int):
    """Import the app's pure paging helpers (shared source of truth)."""
    import sys
    from pathlib import Path
    service = Path(__file__).resolve().parents[2] / "service"
    if str(service) not in sys.path:
        sys.path.insert(0, str(service))
    from app.services import deck_layout  # noqa: E402
    return deck_layout


def _report_status(client: httpx.Client, connected: bool, key_count: int = 0,
                   deck_type: str = "") -> None:
    """Publish deck presence to the app so the editor can scale to the real deck."""
    try:
        client.post("/streamdeck/status", json={
            "connected": connected, "key_count": key_count, "deck_type": deck_type})
    except httpx.HTTPError:
        pass


def fetch_layout(client: httpx.Client, cfg: Config):
    """Return (ordered action ids, {id: action dict}) from the app."""
    layout = client.get(f"/layout/{cfg.surface}").json().get("slots", [])
    actions = client.get("/actions").json().get("actions", [])
    catalog = {a["id"]: a for a in actions}
    return layout, catalog


def run(cfg: Config) -> int:
    """Blocking controller loop. Returns an exit code."""
    try:
        from StreamDeck.DeviceManager import DeviceManager
    except Exception:
        log.error("The streamdeck driver is not installed; cannot open a deck.")
        return 2

    client = httpx.Client(base_url=cfg.base_url, timeout=10)
    decks = DeviceManager().enumerate()
    if not decks:
        log.error("No Stream Deck found.")
        _report_status(client, connected=False)
        return 1
    deck = decks[0]
    deck.open()
    deck.reset()
    deck.set_brightness(cfg.brightness)
    log.info("Opened %s (%d keys)", deck.deck_type(), deck.key_count())
    _report_status(client, connected=True, key_count=deck.key_count(), deck_type=deck.deck_type())

    deck_layout = paging_for(deck.key_count())
    start_ts = time.time()
    # Rotation and brightness are owned by the app (set in the web editor) and
    # pulled each poll, so config changes take effect live without a restart.
    # config.toml only seeds the initial values.
    state = {"page": 0, "rotation": cfg.rotation, "brightness": cfg.brightness}

    def on_press(_deck, key, pressed):
        if not pressed:
            return
        pages = state.get("pages") or []
        if not pages:
            return
        slot = deck_layout.slot_for_physical(key, deck.key_count(), state["rotation"])
        page = pages[state["page"] % len(pages)]
        if slot >= len(page):
            return
        action_id = page[slot]
        if not action_id:
            return
        if action_id == deck_layout.PAGE_NEXT:
            state["page"] = (state["page"] + 1) % max(1, len(pages))
            return
        try:
            client.post(f"/actions/{action_id}/run")
        except httpx.HTTPError as exc:
            log.warning("Run %s failed: %s", action_id, exc)

    deck.set_key_callback(on_press)

    try:
        while True:
            try:
                _report_status(client, connected=True, key_count=deck.key_count(),
                               deck_type=deck.deck_type())
                # Pull desired settings and a possible restart request.
                desired = _fetch_desired(client)
                if desired.get("restart_ts", 0) > start_ts:
                    log.info("Restart requested from the app; exiting for systemd to relaunch")
                    return 0
                if desired.get("brightness") and desired["brightness"] != state["brightness"]:
                    state["brightness"] = desired["brightness"]
                    deck.set_brightness(state["brightness"])
                if desired.get("rotation") is not None and desired["rotation"] != state["rotation"]:
                    state["rotation"] = desired["rotation"]
                    deck.reset()  # re-init before repainting at the new rotation

                layout, catalog = fetch_layout(client, cfg)
                pages = deck_layout.build_pages(layout, deck.key_count())
                state["pages"] = pages
                _paint(deck, pages[state["page"] % len(pages)], catalog, deck_layout,
                       state["rotation"])
            except httpx.HTTPError as exc:
                log.warning("Could not reach the app: %s", exc)
            time.sleep(cfg.poll_seconds)
    except KeyboardInterrupt:
        return 0
    finally:
        try:
            deck.reset()
            deck.close()
        except Exception:
            pass


def _fetch_desired(client: httpx.Client) -> dict:
    """Read the app's desired deck settings and any restart request."""
    try:
        return client.get("/streamdeck/status").json()
    except (httpx.HTTPError, ValueError):
        return {}


def _paint(deck, page, catalog, deck_layout, rotation: int):
    size = deck.key_image_format()["size"]
    from StreamDeck.ImageHelpers import PILHelper
    for slot, action_id in enumerate(page):
        phys = deck_layout.rotated_index(slot, deck.key_count(), rotation)
        spec = catalog.get(action_id) if action_id else None
        if action_id == deck_layout.PAGE_NEXT:
            label, color = "More", "#1f2937"
        elif spec:
            label, color = spec.get("label") or spec["id"], spec.get("color") or "#334155"
        else:
            label, color = "", "#111827"
        img = render_key(label, color, size, rotation)
        if img is not None:
            deck.set_key_image(phys, PILHelper.to_native_format(deck, img))
