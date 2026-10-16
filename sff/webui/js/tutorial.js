/* SteaMidra - Steam game setup and manifest tool (SFF)
 * Copyright (c) 2025-2026 Midrag (https://github.com/Midrags)
 *
 * This file is part of SteaMidra.
 *
 * SteaMidra is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * SteaMidra is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with SteaMidra.  If not, see <https://www.gnu.org/licenses/>.
 */

/**
 * SteaMidra — First-run interactive guide.
 * Pure frontend. Dialog box + spotlight arrow. The dim overlay is
 * built from four panes that leave a hole over the focused element,
 * so the target is never blackened. All downloads are simulated with
 * mock DOM (tutorial-* IDs). No Bridge download call ever fires here.
 */
window.Tutorial = (function() {
    'use strict';

    var MOCK_APP_ID = '999999';
    var HOLE_PAD = 6;
    var _stepIdx = 0;
    var _started = false;
    var _fakeTimer = null;
    var _spotEl = null;
    var _observer = null;

    var KEY_HINTS = {
        freelua: 'Free Providers need no key.',
        hubcap: 'Needs a Hubcap API key (Settings > Paths & Keys).',
        ryuu: 'Needs a Ryuu key (Settings > Paths & Keys).',
        depotbox: 'Needs a DepotBox API key (Settings > Paths & Keys).'
    };

    function _isLinux() {
        if (window.App && typeof window.App.getPlatform === 'function') {
            try { return window.App.getPlatform() !== 'win32'; } catch (e) {}
        }
        return document.body.classList.contains('platform-linux');
    }

    function _get(key, cb) {
        try {
            if (window.Bridge && window.Bridge.callWithCallback) {
                window.Bridge.callWithCallback('get_setting', key, function(val) { cb(val); });
                return;
            }
        } catch (e) {}
        try { cb(window.localStorage.getItem(key)); } catch (e) { cb(null); }
    }

    function _set(key, val) {
        try {
            if (window.Bridge && window.Bridge.call) {
                window.Bridge.call('set_setting', key, val);
                return;
            }
        } catch (e) {}
        try { window.localStorage.setItem(key, val); } catch (e) {}
    }

    function _go(page) {
        try {
            if (window.App && typeof window.App.navigateTo === 'function') {
                window.App.navigateTo(page);
            }
        } catch (e) {}
    }

    function _toast(type, msg) {
        try {
            if (window.Components && typeof window.Components.showToast === 'function') {
                window.Components.showToast(type, msg);
            }
        } catch (e) {}
    }

    function _steps() {
        var linux = _isLinux();
        var steps = [
            {
                page: 'home', sel: null,
                title: 'Add your first game',
                body: 'This takes about a minute.'
            },
            {
                page: 'home',
                sel: linux ? '#page-home [data-action="linux_setup"]' : '[data-action="auto_lc_setup"]',
                title: linux ? 'Run Linux Setup' : 'Run Auto LC Setup',
                body: linux
                    ? 'Click Linux Setup once. It installs SLSsteam and checks .NET 9 so Steam recognizes your games.'
                    : 'Click Auto LC Setup once. It copies the LumaCore files into your Steam folder so Steam recognizes your games.'
            },
            {
                page: 'store', sel: '.nav-item[data-page="store"]',
                title: 'Open the Store tab',
                body: 'The Store is where you find games. Search by name or App ID.'
            },
            {
                page: 'store', sel: '#tutorial-mock-card',
                title: 'Pick a game',
                body: 'This is the top result for your search.'
            },
            {
                page: 'store', sel: '#tutorial-mock-download',
                title: 'Download it',
                body: 'Click Download on the game.'
            },
            {
                page: 'store', sel: '#tutorial-src-freelua',
                title: 'Free Providers',
                body: 'Free Providers need no key. Start here.'
            },
            {
                page: 'store', sel: '#tutorial-src-hubcap',
                title: 'Hubcap',
                body: 'Hubcap is the best source, covering the most games with the quickest updates. It needs an API key. Get one at <a href="#" data-openurl="https://hubcapmanifest.com">hubcapmanifest.com</a>. A Discord account is required to get the key.' +
                    '<div id="tutorial-key-ask-hubcap" style="margin-top:10px;">Add the key now? ' +
                    '<button class="btn btn-sm btn-primary" id="tutorial-key-yes-hubcap" type="button">Yes</button> ' +
                    '<button class="btn btn-sm" id="tutorial-key-no-hubcap" type="button">No</button></div>'
            },
            {
                page: 'store', sel: '#tutorial-src-ryuu',
                title: 'Ryuu',
                body: 'Ryuu is an alternative source with fewer games. Its API key is advertised as premium-only, but everyone seems to get one. Log in at <a href="#" data-openurl="https://generator.ryuu.lol/api">generator.ryuu.lol/api</a> first (you need a Discord account), then open the same link again and your key is at the top.' +
                    '<div id="tutorial-key-ask-ryuu" style="margin-top:10px;">Add the key now? ' +
                    '<button class="btn btn-sm btn-primary" id="tutorial-key-yes-ryuu" type="button">Yes</button> ' +
                    '<button class="btn btn-sm" id="tutorial-key-no-ryuu" type="button">No</button></div>'
            },
            {
                page: 'store', sel: '#tutorial-src-depotbox',
                title: 'DepotBox',
                body: 'DepotBox is paid-only. For details, join their Discord: <a href="#" data-openurl="https://discord.gg/depotbox">discord.gg/depotbox</a>.'
            },
            linux ? {
                page: 'store', sel: '#tutorial-dl-ddmod',
                title: 'Download natively',
                body: 'Choose Native download. It pulls the game files straight from the Steam CDN, falling back to DepotDownloaderMod if needed (.NET 9 required). Through-Steam is Windows-only.'
            } : {
                page: 'store', sel: '#tutorial-dl-fastest',
                title: 'Download through Steam',
                body: 'Choose Download through Steam. Steam pulls the files once everything is set.'
            },
            {
                page: 'downloads', sel: '.nav-item[data-page="downloads"]',
                title: 'Watch it in Downloads',
                body: 'Your download lands here.'
            },
            {
                page: 'downloads', sel: '#tutorial-mock-row',
                title: 'Wait for Done',
                body: 'Each row shows speed, depot, and ETA. This one finishes in a few seconds.'
            }
        ];
        if (linux) {
            steps.push({
                page: 'downloads', sel: '#btn-restart-steam',
                title: 'Restart Steam',
                body: 'Click Restart Steam so the new game shows up.'
            });
        }
        steps.push({
            page: 'home', sel: null,
            title: 'Open Steam',
            body: 'The game is in your library.'
        });
        steps.push({
            page: 'home', sel: null,
            title: 'Join the Discord',
            body: 'Stuck on something? Ask on the SteaMidra server: <a href="#" data-openurl="https://discord.gg/XMFUbxUbRY">discord.gg/XMFUbxUbRY</a>. Replay this guide from Settings any time.'
        });
        return steps;
    }

    function _needsMockCard(idx) {
        var steps = _steps();
        return _started && steps[idx] && steps[idx].page === 'store' && idx >= 3 && idx <= 9;
    }

    function _needsMockRow(idx) {
        var steps = _steps();
        return _started && steps[idx] && steps[idx].page === 'downloads' && idx >= 10;
    }

    function _buildDom() {
        if (document.getElementById('tutorial-overlay')) return;
        var overlay = document.createElement('div');
        overlay.id = 'tutorial-overlay';
        overlay.className = 'hidden';
        ['N', 'S', 'W', 'E'].forEach(function(k) {
            var p = document.createElement('div');
            p.className = 'tutorial-pane hidden';
            p.id = 'tutorial-pane-' + k;
            overlay.appendChild(p);
        });
        document.body.appendChild(overlay);

        var arrow = document.createElement('div');
        arrow.id = 'tutorial-arrow';
        arrow.className = 'hidden';
        arrow.textContent = '\u2B06';
        document.body.appendChild(arrow);

        var dlg = document.createElement('div');
        dlg.id = 'tutorial-dialog';
        dlg.className = 'hidden';
        dlg.innerHTML =
            '<div id="tutorial-dialog-title"></div>' +
            '<div id="tutorial-dialog-body"></div>' +
            '<div id="tutorial-dialog-meta">' +
            '<span id="tutorial-step-count"></span>' +
            '<span id="tutorial-dialog-btns">' +
            '<button id="tutorial-back" class="btn btn-sm">Back</button>' +
            '<button id="tutorial-skip" class="btn btn-sm">Skip</button>' +
            '<button id="tutorial-next" class="btn btn-sm btn-primary">Next</button>' +
            '</span></div>';
        document.body.appendChild(dlg);
        document.getElementById('tutorial-back').addEventListener('click', back);
        document.getElementById('tutorial-skip').addEventListener('click', skip);
        document.getElementById('tutorial-next').addEventListener('click', next);

        var optin = document.createElement('div');
        optin.id = 'tutorial-optin';
        optin.className = 'modal hidden';
        optin.innerHTML =
            '<div class="modal-overlay"></div>' +
            '<div class="modal-content" style="max-width:400px;">' +
            '<div class="modal-header"><h2>New here?</h2></div>' +
            '<div class="modal-body"><p style="line-height:1.6;margin:0;">See how to add your first game in about a minute.</p></div>' +
            '<div class="modal-footer" style="display:flex;justify-content:flex-end;gap:10px;">' +
            '<button id="tutorial-optin-no" class="btn">No thanks</button>' +
            '<button id="tutorial-optin-yes" class="btn btn-primary">Start</button>' +
            '</div></div>';
        document.body.appendChild(optin);
        document.getElementById('tutorial-optin-no').addEventListener('click', function() {
            _set('tutorial_asked', 'True');
            optin.classList.add('hidden');
        });
        document.getElementById('tutorial-optin-yes').addEventListener('click', function() {
            _set('tutorial_asked', 'True');
            optin.classList.add('hidden');
            start();
        });

        window.addEventListener('resize', _relayout);
        window.addEventListener('scroll', _relayout, true);
    }

    function _watchStores() {
        if (_observer) return;
        try {
            _observer = new MutationObserver(function() {
                if (!_started) return;
                if (_needsMockCard(_stepIdx) && !document.getElementById('tutorial-mock-card')) {
                    _injectMockCard();
                    _relayout();
                }
                if (_needsMockRow(_stepIdx) && !document.getElementById('tutorial-mock-row')) {
                    _injectMockRow();
                    _relayout();
                }
            });
            ['store-grid', 'store-list', 'downloads-active-list'].forEach(function(id) {
                var el = document.getElementById(id);
                if (el) _observer.observe(el, { childList: true });
            });
        } catch (e) {}
    }

    function _injectMockCard() {
        _removeMockCard();
        var grid = document.getElementById('store-grid');
        if (!grid) return;
        // The store hides the grid while loading or in list view.
        // The mock lives in the grid, so make sure it is visible.
        grid.classList.remove('hidden');
        var card = document.createElement('div');
        card.className = 'game-card';
        card.id = 'tutorial-mock-card';
        card.dataset.appid = MOCK_APP_ID;
        card.setAttribute('role', 'listitem');
        card.innerHTML =
            '<span class="tutorial-demo-badge">DEMO</span>' +
            '<div class="tutorial-mock-cover">\uD83C\uDFAE</div>' +
            '<div class="game-card-body">' +
            '<div class="game-card-name">Tutorial Demo Game</div>' +
            '<div class="game-card-appid">App ID: 999999 (fake)</div>' +
            '</div>' +
            '<div class="game-card-actions">' +
            '<button id="tutorial-mock-download" class="btn btn-primary btn-download" type="button">Download</button>' +
            '</div>';
        grid.insertBefore(card, grid.firstChild);
        var btn = document.getElementById('tutorial-mock-download');
        if (btn) btn.addEventListener('click', function(ev) {
            ev.preventDefault();
            ev.stopPropagation();
            _showMockModal();
            next();
        });
    }

    function _removeMockCard() {
        var card = document.getElementById('tutorial-mock-card');
        if (card && card.parentNode) card.parentNode.removeChild(card);
    }

    // Same layout as the real #download-modal, tutorial-* IDs,
    // static rows, no backend calls.
    function _showMockModal() {
        _hideMockModal();
        var m = document.createElement('div');
        m.id = 'tutorial-download-modal';
        m.innerHTML =
            '<div class="modal-overlay"></div>' +
            '<div class="modal-content">' +
            '<div class="modal-header"><h2>Download: Tutorial Demo Game (999999)</h2>' +
            '<button class="modal-close" id="tutorial-dl-close" type="button">&times;</button></div>' +
            '<div class="modal-body">' +
            '<div class="dl-source-picker">' +
            '<span class="dl-source-label">Download source:</span>' +
            '<label class="dl-source-option" id="tutorial-src-freelua"><input type="radio" name="tutorial-dl-source" value="freelua" checked> Free Providers</label>' +
            '<label class="dl-source-option" id="tutorial-src-hubcap"><input type="radio" name="tutorial-dl-source" value="hubcap"> Hubcap</label>' +
            '<label class="dl-source-option" id="tutorial-src-ryuu"><input type="radio" name="tutorial-dl-source" value="ryuu"> Ryuu</label>' +
            '<label class="dl-source-option" id="tutorial-src-depotbox"><input type="radio" name="tutorial-dl-source" value="depotbox"> DepotBox</label>' +
            '</div>' +
            '<div id="tutorial-dl-key-hint" style="margin-top:8px; padding-left:4px; font-size:12px; opacity:0.85;">' + KEY_HINTS.freelua + '</div>' +
            '<div style="margin-top:8px; padding-left:4px;">' +
            '<div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:4px;">' +
            '<span style="font-size:11px; opacity:0.7;">Depot OS:</span>' +
            '</div>' +
            '<div class="custom-select"><div class="custom-select-display">' +
            '<span class="custom-select-text">Windows</span>' +
            '<span class="custom-select-arrow">\u25BE</span>' +
            '</div></div>' +
            '</div>' +
            '<div style="margin-top:8px; padding-left:4px;">' +
            '<div style="font-size:11px; opacity:0.7; margin-bottom:4px;">DDMod download location:</div>' +
            '<div style="display:flex; gap:8px; align-items:center;">' +
            '<input type="text" readonly placeholder="Choose where DDMod should download..." style="flex:1; font-size:12px;">' +
            '<button class="btn btn-sm" type="button">Browse</button>' +
            '<button class="btn btn-sm" type="button">Clear</button>' +
            '</div>' +
            '</div>' +
            '<button id="tutorial-dl-fastest" class="download-option" type="button" style="margin-top:12px;">' +
            '<svg class="dl-icon" viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>' +
            '<div class="dl-info"><span class="dl-title">Download through Steam (Fastest)</span>' +
            '<span class="dl-desc">Downloads manifests + keys so Steam installs the game natively. Fastest method.</span></div>' +
            '</button>' +
            '<button id="tutorial-dl-ddmod" class="download-option" type="button">' +
            '<svg class="dl-icon" viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>' +
            '<div class="dl-info"><span class="dl-title">Native download (DDMod fallback)</span>' +
            '<span class="dl-desc">Downloads directly from Steam CDN. Falls back to DepotDownloaderMod if needed (requires .NET 9).</span></div>' +
            '</button>' +
            '<button id="tutorial-dl-older" class="download-option" type="button">' +
            '<svg class="dl-icon" viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>' +
            '<div class="dl-info"><span class="dl-title">Download Older Version</span>' +
            '<span class="dl-desc">Pick a specific older version via DDMod or Steam (Native).</span></div>' +
            '</button>' +
            '<div id="tutorial-dl-nudge">Use the recommended download option here.</div>' +
            '</div>' +
            '<div class="modal-footer"><button class="btn" id="tutorial-dl-cancel" type="button">Cancel</button></div>' +
            '</div>';
        document.body.appendChild(m);
        var radios = m.querySelectorAll('input[name="tutorial-dl-source"]');
        Array.prototype.forEach.call(radios, function(r) {
            r.addEventListener('change', function() {
                var hint = document.getElementById('tutorial-dl-key-hint');
                if (hint) hint.textContent = KEY_HINTS[r.value] || '';
            });
        });
        function nudge(ev) {
            ev.preventDefault();
            ev.stopPropagation();
            var n = document.getElementById('tutorial-dl-nudge');
            if (n) n.classList.add('visible');
        }
        var ddmod = document.getElementById('tutorial-dl-ddmod');
        var older = document.getElementById('tutorial-dl-older');
        var fastest = document.getElementById('tutorial-dl-fastest');
        function advance(ev) {
            ev.preventDefault();
            ev.stopPropagation();
            _hideMockModal();
            var steps = _steps();
            for (var i = 0; i < steps.length; i++) {
                if (steps[i].sel === '.nav-item[data-page="downloads"]') { _stepIdx = i; break; }
            }
            _enterStep();
        }
        if (_isLinux()) {
            // Mirrors the real modal: through-Steam needs LumaCore,
            // so Linux only gets the native download.
            if (fastest) fastest.style.display = 'none';
            if (ddmod) ddmod.addEventListener('click', advance);
        } else {
            if (ddmod) ddmod.addEventListener('click', nudge);
            if (fastest) fastest.addEventListener('click', advance);
        }
        if (older) older.addEventListener('click', nudge);
        function goBack(ev) {
            if (ev) { ev.preventDefault(); ev.stopPropagation(); }
            _hideMockModal();
            back();
        }
        var close = document.getElementById('tutorial-dl-close');
        var cancel = document.getElementById('tutorial-dl-cancel');
        if (close) close.addEventListener('click', goBack);
        if (cancel) cancel.addEventListener('click', goBack);
    }

    function _hideMockModal() {
        var m = document.getElementById('tutorial-download-modal');
        if (m && m.parentNode) m.parentNode.removeChild(m);
    }

    // Inline "Add the key now?" prompt. Yes opens the key modal,
    // No dismisses the question. Same save path as Settings.
    function _wireKeyAsk(kind) {
        var yes = document.getElementById('tutorial-key-yes-' + kind);
        var no = document.getElementById('tutorial-key-no-' + kind);
        if (yes && !yes.dataset.wired) {
            yes.dataset.wired = '1';
            yes.addEventListener('click', function(ev) {
                ev.preventDefault();
                ev.stopPropagation();
                _showKeyModal(kind);
            });
        }
        if (no && !no.dataset.wired) {
            no.dataset.wired = '1';
            no.addEventListener('click', function(ev) {
                ev.preventDefault();
                ev.stopPropagation();
                var ask = document.getElementById('tutorial-key-ask-' + kind);
                if (ask) ask.style.display = 'none';
            });
        }
    }

    function _showKeyModal(kind) {
        _hideKeyModal();
        var label = kind === 'hubcap' ? 'Hubcap API Key' : 'Ryuu API Key';
        var m = document.createElement('div');
        m.id = 'tutorial-key-modal';
        m.style.cssText = 'position:fixed;inset:0;z-index:2007;display:flex;align-items:center;justify-content:center;';
        m.innerHTML =
            '<div class="modal-overlay"></div>' +
            '<div class="modal-content" style="max-width:400px;">' +
            '<div class="modal-header"><h2>' + label + '</h2>' +
            '<button class="modal-close" id="tutorial-key-close" type="button">&times;</button></div>' +
            '<div class="modal-body">' +
            '<div class="input-with-btn">' +
            '<input type="password" id="tutorial-key-input" placeholder="Paste the key here">' +
            '</div></div>' +
            '<div class="modal-footer" style="display:flex;justify-content:flex-end;gap:10px;">' +
            '<button class="btn" id="tutorial-key-cancel" type="button">Cancel</button>' +
            '<button class="btn btn-primary" id="tutorial-key-save" type="button">Save</button>' +
            '</div></div>';
        document.body.appendChild(m);
        function close() { _hideKeyModal(); }
        document.getElementById('tutorial-key-close').addEventListener('click', close);
        document.getElementById('tutorial-key-cancel').addEventListener('click', close);
        document.getElementById('tutorial-key-save').addEventListener('click', function(ev) {
            ev.preventDefault();
            ev.stopPropagation();
            var input = document.getElementById('tutorial-key-input');
            var val = input ? input.value.trim() : '';
            if (!val) { _toast('warning', 'Please enter a value'); return; }
            try {
                if (kind === 'hubcap') {
                    window.Bridge.call('connect_store', val);
                } else {
                    window.Bridge.call('set_setting', 'ryuu_api_key', val);
                }
            } catch (e) {}
            _toast('success', label + ' saved');
            var ask = document.getElementById('tutorial-key-ask-' + kind);
            if (ask) ask.innerHTML = 'Key saved.';
            close();
        });
        var input = document.getElementById('tutorial-key-input');
        if (input) input.focus();
    }

    function _hideKeyModal() {
        var m = document.getElementById('tutorial-key-modal');
        if (m && m.parentNode) m.parentNode.removeChild(m);
    }

    function _injectMockRow() {
        _removeMockRow();
        var list = document.getElementById('downloads-active-list');
        if (!list) return;
        var empty = document.getElementById('downloads-active-empty');
        if (empty) empty.classList.add('hidden');
        var row = document.createElement('div');
        row.className = 'download-item';
        row.id = 'tutorial-mock-row';
        row.innerHTML =
            '<div class="download-item-info">' +
            '<div class="download-item-name">Tutorial Demo Game</div>' +
            '<div class="download-item-status" id="tutorial-fake-status">Downloading... 0%</div>' +
            '<div id="tutorial-fake-progress-track"><div id="tutorial-fake-progress-fill"></div></div>' +
            '</div>';
        list.insertBefore(row, list.firstChild);
        var pct = 0;
        if (_fakeTimer) clearInterval(_fakeTimer);
        _fakeTimer = setInterval(function() {
            pct = Math.min(100, pct + 10);
            var fill = document.getElementById('tutorial-fake-progress-fill');
            var status = document.getElementById('tutorial-fake-status');
            if (!fill || !status) { clearInterval(_fakeTimer); _fakeTimer = null; return; }
            fill.style.width = pct + '%';
            status.textContent = pct >= 100 ? 'Done' : 'Downloading... ' + pct + '%';
            if (pct >= 100) { clearInterval(_fakeTimer); _fakeTimer = null; }
        }, 450);
    }

    function _removeMockRow() {
        if (_fakeTimer) { clearInterval(_fakeTimer); _fakeTimer = null; }
        var row = document.getElementById('tutorial-mock-row');
        if (row && row.parentNode) row.parentNode.removeChild(row);
        var empty = document.getElementById('downloads-active-empty');
        var list = document.getElementById('downloads-active-list');
        if (empty && list && !list.children.length) empty.classList.remove('hidden');
    }

    function _clearSpotlight() {
        if (_spotEl) {
            _spotEl.classList.remove('tutorial-spotlight');
            _spotEl = null;
        }
        var arrow = document.getElementById('tutorial-arrow');
        if (arrow) arrow.classList.add('hidden');
    }

    function _setPane(id, left, top, width, height) {
        var p = document.getElementById(id);
        if (!p) return;
        if (width <= 0 || height <= 0) {
            p.classList.add('hidden');
            return;
        }
        p.classList.remove('hidden');
        p.style.left = left + 'px';
        p.style.top = top + 'px';
        p.style.width = width + 'px';
        p.style.height = height + 'px';
    }

    function _layoutOverlay(rect) {
        var vw = window.innerWidth;
        var vh = window.innerHeight;
        if (!rect) {
            _setPane('tutorial-pane-N', 0, 0, vw, vh);
            _setPane('tutorial-pane-S', 0, 0, 0, 0);
            _setPane('tutorial-pane-W', 0, 0, 0, 0);
            _setPane('tutorial-pane-E', 0, 0, 0, 0);
            return;
        }
        var t = Math.max(0, rect.top - HOLE_PAD);
        var b = Math.min(vh, rect.bottom + HOLE_PAD);
        var l = Math.max(0, rect.left - HOLE_PAD);
        var r = Math.min(vw, rect.right + HOLE_PAD);
        _setPane('tutorial-pane-N', 0, 0, vw, t);
        _setPane('tutorial-pane-S', 0, b, vw, vh - b);
        _setPane('tutorial-pane-W', 0, t, l, b - t);
        _setPane('tutorial-pane-E', r, t, vw - r, b - t);
    }

    function _relayout() {
        if (!_started) return;
        var steps = _steps();
        var cur = steps[_stepIdx];
        if (!cur || !cur.sel || !_spotEl || !document.contains(_spotEl)) return;
        try {
            var rect = _spotEl.getBoundingClientRect();
            _layoutOverlay(rect);
            var arrow = document.getElementById('tutorial-arrow');
            var dlg = document.getElementById('tutorial-dialog');
            if (arrow) {
                var cx = rect.left + rect.width / 2 - 14;
                cx = Math.max(8, Math.min(window.innerWidth - 40, cx));
                // Arrow below the target, pointing up at it.
                // Only go above when there is no room below.
                if (rect.bottom + 48 < window.innerHeight) {
                    arrow.textContent = '\u2B06';
                    arrow.style.left = cx + 'px';
                    arrow.style.top = (rect.bottom + 8) + 'px';
                    arrow.classList.remove('hidden');
                } else if (rect.top - 48 > 0) {
                    arrow.textContent = '\u2B07';
                    arrow.style.left = cx + 'px';
                    arrow.style.top = (rect.top - 40) + 'px';
                    arrow.classList.remove('hidden');
                } else {
                    arrow.classList.add('hidden');
                }
            }
            if (dlg) {
                // Keep the dialog off the target.
                dlg.classList.toggle('tutorial-dialog-top', rect.bottom > window.innerHeight - 240);
            }
        } catch (e) {}
    }

    function _enterStep() {
        var steps = _steps();
        if (_stepIdx < 0) _stepIdx = 0;
        if (_stepIdx >= steps.length) { finish(); return; }
        var st = steps[_stepIdx];
        _clearSpotlight();
        _go(st.page);

        // Reset chrome synchronously so the previous step's hole/arrow
        // never lingers while the next page loads. Full dim until the
        // new target is measured below.
        var titleEarly = document.getElementById('tutorial-dialog-title');
        var bodyEarly = document.getElementById('tutorial-dialog-body');
        var countEarly = document.getElementById('tutorial-step-count');
        if (titleEarly) titleEarly.textContent = st.title;
        if (bodyEarly) bodyEarly.innerHTML = st.body;
        _wireKeyAsk('hubcap');
        _wireKeyAsk('ryuu');
        if (countEarly) countEarly.textContent = (_stepIdx + 1) + ' / ' + steps.length;
        var backEarly = document.getElementById('tutorial-back');
        if (backEarly) backEarly.disabled = _stepIdx === 0;
        var nextEarly = document.getElementById('tutorial-next');
        if (nextEarly) nextEarly.textContent = _stepIdx === steps.length - 1 ? 'Finish' : 'Next';
        var overlayEarly = document.getElementById('tutorial-overlay');
        if (overlayEarly) overlayEarly.classList.remove('hidden');
        var dlgEarly = document.getElementById('tutorial-dialog');
        if (dlgEarly) dlgEarly.classList.remove('hidden');
        _layoutOverlay(null);

        if (_needsMockCard(_stepIdx)) _injectMockCard();
        else if (_stepIdx < 3 || st.page !== 'store') _removeMockCard();
        if (_stepIdx >= 5 && _stepIdx <= 9) {
            if (!document.getElementById('tutorial-download-modal')) _showMockModal();
        } else {
            _hideMockModal();
        }
        if (_needsMockRow(_stepIdx)) _injectMockRow();

        // Defer so navigateTo paints and the store's async render
        // settles before measuring the target.
        setTimeout(function() {
            if (!_started) return;
            // The store re-renders async and can wipe the mock card.
            // Re-add it before measuring.
            if (_needsMockCard(_stepIdx) && !document.getElementById('tutorial-mock-card')) {
                _injectMockCard();
            }
            if (_needsMockRow(_stepIdx) && !document.getElementById('tutorial-mock-row')) {
                _injectMockRow();
            }
            var stepsNow = _steps();
            var cur = stepsNow[_stepIdx];
            if (!cur) return;
            if (!cur.sel) {
                var dlg = document.getElementById('tutorial-dialog');
                if (dlg) dlg.classList.remove('tutorial-dialog-top');
                return;
            }
            var el = document.querySelector(cur.sel);
            if (!el) {
                return;
            }
            try { el.scrollIntoView({ block: 'center', behavior: 'auto' }); } catch (e) {}
            // Measure after the scroll lands.
            setTimeout(function() {
                if (!_started) return;
                var stepsLate = _steps();
                if (!stepsLate[_stepIdx] || stepsLate[_stepIdx].sel !== cur.sel) return;
                var target = document.querySelector(cur.sel);
                if (!target) { _layoutOverlay(null); return; }
                target.classList.add('tutorial-spotlight');
                _spotEl = target;
                _relayout();
            }, 150);
        }, 200);
    }

    function start() {
        _buildDom();
        _watchStores();
        if (_started) return;
        _started = true;
        _stepIdx = 0;
        var overlay = document.getElementById('tutorial-overlay');
        if (overlay) overlay.classList.remove('hidden');
        var dlg = document.getElementById('tutorial-dialog');
        if (dlg) dlg.classList.remove('hidden');
        _enterStep();
    }

    function next() {
        if (!_started) return;
        _stepIdx += 1;
        if (_stepIdx >= _steps().length) finish();
        else _enterStep();
    }

    function back() {
        if (!_started || _stepIdx <= 0) return;
        _stepIdx -= 1;
        _enterStep();
    }

    function skip() { finish(); }

    function finish() {
        _started = false;
        _clearSpotlight();
        _hideMockModal();
        _hideKeyModal();
        _removeMockCard();
        _removeMockRow();
        var overlay = document.getElementById('tutorial-overlay');
        var dlg = document.getElementById('tutorial-dialog');
        if (overlay) overlay.classList.add('hidden');
        if (dlg) {
            dlg.classList.add('hidden');
            dlg.classList.remove('tutorial-dialog-top');
        }
        ['N', 'S', 'W', 'E'].forEach(function(k) {
            var p = document.getElementById('tutorial-pane-' + k);
            if (p) p.classList.add('hidden');
        });
        var arrow = document.getElementById('tutorial-arrow');
        if (arrow) arrow.classList.add('hidden');
        _set('tutorial_seen', 'True');
        _go('home');
    }

    function cleanup() {
        _hideMockModal();
        _hideKeyModal();
        _removeMockCard();
        _removeMockRow();
        _clearSpotlight();
    }

    function init() {
        _buildDom();
        var replay = document.getElementById('settings-tutorial-replay');
        if (replay && !replay.dataset.tutWired) {
            replay.dataset.tutWired = '1';
            replay.addEventListener('click', function() { start(); });
        }
        try {
            if (window.Bridge && window.Bridge.onReady) {
                window.Bridge.onReady(function() {
                    // Delay so Linux guide / self-update popups win the race.
                    setTimeout(function() {
                        _get('tutorial_asked', function(val) {
                            if (val === 'True') return;
                            var optin = document.getElementById('tutorial-optin');
                            if (optin) optin.classList.remove('hidden');
                        });
                    }, 3000);
                });
            }
        } catch (e) {}
    }

    return {
        init: init,
        start: start,
        next: next,
        back: back,
        skip: skip,
        finish: finish,
        cleanup: cleanup
    };
})();

document.addEventListener('DOMContentLoaded', function() {
    try { window.Tutorial.init(); } catch (e) {}
});
