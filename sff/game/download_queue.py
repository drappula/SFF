# SteaMidra - Steam game setup and manifest tool (SFF)
# Copyright (c) 2025-2026 Midrag (https://github.com/Midrags)
#
# This file is part of SteaMidra.
#
# SteaMidra is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# SteaMidra is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with SteaMidra.  If not, see <https://www.gnu.org/licenses/>.

"""Persistent download queue.

FIFO queue with a bounded number of parallel slots. Items run through
the normal Fastest download pipeline; the WebBridge advances the queue
when a download task finishes. State is stored as JSON in the user
data dir, so queued and in-progress items survive restarts.
"""

import json
import logging
import threading
import time
import uuid

from sff.core.utils import sff_data_dir

logger = logging.getLogger(__name__)

QUEUE_FILE = sff_data_dir() / "download_queue.json"

STATE_QUEUED = "queued"
STATE_DOWNLOADING = "downloading"
STATE_DONE = "done"
STATE_FAILED = "failed"

_DEFAULT_PAUSED = False
_DEFAULT_CONCURRENCY = 3


def _load():
    try:
        if not QUEUE_FILE.exists():
            return []
        data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return []
        items = data.get("items")
        if not isinstance(items, list):
            return []
        out = []
        for e in items:
            if isinstance(e, dict) and str(e.get("app_id", "") or "").isdigit():
                out.append({
                    "id": str(e.get("id") or uuid.uuid4()),
                    "app_id": str(e.get("app_id")),
                    "name": str(e.get("name") or ""),
                    "source": str(e.get("source") or "oureveryday"),
                    "state": e.get("state") if e.get("state") in (
                        STATE_QUEUED, STATE_DOWNLOADING, STATE_DONE, STATE_FAILED
                    ) else STATE_QUEUED,
                    "added_at": float(e.get("added_at") or time.time()),
                    "started_at": float(e.get("started_at") or 0) or None,
                    "error": str(e.get("error") or ""),
                })
        return out
    except Exception as e:
        logger.debug("download queue load failed: %s", e)
        return []


def _save(items):
    try:
        QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = QUEUE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"items": items}, indent=2), encoding="utf-8")
        tmp.replace(QUEUE_FILE)
    except Exception as e:
        logger.debug("download queue save failed: %s", e)


def enqueue(app_id, name="", source="oureveryday"):
    """Add an app to the queue. Returns the item dict, or None when the
    app is already queued/downloading."""
    app_id = str(app_id).strip()
    if not app_id.isdigit():
        return None
    items = _load()
    for e in items:
        if e["app_id"] == app_id and e["state"] in (STATE_QUEUED, STATE_DOWNLOADING):
            return e
    item = {
        "id": uuid.uuid4().hex,
        "app_id": app_id,
        "name": str(name or "").strip() or f"App {app_id}",
        "source": str(source or "oureveryday"),
        "state": STATE_QUEUED,
        "added_at": time.time(),
        "started_at": None,
        "error": "",
    }
    items.append(item)
    _save(items)
    logger.info("download queue: enqueued %s (%s)", app_id, item["name"])
    return item


def snapshot():
    """Return {items, paused, concurrency} for the UI."""
    from sff.core.storage.settings import get_setting
    from sff.core.structs import Settings
    try:
        raw = get_setting(Settings.DOWNLOAD_QUEUE_CONCURRENCY) or ""
        concurrency = int(raw) if str(raw).strip().isdigit() else _DEFAULT_CONCURRENCY
    except Exception:
        concurrency = _DEFAULT_CONCURRENCY
    concurrency = max(1, min(concurrency, 10))
    return {
        "items": _load(),
        "paused": _is_paused(),
        "concurrency": concurrency,
    }


_PAUSE_FILE = sff_data_dir() / "download_queue_paused"


def _is_paused():
    try:
        return _PAUSE_FILE.exists()
    except Exception:
        return _DEFAULT_PAUSED


def set_paused(paused):
    try:
        if paused:
            _PAUSE_FILE.write_text("1", encoding="utf-8")
        else:
            _PAUSE_FILE.unlink(missing_ok=True)
    except Exception as e:
        logger.debug("download queue pause toggle failed: %s", e)


def mark_started(item_id):
    items = _load()
    for e in items:
        if e["id"] == str(item_id):
            e["state"] = STATE_DOWNLOADING
            e["started_at"] = time.time()
            _save(items)
            return True
    return False


def mark_finished(app_id, success, error=""):
    """Mark a downloading item done/failed by app id. A cancelled item is
    dropped from the queue instead of being marked failed."""
    if is_cancelled(app_id):
        clear_cancel(app_id)
        _save([e for e in _load() if e["app_id"] != str(app_id)])
        return True
    items = _load()
    found = False
    for e in items:
        if e["app_id"] == str(app_id) and e["state"] == STATE_DOWNLOADING:
            e["state"] = STATE_DONE if success else STATE_FAILED
            if error:
                e["error"] = str(error)[:300]
            found = True
    if found:
        _save(items)
    return found


def remove_item(item_id):
    items = [e for e in _load() if e["id"] != str(item_id)]
    _save(items)


# ── In-flight cancel ──────────────────────────────────────────────────
# The download engines poll request_cancel()/is_cancelled() between depots
# and chunks; the bridge calls it when the user hits Cancel. Process-wide
# (not persisted): a restart requeues interrupted items anyway.
_cancelled: set = set()
_cancel_lock = threading.Lock()


def request_cancel(app_id):
    with _cancel_lock:
        _cancelled.add(str(app_id))


def clear_cancel(app_id):
    with _cancel_lock:
        _cancelled.discard(str(app_id))


def is_cancelled(app_id):
    with _cancel_lock:
        return str(app_id) in _cancelled


def cancel_item(item_id):
    """Cancel a queue item. Queued items are dropped outright; downloading
    items get flagged so the engine stops, and the row is removed once the
    task_finished handler runs. Returns the item dict, or None if unknown."""
    items = _load()
    for e in items:
        if e["id"] == str(item_id):
            if e["state"] == STATE_DOWNLOADING:
                logger.debug("queue: cancel requested for app %s (in flight)", e["app_id"])
                request_cancel(e["app_id"])
            else:
                logger.debug("queue: dropped queued item %s (app %s)", item_id, e["app_id"])
                _save([x for x in items if x["id"] != str(item_id)])
            return e
    return None


def retry_item(item_id):
    items = _load()
    for e in items:
        if e["id"] == str(item_id) and e["state"] in (STATE_FAILED, STATE_DONE):
            e["state"] = STATE_QUEUED
            e["error"] = ""
            e["started_at"] = None
            _save(items)
            return True
    return False


def clear_finished():
    items = [
        e for e in _load()
        if e["state"] in (STATE_QUEUED, STATE_DOWNLOADING)
    ]
    _save(items)


def requeue_interrupted():
    """On startup: items that were downloading when the app closed go
    back to queued so they can be picked up again."""
    items = _load()
    changed = False
    for e in items:
        if e["state"] == STATE_DOWNLOADING:
            e["state"] = STATE_QUEUED
            e["started_at"] = None
            changed = True
    if changed:
        _save(items)
