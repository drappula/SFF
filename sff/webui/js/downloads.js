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
        if (clearBtn) clearBtn.addEventListener('click', function() { Bridge.call('download_queue_clear_finished'); });

        var queueList = document.getElementById('downloads-queue-list');
        if (queueList) {
            queueList.addEventListener('click', function(e) {
                var btn = e.target.closest('[data-queue-action]');
                if (!btn) return;
                var id = btn.dataset.itemId;
                if (btn.dataset.queueAction === 'retry') {
                    Bridge.call('download_queue_retry', id);
                } else if (btn.dataset.queueAction === 'remove') {
                    Bridge.call('download_queue_remove', id);
                }
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
        _downloads[id] = {
            id: id,
            name: data.name || ('App ' + id),
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
            activeList.innerHTML = '';
            activeItems.forEach(function(dl) {
                activeList.appendChild(Components.createDownloadItem(dl));
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

    function _renderQueue() {
        var listEl = document.getElementById('downloads-queue-list');
        var emptyEl = document.getElementById('downloads-queue-empty');
        var pauseBtn = document.getElementById('queue-pause');
        var resumeBtn = document.getElementById('queue-resume');
        var items = (_queueState && _queueState.items) || [];
        if (listEl) {
            listEl.innerHTML = '';
            items.forEach(function(item) {
                var dl = _downloads[String(item.app_id)];
                var progress = dl && typeof dl.progress === 'number' ? dl.progress : 0;
                var stateLabel = item.state;
                var badgeClass = 'queue-badge-' + item.state;
                var actions = '';
                if (item.state === 'failed') {
                    actions += '<button class="btn btn-sm" data-queue-action="retry" data-item-id="' + Components.escapeHtml(item.id) + '">Retry</button>';
                }
                actions += '<button class="btn btn-sm" data-queue-action="remove" data-item-id="' + Components.escapeHtml(item.id) + '">Remove</button>';
                if (item.error) {
                    actions += '<span style="font-size:11px;opacity:0.7;margin-left:6px;" title="' + Components.escapeHtml(item.error) + '">(error)</span>';
                }
                var row = document.createElement('div');
                row.className = 'download-item';
                row.innerHTML =
                    '<div class="download-info" style="flex:1;">' +
                        '<div class="download-name">' + Components.escapeHtml(item.name || ('App ' + item.app_id)) +
                        ' <span class="queue-state-badge ' + badgeClass + '">' + Components.escapeHtml(stateLabel) + '</span>' +
                        ' <span style="font-size:11px;opacity:0.65;">via ' + Components.escapeHtml(item.source) + '</span></div>' +
                        '<div class="progress-bar" style="margin-top:4px;"><div class="progress-fill" style="width:' + Math.min(100, progress) + '%"></div></div>' +
                        '<div style="font-size:11px;opacity:0.6;">' + Math.round(progress) + '%</div>' +
                    '</div>' +
                    '<div class="download-actions" style="display:flex;gap:6px;align-items:center;">' + actions + '</div>';
                listEl.appendChild(row);
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
