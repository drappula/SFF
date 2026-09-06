/**
 * SteaMidra — Downloads Page
 * Active downloads with progress bars + download history + download queue.
 */

window.Downloads = (function() {
    'use strict';

    var _downloads = {};
    var _initialized = false;
    var _MAX_HISTORY = 100;
    var _queueState = { items: [], paused: false, concurrency: 3 };
    var _cancelling = {};  // item ids awaiting engine stop
    var _pendingCancel = null;  // {id, name} while the confirm dialog is open
    var _pendingActiveCancel = null;  // app_id for non-queue downloads

    function _trimHistory() {
        var completed = Object.keys(_downloads).filter(function(id) {
            return !_downloads[id].active;
        }).sort(function(a, b) {
            return (_downloads[b].timestamp || 0) - (_downloads[a].timestamp || 0);
        });
        completed.slice(_MAX_HISTORY).forEach(function(id) {
            delete _downloads[id];
        });
    }

    function init() {
        if (_initialized) return;
        _initialized = true;

        Bridge.on('download_progress', function(json) {
            try {
                var data = JSON.parse(json);
                _updateDownload(data);
                _renderQueue();
            } catch(e) {}
        });

        Bridge.on('task_finished', function(json) {
            try {
                var data = JSON.parse(json);
                if (data.task && data.task.indexOf('download') !== -1) {
                    _completeDownload(data);
                }
            } catch(e) {}
        });

        Bridge.on('download_queue_state', function(json) {
            try {
                _queueState = JSON.parse(json) || { items: [], paused: false, concurrency: 3 };
                _renderQueue();
            } catch(e) {}
        });

        var pauseBtn = document.getElementById('queue-pause');
        var resumeBtn = document.getElementById('queue-resume');
        var clearBtn = document.getElementById('queue-clear-finished');
        if (pauseBtn) pauseBtn.addEventListener('click', function() { Bridge.call('download_queue_pause'); });
        if (resumeBtn) resumeBtn.addEventListener('click', function() { Bridge.call('download_queue_resume'); });
        if (clearBtn) clearBtn.addEventListener('click', function() {
            // "Download History" is rendered from the JS _downloads map, not
            // the backend queue, so clear both or the history stays put.
            Object.keys(_downloads).forEach(function(id) {
                if (!_downloads[id].active) delete _downloads[id];
            });
            _render();
            Bridge.call('download_queue_clear_finished');
        });

        var queueList = document.getElementById('downloads-queue-list');
        if (queueList) {
            queueList.addEventListener('click', function(e) {
                var btn = e.target.closest('[data-queue-action]');
                if (!btn) return;
                var id = btn.dataset.itemId;
                if (btn.dataset.queueAction === 'retry') {
                    Bridge.call('download_queue_retry', id);
                } else if (btn.dataset.queueAction === 'cancel') {
                    var row = btn.closest('.download-item');
                    var nameEl = row && row.querySelector('.download-name');
                    _pendingActiveCancel = null;
                    _pendingCancel = { id: id, name: nameEl ? nameEl.textContent : ('App ' + id) };
                    var nameTarget = document.getElementById('queue-cancel-game-name');
                    if (nameTarget) nameTarget.textContent = _pendingCancel.name;
                    Components.showModal('queue-cancel-modal');
                } else if (btn.dataset.queueAction === 'remove') {
                    Bridge.call('download_queue_remove', id);
                }
            });
        }

        var doCancel = function(deleteFiles) {
            if (_pendingActiveCancel) {
                var btn = activeBtnFor(_pendingActiveCancel);
                if (btn) { btn.disabled = true; btn.textContent = 'Cancelling…'; }
                Bridge.call('download_cancel_active', _pendingActiveCancel, deleteFiles);
                _pendingActiveCancel = null;
            } else if (_pendingCancel) {
                _cancelling[_pendingCancel.id] = true;
                Bridge.call('download_queue_cancel', _pendingCancel.id, deleteFiles);
                _pendingCancel = null;
                _renderQueue();
            }
            Components.hideModal('queue-cancel-modal');
        };
        var activeBtnFor = function(appid) {
            var list = document.getElementById('downloads-active-list');
            return list && list.querySelector('[data-cancel-appid="' + appid + '"]');
        };
        var keepBtn = document.getElementById('queue-cancel-keep');
        var delBtn = document.getElementById('queue-cancel-delete');
        if (keepBtn) keepBtn.addEventListener('click', function() { doCancel(false); });
        if (delBtn) delBtn.addEventListener('click', function() { doCancel(true); });

        var activeList = document.getElementById('downloads-active-list');
        if (activeList) {
            activeList.addEventListener('click', function(e) {
                var btn = e.target.closest('[data-cancel-appid]');
                if (!btn) return;
                _pendingActiveCancel = btn.dataset.cancelAppid;
                var row = btn.closest('.download-item');
                var nameEl = row && row.querySelector('.download-item-name');
                var nameTarget = document.getElementById('queue-cancel-game-name');
                if (nameTarget) nameTarget.textContent = nameEl ? nameEl.textContent : ('App ' + _pendingActiveCancel);
                Components.showModal('queue-cancel-modal');
            });
        }
    }

    function onPageEnter() {
        init();
        _render();
        Bridge.callSync('download_queue_get_state', function(json) {
            try {
                _queueState = JSON.parse(json) || { items: [], paused: false, concurrency: 3 };
                _renderQueue();
            } catch(e) {}
        });
    }

    function _updateDownload(data) {
        var id = data.id || data.app_id || 'unknown';
        var prev = _downloads[id];
        _downloads[id] = {
            id: id,
            name: data.name || (prev && prev.name) || ('App ' + id),
            status: data.status || 'Downloading',
            progress: data.progress || 0,
            active: true,
            timestamp: Date.now()
        };
        _render();
    }

    function _completeDownload(data) {
        // app_id first: task_finished carries task='download_ddmod', which
        // would otherwise create a second row and leave the real one active.
        var id = data.app_id || data.task || 'unknown';
        if (_downloads[id]) {
            _downloads[id].active = false;
            _downloads[id].status = data.success ? 'Completed' : 'Failed';
            _downloads[id].progress = data.success ? 100 : _downloads[id].progress;
        } else {
            _downloads[id] = {
                id: id,
                name: data.message || id,
                status: data.success ? 'Completed' : 'Failed',
                progress: data.success ? 100 : 0,
                active: false,
                timestamp: Date.now()
            };
        }
        _trimHistory();
        _render();
    }

    var _rowEls = {};       // id -> active row element, patched in place
    var _queueRowEls = {};  // queue item id -> row element

    function _render() {
        var activeList = document.getElementById('downloads-active-list');
        var activeEmpty = document.getElementById('downloads-active-empty');
        var historyList = document.getElementById('downloads-history-list');

        var activeItems = [];
        var historyItems = [];

        Object.keys(_downloads).forEach(function(id) {
            var dl = _downloads[id];
            if (dl.active) {
                activeItems.push(dl);
            } else {
                historyItems.push(dl);
            }
        });

        if (activeList) {
            var seen = {};
            activeItems.forEach(function(dl) {
                seen[dl.id] = true;
                var el = _rowEls[dl.id];
                if (!el || el.parentNode !== activeList) {
                    el = Components.createDownloadItem(dl);
                    _rowEls[dl.id] = el;
                    activeList.appendChild(el);
                } else {
                    _patchActiveRow(el, dl);
                }
            });
            Array.prototype.slice.call(activeList.children).forEach(function(el) {
                if (!seen[el.dataset.id]) {
                    delete _rowEls[el.dataset.id];
                    el.remove();
                }
            });
        }
        if (activeEmpty) {
            activeEmpty.classList.toggle('hidden', activeItems.length > 0);
        }

        if (historyList) {
            historyList.innerHTML = '';
            historyItems.sort(function(a, b) { return (b.timestamp || 0) - (a.timestamp || 0); });
            historyItems.forEach(function(dl) {
                historyList.appendChild(Components.createDownloadItem(dl));
            });
        }
    }

    function _patchActiveRow(el, dl) {
        var nameEl = el.querySelector('.download-item-name');
        if (nameEl && dl.name && nameEl.textContent !== dl.name) nameEl.textContent = dl.name;
        var statusEl = el.querySelector('.download-item-status');
        if (statusEl) {
            var t = dl.status || 'Pending';
            if (dl.progress !== undefined) t += ' — ' + Math.round(dl.progress) + '%';
            if (statusEl.textContent !== t) statusEl.textContent = t;
        }
        var fill = el.querySelector('.download-progress-fill');
        if (fill) fill.style.width = (dl.progress || 0) + '%';
    }

    function _buildQueueRow(item) {
        var stateLabel = item.state;
        var badgeClass = 'queue-badge-' + item.state;
        var actions = '';
        if (item.state === 'failed') {
            actions += '<button class="btn btn-sm" data-queue-action="retry" data-item-id="' + Components.escapeHtml(item.id) + '">Retry</button>';
        }
        if (item.state === 'downloading') {
            if (_cancelling[item.id]) {
                actions += '<button class="btn btn-sm" disabled>Cancelling…</button>';
            } else {
                actions += '<button class="btn btn-sm" data-queue-action="cancel" data-item-id="' + Components.escapeHtml(item.id) + '">Cancel</button>';
            }
        } else {
            actions += '<button class="btn btn-sm" data-queue-action="remove" data-item-id="' + Components.escapeHtml(item.id) + '">Remove</button>';
        }
        if (item.error) {
            actions += '<span style="font-size:11px;opacity:0.7;margin-left:6px;" title="' + Components.escapeHtml(item.error) + '">(error)</span>';
        }
        var row = document.createElement('div');
        row.className = 'download-item';
        row.dataset.itemid = item.id;
        row.innerHTML =
            '<div class="download-info" style="flex:1;">' +
                '<div class="download-name">' + Components.escapeHtml(item.name || ('App ' + item.app_id)) +
                ' <span class="queue-state-badge ' + badgeClass + '">' + Components.escapeHtml(stateLabel) + '</span>' +
                ' <span style="font-size:11px;opacity:0.65;">via ' + Components.escapeHtml(item.source) + '</span></div>' +
                '<div class="progress-bar" style="margin-top:4px;"><div class="progress-fill" style="width:0%"></div></div>' +
                '<div class="queue-pct" style="font-size:11px;opacity:0.6;">0%</div>' +
            '</div>' +
            '<div class="download-actions" style="display:flex;gap:6px;align-items:center;">' + actions + '</div>';
        return row;
    }

    function _renderQueue() {
        var listEl = document.getElementById('downloads-queue-list');
        var emptyEl = document.getElementById('downloads-queue-empty');
        var pauseBtn = document.getElementById('queue-pause');
        var resumeBtn = document.getElementById('queue-resume');
        var items = (_queueState && _queueState.items) || [];
        var liveIds = {};
        items.forEach(function(item) { liveIds[item.id] = true; });
        Object.keys(_cancelling).forEach(function(id) {
            if (!liveIds[id]) delete _cancelling[id];
        });
        if (listEl) {
            var seenIds = {};
            items.forEach(function(item) {
                seenIds[item.id] = true;
                var dl = _downloads[String(item.app_id)];
                var progress = dl && typeof dl.progress === 'number' ? dl.progress : 0;
                var row = _queueRowEls[item.id];
                var sig = item.state + '|' + item.source + '|' + (item.name || '') + '|' + (item.error || '') + '|' + !!_cancelling[item.id];
                if (!row || row.parentNode !== listEl || row.dataset.sig !== sig) {
                    var fresh = _buildQueueRow(item);
                    fresh.dataset.sig = sig;
                    _queueRowEls[item.id] = fresh;
                    if (row && row.parentNode === listEl) listEl.replaceChild(fresh, row);
                    else listEl.appendChild(fresh);
                    row = fresh;
                }
                var fill = row.querySelector('.progress-fill');
                if (fill) fill.style.width = Math.min(100, progress) + '%';
                var pct = row.querySelector('.queue-pct');
                if (pct) pct.textContent = Math.round(progress) + '%';
            });
            Array.prototype.slice.call(listEl.children).forEach(function(el) {
                if (!seenIds[el.dataset.itemid]) {
                    delete _queueRowEls[el.dataset.itemid];
                    el.remove();
                }
            });
        }
        if (emptyEl) emptyEl.classList.toggle('hidden', items.length > 0);
        if (pauseBtn) pauseBtn.disabled = !!(_queueState && _queueState.paused);
        if (resumeBtn) resumeBtn.disabled = !(_queueState && _queueState.paused);
    }

    return {
        init: init,
        onPageEnter: onPageEnter
    };
})();
