"""The controller loop.

Open the deck, poll the app for the shared surface layout plus the action
catalog, paint one page of key faces, and on a press POST to the app's run
endpoint. Paging across a layout larger than the deck reuses the app's pure
``deck_layout`` math, so the deck and the web grid agree on where keys land.

Resilience is the point of the structure here: a Stream Deck write can fail
transiently (a USB hiccup, a brief re-enumeration, a bad state after a rapid
flurry of repaints), and a layout or settings change should never be able to
crash the process. So the loop NEVER exits on an error: a deck/USB error drops
the deck and re-opens it in-process, an app-unreachable error is logged and
retried, and painting is defensive per key. This mirrors the source project's
"recovers a lost or unplugged deck in-process" behavior; the earlier version
exited on any non-HTTP error and systemd relaunched it straight back into the
same crash, so a bad layout wedged the deck permanently.
"""
from __future__ import annotations

import json
import logging
import os
import time

import httpx

from . import deck_layout
from .config import Config
from .render import render_key

log = logging.getLogger(__name__)


class _ReopenDeck(Exception):
    """Raised to drop the current deck and re-open it (recovery / restart)."""


def _safe(fn) -> None:
    try:
        fn()
    except Exception:
        pass


def _report_status(client: httpx.Client, connected: bool, key_count: int = 0,
                   deck_type: str = "") -> None:
    """Publish deck presence to the app so the editor can scale to the real deck."""
    try:
        client.post("/streamdeck/status", json={
            "connected": connected, "key_count": key_count, "deck_type": deck_type})
    except httpx.HTTPError:
        pass


def _fetch_desired(client: httpx.Client) -> dict:
    """Read the app's desired deck settings and any restart request."""
    try:
        return client.get("/streamdeck/status").json()
    except (httpx.HTTPError, ValueError):
        return {}


def _read_json(path: str):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def read_local_slots(cfg: Config):
    """Read this surface's key layout straight from the app's data dir.

    Reading the file (not HTTP) is what keeps the deck showing its keys while
    the app container restarts during an update, and never blanks the deck just
    because a poll hit the app mid-restart. Returns a list of slots, or None
    when the data dir is not readable (then the caller falls back to HTTP).
    """
    if not cfg.data_dir:
        return None
    doc = _read_json(os.path.join(cfg.data_dir, "layout.json"))
    if not isinstance(doc, dict):
        return None
    slots = doc.get(cfg.surface)
    return slots if isinstance(slots, list) else []


def read_local_settings(cfg: Config) -> dict:
    """Read deck rotation/brightness from the app's data dir (best-effort)."""
    doc = _read_json(os.path.join(cfg.data_dir, "settings.json")) if cfg.data_dir else None
    out = {}
    if isinstance(doc, dict):
        if isinstance(doc.get("deck_rotation"), int):
            out["rotation"] = doc["deck_rotation"]
        if isinstance(doc.get("deck_brightness"), int):
            out["brightness"] = doc["deck_brightness"]
    status = _read_json(os.path.join(cfg.data_dir, "streamdeck-status.json")) if cfg.data_dir else None
    if isinstance(status, dict) and status.get("restart_ts"):
        out["restart_ts"] = status["restart_ts"]
    return out


def fetch_catalog(client: httpx.Client) -> dict:
    """Fetch the action catalog (labels/colors, incl. builtins) over HTTP."""
    actions = client.get("/actions").json().get("actions", [])
    return {a["id"]: a for a in actions if isinstance(a, dict) and a.get("id")}


def run(cfg: Config) -> int:
    """Blocking controller loop. Recovers from deck loss in-process; returns 0."""
    try:
        from StreamDeck.DeviceManager import DeviceManager
    except Exception:
        log.error("The streamdeck driver is not installed; cannot open a deck.")
        return 2

    client = httpx.Client(base_url=cfg.base_url, timeout=10)
    state = {"page": 0, "rotation": cfg.rotation, "brightness": cfg.brightness,
             "pages": [], "start_ts": time.time(), "catalog": {}}
    deck = None
    try:
        while True:
            try:
                if deck is None:
                    deck = _open_deck(DeviceManager, cfg, client, state)
                    if deck is None:
                        time.sleep(max(2, cfg.poll_seconds))
                        continue
                _tick(deck, client, cfg, state)
                time.sleep(cfg.poll_seconds)
            except KeyboardInterrupt:
                raise
            except _ReopenDeck as exc:
                log.info("Re-opening the deck: %s", exc)
                _safe(lambda: deck.close())
                deck = None
                _report_status(client, connected=False)
                time.sleep(1)
            except Exception as exc:
                # Any other error (a USB write failure, a paint error) must not
                # kill the process. Drop the deck and re-open it next pass.
                log.warning("Controller error; will re-open the deck: %s", exc)
                _safe(lambda: deck and deck.close())
                deck = None
                _report_status(client, connected=False)
                time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        _safe(lambda: deck and deck.reset())
        _safe(lambda: deck and deck.close())
    return 0


def _open_deck(DeviceManager, cfg: Config, client: httpx.Client, state: dict):
    """Enumerate and open the first deck, or return None if none is present."""
    decks = DeviceManager().enumerate()
    if not decks:
        log.info("No Stream Deck found; waiting for one to appear.")
        _report_status(client, connected=False)
        return None
    deck = decks[0]
    deck.open()
    deck.reset()
    deck.set_brightness(state["brightness"])
    deck.set_key_callback(_make_on_press(deck, client, state))
    state["start_ts"] = time.time()
    log.info("Opened %s (%d keys)", deck.deck_type(), deck.key_count())
    _report_status(client, connected=True, key_count=deck.key_count(), deck_type=deck.deck_type())
    return deck


def _make_on_press(deck, client: httpx.Client, state: dict):
    def on_press(_deck, key, pressed):
        if not pressed:
            return
        try:
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
            client.post(f"/actions/{action_id}/run")
        except httpx.HTTPError as exc:
            log.warning("Key run failed: %s", exc)
        except Exception as exc:  # a callback must never bubble into the driver
            log.warning("Key press handling error: %s", exc)
    return on_press


def _tick(deck, client: httpx.Client, cfg: Config, state: dict) -> None:
    """One poll: report presence, apply desired settings, repaint. Raises
    _ReopenDeck when the deck is gone or a restart was requested."""
    if hasattr(deck, "connected") and not deck.connected():
        raise _ReopenDeck("deck reports disconnected")

    _report_status(client, connected=True, key_count=deck.key_count(), deck_type=deck.deck_type())

    # Desired settings + restart signal: local files first (survive an app
    # restart), HTTP as a fallback when the data dir is not readable.
    desired = read_local_settings(cfg)
    if not desired:
        desired = _fetch_desired(client)
    if desired.get("restart_ts", 0) > state.get("start_ts", 0):
        raise _ReopenDeck("restart requested from the app")
    br = desired.get("brightness")
    if isinstance(br, int) and br != state["brightness"]:
        state["brightness"] = br
        deck.set_brightness(br)
    rot = desired.get("rotation")
    if rot is not None and rot != state["rotation"]:
        state["rotation"] = rot
        deck.reset()

    # Layout: read the slots straight from the app's data dir so the deck keeps
    # its keys while the app container restarts. Fall back to HTTP only when the
    # data dir is not readable.
    slots = read_local_slots(cfg)
    if slots is None:
        try:
            slots = client.get(f"/layout/{cfg.surface}").json().get("slots", [])
        except httpx.HTTPError as exc:
            log.warning("Could not reach the app for the layout: %s", exc)
            return  # keep the deck showing its last page
    # Catalog (labels/colors, incl. builtins) is fetched over HTTP and cached,
    # so a transient app-down keeps the faces correct instead of blanking them.
    try:
        state["catalog"] = fetch_catalog(client)
    except httpx.HTTPError:
        pass
    catalog = state.get("catalog") or {}

    pages = deck_layout.build_pages(slots, deck.key_count())
    if state["page"] >= len(pages):
        state["page"] = 0
    state["pages"] = pages
    page_index = state["page"] % len(pages)
    _paint(deck, pages[page_index], catalog, state["rotation"], page_index, len(pages))


def _paint(deck, page, catalog: dict, rotation: int, page_index: int = 0, total_pages: int = 1) -> None:
    """Paint one page of key faces, matching the on-screen tile per key.

    Each key's face is derived from the same label/icon/color an ActionSpec
    carries, so the physical deck shows what the user arranged on screen. The
    page-cycle key gets a small "n/total" badge naming the page it advances
    to. Painting is defensive per key and per face: a bad glyph or a driver
    write failure drops to a plainer face (label-only, then a blank tile of
    the right color) rather than aborting the page or wedging the loop.
    """
    from StreamDeck.ImageHelpers import PILHelper
    size = deck.key_image_format()["size"]
    for slot, action_id in enumerate(page):
        try:
            phys = deck_layout.rotated_index(slot, deck.key_count(), rotation)
            badge = None
            if action_id == deck_layout.PAGE_NEXT:
                spec = catalog.get(deck_layout.PAGE_NEXT, {})
                label = spec.get("label") or "More"
                icon = spec.get("icon") or "bi-chevron-right"
                color = spec.get("color") or "#1f2937"
                next_page = (page_index + 1) % max(1, total_pages) + 1
                badge = f"{next_page}/{total_pages}" if total_pages > 1 else None
            elif isinstance(action_id, str) and action_id:
                spec = catalog.get(action_id, {})
                label = spec.get("label") or action_id
                icon = spec.get("icon") or ""
                color = spec.get("color") or "#334155"
            else:
                label, icon, color = "", "", "#111827"
            img = _render_with_fallback(label, icon, color, size, rotation, badge)
            if img is not None:
                deck.set_key_image(phys, PILHelper.to_native_format(deck, img))
        except Exception as exc:
            # One bad key must not abort the whole page (or wedge the loop).
            log.debug("Painting key %s failed: %s", slot, exc)


def _render_with_fallback(label: str, icon: str, color: str, size, rotation: int, badge):
    """Render a key face, degrading gracefully if the full face fails.

    Tries icon+label+color first, then label-only, then a blank tile of the
    right color. render_key already never raises; this just widens the
    fallback chain so a bad icon can never blank a key that could otherwise
    at least show its label and color.
    """
    img = render_key(label, icon, color, size, rotation, badge=badge)
    if img is None and icon:
        img = render_key(label, "", color, size, rotation, badge=badge)
    if img is None:
        img = render_key("", "", color, size, rotation)
    return img
