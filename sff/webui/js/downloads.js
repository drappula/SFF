/**
 * SteaMidra — Downloads Page
 * One entry per app, keyed by app_id. Each entry's status decides which
 * section renders it:
 *   downloading                          -> Active Downloads
 *   queued / paused / failed / done (with a queue item) -> Download Queue
 *   done / cancelled / failed (no item)  -> Download History
 */

window.Downloads = (function() {
    'use strict';

    var _items = {};        // app_id -> entry
    var _initialized = false;
    var _MAX_HISTORY = 100;
    var _queueState = { items: [], paused: false, concurrency: 3 };
    var _pendingCancel = null;  // {appid, qid, name} while the confirm dialog is open
    var _rowEls = {};           // app_id -> active/queue row element

    function _get(appid) {
        var id = String(appid);
        if (!_items[id]) {
            _items[id] = {
                app_id: id, qid: null, name: 'App ' + id, source: '', sourceLocked: false,
                status: 'queued', progress: 0, statusText: '',
                error: '', timestamp: Date.now(),
                pendingPause: false, cancelling: false
            };
        }
        return _items[id];
    }

    function _findByQid(qid) {
        var ids = Object.keys(_items);
        for (var i = 0; i < ids.length; i++) {
            if (_items[ids[i]].qid === qid) return _items[ids[i]];
        }
        return null;
    }

    function _trim() {
        var terminal = Object.keys(_items).filter(function(id) {
            return _items[id].status === 'done' || _items[id].status === 'cancelled';
        }).sort(function(a, b) {
            return (_items[b].timestamp || 0) - (_items[a].timestamp || 0);
        });
        terminal.slice(_MAX_HISTORY).forEach(function(id) { delete _items[id]; });
    }

    function init() {
        if (_initialized) return;
        _initialized = true;

        Bridge.on('download_progress', function(json) {
            try {
                var data = JSON.parse(json);
                if (!data.app_id) return;
                var it = _get(data.app_id);
                // A finished run's row must not swallow the next run's
                // events: re-downloading the same app kept showing the old
                // 'done' in History while the new download ran invisibly.
                // Every download path opens with a progress-0 setup event;
                // late events from the previous run carry > 0 or 'Complete'.
                if ((it.status === 'done' || it.status === 'cancelled') &&
                        data.progress === 0 && typeof data.status === 'string' &&
                        data.status !== 'Complete') {
                    it.status = 'downloading';
                    it.error = '';
                    it.timestamp = Date.now();
                } else if (it.status === 'cancelled' || it.status === 'done') return;
                if (data.name) it.name = data.name;
                if (data.status) it.statusText = data.status;
                if (typeof data.progress === 'number' && data.progress >= 0) {
                    if (data.progress < it.progress && it.status === 'downloading' && it.progress < 100) {
                        // Drop backward progress within same download (depot switch glitch where next depot briefly reports 0)
                    } else {
                        it.progress = data.progress;
                    }
                }
                if (it.status === 'queued' || it.status === 'failed') {
                    it.status = 'downloading';
                }
                _render();
            } catch(e) {}
        });

        Bridge.on('task_finished', function(json) {
            try {
                var data = JSON.parse(json);
                if (!data.task || data.task.indexOf('download') === -1) return;
                if (!data.app_id) return;
                var it = _get(data.app_id);
                it.pendingPause = false;
                it.cancelling = false;
                if (data.paused) it.status = 'paused';
                else if (data.cancelled) it.status = 'cancelled';
                else if (data.success) { it.status = 'done'; it.progress = 100; }
                else it.status = 'failed';
                if (!data.success && data.message) it.error = data.message;
                it.timestamp = Date.now();
                _trim();
                _render();
            } catch(e) {}
        });

        Bridge.on('download_queue_state', function(json) {
            try {
                _queueState = JSON.parse(json) || { items: [], paused: false, concurrency: 3 };
                _mergeQueue();
                _render();
            } catch(e) {}
        });

        var pauseBtn = document.getElementById('queue-pause');
        var resumeBtn = document.getElementById('queue-resume');
        var clearBtn = document.getElementById('queue-clear-finished');
        if (pauseBtn) pauseBtn.addEventListener('click', function() { Bridge.call('download_queue_pause'); });
        if (resumeBtn) resumeBtn.addEventListener('click', function() { Bridge.call('download_queue_resume'); });
        if (clearBtn) clearBtn.addEventListener('click', function() {
            Object.keys(_items).forEach(function(id) {
                var s = _items[id].status;
                if (s === 'done' || s === 'cancelled' || (s === 'failed' && !_items[id].qid)) {
                    delete _items[id];
                }
            });
            _render();
            Bridge.call('download_queue_clear_finished');
        });

        var _wireList = function(listEl) {
            if (!listEl) return;
            listEl.addEventListener('click', function(e) {
                var pbtn = e.target.closest('[data-pause-appid]');
                if (pbtn) {
                    var it = _get(pbtn.dataset.pauseAppid);
                    it.pendingPause = true;
                    _render();
                    Bridge.call('download_pause_active', it.app_id, it.name, it.source || 'freelua');
                    return;
                }
                var cbtn = e.target.closest('[data-cancel-appid]');
                if (cbtn) {
                    var it2 = _get(cbtn.dataset.cancelAppid);
                    _pendingCancel = { appid: it2.app_id, qid: it2.qid, name: it2.name };
                    var t = document.getElementById('queue-cancel-game-name');
                    if (t) t.textContent = it2.name;
                    Components.showModal('queue-cancel-modal');
                    return;
                }
                var qbtn = e.target.closest('[data-queue-action]');
                if (!qbtn) return;
                var act = qbtn.dataset.queueAction;
                var qid = qbtn.dataset.itemId;
                if (act === 'retry') {
                    Bridge.call('download_queue_retry', qid);
                } else if (act === 'resume') {
                    Bridge.call('download_queue_resume_item', qid);
                } else if (act === 'remove') {
                    var it4 = _findByQid(qid);
                    if (it4) delete _items[it4.app_id];
                    Bridge.call('download_queue_remove', qid);
                } else if (act === 'cancel') {
                    var it3 = _findByQid(qid);
                    _pendingCancel = { appid: it3 ? it3.app_id : null, qid: qid,
                                       name: it3 ? it3.name : '' };
                    var t2 = document.getElementById('queue-cancel-game-name');
                    if (t2) t2.textContent = _pendingCancel.name;
                    Components.showModal('queue-cancel-modal');
                }
            });
        };
        _wireList(document.getElementById('downloads-active-list'));
        _wireList(document.getElementById('downloads-queue-list'));
        _wireList(document.getElementById('downloads-history-list'));

        var doCancel = function(deleteFiles) {
            if (_pendingCancel) {
                if (_pendingCancel.appid) {
                    var it = _get(_pendingCancel.appid);
                    it.cancelling = true;
                    it.pendingPause = false;
                }
                if (_pendingCancel.qid) {
                    Bridge.call('download_queue_cancel', _pendingCancel.qid, deleteFiles);
                } else if (_pendingCancel.appid) {
                    Bridge.call('download_cancel_active', _pendingCancel.appid, deleteFiles);
                }
                _pendingCancel = null;
                _render();
            }
            Components.hideModal('queue-cancel-modal');
        };
        var keepBtn = document.getElementById('queue-cancel-keep');
        var delBtn = document.getElementById('queue-cancel-delete');
        if (keepBtn) keepBtn.addEventListener('click', function() { doCancel(false); });
        if (delBtn) delBtn.addEventListener('click', function() { doCancel(true); });
    }

    function onPageEnter() {
        init();
        Bridge.callSync('download_queue_get_state', function(json) {
            try {
                _queueState = JSON.parse(json) || { items: [], paused: false, concurrency: 3 };
                _mergeQueue();
            } catch(e) {}
            _render();
        });
    }

    function _mergeQueue() {
        var seen = {};
        ((_queueState && _queueState.items) || []).forEach(function(item) {
            var id = String(item.app_id);
            seen[id] = true;
            var it = _get(id);
            it.qid = item.id;
            if (item.name) it.name = item.name;
            if (item.source && !it.sourceLocked) it.source = item.source;
            if (item.error) it.error = item.error;
            // Engine still winding down after a pause/cancel request: the
            // row stays in Active until task_finished reports back.
            if (it.status === 'downloading' || it.status === 'parked') {
                if (item.state === 'downloading') {
                    it.status = item.paused ? 'parked' : 'downloading';
                    it.pendingPause = false;
                }
                return;
            }
            if (item.state === 'downloading') it.status = 'downloading';
            else if (item.state === 'queued') it.status = item.paused ? 'paused' : 'queued';
            else if (item.state === 'failed') it.status = 'failed';
            else if (item.state === 'done') it.status = 'done';
            if (typeof item.progress === 'number' && item.progress > (it.progress || 0)) {
                it.progress = item.progress;  // survive a restart at real %
            }
        });
        Object.keys(_items).forEach(function(id) {
            var it = _items[id];
            if (it.qid && !seen[id]) {
                it.qid = null;
                if (it.status === 'queued' || it.status === 'paused') it.status = 'cancelled';
            }
        });
    }

    function _badge(it) {
        if (it.cancelling) return ['cancelling', 'queue-badge-failed'];
        if (it.pendingPause) return ['pausing', 'queue-badge-paused'];
        if (it.status === 'parked') return ['paused', 'queue-badge-paused'];
        var cls = it.status === 'cancelled' ? 'failed' : it.status;
        return [it.status, 'queue-badge-' + cls];
    }

    function _actionsHtml(it) {
        var esc = Components.escapeHtml;
        if (it.status === 'downloading') {
            if (it.cancelling) return '<button class="btn btn-sm" disabled>Cancelling…</button>';
            if (it.pendingPause) return '<button class="btn btn-sm" disabled>Pausing…</button>';
            return '<button class="btn btn-sm" data-pause-appid="' + esc(it.app_id) + '">Pause</button>' +
                   '<button class="btn btn-sm" data-cancel-appid="' + esc(it.app_id) + '">Cancel</button>';
        }
        if (it.status === 'parked') {
            if (it.cancelling) return '<button class="btn btn-sm" disabled>Cancelling…</button>';
            return '<button class="btn btn-sm" data-queue-action="resume" data-item-id="' + esc(it.qid) + '">Resume</button>' +
                   '<button class="btn btn-sm" data-queue-action="cancel" data-item-id="' + esc(it.qid) + '">Cancel</button>';
        }
        if (it.status === 'paused') {
            return '<button class="btn btn-sm" data-queue-action="resume" data-item-id="' + esc(it.qid) + '">Resume</button>' +
                   '<button class="btn btn-sm" data-queue-action="cancel" data-item-id="' + esc(it.qid) + '">Cancel</button>';
        }
        if (it.status === 'queued') {
            return '<button class="btn btn-sm" data-queue-action="remove" data-item-id="' + esc(it.qid) + '">Remove</button>';
        }
        if (it.status === 'failed') {
            return it.qid
                ? '<button class="btn btn-sm" data-queue-action="retry" data-item-id="' + esc(it.qid) + '">Retry</button>'
                : '';
        }
        if (it.status === 'done') {
            return it.qid
                ? '<button class="btn btn-sm" data-queue-action="remove" data-item-id="' + esc(it.qid) + '">Remove</button>'
                : '';
        }
        return '';
    }

    function _sig(it) {
        return it.status + '|' + (it.pendingPause ? 1 : 0) + '|' + (it.cancelling ? 1 : 0) +
               '|' + (it.error || '') + '|' + (it.name || '') + '|' + (it.source || '');
    }

    function _buildRow(it) {
        var row = document.createElement('div');
        row.className = 'download-item';
        row.dataset.appid = it.app_id;
        row.dataset.sig = _sig(it);
        var b = _badge(it);
        var sourceHtml = it.source
            ? ' <span style="font-size:11px;opacity:0.65;">via ' + Components.escapeHtml(it.source) + '</span>'
            : '';
        var errHtml = (it.error && it.status === 'failed')
            ? ' <span style="font-size:11px;opacity:0.7;" title="' + Components.escapeHtml(it.error) + '">(error)</span>'
            : '';
        var progressHtml = (it.status === 'cancelled' || it.status === 'done') ? '' :
            '<div class="queue-pct" style="font-size:11px;opacity:0.6;">' + Math.round(it.progress || 0) + '%</div>' +
            '<div class="queue-status" style="font-size:11px;opacity:0.7;">' + Components.escapeHtml(it.statusText || '') + '</div>';
        row.innerHTML =
            '<div class="download-info" style="flex:1;">' +
                '<div class="download-name"><span class="download-name-text">' + Components.escapeHtml(it.name) + '</span>' +
                ' <span class="queue-state-badge ' + b[1] + '">' + b[0] + '</span>' + sourceHtml + errHtml + '</div>' +
                progressHtml +
            '</div>' +
            '<div class="download-actions" style="display:flex;gap:6px;align-items:center;">' + _actionsHtml(it) + '</div>';
        _patchRow(row, it);
        return row;
    }

    function _patchRow(el, it) {
        var pctVal = it.status === 'cancelled' ? 0 : Math.max(0, Math.min(100, it.progress || 0));
        el.style.setProperty('--dl-progress', pctVal + '%');
        var pct = el.querySelector('.queue-pct');
        if (pct) pct.textContent = Math.round(it.progress || 0) + '%';
        var stat = el.querySelector('.queue-status');
        if (stat && stat.textContent !== (it.statusText || '')) stat.textContent = it.statusText || '';
    }

    function _syncList(list, entries) {
        if (!list) return;
        var seen = {};
        entries.forEach(function(it) {
            seen[it.app_id] = true;
            var el = _rowEls[it.app_id];
            if (!el || el.parentNode !== list || el.dataset.sig !== _sig(it)) {
                var fresh = _buildRow(it);
                if (el && el.parentNode === list) list.replaceChild(fresh, el);
                else list.appendChild(fresh);
                _rowEls[it.app_id] = fresh;
            } else {
                _patchRow(el, it);
            }
        });
        Array.prototype.slice.call(list.children).forEach(function(el) {
            if (!seen[el.dataset.appid]) {
                // Only drop the registration if this element IS the tracked
                // one; a row that moved to the other list re-registered.
                if (_rowEls[el.dataset.appid] === el) delete _rowEls[el.dataset.appid];
                el.remove();
            }
        });
    }

    function _render() {
        var active = [], queue = [], history = [];
        Object.keys(_items).forEach(function(id) {
            var it = _items[id];
            if (it.status === 'downloading' || it.status === 'parked') { active.push(it); return; }
            if (it.qid && (it.status === 'paused' || it.status === 'queued' ||
                           it.status === 'failed')) queue.push(it);
            if (it.status === 'done' || it.status === 'cancelled' ||
                (it.status === 'failed' && !it.qid)) history.push(it);
        });

        _syncList(document.getElementById('downloads-active-list'), active);
        var activeEmpty = document.getElementById('downloads-active-empty');
        if (activeEmpty) activeEmpty.classList.toggle('hidden', active.length > 0);

        _syncList(document.getElementById('downloads-queue-list'), queue);
        var queueEmpty = document.getElementById('downloads-queue-empty');
        if (queueEmpty) queueEmpty.classList.toggle('hidden', queue.length > 0);

        var historyList = document.getElementById('downloads-history-list');
        if (historyList) {
            historyList.innerHTML = '';
            history.sort(function(a, b) { return (b.timestamp || 0) - (a.timestamp || 0); });
            history.forEach(function(it) { historyList.appendChild(_buildRow(it)); });
        }

        var pauseBtn = document.getElementById('queue-pause');
        var resumeBtn = document.getElementById('queue-resume');
        if (pauseBtn) pauseBtn.disabled = !!(_queueState && _queueState.paused);
        if (resumeBtn) resumeBtn.disabled = !(_queueState && _queueState.paused);
    }

    function setSource(appid, source) {
        var it = _get(appid);
        it.source = source || '';
        it.sourceLocked = true;
        _render();
    }

    return {
        init: init,
        onPageEnter: onPageEnter,
        setSource: setSource
    };
})();
