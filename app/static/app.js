'use strict';

// ============================================================
// CONSTANTS & CONFIG
// ============================================================
const HISTORY_MAX = 60;

const TABS = [
  { id: 'overview',   label: 'Overview' },
  { id: 'cpu',        label: 'CPU' },
  { id: 'ram',        label: 'RAM' },
  { id: 'gpu',        label: 'GPU' },
  { id: 'storage',    label: 'Storage' },
  { id: 'network',    label: 'Network' },
  { id: 'processes',  label: 'Processes' },
  { id: 'sensors',    label: 'Sensors' },
  { id: 'system',     label: 'System Info' },
  { id: 'history',    label: 'History' },
];

const HISTORY_RANGES = [
  { hours: 1,   bucket: 30,   label: '1h'  },
  { hours: 6,   bucket: 60,   label: '6h'  },
  { hours: 24,  bucket: 300,  label: '24h' },
  { hours: 168, bucket: 1800, label: '7d'  },
  { hours: 720, bucket: 7200, label: '30d' },
];

// ============================================================
// STATE
// ============================================================
const S = {
  data: {},
  tab: 'overview',
  procTab: 'cpu',
  autoRefresh: true,
  intervalSec: 5,
  timerId: null,
  charts: {},
  history: {
    ts:     [],
    cpu:    [],
    ram:    [],
    gpu:    [],
    gpus:   [],   // per-GPU: [[gpu0 samples], [gpu1 samples], ...]
    netRx:  [],
    netTx:  [],
  },
  prevNet: null,
  prevNetAt: 0,
  historyRange: 6,
  historyFetchId: 0,
};

// ============================================================
// UTILITIES
// ============================================================
function esc(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function pct(v, d) {
  d = d == null ? 1 : d;
  var n = parseFloat(v) || 0;
  return Math.min(100, Math.max(0, n)).toFixed(d);
}

function fmtBytes(bytes, d) {
  d = d == null ? 1 : d;
  var b = parseFloat(bytes) || 0;
  if (b === 0) return '0 B';
  var units = ['B', 'KB', 'MB', 'GB', 'TB'];
  var i = Math.min(Math.floor(Math.log(b) / Math.log(1024)), units.length - 1);
  return (b / Math.pow(1024, i)).toFixed(d) + ' ' + units[i];
}

function fmtRate(bps) {
  return fmtBytes(bps, 1) + '/s';
}

function fmtKb(kb) {
  var n = parseInt(kb) || 0;
  if (n === 0) return '<span class="muted-text">—</span>';
  if (n < 1024) return n + ' KB';
  if (n < 1048576) return (n / 1024).toFixed(1) + ' MB';
  return (n / 1048576).toFixed(2) + ' GB';
}

function showCopyToast(el) {
  var rect = el.getBoundingClientRect();
  var toast = document.createElement('div');
  toast.className = 'copy-toast';
  toast.textContent = 'Copied!';
  toast.style.top  = (rect.top  + window.scrollY - 30) + 'px';
  toast.style.left = (rect.left + window.scrollX + rect.width / 2) + 'px';
  document.body.appendChild(toast);
  requestAnimationFrame(function() { toast.classList.add('copy-toast-show'); });
  setTimeout(function() {
    toast.classList.add('copy-toast-hide');
    setTimeout(function() { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 300);
  }, 900);
}

function copyCell(el) {
  var val = (el.getAttribute('data-copy') || el.textContent || '').trim();
  if (!val) return;
  var finish = function() { showCopyToast(el); };
  if (navigator.clipboard) {
    navigator.clipboard.writeText(val).then(finish).catch(finish);
  } else {
    var ta = document.createElement('textarea');
    ta.value = val;
    ta.style.cssText = 'position:fixed;top:-9999px;opacity:0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } catch(e) {}
    document.body.removeChild(ta);
    finish();
  }
}

function colorClass(v, warn, crit) {
  warn = warn == null ? 80 : warn;
  crit = crit == null ? 90 : crit;
  if (v >= crit) return 'color-pink';
  if (v >= warn) return 'color-yellow';
  return 'color-cyan';
}

function barColor(v, warn, crit) {
  warn = warn == null ? 80 : warn;
  crit = crit == null ? 90 : crit;
  if (v >= crit) return 'var(--pink)';
  if (v >= warn) return 'var(--yellow)';
  return 'var(--cyan)';
}

// ============================================================
// HTML HELPERS
// ============================================================
function progressBar(value, warn, crit) {
  var p = parseFloat(pct(value));
  var color = barColor(p, warn, crit);
  return '<div class="progress"><div class="progress-fill" style="width:' + p + '%;background:' + color + '"></div></div>';
}

function statCard(title, value, unit, sub, progressVal, warn, crit) {
  var p = progressVal != null ? progressBar(progressVal, warn, crit) : '';
  var cls = progressVal != null ? colorClass(parseFloat(pct(progressVal)), warn, crit) : 'color-cyan';
  return '<div class="card stat-card">' +
    '<div class="card-title">' + title + '</div>' +
    '<div class="stat-value ' + cls + '">' + esc(value) + '<span class="stat-unit">' + esc(unit || '') + '</span></div>' +
    p +
    (sub ? '<div class="stat-sub">' + sub + '</div>' : '') +
    '</div>';
}

function kv(key, value, valClass) {
  return '<div class="kv-row"><span class="kv-key">' + key + '</span><span class="kv-val ' + (valClass || '') + '">' + value + '</span></div>';
}

function trow(cells, isHeader) {
  var tag = isHeader ? 'th' : 'td';
  return '<tr>' + cells.map(function(c) { return '<' + tag + '>' + c + '</' + tag + '>'; }).join('') + '</tr>';
}

function alert_(msg, level) {
  var cls = level === 'crit' ? 'alert-crit' : (level === 'info' ? 'alert-info' : 'alert-warn');
  var icon = level === 'crit' ? '&#9888;' : (level === 'info' ? '&#x2139;' : '&#9651;');
  return '<div class="alert ' + cls + '">' + icon + ' ' + esc(msg) + '</div>';
}

// hint(label, tip) — wraps label in a hoverable span; tip=null returns plain label
function hint(label, tip) {
  if (!tip) return label;
  return '<span class="hint" data-hint="' + esc(tip) + '">' + label + '</span>';
}

// Maps Linux network interface names to plain-English descriptions
function ifaceHint(name) {
  var n = (name || '').toLowerCase();
  if (n === 'lo')
    return 'Loopback — virtual interface used by the OS to talk to itself. Not a physical network card.';
  if (n.startsWith('eth') || n.startsWith('en'))
    return 'Ethernet — wired network adapter. The suffix encodes its physical location on the motherboard.';
  if (n.startsWith('wl') || n.startsWith('wifi'))
    return 'WiFi — wireless network adapter.';
  if (n.startsWith('docker') || n.startsWith('br-') || n.startsWith('virbr'))
    return 'Virtual bridge — software network created by Docker or a VM hypervisor for container/VM isolation.';
  if (n.startsWith('veth'))
    return 'Virtual Ethernet — one end of a tunnel connecting a container to the host network.';
  if (n.startsWith('tun') || n.startsWith('tap'))
    return 'VPN tunnel — virtual interface created by a VPN client (e.g. WireGuard, OpenVPN).';
  if (n.startsWith('bond'))
    return 'Network bond — multiple physical links combined for higher speed or redundancy (failover).';
  if (n.indexOf('.') >= 0 || n.startsWith('vlan'))
    return 'VLAN — virtual network segment layered on top of a physical interface.';
  return null;
}

// Maps filesystem type names to plain-English descriptions
function fsHint(name) {
  var n = (name || '').toLowerCase();
  if (n === 'tmpfs')                       return 'tmpfs — temporary filesystem stored in RAM. Fast, but all contents are lost on reboot.';
  if (n === 'overlay')                     return 'overlay — layered filesystem used by Docker/Podman containers to stack images.';
  if (n.startsWith('devtmpfs') || n === 'udev') return 'devtmpfs — virtual filesystem that provides device files (/dev). Not real disk storage.';
  if (n === 'shm' || n.endsWith('/shm'))   return 'shm — POSIX shared memory (/dev/shm). Stored in RAM; used for fast communication between processes.';
  if (n.startsWith('cgroup'))              return 'cgroup — kernel resource-control filesystem. Used to limit CPU/RAM/IO for containers and system services.';
  if (n === 'proc')                        return 'proc — virtual filesystem that exposes live kernel and process information (/proc). Not real disk storage.';
  if (n === 'sysfs')                       return 'sysfs — virtual filesystem that exposes hardware and driver information (/sys). Not real disk storage.';
  return null;
}

var PROC_STATE_HINTS = {
  'R': 'Running — actively executing on a CPU core right now.',
  'S': 'Sleeping — idle, waiting for an event such as user input or a timer. Can be interrupted.',
  'D': 'Disk sleep (uninterruptible) — waiting for I/O to complete and cannot be interrupted. High counts can indicate slow storage.',
  'Z': 'Zombie — the process has exited, but its parent hasn\'t collected its exit code yet. Usually disappears quickly.',
  'T': 'Stopped — paused by a signal (e.g. Ctrl+Z) or a debugger.',
  'I': 'Idle — kernel idle thread; not doing any work.',
  'X': 'Dead — in the process of being torn down.',
};

function procStateHint(state) {
  return PROC_STATE_HINTS[String(state || '').toUpperCase()] || null;
}

var LOAD_AVG_HINT = 'Load average — average number of processes waiting for CPU time over this period. Values below your CPU core count are healthy; above it means the system is backlogged.';

// ============================================================
// HINT TOOLTIP ENGINE
// ============================================================
var _hintTooltip = null;

function initHintTooltip() {
  var el = document.createElement('div');
  el.className = 'hint-tooltip';
  document.body.appendChild(el);
  _hintTooltip = el;

  document.addEventListener('mouseover', function(e) {
    var t = e.target && e.target.closest ? e.target.closest('[data-hint]') : null;
    if (t) {
      _hintTooltip.textContent = t.getAttribute('data-hint');
      _hintTooltip.style.opacity = '1';
      _positionHint(e);
    } else {
      _hintTooltip.style.opacity = '0';
    }
  });

  document.addEventListener('mousemove', function(e) {
    if (_hintTooltip.style.opacity === '1') _positionHint(e);
  });
}

function _positionHint(e) {
  if (!_hintTooltip) return;
  var x = e.clientX + 14;
  var y = e.clientY - 42;
  var w = _hintTooltip.offsetWidth;
  var h = _hintTooltip.offsetHeight;
  if (x + w > window.innerWidth  - 8) x = e.clientX - w - 14;
  if (y < 8)                           y = e.clientY + 18;
  _hintTooltip.style.left = x + 'px';
  _hintTooltip.style.top  = y + 'px';
}

// ============================================================
// HISTORY
// ============================================================
function addHistory(cpu, ram, gpu, netRx, netTx, gpuPerDevice) {
  var ts = new Date().toLocaleTimeString('en-US', { hour12: false });
  S.history.ts.push(ts);
  S.history.cpu.push(parseFloat(cpu) || 0);
  S.history.ram.push(parseFloat(ram) || 0);
  S.history.gpu.push(parseFloat(gpu) || 0);
  S.history.netRx.push(parseFloat(netRx) || 0);
  S.history.netTx.push(parseFloat(netTx) || 0);
  if (Array.isArray(gpuPerDevice)) {
    gpuPerDevice.forEach(function(u, i) {
      if (!S.history.gpus[i]) S.history.gpus[i] = [];
      S.history.gpus[i].push(parseFloat(u) || 0);
      if (S.history.gpus[i].length > HISTORY_MAX) S.history.gpus[i].shift();
    });
  }
  if (S.history.ts.length > HISTORY_MAX) {
    ['ts','cpu','ram','gpu','netRx','netTx'].forEach(function(k) { S.history[k].shift(); });
  }
}

function calcNetRates(interfaces) {
  var now = Date.now();
  var totRx = 0, totTx = 0;
  interfaces.forEach(function(i) {
    totRx += parseInt(i.rx_bytes) || 0;
    totTx += parseInt(i.tx_bytes) || 0;
  });
  var rxRate = 0, txRate = 0;
  if (S.prevNet && S.prevNetAt) {
    var dt = (now - S.prevNetAt) / 1000;
    if (dt > 0) {
      rxRate = Math.max(0, (totRx - S.prevNet.rx) / dt);
      txRate = Math.max(0, (totTx - S.prevNet.tx) / dt);
    }
  }
  S.prevNet = { rx: totRx, tx: totTx };
  S.prevNetAt = now;
  return { rxRate: rxRate, txRate: txRate };
}

// ============================================================
// CHART HELPERS
// ============================================================
function destroyCharts() {
  Object.values(S.charts).forEach(function(c) {
    try { c.destroy(); } catch(e) {}
  });
  S.charts = {};
}

function mkDs(label, data, color, fill) {
  return {
    label: label,
    data: data.slice(),
    borderColor: color,
    backgroundColor: color + '18',
    fill: fill == null ? true : fill,
    tension: 0.4,
    pointRadius: 0,
    pointHoverRadius: 3,
    borderWidth: 1.5,
  };
}

var CHART_TOOLTIP = {
  backgroundColor: '#181818',
  borderColor: '#2a2a2a',
  borderWidth: 1,
  titleColor: '#888',
  bodyColor: '#dde',
  titleFont: { family: 'Courier New', size: 10 },
  bodyFont: { family: 'Courier New', size: 11 },
};

function pctChartCfg(labels, datasets) {
  return {
    type: 'line',
    data: { labels: labels, datasets: datasets },
    options: {
      animation: { duration: 250 },
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          display: datasets.length > 1,
          labels: { color: '#555', font: { family: 'Courier New', size: 10 }, boxWidth: 10 },
        },
        tooltip: Object.assign({}, CHART_TOOLTIP),
      },
      scales: {
        x: { display: false },
        y: {
          min: 0,
          max: 100,
          display: true,
          grid: { color: '#1a1a1a' },
          border: { color: '#222' },
          ticks: {
            color: '#444',
            font: { size: 10 },
            maxTicksLimit: 5,
            callback: function(v) { return v + '%'; },
          },
        },
      },
    },
  };
}

function barChartCfg(labels, data, color) {
  return {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        data: data,
        backgroundColor: color + '2a',
        borderColor: color,
        borderWidth: 1,
        borderRadius: 2,
      }],
    },
    options: {
      animation: { duration: 250 },
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: Object.assign({}, CHART_TOOLTIP, {
          callbacks: { label: function(ctx) { return ctx.parsed.y.toFixed(1) + '%'; } },
        }),
      },
      scales: {
        x: {
          grid: { color: '#1a1a1a' },
          border: { color: '#222' },
          ticks: { color: '#444', font: { size: 9 } },
        },
        y: {
          min: 0,
          max: 100,
          grid: { color: '#1a1a1a' },
          border: { color: '#222' },
          ticks: {
            color: '#444',
            font: { size: 10 },
            maxTicksLimit: 5,
            callback: function(v) { return v + '%'; },
          },
        },
      },
    },
  };
}

function netChartCfg(labels, datasets) {
  var allVals = [];
  datasets.forEach(function(d) { allVals = allVals.concat(d.data); });
  var maxVal = Math.max.apply(null, allVals.filter(function(v) { return v > 0; }).concat([1024])) * 1.15;
  return {
    type: 'line',
    data: { labels: labels, datasets: datasets },
    options: {
      animation: { duration: 250 },
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          display: true,
          labels: { color: '#555', font: { family: 'Courier New', size: 10 }, boxWidth: 10 },
        },
        tooltip: Object.assign({}, CHART_TOOLTIP, {
          callbacks: {
            label: function(ctx) { return ctx.dataset.label + ': ' + fmtRate(ctx.parsed.y); },
          },
        }),
      },
      scales: {
        x: { display: false },
        y: {
          min: 0,
          suggestedMax: maxVal,
          display: true,
          grid: { color: '#1a1a1a' },
          border: { color: '#222' },
          ticks: {
            color: '#444',
            font: { size: 10 },
            maxTicksLimit: 5,
            callback: function(v) { return fmtRate(v); },
          },
        },
      },
    },
  };
}

function mkChart(canvasId, cfg) {
  var el = document.getElementById(canvasId);
  if (!el) return null;
  var chart = new Chart(el, cfg);
  S.charts[canvasId] = chart;
  return chart;
}

// ============================================================
// RENDERERS
// ============================================================
function renderLoading() {
  return '<div class="loading-box">Fetching metrics&hellip;</div>';
}
function renderError(msg) {
  return '<div class="error-box">&#9888; ' + esc(msg) + '</div>';
}

/* ---------- OVERVIEW ---------- */
function renderOverview(d) {
  if (!d) return renderLoading();
  if (d.error) return renderError(d.error);

  var mem  = d.memory_usage || {};
  var disk = d.disk_usage   || {};
  var load = d.load_average || {};
  var up   = d.uptime       || {};
  var si   = d.system_info  || {};

  var cpuVal  = parseFloat(d.cpu_usage) || 0;
  var ramVal  = parseFloat(mem.used_percent) || 0;
  var diskVal = parseFloat(disk.used_percent) || 0;
  var uptimeStr = (up.days || 0) + 'd ' + (up.hours || 0) + 'h ' + (up.minutes || 0) + 'm';

  var alerts = [];
  if (cpuVal  >= 90) alerts.push(alert_('CPU critical: '  + pct(cpuVal)  + '%', 'crit'));
  else if (cpuVal  >= 80) alerts.push(alert_('CPU high: '   + pct(cpuVal)  + '%', 'warn'));
  if (ramVal  >= 95) alerts.push(alert_('RAM critical: '  + pct(ramVal)  + '%', 'crit'));
  else if (ramVal  >= 85) alerts.push(alert_('RAM high: '   + pct(ramVal)  + '%', 'warn'));
  if (diskVal >= 90) alerts.push(alert_('Disk critical: ' + pct(diskVal) + '%', 'crit'));
  else if (diskVal >= 80) alerts.push(alert_('Disk high: '  + pct(diskVal) + '%', 'warn'));

  return alerts.join('') +
    '<div class="grid grid-4">' +
      statCard('CPU Usage',     pct(d.cpu_usage),       '%',  'Load: ' + (load['1min']||0).toFixed(2) + ' / ' + (load['5min']||0).toFixed(2) + ' / ' + (load['15min']||0).toFixed(2), d.cpu_usage,       80, 90) +
      statCard('RAM Usage',     pct(mem.used_percent),  '%',  (mem.used_mb||0).toLocaleString() + ' MB / ' + (mem.total_mb||0).toLocaleString() + ' MB', mem.used_percent,  85, 95) +
      statCard('Disk Usage',    String(diskVal),         '%',  esc(disk.used||'?') + ' / ' + esc(disk.size||'?'), disk.used_percent, 80, 90) +
      statCard('Processes',     String(d.process_count||0), '', 'Uptime: ' + uptimeStr, null) +
    '</div>' +
    '<div class="grid grid-2 mt-16">' +
      '<div class="card">' +
        '<div class="card-title">System Info</div>' +
        kv('Hostname', esc(si.hostname||'—'), 'color-cyan') +
        kv('OS',       esc(si.os||'—')) +
        kv('Kernel',   esc(si.kernel||'—')) +
        kv('Time',     esc(d.current_time||'—')) +
        kv('Uptime',   uptimeStr, 'color-green') +
      '</div>' +
      '<div class="card">' +
        '<div class="card-title">Load Average</div>' +
        kv(hint('1 min',  LOAD_AVG_HINT), '<span class="' + colorClass(parseFloat(load['1min']||0) * 20) + '">' + (load['1min']||0).toFixed(2) + '</span>') +
        kv(hint('5 min',  LOAD_AVG_HINT), (load['5min']||0).toFixed(2)) +
        kv(hint('15 min', LOAD_AVG_HINT), (load['15min']||0).toFixed(2)) +
        kv('Processes', String(d.process_count||0)) +
      '</div>' +
    '</div>';
}

/* ---------- CPU ---------- */
function renderCpu(d) {
  if (!d) return renderLoading();
  if (d.error) return renderError(d.error);

  var freq  = d.cpu_frequency    || {};
  var temp  = d.cpu_temperature  || {};
  var load  = d.load_average     || {};
  var cores = d.per_core_usage   || [];
  var procs = d.top_processes    || [];

  var tempVal   = parseFloat(temp.average) || 0;
  var tempClass = tempVal >= 85 ? 'color-pink' : tempVal >= 70 ? 'color-yellow' : 'color-green';

  var procRows = procs.map(function(p) {
    return trow([
      esc(p.pid),
      esc(p.user),
      '<span class="' + colorClass(p.cpu_percent||0) + '">' + (+(p.cpu_percent)||0).toFixed(1) + '</span>',
      (+(p.memory_percent)||0).toFixed(1),
      esc(p.virtual_memory||''),
      esc(p.resident_memory||''),
      esc(p.cpu_time||''),
      '<span class="cmd">' + esc(p.command||'') + '</span>',
    ]);
  }).join('');

  return '<div class="grid grid-4">' +
      statCard('Total CPU',     pct(d.total_cpu), '%', (d.logical_cores||0) + ' logical / ' + (d.physical_cores||0) + ' physical', d.total_cpu) +
      '<div class="card stat-card"><div class="card-title">CPU Model</div><div class="cpu-model">' + esc(d.cpu_model||'Unknown') + '</div></div>' +
      '<div class="card stat-card"><div class="card-title">Frequency (MHz)</div>' +
        kv('Current', '<span class="color-cyan">' + (freq.current||0).toFixed(0) + '</span>') +
        kv('Min', (freq.min||0).toFixed(0)) +
        kv('Max', (freq.max||0).toFixed(0)) +
      '</div>' +
      '<div class="card stat-card"><div class="card-title">Temperature</div>' +
        '<div class="stat-value ' + tempClass + '">' + tempVal.toFixed(1) + '<span class="stat-unit">&#176;C</span></div>' +
        kv('Max', (temp.max||0).toFixed(1) + '&#176;C') +
        kv('Min', (temp.min||0).toFixed(1) + '&#176;C') +
      '</div>' +
    '</div>' +

    '<div class="grid grid-2 mt-16">' +
      '<div class="card"><div class="card-title">CPU Usage History (' + S.history.cpu.length + ' samples)</div>' +
        '<div class="chart-container"><canvas id="chart-cpu-history"></canvas></div>' +
      '</div>' +
      '<div class="card"><div class="card-title">Per-Core Usage' + (cores.length ? ' (' + cores.length + ' cores)' : '') + '</div>' +
        '<div class="chart-container"><canvas id="chart-cpu-cores"></canvas></div>' +
      '</div>' +
    '</div>' +

    '<div class="card mt-16"><div class="card-title">Load Average</div>' +
      '<div class="grid grid-3">' +
        '<div>' + kv('1 min',  '<span class="color-cyan">'   + (load['1min']||0).toFixed(2) + '</span>') + '</div>' +
        '<div>' + kv('5 min',  (load['5min']||0).toFixed(2))  + '</div>' +
        '<div>' + kv('15 min', (load['15min']||0).toFixed(2)) + '</div>' +
      '</div>' +
    '</div>' +

    '<div class="card mt-16"><div class="card-title">Top CPU Processes</div>' +
      '<div class="table-wrap"><table>' +
        '<thead>' + trow(['PID','USER','CPU%','MEM%',
          hint('VSZ',  'Virtual Size — total address space reserved by the process, including shared libs and memory-mapped files. Usually much larger than actual RAM used.'),
          hint('RSS',  'Resident Set Size — physical RAM actually held by the process right now. The most meaningful memory indicator.'),
          hint('TIME', 'Cumulative CPU time consumed by this process since it started. High values mean it has historically done a lot of work.'),
          'COMMAND'], true) + '</thead>' +
        '<tbody>' + (procRows || trow(['<span class="muted-text" colspan="8">No data</span>'])) + '</tbody>' +
      '</table></div>' +
    '</div>';
}

/* ---------- RAM ---------- */
function renderRam(d) {
  if (!d) return renderLoading();
  if (d.error) return renderError(d.error);

  var r     = d.ram_info || {};
  var swap  = d.swap_info || [];
  var procs = d.top_processes || [];

  var swapTotal = swap.reduce(function(a, s) { return a + (s.size_mb||0); }, 0);
  var swapUsed  = swap.reduce(function(a, s) { return a + (s.used_mb||0); }, 0);
  var swapPct   = swapTotal > 0 ? (swapUsed / swapTotal) * 100 : 0;
  var totalBytes = (r.total_mb||0) * 1024 * 1024;

  var procRows = procs.map(function(p) {
    return trow([
      esc(p.pid),
      esc(p.name||''),
      (p.vm_rss_mb||0).toLocaleString() + ' MB',
      '<span class="' + colorClass(p.memory_percent||0, 10, 25) + '">' + (+(p.memory_percent)||0).toFixed(1) + '%</span>',
      '<span class="cmd">' + esc(p.command||'') + '</span>',
    ]);
  }).join('');

  var usedCls = colorClass(parseFloat(pct(r.used_percent)), 85, 95);
  return '<div class="card stat-card stat-card-wide mb-16">' +
      '<div class="stat-card-wide-left">' +
        '<div class="card-title">RAM Used</div>' +
        '<div class="stat-value ' + usedCls + '">' + pct(r.used_percent) + '<span class="stat-unit">%</span></div>' +
      '</div>' +
      '<div class="stat-card-wide-right">' +
        progressBar(r.used_percent, 85, 95) +
        '<div class="stat-sub">' + (r.used_mb||0).toLocaleString() + ' MB used &nbsp;·&nbsp; ' + (r.total_mb||0).toLocaleString() + ' MB total</div>' +
      '</div>' +
    '</div>' +

    '<div class="grid grid-4 mb-16">' +
      statCard('Total RAM',  fmtBytes(totalBytes), '', 'Installed physical memory', null) +
      statCard(hint('Available', 'Memory available for new processes — includes reclaimable cache. More useful than "Free" as a health indicator.'), fmtBytes((r.available_mb||0)*1048576), '', 'Free: ' + fmtBytes((r.free_mb||0)*1048576), null) +
      statCard(hint('Cache+Buf', 'Memory the OS uses to cache disk reads and buffer writes. It speeds up file access but is instantly reclaimed when a process needs RAM — it is not "wasted" memory.'), fmtBytes(((r.cached_mb||0)+(r.buffers_mb||0))*1048576), '', 'Cached: ' + fmtBytes((r.cached_mb||0)*1048576), null) +
      statCard(hint('Swap', 'Swap space — disk used as overflow when RAM fills up. Much slower than RAM; heavy swap usage usually means the system needs more memory.'), swapTotal > 0 ? pct(swapPct) + '%' : 'None', '', swapTotal > 0 ? swapUsed.toLocaleString() + ' / ' + swapTotal.toLocaleString() + ' MB' : 'No swap configured', swapTotal > 0 ? swapPct : null) +
    '</div>' +

    '<div class="card mt-16"><div class="card-title">RAM Usage History (' + S.history.ram.length + ' samples)</div>' +
      '<div class="chart-container"><canvas id="chart-ram-history"></canvas></div>' +
    '</div>' +

    '<div class="card mt-16"><div class="card-title">Memory Breakdown</div>' +
      '<div class="mem-breakdown">' +
        '<div class="mem-bar-row"><span class="mem-label">Used</span>'     + progressBar(r.used_percent,                                     85, 95)   + '<span class="mem-val">' + (r.used_mb||0).toLocaleString() + ' MB</span></div>' +
        '<div class="mem-bar-row"><span class="mem-label">' + hint('Cached',  'Disk cache — memory the OS uses to speed up file reads. Returned to processes immediately if needed.') + '</span>'   + progressBar((r.cached_mb||0) /(r.total_mb||1)*100,  200, 200) + '<span class="mem-val">' + (r.cached_mb||0).toLocaleString() + ' MB</span></div>' +
        '<div class="mem-bar-row"><span class="mem-label">' + hint('Buffers', 'I/O buffers — small memory pools for block-device read/write operations. Also reclaimable on demand.') + '</span>'  + progressBar((r.buffers_mb||0)/(r.total_mb||1)*100, 200, 200) + '<span class="mem-val">' + (r.buffers_mb||0).toLocaleString() + ' MB</span></div>' +
        '<div class="mem-bar-row"><span class="mem-label">Free</span>'     + progressBar((r.free_mb||0)   /(r.total_mb||1)*100,             200, 200) + '<span class="mem-val">' + (r.free_mb||0).toLocaleString() + ' MB</span></div>' +
      '</div>' +
    '</div>' +

    '<div class="card mt-16"><div class="card-title">Top Memory Processes</div>' +
      '<div class="table-wrap"><table>' +
        '<thead>' + trow(['PID','PROCESS','RAM USED','MEM%','COMMAND'], true) + '</thead>' +
        '<tbody>' + (procRows || trow(['<span class="muted-text">No data</span>'])) + '</tbody>' +
      '</table></div>' +
    '</div>';
}

/* ---------- GPU ---------- */
function renderGpu(d) {
  if (!d) return renderLoading();

  if (!d.nvidia_available) {
    var others = Array.isArray(d.other_gpus) ? d.other_gpus : [];
    return alert_('NVIDIA GPU not detected or nvidia-smi not available inside the container.', 'info') +
      (others.length ? '<div class="card mt-16"><div class="card-title">Detected Graphics Devices (lspci)</div>' +
        others.map(function(g) { return '<div class="kv-row"><span class="kv-val muted-text">' + esc(g.device||'') + '</span></div>'; }).join('') +
      '</div>' : '');
  }

  var gpus = d.gpus || [];
  if (!gpus.length) return '<div class="card"><p class="muted-text">No GPU data returned.</p></div>';

  // Summary stat cards across all GPUs
  var totalVramMb  = gpus.reduce(function(a, g) { return a + (g.memory_total_mb||0); }, 0);
  var usedVramMb   = gpus.reduce(function(a, g) { return a + (g.memory_used_mb||0);  }, 0);
  var avgUtil      = gpus.reduce(function(a, g) { return a + (g.utilization||0); }, 0) / gpus.length;
  var maxTemp      = Math.max.apply(null, gpus.map(function(g) { return g.temperature||0; }));
  var totalPower   = gpus.reduce(function(a, g) { return a + (g.power_draw_watts||0); }, 0);
  var totalPowerLim= gpus.reduce(function(a, g) { return a + (g.power_limit_watts||0); }, 0);
  var totalVramPct = totalVramMb > 0 ? (usedVramMb / totalVramMb) * 100 : 0;

  var summary = '<div class="grid grid-4">' +
    statCard('Avg GPU Util', pct(avgUtil),        '%',   gpus.length + ' GPU' + (gpus.length > 1 ? 's' : ''), avgUtil) +
    statCard('VRAM Used',    pct(totalVramPct),   '%',   usedVramMb.toLocaleString() + ' / ' + totalVramMb.toLocaleString() + ' MB', totalVramPct) +
    statCard('Max Temp',     String(maxTemp),     '°C', 'Hottest GPU', maxTemp, 70, 85) +
    '<div class="card stat-card"><div class="card-title">Total Power</div>' +
      '<div class="stat-value color-cyan">' + totalPower.toFixed(0) + '<span class="stat-unit">W</span></div>' +
      '<div class="stat-sub">Limit: ' + totalPowerLim.toFixed(0) + ' W</div>' +
    '</div>' +
  '</div>';

  // Per-GPU sections: history chart first, then stat cards
  var gpuCards = gpus.map(function(g, idx) {
    var memPct    = g.memory_used_pct || 0;
    var samples   = (S.history.gpus[idx] || []).length;
    return '<div class="section-label mt-16">GPU ' + g.index + ' &mdash; ' + esc(g.name||'') + '</div>' +
      '<div class="card mt-16"><div class="card-title">Utilization History (' + samples + ' samples)</div>' +
        '<div class="chart-container"><canvas id="chart-gpu-history-' + idx + '"></canvas></div>' +
      '</div>' +
      '<div class="grid grid-4 mt-16">' +
        statCard('Utilization',  pct(g.utilization), '%',   '', g.utilization) +
        statCard('VRAM Used',    pct(memPct),         '%',   (g.memory_used_mb||0).toLocaleString() + ' / ' + (g.memory_total_mb||0).toLocaleString() + ' MB', memPct) +
        statCard('Temperature',  String(g.temperature||0), '°C', 'Fan: ' + (g.fan_speed||0) + '%', g.temperature||0, 70, 85) +
        statCard('Power Draw',   (g.power_draw_watts||0).toFixed(1), 'W', 'Limit: ' + (g.power_limit_watts||0).toFixed(0) + ' W', null) +
      '</div>' +
      '<div class="card mt-16">' +
        kv('Driver Version', esc(g.driver_version||'—')) +
        kv('CUDA Version',   esc(g.cuda_version||'—')) +
        kv('VRAM Free',      '<span class="color-green">' + (g.memory_free_mb||0).toLocaleString() + ' MB free of ' + (g.memory_total_mb||0).toLocaleString() + ' MB total</span>') +
      '</div>';
  }).join('');

  return summary + gpuCards;
}

/* ---------- STORAGE ---------- */
function renderStorage(d) {
  if (!d) return renderLoading();
  if (d.error) return renderError(d.error);

  var disks = d.disk_usage || [];

  function diskRow(dk, realOnly) {
    var fs = dk.filesystem || '';
    if (realOnly && (fs.startsWith('tmpfs') || fs.startsWith('overlay') || fs.startsWith('shm') || fs.startsWith('devtmpfs') || fs.startsWith('udev'))) return '';
    var p = parseFloat(dk.used_percent) || 0;
    var rowCls = p >= 90 ? 'row-crit' : p >= 80 ? 'row-warn' : '';
    var pctCls = p >= 90 ? 'color-pink' : p >= 80 ? 'color-yellow' : '';
    return '<tr class="' + rowCls + '">' +
      '<td>' + hint(esc(fs), fsHint(fs)) + '</td>' +
      '<td>' + esc(dk.size||'') + '</td>' +
      '<td>' + esc(dk.used||'') + '</td>' +
      '<td>' + esc(dk.available||'') + '</td>' +
      '<td><div style="display:flex;align-items:center;gap:8px;min-width:120px">' +
        '<div class="progress" style="flex:1;margin:0"><div class="progress-fill" style="width:' + p + '%;background:' + barColor(p) + '"></div></div>' +
        '<span class="' + pctCls + '">' + p + '%</span>' +
      '</div></td>' +
      '<td>' + esc(dk.mount_point||'') + '</td>' +
    '</tr>';
  }

  var realRows = disks.map(function(dk) { return diskRow(dk, true); }).join('');
  var allRows  = disks.map(function(dk) { return diskRow(dk, false); }).join('');
  var hdrs = trow(['Filesystem','Size','Used','Avail','Use%','Mount'], true);

  return '<div class="card">' +
      '<div class="card-title">Real Filesystems</div>' +
      '<div class="table-wrap"><table><thead>' + hdrs + '</thead><tbody>' +
        (realRows || '<tr><td colspan="6" class="muted-text">No real filesystems</td></tr>') +
      '</tbody></table></div>' +
    '</div>' +

    '<div class="card mt-16">' +
      '<div class="card-title">All Mounts</div>' +
      '<div class="table-wrap"><table><thead>' + hdrs + '</thead><tbody>' +
        (allRows || '<tr><td colspan="6" class="muted-text">No data</td></tr>') +
      '</tbody></table></div>' +
    '</div>';
}

/* ---------- NETWORK ---------- */
function renderNetwork(d) {
  if (!d) return renderLoading();
  if (d.error) return renderError(d.error);

  var ifaces = d.interfaces || [];
  var conns  = (d.stats && d.stats.connections) || [];

  var lastRx = S.history.netRx.length ? S.history.netRx[S.history.netRx.length - 1] : 0;
  var lastTx = S.history.netTx.length ? S.history.netTx[S.history.netTx.length - 1] : 0;

  var ifaceCards = ifaces.map(function(i) {
    return '<div class="card">' +
      '<div class="card-title">' + hint(esc(i.interface), ifaceHint(i.interface)) + '</div>' +
      kv('RX Total',   fmtBytes(i.rx_bytes),   'color-cyan') +
      kv('TX Total',   fmtBytes(i.tx_bytes),   'color-purple') +
      kv('RX Packets', (i.rx_packets||0).toLocaleString()) +
      kv('TX Packets', (i.tx_packets||0).toLocaleString()) +
      kv(hint('RX Errors',  'Inbound packets discarded due to hardware or driver errors.'),  String(i.rx_errors||0)) +
      kv(hint('TX Errors',  'Outbound packets that failed to send due to hardware or driver errors.'), String(i.tx_errors||0)) +
      kv(hint('RX Dropped', 'Inbound packets dropped before processing — often due to receive buffer overflow or firewall rules.'), String(i.rx_dropped||0)) +
      kv(hint('TX Dropped', 'Outbound packets dropped before being sent — often due to transmit queue overflow.'), String(i.tx_dropped||0)) +
    '</div>';
  }).join('');

  var connRows = conns.slice(0, 30).map(function(c) {
    return trow([esc(c.protocol), esc(c.local_address), '<span class="badge">' + esc(c.state||'') + '</span>']);
  }).join('');

  return '<div class="grid grid-2 mb-16">' +
      '<div class="card stat-card"><div class="card-title">RX Rate</div>' +
        '<div class="stat-value color-cyan">' + fmtRate(lastRx) + '</div>' +
      '</div>' +
      '<div class="card stat-card"><div class="card-title">TX Rate</div>' +
        '<div class="stat-value color-purple">' + fmtRate(lastTx) + '</div>' +
      '</div>' +
    '</div>' +

    '<div class="card mb-16"><div class="card-title">Network Throughput History</div>' +
      '<div class="chart-container"><canvas id="chart-net-history"></canvas></div>' +
    '</div>' +

    '<div class="grid grid-3 mb-16">' +
      (ifaceCards || '<div class="card"><p class="muted-text">No interfaces</p></div>') +
    '</div>' +

    '<div class="card"><div class="card-title">Listening Sockets / Connections (first 30)</div>' +
      '<div class="table-wrap"><table>' +
        '<thead>' + trow(['Protocol','Local Address','State'], true) + '</thead>' +
        '<tbody>' + (connRows || '<tr><td colspan="3" class="muted-text">No data</td></tr>') + '</tbody>' +
      '</table></div>' +
    '</div>';
}

/* ---------- PROCESSES ---------- */
function renderProcesses(d) {
  if (!d) return renderLoading();
  if (d.error) return renderError(d.error);

  var tab      = S.procTab || 'cpu';
  var counts   = d.process_counts || {};
  var allProcs = d.all_processes  || [];

  var countBadges = Object.entries(counts).map(function(e) {
    return '<span class="badge-outline">' + hint(esc(e[0]), procStateHint(e[0])) + ': ' + e[1] + '</span>';
  }).join('');

  var PROC_TABS = [
    { id: 'core', label: 'CORE' },
    { id: 'disk', label: 'Disk' },
    { id: 'gpu',  label: 'GPU'  },
  ];

  var isCoreTab = (tab === 'cpu' || tab === 'memory' || tab === 'user');

  var subNav = '<div class="proc-sub-nav">' +
    PROC_TABS.map(function(t) {
      var active = t.id === 'core' ? isCoreTab : tab === t.id;
      var onclick = t.id === 'core'
        ? 'onclick="(S.procTab===\'disk\'||S.procTab===\'gpu\')?switchProcTab(\'cpu\'):renderTab(\'processes\')"'
        : 'onclick="switchProcTab(\'' + t.id + '\')"';
      return '<button class="proc-sub-btn' + (active ? ' active' : '') + '" ' + onclick + '>' + t.label + '</button>';
    }).join('') +
  '</div>';

  var statesCard = '<div class="card mb-16"><div class="card-title">Process States</div>' +
    '<div style="padding:8px 0">' + (countBadges || '<span class="muted-text">No data</span>') + '</div>' +
  '</div>';

  // ---- GPU: separate view ----
  if (tab === 'gpu') {
    var gpuData  = S.data.gpu || {};
    var gpuProcs = gpuData.gpu_processes || [];
    if (!gpuData.nvidia_available) {
      return statesCard + subNav +
        '<div class="card"><p class="muted-text" style="padding:32px 0;text-align:center">' +
        'No NVIDIA GPU detected.' +
        '</p></div>';
    }
    var procMap = {};
    allProcs.forEach(function(p) { procMap[String(p.pid)] = p; });

    var gpuHdrs = '<tr>' +
      '<th>GPU</th><th>PID</th><th>USER</th><th>TYPE</th>' +
      '<th class="color-cyan">' + hint('SM%', 'Streaming Multiprocessor usage — how busy the GPU\'s compute cores are, analogous to CPU%.') + '</th>' +
      '<th class="color-cyan">' + hint('VRAM MEM%', 'Percentage of the GPU\'s video RAM used by this process.') + '</th><th>VRAM MB</th>' +
      '<th>CPU%</th><th>SYS MEM%</th><th>COMMAND</th>' +
    '</tr>';
    var gpuRows = gpuProcs.map(function(g) {
      var sys = procMap[String(g.pid)] || {};
      var cmd = esc(g.command || sys.command || '—');
      return '<tr>' +
        '<td>' + esc(String(g.gpu_index)) + '</td>' +
        '<td class="copy-cell" onclick="copyCell(this)" data-copy="' + esc(String(g.pid)) + '" title="Copy PID">' + esc(String(g.pid)) + '</td>' +
        '<td>' + esc(sys.user || '—') + '</td>' +
        '<td><span class="badge">' + esc(g.type || '—') + '</span></td>' +
        '<td><span class="' + colorClass(g.sm_pct||0) + '">' + (g.sm_pct||0).toFixed(1) + '</span></td>' +
        '<td><span class="' + colorClass(g.mem_pct||0,10,25) + '">' + (g.mem_pct||0).toFixed(1) + '</span></td>' +
        '<td>' + esc(String(g.fb_mb || 0)) + '</td>' +
        '<td><span class="' + colorClass(sys.cpu_percent||0) + '">' + (+(sys.cpu_percent)||0).toFixed(1) + '</span></td>' +
        '<td><span class="' + colorClass(sys.memory_percent||0,10,25) + '">' + (+(sys.memory_percent)||0).toFixed(1) + '</span></td>' +
        '<td class="copy-cell" onclick="copyCell(this)" data-copy="' + cmd + '" title="Copy command"><span class="cmd">' + cmd + '</span></td>' +
      '</tr>';
    }).join('') || '<tr><td colspan="10" class="muted-text" style="text-align:center;padding:24px 0">No GPU processes running</td></tr>';

    return statesCard + subNav +
      '<div class="card"><div class="table-wrap"><table>' +
        '<thead>' + gpuHdrs + '</thead><tbody>' + gpuRows + '</tbody>' +
      '</table></div></div>';
  }

  // ---- DISK: separate view ----
  if (tab === 'disk') {
    function fmtRate(bps) {
      if (!bps) return '<span class="muted-text">—</span>';
      if (bps < 1024)    return bps.toFixed(0) + ' B/s';
      if (bps < 1048576) return (bps / 1024).toFixed(1) + ' KB/s';
      return (bps / 1048576).toFixed(1) + ' MB/s';
    }
    function fmtTotal(bytes) {
      if (!bytes) return '<span class="muted-text">—</span>';
      if (bytes < 1024)       return bytes + ' B';
      if (bytes < 1048576)    return (bytes / 1024).toFixed(1) + ' KB';
      if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + ' MB';
      return (bytes / 1073741824).toFixed(2) + ' GB';
    }
    var diskProcs = (d.top_disk || []).filter(function(p) {
      return (p.disk_read_bytes || 0) + (p.disk_write_bytes || 0) > 0;
    }).slice(0, 50);
    var diskHdrs = '<tr>' +
      '<th>PID</th><th>USER</th>' +
      '<th class="color-cyan">READ TOTAL</th><th class="color-cyan">WRITE TOTAL</th>' +
      '<th>READ/s</th><th>WRITE/s</th>' +
      '<th>CPU%</th><th>MEM%</th><th>COMMAND</th>' +
    '</tr>';
    var diskRows = diskProcs.map(function(p) {
      return '<tr>' +
        '<td class="copy-cell" onclick="copyCell(this)" data-copy="' + esc(p.pid) + '" title="Copy PID">' + esc(p.pid) + '</td>' +
        '<td>' + esc(p.user) + '</td>' +
        '<td>' + fmtTotal(p.disk_read_bytes  || 0) + '</td>' +
        '<td>' + fmtTotal(p.disk_write_bytes || 0) + '</td>' +
        '<td>' + fmtRate(p.disk_read_bps  || 0) + '</td>' +
        '<td>' + fmtRate(p.disk_write_bps || 0) + '</td>' +
        '<td><span class="' + colorClass(p.cpu_percent||0) + '">' + (+(p.cpu_percent)||0).toFixed(1) + '</span></td>' +
        '<td><span class="' + colorClass(p.memory_percent||0,10,25) + '">' + (+(p.memory_percent)||0).toFixed(1) + '</span></td>' +
        '<td class="copy-cell" onclick="copyCell(this)" data-copy="' + esc(p.command||'') + '" title="Copy command"><span class="cmd">' + esc(p.command||'') + '</span></td>' +
      '</tr>';
    }).join('') || '<tr><td colspan="9" class="muted-text" style="text-align:center;padding:24px 0">No disk I/O data available</td></tr>';
    return statesCard + subNav +
      '<div class="card"><div class="table-wrap"><table>' +
        '<thead>' + diskHdrs + '</thead><tbody>' + diskRows + '</tbody>' +
      '</table></div></div>';
  }

  // ---- CORE: CPU / MEMORY / USER in one tab with clickable sort headers ----
  var sorted = allProcs.slice();
  if (tab === 'cpu') {
    sorted.sort(function(a, b) { return (b.cpu_percent||0) - (a.cpu_percent||0); });
  } else if (tab === 'memory') {
    sorted.sort(function(a, b) { return (b.memory_percent||0) - (a.memory_percent||0); });
  } else {
    sorted.sort(function(a, b) {
      var ua = String(a.user), ub = String(b.user);
      if (ua < ub) return -1;
      if (ua > ub) return  1;
      return (b.cpu_percent||0) - (a.cpu_percent||0);
    });
  }
  sorted = sorted.slice(0, 50);

  function sortTh(label, sortId) {
    var active = tab === sortId;
    return '<th onclick="switchProcTab(\'' + sortId + '\')" class="proc-sort-th' + (active ? ' active' : '') + '">' +
      label + (active ? ' &#9660;' : '') + '</th>';
  }

  var mainHdrs = '<tr>' +
    '<th title="Click to copy">PID</th>' +
    sortTh('USER', 'user') +
    sortTh('CPU%', 'cpu') +
    sortTh('MEM%', 'memory') +
    '<th>' + hint('VSZ',   'Virtual Size — total address space reserved by the process, including shared libs and memory-mapped files. Usually much larger than actual RAM used.') + '</th>' +
    '<th>' + hint('RSS',   'Resident Set Size — physical RAM actually held by the process right now. The most meaningful memory indicator.') + '</th>' +
    '<th>' + hint('STATE', 'Process state: R=Running, S=Sleeping, D=Disk sleep (uninterruptible I/O), Z=Zombie, T=Stopped, I=Idle.') + '</th>' +
    '<th>' + hint('TIME',  'Cumulative CPU time consumed by this process since it started.') + '</th>' +
    '<th title="Click to copy">COMMAND</th>' +
  '</tr>';

  var mainRows = sorted.map(function(p) {
    return '<tr>' +
      '<td class="copy-cell" onclick="copyCell(this)" data-copy="' + esc(p.pid) + '" title="Copy PID">' + esc(p.pid) + '</td>' +
      '<td class="copy-cell" onclick="copyCell(this)" data-copy="' + esc(p.user) + '" title="Copy user">' + esc(p.user) + '</td>' +
      '<td><span class="' + colorClass(p.cpu_percent||0) + '">' + (+(p.cpu_percent)||0).toFixed(1) + '</span></td>' +
      '<td><span class="' + colorClass(p.memory_percent||0,10,25) + '">' + (+(p.memory_percent)||0).toFixed(1) + '</span></td>' +
      '<td>' + fmtKb(p.virtual_memory) + '</td>' +
      '<td>' + fmtKb(p.resident_memory) + '</td>' +
      '<td><span class="badge">' + hint(esc(p.status||''), procStateHint(p.status)) + '</span></td>' +
      '<td>' + esc(p.cpu_time||'') + '</td>' +
      '<td class="copy-cell" onclick="copyCell(this)" data-copy="' + esc(p.command||'') + '" title="Copy command"><span class="cmd">' + esc(p.command||'') + '</span></td>' +
    '</tr>';
  }).join('') || '<tr><td colspan="9" class="muted-text">No data</td></tr>';

  return statesCard + subNav +
    '<div class="card"><div class="table-wrap"><table>' +
      '<thead>' + mainHdrs + '</thead><tbody>' + mainRows + '</tbody>' +
    '</table></div></div>';
}

/* ---------- SENSORS ---------- */
function renderSensors(d) {
  if (!d) return renderLoading();
  if (d.error) return renderError(d.error);

  var temps  = d.temperatures   || [];
  var fans   = d.fans           || [];
  var powers = d.power_supplies || [];

  if (!temps.length && !fans.length && !powers.length) {
    return '<div class="card">' +
      '<p class="muted-text">No sensor data available.</p>' +
      '<p class="muted-text mt-8">Install <code>lm-sensors</code> on the host and run <code>sensors-detect</code>, then rebuild the container.</p>' +
    '</div>';
  }

  var tempCards = temps.map(function(t) {
    var tv  = parseFloat(t.temperature) || 0;
    var cls = tv >= 85 ? 'color-pink' : tv >= 70 ? 'color-yellow' : 'color-green';
    return '<div class="card sensor-card"><div class="card-title">' + esc(t.sensor||'Sensor') + '</div>' +
      '<div class="stat-value ' + cls + '">' + tv.toFixed(1) + '<span class="stat-unit">&#176;C</span></div></div>';
  }).join('');

  var fanCards = fans.map(function(f) {
    return '<div class="card sensor-card"><div class="card-title">' + esc(f.fan||'Fan') + '</div>' +
      '<div class="stat-value color-cyan">' + (f.speed||0) + '<span class="stat-unit">RPM</span></div></div>';
  }).join('');

  var powerCards = powers.map(function(p) {
    var cap = parseFloat(p.capacity) || 0;
    return '<div class="card sensor-card"><div class="card-title">' + esc(p.supply||'PSU') + '</div>' +
      '<div class="stat-value ' + colorClass(100 - cap, 20, 10) + '">' + cap + '<span class="stat-unit">%</span></div></div>';
  }).join('');

  return (temps.length  ? '<div class="section-label">Temperatures</div><div class="grid grid-4 mb-16">' + tempCards  + '</div>' : '') +
         (fans.length   ? '<div class="section-label">Fan Speeds</div><div class="grid grid-4 mb-16">'   + fanCards   + '</div>' : '') +
         (powers.length ? '<div class="section-label">Power Supplies</div><div class="grid grid-4">'     + powerCards + '</div>' : '');
}

/* ---------- SYSTEM ---------- */
function renderSystem(d) {
  if (!d) return renderLoading();
  if (d.error) return renderError(d.error);

  var si   = d.system_info || {};
  var ki   = d.kernel_info || {};
  var up   = d.uptime      || {};
  var load = d.load_average|| {};
  var users= d.users       || [];

  var uptimeStr = (up.days||0) + 'd ' + (up.hours||0) + 'h ' + (up.minutes||0) + 'm';

  var userRows = users.map(function(u) {
    return trow([esc(u.user), esc(u.tty), esc(u.login_time)]);
  }).join('');

  return '<div class="grid grid-2">' +
      '<div class="card"><div class="card-title">System</div>' +
        kv('Hostname',     esc(si.hostname||'—'), 'color-cyan') +
        kv('OS',           esc(si.os||'—')) +
        kv('Kernel',       esc(si.kernel||'—')) +
        kv('Architecture', esc(d.architecture||si.machine||'—')) +
        kv('Boot Time',    esc(d.boot_time||'—')) +
        kv('Uptime',       uptimeStr, 'color-green') +
      '</div>' +
      '<div class="card"><div class="card-title">Kernel</div>' +
        kv('Version',    esc(ki.version||'—')) +
        kv('Build Date', esc(ki.build_date||'—')) +
        '<div class="kv-row" style="flex-direction:column;align-items:flex-start;gap:4px;padding-top:8px">' +
          '<span class="kv-key">' + hint('Cmdline', 'The exact command the bootloader passed to the Linux kernel, including all boot parameters and flags.') + '</span>' +
          '<code class="cmdline">' + esc(ki.command_line||'—') + '</code>' +
        '</div>' +
      '</div>' +
    '</div>' +

    '<div class="card mt-16"><div class="card-title">Load Average</div>' +
      '<div class="grid grid-3">' +
        statCard(hint('1 min',  LOAD_AVG_HINT), (load['1min'] ||0).toFixed(2), '', '', null) +
        statCard(hint('5 min',  LOAD_AVG_HINT), (load['5min'] ||0).toFixed(2), '', '', null) +
        statCard(hint('15 min', LOAD_AVG_HINT), (load['15min']||0).toFixed(2), '', '', null) +
      '</div>' +
    '</div>' +

    '<div class="card mt-16"><div class="card-title">Logged-In Users</div>' +
      (users.length
        ? '<div class="table-wrap"><table><thead>' + trow(['User','TTY','Login Time'], true) + '</thead><tbody>' + userRows + '</tbody></table></div>'
        : '<p class="muted-text">No users currently logged in.</p>') +
    '</div>';
}

// ============================================================
// HISTORY TAB
// ============================================================
function fmtHistTs(unixSec, hours) {
  var d = new Date(unixSec * 1000);
  if (hours <= 24) return d.toTimeString().slice(0, 5);
  return ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][d.getDay()] + ' ' + d.toTimeString().slice(0, 5);
}

// ── Histogram point-click tooltip ────────────────────────────
var _histTooltipEl = null;

function _getHistTooltip() {
  if (!_histTooltipEl) {
    _histTooltipEl = document.createElement('div');
    _histTooltipEl.id = 'hist-proc-tooltip';
    _histTooltipEl.className = 'hist-proc-tooltip';
    document.body.appendChild(_histTooltipEl);
  }
  return _histTooltipEl;
}

function _positionTooltip(el, clientX, clientY) {
  el.style.left = (clientX + 14) + 'px';
  el.style.top  = (clientY - 10) + 'px';
  requestAnimationFrame(function() {
    var r = el.getBoundingClientRect();
    if (r.right  > window.innerWidth  - 8) el.style.left = (clientX - r.width  - 14) + 'px';
    if (r.bottom > window.innerHeight - 8) el.style.top  = (clientY - r.height + 10) + 'px';
  });
}

function _closeHistTooltip() {
  var el = _getHistTooltip();
  el.style.display = 'none';
}

function _addOutsideListener() {
  setTimeout(function() {
    document.addEventListener('click', function handler(e) {
      var el = _getHistTooltip();
      if (el && !el.contains(e.target)) {
        el.style.display = 'none';
      } else {
        document.addEventListener('click', handler, { once: true });
      }
    }, { once: true });
  }, 0);
}

function makeHistClickHandler(timestamps, windowSec) {
  return function(event, elements) {
    if (!elements || !elements.length) return;
    var idx = elements[0].index;
    var ts = timestamps[idx];
    if (ts == null) return;
    if (event.native) event.native.stopPropagation();
    var el = _getHistTooltip();
    var d = new Date(ts * 1000);
    var label = d.toLocaleDateString([], {month:'short', day:'numeric'}) +
                ' ' + d.toTimeString().slice(0, 5);
    el.innerHTML =
      '<div class="hist-tooltip-hdr">' +
        '<span class="color-cyan">' + esc(label) + '</span>' +
        '<button class="hist-tooltip-close" onclick="_closeHistTooltip()">&#x2715;</button>' +
      '</div>' +
      '<div class="hist-tooltip-loading">Loading&hellip;</div>';
    el.style.display = 'block';
    if (event.native) _positionTooltip(el, event.native.clientX, event.native.clientY);
    _addOutsideListener();
    _fetchProcessesAt(ts, windowSec, label);
  };
}

async function _fetchProcessesAt(ts, windowSec, label) {
  try {
    var resp = await fetch('/api/history/processes/at?timestamp=' + ts + '&window_sec=' + windowSec);
    var body = await resp.json();
    var el = _getHistTooltip();
    if (el.style.display === 'none') return;
    var close = '<button class="hist-tooltip-close" onclick="_closeHistTooltip()">&#x2715;</button>';
    var hdr = '<div class="hist-tooltip-hdr"><span class="color-cyan">' + esc(label) + '</span>' + close + '</div>';
    var procs = body.processes || body;  // backwards-compat if shape changes
    var trackingStart = body.tracking_start;

    if (!procs || !procs.length) {
      var msg = 'No process data recorded at this time.';
      if (trackingStart && ts < trackingStart) {
        var sd = new Date(trackingStart * 1000);
        var sl = sd.toLocaleDateString([], {month:'short', day:'numeric'}) + ' ' + sd.toTimeString().slice(0, 5);
        msg = 'Process tracking started at ' + sl + '.<br>Click a more recent point.';
      }
      el.innerHTML = hdr + '<div class="hist-tooltip-empty">' + msg + '</div>';
      return;
    }
    var rows = procs.map(function(p) {
      return '<tr>' +
        '<td class="color-cyan">' + esc(p.name) + '</td>' +
        '<td>' + pct(p.cpu_pct, 1) + '%</td>' +
        '<td>' + (p.mem_pct != null ? pct(p.mem_pct, 1) + '%' : '<span class="muted-text">—</span>') + '</td>' +
        '</tr>';
    }).join('');
    el.innerHTML = hdr +
      '<table class="hist-tooltip-tbl">' +
        '<thead><tr><th>Process</th><th>CPU</th><th>Mem</th></tr></thead>' +
        '<tbody>' + rows + '</tbody>' +
      '</table>';
  } catch (e) {
    var el2 = _getHistTooltip();
    if (el2) el2.innerHTML = '<span class="muted-text">Error loading processes.</span>';
  }
}

function _histOnHover(e, els) {
  if (e.native) e.native.target.style.cursor = els.length ? 'pointer' : 'default';
}

function _withClick(cfg, timestamps, windowSec) {
  cfg.options.onClick = makeHistClickHandler(timestamps, windowSec);
  cfg.options.onHover = _histOnHover;
  return cfg;
}

function renderHistory() {
  var rangeBar = HISTORY_RANGES.map(function(r) {
    var active = r.hours === S.historyRange ? ' active' : '';
    return '<button class="tab-btn' + active + '" onclick="setHistoryRange(' + r.hours + ')">' + r.label + '</button>';
  }).join('');
  return '<div class="hist-range-bar">' + rangeBar + '</div>' +
    '<div id="hist-charts"><div class="loading-box">Loading history&hellip;</div></div>';
}

function setHistoryRange(hours) {
  S.historyRange = hours;
  renderTab('history');
}

async function loadHistoryCharts() {
  var myId = ++S.historyFetchId;
  var r = HISTORY_RANGES.find(function(x) { return x.hours === S.historyRange; }) || HISTORY_RANGES[1];
  try {
    var results = await Promise.all([
      fetch('/api/history/metrics?hours=' + r.hours + '&bucket_sec=' + r.bucket),
      fetch('/api/history/disk?hours='    + r.hours + '&bucket_sec=' + r.bucket),
      fetch('/api/history/processes?hours=' + r.hours),
    ]);
    var metrics = await results[0].json();
    var disk    = await results[1].json();
    var procs   = await results[2].json();
    if (S.historyFetchId !== myId || S.tab !== 'history') return;
    renderHistoryCharts(metrics, disk, procs, r.hours);
  } catch (e) {
    if (S.historyFetchId !== myId) return;
    var el = document.getElementById('hist-charts');
    if (el) el.innerHTML = '<p class="muted-text">Failed to load history: ' + esc(String(e)) + '</p>';
  }
}

function renderHistoryCharts(metrics, disk, procs, hours) {
  var el = document.getElementById('hist-charts');
  if (!el) return;

  if (!metrics || !metrics.length) {
    el.innerHTML = '<div class="alert alert-info">&#x2139; No history yet — data is collected every 10 seconds.</div>';
    return;
  }

  var rangeConf  = HISTORY_RANGES.find(function(x) { return x.hours === hours; }) || HISTORY_RANGES[1];
  var windowSec  = Math.max(15, Math.round(rangeConf.bucket / 2));
  var metricTs   = metrics.map(function(r) { return r.timestamp; });
  var ts         = metrics.map(function(r) { return fmtHistTs(r.timestamp, hours); });

  var hasGpu = metrics.filter(function(r) { return r.gpu_pct != null; }).length >= 2;
  var diskSection = '';
  if (disk && disk.length) {
    diskSection = '<div class="card mb-16"><div class="card-title">Disk Usage <span class="hist-click-hint">click any point for processes</span></div><div style="position:relative"><canvas id="hist-disk"></canvas></div></div>';
  }
  var gpuSection = hasGpu
    ? '<div class="card mb-16"><div class="card-title">GPU Usage <span class="hist-click-hint">click any point for processes</span></div><div style="position:relative"><canvas id="hist-gpu"></canvas></div></div>'
    : '';

  el.innerHTML =
    '<div class="card mb-16"><div class="card-title">CPU Usage <span class="hist-click-hint">click any point for processes</span></div><div style="position:relative"><canvas id="hist-cpu"></canvas></div></div>' +
    '<div class="card mb-16"><div class="card-title">RAM Usage <span class="hist-click-hint">click any point for processes</span></div><div style="position:relative"><canvas id="hist-ram"></canvas></div></div>' +
    gpuSection +
    '<div class="card mb-16"><div class="card-title">Load Average <span class="hist-click-hint">click any point for processes</span></div><div style="position:relative"><canvas id="hist-load"></canvas></div></div>' +
    '<div class="card mb-16"><div class="card-title">Network Throughput <span class="hist-click-hint">click any point for processes</span></div><div style="position:relative"><canvas id="hist-net"></canvas></div></div>' +
    diskSection +
    renderTopProcsTable(procs);

  mkChart('hist-cpu',  _withClick(pctChartCfg(ts, [mkDs('CPU %', metrics.map(function(r) { return r.cpu_pct; }), '#00e5ff')]), metricTs, windowSec));
  mkChart('hist-ram',  _withClick(pctChartCfg(ts, [mkDs('RAM %', metrics.map(function(r) { return r.ram_pct; }), '#bb00ff')]), metricTs, windowSec));

  if (hasGpu) {
    var gpuRows = metrics.filter(function(r) { return r.gpu_pct != null; });
    var gpuTs   = gpuRows.map(function(r) { return fmtHistTs(r.timestamp, hours); });
    var gpuRawTs = gpuRows.map(function(r) { return r.timestamp; });
    var gpuDs   = mkDs('GPU %', gpuRows.map(function(r) { return r.gpu_pct; }), '#00ff41');
    gpuDs.spanGaps = true;
    var gpuCfg  = pctChartCfg(gpuTs, [gpuDs]);
    delete gpuCfg.options.scales.y.max;
    gpuCfg.options.scales.y.suggestedMax = 10;
    mkChart('hist-gpu', _withClick(gpuCfg, gpuRawTs, windowSec));
  }

  var loadCfg = pctChartCfg(ts, [
    mkDs('1m',  metrics.map(function(r) { return r.load_1m;  }), '#00e5ff'),
    mkDs('5m',  metrics.map(function(r) { return r.load_5m;  }), '#ffb300'),
    mkDs('15m', metrics.map(function(r) { return r.load_15m; }), '#00ff41'),
  ]);
  delete loadCfg.options.scales.y.max;
  loadCfg.options.scales.y.suggestedMax = 1;
  mkChart('hist-load', _withClick(loadCfg, metricTs, windowSec));

  var rxRates = [0], txRates = [0];
  for (var i = 1; i < metrics.length; i++) {
    var dt = metrics[i].timestamp - metrics[i - 1].timestamp;
    rxRates.push(dt > 0 ? Math.max(0, (metrics[i].net_rx_bytes - metrics[i - 1].net_rx_bytes) / dt) : 0);
    txRates.push(dt > 0 ? Math.max(0, (metrics[i].net_tx_bytes - metrics[i - 1].net_tx_bytes) / dt) : 0);
  }
  mkChart('hist-net', _withClick(netChartCfg(ts, [
    mkDs('RX', rxRates, '#00e5ff', false),
    mkDs('TX', txRates, '#bb00ff', false),
  ]), metricTs, windowSec));

  if (disk && disk.length) {
    var diskTsSet = {}, diskTs = [];
    disk.forEach(function(r) {
      if (!diskTsSet[r.timestamp]) { diskTsSet[r.timestamp] = true; diskTs.push(r.timestamp); }
    });
    diskTs.sort(function(a, b) { return a - b; });
    var diskByMount = {};
    disk.forEach(function(r) {
      if (!diskByMount[r.mount_point]) diskByMount[r.mount_point] = {};
      diskByMount[r.mount_point][r.timestamp] = r.used_percent;
    });
    var mounts = Object.keys(diskByMount).sort();
    var diskColors = ['#00e5ff', '#bb00ff', '#00ff41', '#ffb300', '#ff1744'];
    var diskDatasets = mounts.map(function(m, idx) {
      return mkDs(m, diskTs.map(function(t) {
        var v = diskByMount[m][t];
        return v != null ? v : null;
      }), diskColors[idx % diskColors.length]);
    });
    mkChart('hist-disk', _withClick(
      pctChartCfg(diskTs.map(function(t) { return fmtHistTs(t, hours); }), diskDatasets),
      diskTs, windowSec
    ));
  }
}

function renderTopProcsTable(procs) {
  if (!procs || !procs.length) return '';
  var rows = procs.slice(0, 15).map(function(p) {
    return trow([
      '<span class="color-cyan">' + esc(p.name) + '</span>',
      pct(p.peak_cpu_pct, 1) + '%',
      pct(p.avg_cpu_pct,  1) + '%',
      p.peak_mem_pct != null ? pct(p.peak_mem_pct, 1) + '%' : '<span class="muted-text">—</span>',
    ]);
  });
  return '<div class="card mt-16">' +
    '<div class="card-title">Top Processes — CPU (selected range)</div>' +
    '<div class="table-wrap"><table><thead>' +
      trow(['Process', 'Peak CPU', 'Avg CPU', 'Peak Mem'], true) +
    '</thead><tbody>' + rows.join('') + '</tbody></table></div>' +
    '</div>';
}

// ============================================================
// CHART INITIALIZERS (run after innerHTML is set)
// ============================================================
function initCharts(tabId) {
  var h = S.history;

  if (tabId === 'cpu') {
    mkChart('chart-cpu-history', pctChartCfg(h.ts, [mkDs('CPU %', h.cpu, '#00e5ff')]));
    var cores = (S.data.cpu && S.data.cpu.per_core_usage) || [];
    if (cores.length) {
      mkChart('chart-cpu-cores', barChartCfg(
        cores.map(function(c) { return 'C' + c.core; }),
        cores.map(function(c) { return parseFloat(c.usage) || 0; }),
        '#00e5ff'
      ));
    }
  }

  if (tabId === 'ram') {
    mkChart('chart-ram-history', pctChartCfg(h.ts, [mkDs('RAM %', h.ram, '#bb00ff')]));
  }

  if (tabId === 'gpu' && S.data.gpu && S.data.gpu.nvidia_available) {
    var gpus = S.data.gpu.gpus || [];
    gpus.forEach(function(g, i) {
      var cfg = pctChartCfg(h.ts, [mkDs('GPU ' + i + ' %', S.history.gpus[i] || [], '#00ff41')]);
      // Remove hard max so 0% idle lines are visible; always show at least 0–10% range
      delete cfg.options.scales.y.max;
      cfg.options.scales.y.suggestedMax = 10;
      mkChart('chart-gpu-history-' + i, cfg);
    });
  }

  if (tabId === 'network') {
    mkChart('chart-net-history', netChartCfg(h.ts, [
      mkDs('RX', h.netRx, '#00e5ff', false),
      mkDs('TX', h.netTx, '#bb00ff', false),
    ]));
  }

  if (tabId === 'history') {
    loadHistoryCharts();
  }
}

// ============================================================
// RENDER ACTIVE TAB
// ============================================================
var RENDERERS = {
  overview:  renderOverview,
  cpu:       renderCpu,
  ram:       renderRam,
  gpu:       renderGpu,
  storage:   renderStorage,
  network:   renderNetwork,
  processes: renderProcesses,
  sensors:   renderSensors,
  system:    renderSystem,
  history:   renderHistory,
};

function renderTab(tabId) {
  destroyCharts();
  var panel = document.getElementById('panel-' + tabId);
  if (!panel) return;
  var fn = RENDERERS[tabId];
  panel.innerHTML = fn ? fn(S.data[tabId]) : '<p class="muted-text">Unknown tab</p>';
  initCharts(tabId);
}

// ============================================================
// TAB SWITCHING
// ============================================================
function switchTab(id) {
  S.tab = id;
  document.querySelectorAll('.tab-btn').forEach(function(b) {
    b.classList.toggle('active', b.dataset.tab === id);
  });
  document.querySelectorAll('.tab-panel').forEach(function(p) {
    p.classList.toggle('active', p.id === 'panel-' + id);
  });
  renderTab(id);
}

function switchProcTab(id) {
  S.procTab = id;
  renderTab('processes');
}

// ============================================================
// DATA FETCHING
// ============================================================
async function fetchAll() {
  try {
    var resp = await fetch('/api/all');
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    var all = await resp.json();
    S.data = all;

    // Extract key metrics for history
    var cpuPct = parseFloat(
      (all.cpu && all.cpu.total_cpu) ||
      (all.overview && all.overview.cpu_usage) || 0
    );
    var ramPct = parseFloat(
      (all.ram && all.ram.ram_info && all.ram.ram_info.used_percent) ||
      (all.overview && all.overview.memory_usage && all.overview.memory_usage.used_percent) || 0
    );
    var gpuPct = 0;
    var gpuPerDevice = [];
    if (all.gpu && all.gpu.nvidia_available && all.gpu.gpus && all.gpu.gpus.length) {
      var gpuArr = all.gpu.gpus;
      gpuPct = gpuArr.reduce(function(a, g) { return a + (g.utilization||0); }, 0) / gpuArr.length;
      gpuPerDevice = gpuArr.map(function(g) { return g.utilization || 0; });
    }

    var ifaces = (all.network && all.network.interfaces) || [];
    var rates = calcNetRates(ifaces);
    addHistory(cpuPct, ramPct, gpuPct, rates.rxRate, rates.txRate, gpuPerDevice);

    // Hostname
    var hostname = (all.overview && all.overview.system_info && all.overview.system_info.hostname) ||
                   (all.system   && all.system.system_info   && all.system.system_info.hostname)   || '';
    var hnEl = document.getElementById('hostname');
    if (hnEl && hostname) hnEl.textContent = hostname;

    // Last updated
    var luEl = document.getElementById('last-updated');
    if (luEl) luEl.textContent = 'Updated ' + new Date().toLocaleTimeString();

    if (S.tab !== 'history') renderTab(S.tab);
  } catch (e) {
    console.error('Fetch error:', e);
    var luEl = document.getElementById('last-updated');
    if (luEl) luEl.textContent = 'Error: ' + e.message;
  }
}

// ============================================================
// AUTO-REFRESH
// ============================================================
function startTimer() {
  if (S.timerId) clearInterval(S.timerId);
  if (S.autoRefresh) {
    S.timerId = setInterval(fetchAll, S.intervalSec * 1000);
  }
}
function stopTimer() {
  if (S.timerId) { clearInterval(S.timerId); S.timerId = null; }
}

// ============================================================
// EXPORT
// ============================================================
function exportJson() {
  var json = JSON.stringify(S.data, null, 2);
  var blob = new Blob([json], { type: 'application/json' });
  var url  = URL.createObjectURL(blob);
  var a    = document.createElement('a');
  a.href   = url;
  a.download = 'activity-monitor-' + new Date().toISOString().slice(0, 19).replace(/:/g, '-') + '.json';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ============================================================
// DOM SETUP
// ============================================================
function buildNav() {
  var nav = document.getElementById('tab-nav');
  TABS.forEach(function(t) {
    var btn = document.createElement('button');
    btn.className    = 'tab-btn';
    btn.dataset.tab  = t.id;
    btn.textContent  = t.label;
    btn.addEventListener('click', function() { switchTab(t.id); });
    nav.appendChild(btn);
  });
}

function buildPanels() {
  var container = document.getElementById('tab-panels');
  TABS.forEach(function(t) {
    var div    = document.createElement('div');
    div.className = 'tab-panel';
    div.id        = 'panel-' + t.id;
    div.innerHTML = '<div class="loading-box">Loading&hellip;</div>';
    container.appendChild(div);
  });
}

// ============================================================
// INIT
// ============================================================
function init() {
  buildNav();
  buildPanels();
  buildSettingsNav();
  initHintTooltip();

  document.getElementById('btn-refresh').addEventListener('click', fetchAll);
  document.getElementById('btn-export').addEventListener('click', exportJson);
  document.getElementById('btn-settings').addEventListener('click', showSettings);

  var toggle = document.getElementById('auto-refresh-toggle');
  toggle.addEventListener('change', function() {
    S.autoRefresh = toggle.checked;
    document.getElementById('interval-select').disabled = !S.autoRefresh;
    if (S.autoRefresh) startTimer(); else stopTimer();
  });

  var sel = document.getElementById('interval-select');
  sel.addEventListener('change', function() {
    S.intervalSec = parseInt(sel.value, 10);
    if (S.autoRefresh) startTimer();
  });

  // Clock
  function tick() {
    var el = document.getElementById('clock');
    if (el) el.textContent = new Date().toLocaleTimeString();
  }
  tick();
  setInterval(tick, 1000);

  // Show first tab, load data
  switchTab('overview');
  fetchAll();
  startTimer();
}

document.addEventListener('DOMContentLoaded', init);

// ============================================================
// SETTINGS STATE
// ============================================================
S.view         = 'monitor';
S.settingsTab  = 'webhooks';
S.webhooks     = [];
S.thresholds   = {};
S.messages     = {};
S.enabled      = {};
S.expandedMsgs = {};

// ============================================================
// SETTINGS: SHOW / HIDE
// ============================================================
function showSettings() {
  S.view = 'settings';
  stopTimer();
  document.getElementById('tab-nav').style.display        = 'none';
  document.getElementById('settings-nav').style.display   = 'flex';
  document.getElementById('tab-panels').style.display     = 'none';
  document.getElementById('settings-content').style.display = 'block';
  document.querySelectorAll('#settings-nav [data-stab]').forEach(function(b) {
    b.classList.toggle('active', b.dataset.stab === S.settingsTab);
  });
  loadSettingsData();
}

function hideSettings() {
  S.view = 'monitor';
  document.getElementById('tab-nav').style.display        = '';
  document.getElementById('settings-nav').style.display   = 'none';
  document.getElementById('tab-panels').style.display     = '';
  document.getElementById('settings-content').style.display = 'none';
  if (S.autoRefresh) startTimer();
  fetchAll();
}

function loadSettingsData() {
  var el = document.getElementById('settings-content');
  el.innerHTML = '<div class="loading-box">Loading settings&hellip;</div>';
  Promise.all([
    fetch('/api/settings/webhooks').then(function(r) { return r.json(); }),
    fetch('/api/settings/thresholds').then(function(r) { return r.json(); }),
    fetch('/api/settings/messages').then(function(r) { return r.json(); }),
    fetch('/api/settings/enabled').then(function(r) { return r.json(); }),
  ]).then(function(results) {
    S.webhooks   = results[0];
    S.thresholds = results[1];
    S.messages   = results[2];
    S.enabled    = results[3];
    renderSettingsContent();
  }).catch(function(e) {
    el.innerHTML = renderError('Failed to load settings: ' + e.message);
  });
}

function switchSettingsTab(id) {
  S.settingsTab = id;
  document.querySelectorAll('#settings-nav [data-stab]').forEach(function(b) {
    b.classList.toggle('active', b.dataset.stab === id);
  });
  renderSettingsContent();
}

function renderSettingsContent() {
  var el = document.getElementById('settings-content');
  if (!el) return;
  el.innerHTML = S.settingsTab === 'webhooks' ? renderWebhooksTab() : renderThresholdsTab();
}

// ============================================================
// SETTINGS: WEBHOOKS TAB
// ============================================================
function renderWebhooksTab() {
  var list;
  if (!S.webhooks.length) {
    list = '<div class="settings-empty">No webhooks configured yet.</div>';
  } else {
    list = S.webhooks.map(function(h) {
      return '<div class="webhook-item" id="wh-item-' + esc(h.id) + '">' +
        '<div class="webhook-info">' +
          '<div class="webhook-name">' + esc(h.name) + '</div>' +
          '<div class="webhook-url muted-text">' + esc(h.url) + '</div>' +
        '</div>' +
        '<div class="webhook-actions">' +
          '<button class="btn btn-sm btn-test" id="wh-test-' + esc(h.id) + '" onclick="testWebhook(\'' + esc(h.id) + '\')">TEST</button>' +
          '<button class="btn btn-sm" onclick="editWebhook(\'' + esc(h.id) + '\')">EDIT</button>' +
          '<button class="btn btn-sm btn-danger" onclick="deleteWebhook(\'' + esc(h.id) + '\')">DEL</button>' +
        '</div>' +
      '</div>';
    }).join('');
  }

  return '<div class="settings-page">' +
    '<div class="settings-section">' +
      '<div class="settings-section-title">Configured Webhooks</div>' +
      '<div id="webhooks-list">' + list + '</div>' +
    '</div>' +
    '<div class="settings-section">' +
      '<div class="settings-section-title">Add Webhook</div>' +
      '<div class="settings-form">' +
        '<div class="form-row">' +
          '<label class="form-label">Name</label>' +
          '<input type="text" id="new-wh-name" class="form-input" placeholder="e.g. Discord Alerts" />' +
        '</div>' +
        '<div class="form-row">' +
          '<label class="form-label">Webhook URL</label>' +
          '<input type="url" id="new-wh-url" class="form-input" placeholder="https://discord.com/api/webhooks/..." />' +
          '<button class="btn btn-sm btn-test" id="new-wh-test-btn" onclick="testNewWebhookUrl()">TEST</button>' +
        '</div>' +
        '<div style="display:flex;align-items:center;gap:12px;margin-top:8px">' +
          '<button class="btn" onclick="addWebhook()">+ Add Webhook</button>' +
          '<span id="new-wh-status" class="form-status"></span>' +
        '</div>' +
      '</div>' +
    '</div>' +
  '</div>';
}

function addWebhook() {
  var name   = document.getElementById('new-wh-name').value.trim();
  var url    = document.getElementById('new-wh-url').value.trim();
  var status = document.getElementById('new-wh-status');
  if (!name || !url) {
    status.textContent = 'Enter both a name and a URL.';
    status.className = 'form-status form-status-error';
    return;
  }
  status.textContent = 'Adding…';
  status.className = 'form-status';
  fetch('/api/settings/webhooks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: name, url: url }),
  }).then(function(r) { return r.json(); }).then(function(hook) {
    S.webhooks.push(hook);
    renderSettingsContent();
  }).catch(function(e) {
    status.textContent = 'Error: ' + e.message;
    status.className = 'form-status form-status-error';
  });
}

function deleteWebhook(id) {
  if (!confirm('Delete this webhook?')) return;
  fetch('/api/settings/webhooks/' + id, { method: 'DELETE' })
    .then(function() {
      S.webhooks = S.webhooks.filter(function(h) { return h.id !== id; });
      renderSettingsContent();
    });
}

function testWebhook(id) {
  var btn = document.getElementById('wh-test-' + id);
  if (!btn) return;
  var orig = btn.textContent;
  btn.textContent = '…';
  btn.disabled = true;
  fetch('/api/settings/webhooks/' + id + '/test', { method: 'POST' })
    .then(function(r) { return r.json(); })
    .then(function(res) {
      btn.textContent = res.ok ? 'OK ✓' : 'FAIL ✗';
      btn.style.color = res.ok ? 'var(--green)' : 'var(--pink)';
      setTimeout(function() { btn.textContent = orig; btn.style.color = ''; btn.disabled = false; }, 2500);
    })
    .catch(function() {
      btn.textContent = 'ERR ✗';
      btn.style.color = 'var(--pink)';
      setTimeout(function() { btn.textContent = orig; btn.style.color = ''; btn.disabled = false; }, 2500);
    });
}

function testNewWebhookUrl() {
  var url    = (document.getElementById('new-wh-url') || {}).value || '';
  url = url.trim();
  var btn    = document.getElementById('new-wh-test-btn');
  var status = document.getElementById('new-wh-status');
  if (!url) {
    status.textContent = 'Enter a webhook URL first.';
    status.className = 'form-status form-status-error';
    return;
  }
  var orig = btn ? btn.textContent : 'TEST';
  if (btn) { btn.textContent = '…'; btn.disabled = true; }
  status.textContent = 'Sending test message…';
  status.className = 'form-status';
  fetch('/api/settings/webhooks/test-url', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url: url }),
  }).then(function(r) { return r.json(); }).then(function(res) {
    if (btn) { btn.textContent = res.ok ? 'OK ✓' : 'FAIL ✗'; btn.style.color = res.ok ? 'var(--green)' : 'var(--pink)'; }
    status.textContent = res.ok ? 'Test message sent.' : 'Test failed — check the URL.';
    status.className = res.ok ? 'form-status form-status-ok' : 'form-status form-status-error';
    setTimeout(function() {
      if (btn) { btn.textContent = orig; btn.style.color = ''; btn.disabled = false; }
    }, 3000);
  }).catch(function() {
    if (btn) { btn.textContent = 'ERR ✗'; btn.style.color = 'var(--pink)'; }
    status.textContent = 'Request failed.';
    status.className = 'form-status form-status-error';
    setTimeout(function() {
      if (btn) { btn.textContent = orig; btn.style.color = ''; btn.disabled = false; }
    }, 3000);
  });
}

function editWebhook(id) {
  var hook = S.webhooks.filter(function(h) { return h.id === id; })[0];
  if (!hook) return;
  var item = document.getElementById('wh-item-' + id);
  if (!item) return;
  item.innerHTML =
    '<div class="webhook-edit-form">' +
      '<div class="form-row">' +
        '<label class="form-label">Name</label>' +
        '<input type="text" id="edit-wh-name-' + esc(id) + '" class="form-input" value="' + esc(hook.name) + '" />' +
      '</div>' +
      '<div class="form-row">' +
        '<label class="form-label">URL</label>' +
        '<input type="url" id="edit-wh-url-' + esc(id) + '" class="form-input" value="' + esc(hook.url) + '" />' +
      '</div>' +
      '<div class="webhook-edit-actions">' +
        '<button class="btn btn-sm" onclick="saveWebhookEdit(\'' + esc(id) + '\')">Save</button>' +
        '<button class="btn btn-sm" onclick="renderSettingsContent()">Cancel</button>' +
      '</div>' +
    '</div>';
}

function saveWebhookEdit(id) {
  var nameEl = document.getElementById('edit-wh-name-' + id);
  var urlEl  = document.getElementById('edit-wh-url-' + id);
  if (!nameEl || !urlEl) return;
  var n = nameEl.value.trim();
  var u = urlEl.value.trim();
  if (!n || !u) { alert('Name and URL are required.'); return; }
  fetch('/api/settings/webhooks/' + id, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: n, url: u }),
  }).then(function(r) { return r.json(); }).then(function(updated) {
    for (var i = 0; i < S.webhooks.length; i++) {
      if (S.webhooks[i].id === id) { S.webhooks[i] = updated; break; }
    }
    renderSettingsContent();
  });
}

// ============================================================
// SETTINGS: THRESHOLDS TAB
// ============================================================
// msgKey maps to the DEFAULT_MESSAGES key prefix (msg_{msgKey}_warn / msg_{msgKey}_crit)
// vars lists the extra template variables available for that alert type
var THRESHOLD_DEFS = [
  { label: 'CPU Usage',         msgKey: 'cpu',      warn: 'cpu_warn',         crit: 'cpu_crit',         unit: '%',    vars: ''              },
  { label: 'RAM Usage',         msgKey: 'ram',      warn: 'ram_warn',         crit: 'ram_crit',         unit: '%',    vars: ''              },
  { label: 'Swap Usage',        msgKey: 'swap',     warn: 'swap_warn',        crit: 'swap_crit',        unit: '%',    vars: ''              },
  { label: 'CPU Temperature',   msgKey: 'cpu_temp', warn: 'cpu_temp_warn',    crit: 'cpu_temp_crit',    unit: '°C', vars: ''           },
  { label: 'GPU Utilization',   msgKey: 'gpu_util', warn: 'gpu_util_warn',    crit: 'gpu_util_crit',    unit: '%',    vars: '{gpu_index}'   },
  { label: 'GPU Temperature',   msgKey: 'gpu_temp', warn: 'gpu_temp_warn',    crit: 'gpu_temp_crit',    unit: '°C', vars: '{gpu_index}' },
  { label: 'Storage Usage',     msgKey: 'storage',  warn: 'storage_warn',     crit: 'storage_crit',     unit: '%',    vars: '{mount}'       },
  { label: 'Network RX',        msgKey: 'net_rx',   warn: 'net_rx_warn_mbps', crit: 'net_rx_crit_mbps', unit: 'MB/s', vars: ''              },
  { label: 'Network TX',        msgKey: 'net_tx',   warn: 'net_tx_warn_mbps', crit: 'net_tx_crit_mbps', unit: 'MB/s', vars: ''              },
  { label: 'Load Average (1m)', msgKey: 'load',     warn: 'load_warn',        crit: 'load_crit',        unit: '',     vars: ''              },
  { label: 'Zombie Processes',  msgKey: 'zombie',   warn: 'zombie_warn',      crit: 'zombie_crit',      unit: 'procs',vars: ''              },
];

function renderThresholdsTab() {
  var th   = S.thresholds;
  var msgs = S.messages;
  var en   = S.enabled;

  var rows = THRESHOLD_DEFS.map(function(d) {
    var wk      = 'msg_' + d.msgKey + '_warn';
    var ck      = 'msg_' + d.msgKey + '_crit';
    var warnMsg = msgs[wk] || '';
    var critMsg = msgs[ck] || '';
    var expanded  = !!S.expandedMsgs[d.msgKey];
    var varHint   = '{value} {threshold}' + (d.vars ? ' ' + d.vars : '');
    var isOn      = en[d.msgKey] !== false;

    return '<div class="threshold-row-group">' +
      '<div class="threshold-row">' +
        '<span class="threshold-label">' + d.label + '</span>' +
        '<div class="threshold-inputs">' +
          '<label class="alert-toggle-wrap" title="Enable alerts for this metric">' +
            '<input type="checkbox" class="alert-toggle" id="tog-' + d.msgKey + '"' + (isOn ? ' checked' : '') + ' />' +
            '<span class="alert-toggle-pill"></span>' +
          '</label>' +
          '<label class="threshold-level color-yellow">WARN</label>' +
          '<input type="number" step="any" class="form-input-sm" id="th-' + d.warn + '" value="' + esc(String(th[d.warn] != null ? th[d.warn] : '')) + '" />' +
          '<label class="threshold-level color-pink">CRIT</label>' +
          '<input type="number" step="any" class="form-input-sm" id="th-' + d.crit + '" value="' + esc(String(th[d.crit] != null ? th[d.crit] : '')) + '" />' +
          '<span class="threshold-unit muted-text">' + d.unit + '</span>' +
          '<button class="btn btn-sm msg-toggle-btn" id="msg-btn-' + d.msgKey + '" ' +
            'onclick="toggleMsgRow(\'' + d.msgKey + '\')">' +
            (expanded ? 'MSG ▲' : 'MSG ▼') +
          '</button>' +
        '</div>' +
      '</div>' +
      '<div class="msg-edit-row' + (expanded ? ' msg-edit-open' : '') + '" id="msg-row-' + d.msgKey + '">' +
        '<div class="msg-edit-field">' +
          '<label class="msg-edit-label color-yellow">WARN</label>' +
          '<input type="text" class="form-input" id="' + wk + '" value="' + esc(warnMsg) + '" placeholder="' + esc(warnMsg || 'warn message…') + '" />' +
        '</div>' +
        '<div class="msg-edit-field">' +
          '<label class="msg-edit-label color-pink">CRIT</label>' +
          '<input type="text" class="form-input" id="' + ck + '" value="' + esc(critMsg) + '" placeholder="' + esc(critMsg || 'crit message…') + '" />' +
        '</div>' +
        '<div class="msg-vars-hint muted-text">Variables: <code>' + varHint + '</code></div>' +
      '</div>' +
    '</div>';
  }).join('');

  var cdVal = th['cooldown_sec'] != null ? th['cooldown_sec'] : 300;

  return '<div class="settings-page">' +
    '<div class="settings-section">' +
      '<div class="settings-section-title">Alert Thresholds &amp; Messages</div>' +
      '<div class="settings-info muted-text">' +
        'Alerts fire to all configured webhooks when a threshold is crossed. ' +
        'Use the MSG button on each row to preview and edit the message sent. ' +
        'Variables <code>{value}</code> and <code>{threshold}</code> are substituted at fire time.' +
      '</div>' +
      '<div class="cooldown-row">' +
        '<span class="threshold-label">Alert Cooldown</span>' +
        '<div class="threshold-inputs">' +
          '<input type="number" step="1" min="60" class="form-input-sm" style="width:80px" id="th-cooldown_sec" value="' + esc(String(cdVal)) + '" />' +
          '<span class="threshold-unit muted-text">sec</span>' +
        '</div>' +
      '</div>' +
      '<div class="thresholds-table">' + rows + '</div>' +
      '<div class="threshold-save-row">' +
        '<button class="btn" onclick="saveThresholds()">Save All</button>' +
        '<span id="th-save-status" class="form-status"></span>' +
      '</div>' +
    '</div>' +
  '</div>';
}

function toggleMsgRow(key) {
  S.expandedMsgs[key] = !S.expandedMsgs[key];
  var row = document.getElementById('msg-row-' + key);
  if (row) row.classList.toggle('msg-edit-open', !!S.expandedMsgs[key]);
  var btn = document.getElementById('msg-btn-' + key);
  if (btn) btn.textContent = S.expandedMsgs[key] ? 'MSG ▲' : 'MSG ▼';
}

function saveThresholds() {
  // Collect thresholds
  var th = {};
  THRESHOLD_DEFS.forEach(function(d) {
    [d.warn, d.crit].forEach(function(k) {
      var el = document.getElementById('th-' + k);
      if (el) th[k] = parseFloat(el.value) || 0;
    });
  });
  var cdEl = document.getElementById('th-cooldown_sec');
  if (cdEl) th['cooldown_sec'] = parseFloat(cdEl.value) || 300;

  // Collect messages
  var msgs = {};
  THRESHOLD_DEFS.forEach(function(d) {
    ['msg_' + d.msgKey + '_warn', 'msg_' + d.msgKey + '_crit'].forEach(function(k) {
      var el = document.getElementById(k);
      if (el) msgs[k] = el.value;
    });
  });

  // Collect enabled state
  var enMap = {};
  THRESHOLD_DEFS.forEach(function(d) {
    var el = document.getElementById('tog-' + d.msgKey);
    enMap[d.msgKey] = el ? el.checked : true;
  });

  Promise.all([
    fetch('/api/settings/thresholds', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(th),
    }).then(function(r) { return r.json(); }),
    fetch('/api/settings/messages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(msgs),
    }).then(function(r) { return r.json(); }),
    fetch('/api/settings/enabled', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(enMap),
    }).then(function(r) { return r.json(); }),
  ]).then(function(results) {
    S.thresholds = results[0];
    S.messages   = results[1];
    S.enabled    = results[2];
    var el = document.getElementById('th-save-status');
    if (el) { el.textContent = 'Saved ✓'; el.className = 'form-status form-status-ok'; }
    setTimeout(function() {
      var e = document.getElementById('th-save-status');
      if (e) { e.textContent = ''; e.className = 'form-status'; }
    }, 2500);
  }).catch(function() {
    var el = document.getElementById('th-save-status');
    if (el) { el.textContent = 'Save failed'; el.className = 'form-status form-status-error'; }
  });
}

// ============================================================
// SETTINGS: NAV BUILDER (called from init)
// ============================================================
function buildSettingsNav() {
  var nav = document.getElementById('settings-nav');

  var back = document.createElement('button');
  back.className = 'tab-btn';
  back.innerHTML = '← Monitor';
  back.addEventListener('click', hideSettings);
  nav.appendChild(back);

  var sep = document.createElement('div');
  sep.className = 'settings-nav-sep';
  nav.appendChild(sep);

  [{ id: 'webhooks', label: 'Webhooks' }, { id: 'thresholds', label: 'Thresholds' }].forEach(function(t) {
    var btn = document.createElement('button');
    btn.className = 'tab-btn';
    btn.dataset.stab = t.id;
    btn.textContent = t.label;
    btn.addEventListener('click', function() { switchSettingsTab(t.id); });
    nav.appendChild(btn);
  });
}
