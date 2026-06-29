// ============================================================
// The Morning Ledger — client-side portfolio news briefing
// Everything runs in your phone's browser. Nothing is sent to
// any server except direct calls to Google News RSS when you tap
// "Fetch today's news".
// ============================================================

const DEFAULT_STOCKS = [
  ["VBL","Varun Beverages","Top30"],["SHRIRAMFIN","Shriram Finance","Top30"],
  ["MAXHEALTH","Max Healthcare","Top30"],["CGPOWER","CG Power & Industrial","Top30"],
  ["MTARTECH","MTAR Technologies","Top30"],["CAMS","CAMS","Top30"],
  ["BSE","BSE Ltd","Top30"],["LAURUSLABS","Laurus Labs","Top30"],
  ["DATAPATTNS","Data Patterns","Top30"],["RAINBOW","Rainbow Children's Medicare","Top30"],
  ["KFINTECH","KFin Technologies","Top30"],["THYROCARE","Thyrocare Technologies","Top30"],
  ["BEL","Bharat Electronics","Top30"],["VINATIORGA","Vinati Organics","Top30"],
  ["SRF","SRF Ltd","Top30"],["PARAS","Paras Defence","Top30"],
  ["YATHARTH","Yatharth Hospital","Top30"],["AFFLE","Affle India","Top30"],
  ["SONACOMS","Sona BLW Precision","Top30"],["UNIMECH","Unimech Aerospace","Top30"],
  ["KAYNES","Kaynes Technology","Top30"],["IZMO","izmo Ltd","Top30"],
  ["SYRMA","Syrma SGS Technology","Top30"],["ZENTEC","Zen Technologies","Top30"],
  ["M&M","Mahindra & Mahindra","Top30"],["ZYDUSLIFE","Zydus Lifesciences","Top30"],
  ["NETWEB","Netweb Technologies","Top30"],["SUZLON","Suzlon Energy","Top30"],
  ["CYIENTDLM","Cyient DLM","Top30"],["SYNGENE","Syngene International","Top30"],
  ["WAAREEENER","Waaree Energies","Top31-50"],["TARIL","Transformers & Rectifiers","Top31-50"],
  ["UNOMINDA","UNO Minda","Top31-50"],["MARKSANS","Marksans Pharma","Top31-50"],
  ["MOTHERSON","Samvardhana Motherson","Top31-50"],["CCL","CCL Products","Top31-50"],
  ["CPPLUS","CP Plus","Top31-50"],["HBLENGINE","HBL Engineering","Top31-50"],
  ["PRAJIND","Praj Industries","Top31-50"],["AARTIIND","Aarti Industries","Top31-50"],
  ["WABAG","VA Tech Wabag","Top31-50"],["ZAGGLE","Zaggle Prepaid","Top31-50"],
  ["GRAVITA","Gravita India","Top31-50"],["SAREGAMA","Saregama India","Top31-50"],
  ["ASTRAMICRO","Astra Microwave","Top31-50"],["COFORGE","Coforge","Top31-50"],
  ["PARAGMILK","Parag Milk Foods","Top31-50"],["BDL","Bharat Dynamics","Top31-50"],
  ["APLAPOLLO","APL Apollo Tubes","Top31-50"],["STALLION","Stallion India Fluorochemicals","Top31-50"],
  ["VISHNU","Vishnu Chemicals","Top31-50"],["HCLTECH","HCL Technologies","Top31-50"],
  ["GENUSPOWER","Genus Power","Top31-50"],
  ["GRSE","Garden Reach Shipbuilders","Top51-75"],["RAILTEL","RailTel","Top51-75"],
  ["FIEMIND","Fiem Industries","Top51-75"],["RRKABEL","RR Kabel","Top51-75"],
  ["FCL","Fineotex Chemical","Top51-75"],["BELRISE","Belrise Industries","Top51-75"],
  ["AXISCADES","AXISCADES Technologies","Top51-75"],["VIMTALABS","Vimta Labs","Top51-75"],
  ["LTFOODS","LT Foods","Top51-75"],["TEJASNET","Tejas Networks","Top51-75"],
  ["MAZDOCK","Mazagon Dock","Top51-75"],["MCX","MCX India","Top51-75"],
  ["E2E","E2E Networks","Top51-75"],["HONASA","Honasa Consumer","Top51-75"],
  ["UNITDSPR","United Spirits","Top51-75"],["APOLLO","Apollo Micro Systems","Top51-75"],
  ["KAJARIACER","Kajaria Ceramics","Top51-75"],["AZAD","Azad Engineering","Top51-75"],
  ["POONAWALLA","Poonawalla Fincorp","Top51-75"],["IKS","IKS Health","Top51-75"],
  ["INOXINDIA","Inox India","Top51-75"],["GROWW","Groww","Top51-75"],
  ["DCXINDIA","DCX Systems","Top51-75"],
  ["ATHERENERG","Ather Energy","Watch"],["SHARDACROP","Sharda Cropchem","Watch"],
  ["SIGMAADV","Sigma Solve","Watch"],["SHAKTIPUMP","Shakti Pumps","Watch"],
  ["OSWALPUMPS","Oswal Pumps","Watch"],["PREMEXPLN","Premier Explosives","Watch"],
  ["TRAVELFOOD","Travel Food Services","Watch"],["GMDCLTD","GMDC","Watch"],
  ["ETERNAL","Eternal (Zomato)","Watch"],["TRIVENI","Triveni Engineering","Watch"],
  ["DEEPINDS","Deep Industries","Watch"],["STLTECH-BE","Sterlite Technologies","Watch"],
  ["PRECWIRE","Precision Wires","Watch"],["PACEDIGITK","Pace Digital","Watch"],
  ["ADFFOODS","ADF Foods","Watch"],["QPOWER-BE","Q Power","Watch"],
  ["AEROFLEX","Aeroflex Industries","Watch"],["SPICEJET","SpiceJet","Watch"],
  ["IDEA","Vodafone Idea","Watch"],["HFCL","HFCL Ltd","Watch"],
];

const TIER_LABELS = {
  "Top30": "⭐ Top 30",
  "Top31-50": "Ranks 31–50",
  "Top51-75": "Ranks 51–75",
  "Watch": "Watch list",
};
const TIER_ORDER = ["Top30", "Top31-50", "Top51-75", "Watch"];

// ---------- Storage helpers ----------
const Store = {
  getApiKey: () => localStorage.getItem('ml_api_key') || '',
  setApiKey: (v) => localStorage.setItem('ml_api_key', v),
  getStocks: () => {
    const raw = localStorage.getItem('ml_stocks');
    if (!raw) return DEFAULT_STOCKS;
    try { return JSON.parse(raw); } catch { return DEFAULT_STOCKS; }
  },
  setStocks: (arr) => localStorage.setItem('ml_stocks', JSON.stringify(arr)),
  getCache: () => {
    const raw = localStorage.getItem('ml_news_cache');
    if (!raw) return null;
    try { return JSON.parse(raw); } catch { return null; }
  },
  setCache: (obj) => localStorage.setItem('ml_news_cache', JSON.stringify(obj)),
  getKiteApiKey: () => localStorage.getItem('ml_kite_api_key') || '',
  setKiteApiKey: (v) => localStorage.setItem('ml_kite_api_key', v),
  // Deliberately NO access_token storage here. Earlier versions stored it
  // in localStorage with a same-day expiry check, but that mechanism kept
  // producing "session expired" false reports that were genuinely hard to
  // pin down (v12-v15). The price button now does a fresh login every
  // time and uses the resulting token immediately, once, then discards
  // it — removing this whole category of persistence bug entirely rather
  // than continuing to patch it.
};
const KITE_BACKEND_URL_KEY = 'ml_kite_backend_url';

// ---------- State ----------
let currentFilter = 'all';
let currentSentiment = 'all';
let newsData = null; // { fetchedAt: ISOstring, results: [{ticker,company,tier,articles:[...]}] }
let lastFetchDiagnostics = { errorCount: 0, emptyCount: 0, totalCount: 0, lastError: null };
// (lastQuotesError removed — the new fresh-login-per-fetch design for
// prices reports status directly via priceStatusUpdate() instead of
// through a separate tracked-error variable.)

// ---------- DOM refs ----------
const $ = (sel) => document.querySelector(sel);
const contentEl = $('#content');
const refreshBtn = $('#refresh-btn');
const refreshLabel = $('#refresh-label');
const refreshStatus = $('#refresh-status');
const datelineDate = $('#dateline-date');
const datelineStatus = $('#dateline-status');
const lookupInput = $('#lookup-input');
const lookupSuggestions = $('#lookup-suggestions');
const lookupResult = $('#lookup-result');

function todayLabel() {
  return new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' });
}

function isToday(isoString) {
  if (!isoString) return false;
  const d = new Date(isoString);
  const now = new Date();
  return d.toDateString() === now.toDateString();
}

function timeLabel(isoString) {
  return new Date(isoString).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
}

// ---------- Init ----------
function init() {
  datelineDate.textContent = todayLabel();

  const cached = Store.getCache();
  if (cached && cached.results) {
    newsData = cached;
    renderContent();
    updateStatusBar();
  }

  document.querySelectorAll('.chip[data-filter]').forEach(chip => {
    chip.addEventListener('click', () => {
      document.querySelectorAll('.chip[data-filter]').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      currentFilter = chip.dataset.filter;
      renderContent();
    });
  });

  document.querySelectorAll('.chip[data-sentiment]').forEach(chip => {
    chip.addEventListener('click', () => {
      document.querySelectorAll('.chip[data-sentiment]').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      currentSentiment = chip.dataset.sentiment;
      renderContent();
    });
  });

  refreshBtn.addEventListener('click', fetchAllNews);
  const priceBtn = $('#price-refresh-btn');
  if (priceBtn) priceBtn.addEventListener('click', fetchLatestPrices);

  // Single-stock lookup
  let lookupDebounceTimer = null;
  lookupInput.addEventListener('input', () => {
    clearTimeout(lookupDebounceTimer);
    const val = lookupInput.value;
    lookupDebounceTimer = setTimeout(() => renderSuggestions(val), 150);
  });
  lookupInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      const val = lookupInput.value.trim();
      if (!val) return;
      lookupSuggestions.classList.remove('open');
      const matches = getStockSuggestions(val);
      if (matches.length > 0) {
        runSingleStockLookup(matches[0][0], matches[0][1]);
      } else {
        runSingleStockLookup(val, val);
      }
    } else if (e.key === 'Escape') {
      lookupSuggestions.classList.remove('open');
    }
  });
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.lookup-bar')) {
      lookupSuggestions.classList.remove('open');
    }
  });

  // Settings panel
  $('#settings-fab').addEventListener('click', openSettings);
  $('#settings-close').addEventListener('click', closeSettings);
  $('#settings-cancel').addEventListener('click', closeSettings);
  $('#settings-save').addEventListener('click', saveSettings);

  // XLSX/XLS/CSV upload — SheetJS handles all three
  $('#csv-upload-btn').addEventListener('click', () => $('#csv-file-input').click());
  $('#csv-file-input').addEventListener('change', handleSpreadsheetUpload);

  // Kite holdings import
  $('#kite-import-btn').addEventListener('click', importFromKite);

  // Install banner (Android/Chrome)
  let deferredPrompt = null;
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    if (!localStorage.getItem('ml_install_dismissed')) {
      $('#install-banner').classList.add('show');
    }
  });
  $('#install-btn').addEventListener('click', async () => {
    if (deferredPrompt) {
      deferredPrompt.prompt();
      await deferredPrompt.userChoice;
      deferredPrompt = null;
    }
    $('#install-banner').classList.remove('show');
  });
  $('#install-dismiss').addEventListener('click', () => {
    localStorage.setItem('ml_install_dismissed', '1');
    $('#install-banner').classList.remove('show');
  });

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('sw.js').catch(() => {});
  }
}

function updateStatusBar() {
  if (!newsData) {
    refreshStatus.textContent = 'Not yet fetched today';
    datelineStatus.textContent = "Tap refresh to fetch today's news";
    datelineStatus.classList.remove('fresh');
    updatePriceStatus();
    return;
  }
  const fresh = isToday(newsData.fetchedAt);
  const d = lastFetchDiagnostics;
  let diagSuffix = '';
  if (d && d.totalCount > 0 && d.errorCount > 0) {
    if (d.errorCount === d.totalCount) {
      diagSuffix = ` — ⚠ backend could not be reached for any stock (${escapeHtml(d.lastError || 'unknown error')}). Check your backend URL in Settings and that it's running.`;
    } else if (d.errorCount > d.totalCount * 0.3) {
      diagSuffix = ` — ⚠ ${d.errorCount}/${d.totalCount} stocks failed to fetch (${escapeHtml(d.lastError || 'see details')})`;
    }
  }
  refreshStatus.textContent = `Last fetched ${timeLabel(newsData.fetchedAt)}${fresh ? ' today' : ' (older — refresh for today)'}${diagSuffix}`;
  datelineStatus.textContent = fresh ? 'Updated this morning' : 'Stale — tap refresh';
  datelineStatus.classList.toggle('fresh', fresh);

  updatePriceStatus();
}

// Sets the baseline price status (idle state, reflecting whether any
// price data is currently showing). Live progress messages during an
// actual login+fetch attempt are set directly via priceStatusUpdate(),
// not through this function — this only runs to (re)establish the
// resting state after a render.
function updatePriceStatus() {
  const priceStatusEl = $('#price-status');
  if (!priceStatusEl) return;

  const hasAnyQuote = newsData && newsData.results && newsData.results.some(r => r.quote && r.quote.last_price != null);
  priceStatusEl.textContent = hasAnyQuote ? 'Prices updated' : 'Prices: tap to fetch';
}

// ---------- Settings panel ----------
function openSettings() {
  const stocks = Store.getStocks();
  $('#stocklist-input').value = stocks.map(s => s.join(',')).join('\n');
  // Pre-fill saved Kite API key and backend URL if any
  const savedKey = Store.getKiteApiKey();
  if (savedKey) $('#kite-api-key-input').value = savedKey;
  const savedBackend = localStorage.getItem(KITE_BACKEND_URL_KEY);
  if (savedBackend) $('#kite-backend-url-input').value = savedBackend;
  $('#settings-overlay').classList.add('open');
}
function closeSettings() {
  $('#settings-overlay').classList.remove('open');
}
function saveSettings() {
  // Save Kite API key and backend URL if entered
  const kiteKey = $('#kite-api-key-input').value.trim();
  if (kiteKey) Store.setKiteApiKey(kiteKey);
  const backendUrl = $('#kite-backend-url-input').value.trim();
  if (backendUrl) localStorage.setItem(KITE_BACKEND_URL_KEY, backendUrl.replace(/\/$/, ''));

  const lines = $('#stocklist-input').value.split('\n').map(l => l.trim()).filter(Boolean);
  const parsed = lines.map(l => {
    const parts = l.split(',').map(p => p.trim());
    return [parts[0] || '', parts[1] || parts[0] || '', parts[2] || 'Watch'];
  }).filter(p => p[0]);
  if (parsed.length) Store.setStocks(parsed);
  closeSettings();
}

// ---------- Spreadsheet upload (XLSX / XLS / CSV) via SheetJS ----------
const VALID_TIERS = ['Top30', 'Top31-50', 'Top51-75', 'Watch'];

// Load SheetJS lazily on first use
let _sheetjsLoaded = false;
function ensureSheetJS() {
  return new Promise((resolve, reject) => {
    if (window.XLSX) { resolve(); return; }
    if (_sheetjsLoaded) { resolve(); return; }
    const script = document.createElement('script');
    script.src = 'https://cdn.sheetjs.com/xlsx-0.20.3/package/dist/xlsx.full.min.js';
    script.onload = () => { _sheetjsLoaded = true; resolve(); };
    script.onerror = () => reject(new Error('Could not load SheetJS'));
    document.head.appendChild(script);
  });
}

// A real NSE/BSE ticker is letters/digits/&/- only, 1-20 chars, and critically
// is NOT a sentence, a label, or a plain number. This single check is what
// was missing before — without it, statement text like "Client ID" or
// "585017.85" or "Equity Holdings Statement as on..." got accepted as if
// it were a stock ticker, because the old fallback parser trusted column 0
// blindly with no validation at all.
// ISINs are a distinct, checkable format that should never be treated as a
// ticker: exactly 12 characters, starting with a 2-letter country code (e.g.
// "IN" for India) followed by a security-type letter (commonly "E" for
// equity), 9 alphanumeric characters total after the country code, ending
// in 1 check digit. Real tickers don't follow this shape. Without this
// check, an ISIN like INE918Z01012 structurally passes a generic
// "looks like a short alphanumeric code" test, but Google News has no
// listing for an ISIN — only for the company name or trading symbol.
function looksLikeISIN(value) {
  return /^[A-Z]{2}[A-Z0-9]{9}\d$/.test(String(value || '').trim().toUpperCase());
}

// Common section labels and words that appear in Kite statements/reports
// and happen to be short, space-free, and alphanumeric enough to pass the
// shape checks above — but are never real tickers. This list was built
// directly from the exact garbage that showed up in testing (e.g.
// "Summary", "Total", "Client ID" minus its space). It's not exhaustive —
// shape-based validation fundamentally cannot catch every possible label
// with certainty — but it closes the specific gaps already seen in practice.
const KNOWN_NON_TICKER_LABELS = new Set([
  'SUMMARY', 'TOTAL', 'GRAND', 'SUBTOTAL', 'NOTES', 'DISCLAIMER', 'PAGE',
  'DATE', 'NAME', 'ADDRESS', 'PAN', 'EMAIL', 'PHONE', 'STATEMENT', 'REPORT',
  'HOLDINGS', 'PORTFOLIO', 'EQUITY', 'QUANTITY', 'VALUE', 'AMOUNT', 'BALANCE',
  'OPENING', 'CLOSING', 'PERIOD', 'YEAR', 'FINANCIAL', 'ANNUAL', 'TAX',
  'GUIDE', 'FILING', 'CLIENT', 'SEGMENT', 'CATEGORY', 'TYPE', 'STATUS',
]);

function looksLikeRealTicker(value) {
  const v = String(value || '').trim();
  if (!v) return false;
  if (v.length > 20) return false; // tickers aren't sentences
  if (/\s/.test(v)) return false; // tickers never contain spaces; labels/sentences do
  if (/^-?\d+(\.\d+)?$/.test(v)) return false; // pure numbers are amounts, not tickers
  if (!/^[A-Z0-9&\-]+$/i.test(v)) return false; // only letters, digits, & and - allowed
  if (!/[A-Z]/i.test(v)) return false; // must contain at least one letter
  if (looksLikeISIN(v)) return false; // ISINs are identifiers, not searchable tickers
  if (KNOWN_NON_TICKER_LABELS.has(v.toUpperCase())) return false; // known statement label, not a stock
  return true;
}

function parseRowsFromSheet(rows) {
  if (!rows || rows.length === 0) return [];
  const firstRow = rows[0].map(c => String(c || '').toLowerCase().trim());
  const hasHeader = firstRow.some(c => c.includes('ticker') || c.includes('symbol') || c.includes('instrument'));
  const startIdx = hasHeader ? 1 : 0;

  const result = [];
  let skippedCount = 0;
  for (let i = startIdx; i < rows.length; i++) {
    const row = rows[i];
    if (!row || !row[0]) continue;

    const ticker = String(row[0]).trim().toUpperCase();
    if (!looksLikeRealTicker(ticker)) {
      skippedCount++;
      continue; // refuse to accept statement text, labels, or numbers as a "ticker"
    }
    const company = String(row[1] || row[0]).trim();
    let tier = String(row[2] || '').trim();
    if (!VALID_TIERS.includes(tier)) tier = 'Watch';
    result.push([ticker, company, tier]);
  }
  if (skippedCount > 0) {
    console.warn(`Skipped ${skippedCount} row(s) that didn't look like real tickers (likely statement text, not a stock list).`);
  }
  return result;
}

// Detect Kite Holdings export format and remap columns.
// Broadened beyond exact column-name matches: Kite has multiple export
// formats (Holdings CSV, tax P&L statement, equity holdings statement) with
// different headers. We now also try matching on ISIN columns and a wider
// set of header name variants, since a statement export's headers don't
// always say exactly "instrument" or "tradingsymbol".
function parseKiteHoldingsRows(rows) {
  if (!rows || rows.length === 0) return null;
  const header = rows[0].map(c => String(c || '').toLowerCase().trim());

  const instrIdx = header.findIndex(h =>
    h === 'instrument' || h === 'tradingsymbol' || h === 'symbol' || h.includes('trading symbol'));

  if (instrIdx === -1) return null; // genuinely not a recognizable Kite holdings format

  const result = [];
  for (let i = 1; i < rows.length; i++) {
    const row = rows[i];
    const ticker = String(row[instrIdx] || '').trim().toUpperCase();
    if (!looksLikeRealTicker(ticker)) continue; // same validation, even on the Kite-format path
    result.push([ticker, ticker, 'Watch']);
  }
  return result.length > 0 ? result : null;
}

async function handleSpreadsheetUpload(event) {
  const file = event.target.files[0];
  if (!file) return;

  const filenameEl = $('#csv-filename');
  filenameEl.textContent = 'Reading…';
  filenameEl.style.color = 'var(--ink-soft)';

  try {
    await ensureSheetJS();
  } catch (e) {
    filenameEl.textContent = 'Could not load spreadsheet reader — check your connection.';
    filenameEl.style.color = 'var(--clay)';
    return;
  }

  const reader = new FileReader();
  reader.onload = (e) => {
    try {
      const data = new Uint8Array(e.target.result);
      const workbook = XLSX.read(data, { type: 'array' });
      const firstSheet = workbook.Sheets[workbook.SheetNames[0]];
      // Get as array of arrays
      const rows = XLSX.utils.sheet_to_json(firstSheet, { header: 1, defval: '' });

      // Try Kite format first
      let parsed = parseKiteHoldingsRows(rows);
      let isKite = !!parsed;
      if (!parsed) parsed = parseRowsFromSheet(rows);

      if (!parsed || parsed.length === 0) {
        filenameEl.textContent = 'Could not find any real stock tickers in this file — it may be a tax/contract statement rather than a holdings list. Try Console → Portfolio → Holdings → Export instead.';
        filenameEl.style.color = 'var(--clay)';
        return;
      }

      $('#stocklist-input').value = parsed.map(r => r.join(',')).join('\n');
      filenameEl.textContent = isKite
        ? `✓ ${file.name} — ${parsed.length} holdings from Kite export (all set to Watch tier — edit tiers above)`
        : `✓ ${file.name} — ${parsed.length} stocks loaded`;
      filenameEl.style.color = 'var(--sage)';
    } catch (err) {
      filenameEl.textContent = `Could not read "${file.name}" — try saving as .xlsx`;
      filenameEl.style.color = 'var(--clay)';
    }
  };
  reader.onerror = () => {
    filenameEl.textContent = 'Could not read that file.';
    filenameEl.style.color = 'var(--clay)';
  };
  reader.readAsArrayBuffer(file); // SheetJS needs ArrayBuffer, not text
}

// ---------- Kite Connect holdings import ----------
// Full flow: user visits Kite login → gets redirected back with
// ?request_token=... → app sends that token to YOUR backend (which holds
// the api_secret safely) → backend exchanges it, fetches holdings, and
// returns them here. The api_secret and access_token never touch the browser.

// Backend URL is configured by the user in Settings (see KITE_BACKEND_URL_KEY
// near the top of this file, alongside the other storage keys).

async function importFromKite() {
  return startKiteLogin('holdings');
}

// Prices no longer need Kite login at all — they come from Yahoo Finance
// via the backend's /api/quotes endpoint, which needs no authentication.
// This replaced an earlier design that tried to use Kite's own quote API,
// which turned out to require a paid market-data subscription Kite never
// actually grants through the free Personal API — confirmed directly by
// testing (a permissions error), not assumed. Yahoo Finance is free and,
// as a side benefit, also provides 52-week high/low and a real volume
// average, neither of which Kite's API exposes at all regardless of plan.
async function fetchLatestPrices() {
  const backendUrl = getBackendUrl();
  if (!backendUrl) {
    openSettings();
    showKiteStatus('Enter your backend URL first (see instructions below) before fetching prices.', 'error');
    return;
  }

  const stocks = Store.getStocks();
  if (!stocks || stocks.length === 0) return;

  const priceBtn = $('#price-refresh-btn');
  if (priceBtn) priceBtn.classList.add('spinning');
  priceStatusUpdate('Fetching prices…');

  const symbols = stocks.map(([ticker]) => ticker).join(',');

  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 25000); // a full 96-symbol batch can take a little while
    const resp = await fetch(`${backendUrl}/api/quotes?symbols=${encodeURIComponent(symbols)}`, { signal: controller.signal });
    clearTimeout(timer);
    const data = await resp.json();

    if (priceBtn) priceBtn.classList.remove('spinning');

    if (!resp.ok || data.status !== 'success') {
      priceStatusUpdate(`Prices unavailable: ${data.error || `HTTP ${resp.status}`}`);
      return;
    }

    applyFetchedQuotes(data.quotes || {});
    const successCount = Object.values(data.quotes || {}).filter(q => !q.error).length;
    priceStatusUpdate(`Prices updated (${successCount}/${stocks.length})`);
  } catch (e) {
    if (priceBtn) priceBtn.classList.remove('spinning');
    priceStatusUpdate(`Prices unavailable: ${e.message || e}`);
  }
}

async function startKiteLogin(intent) {
  const apiKey = $('#kite-api-key-input').value.trim() || Store.getKiteApiKey();
  const backendUrl = $('#kite-backend-url-input').value.trim() || localStorage.getItem(KITE_BACKEND_URL_KEY);

  if (!apiKey) {
    openSettings();
    showKiteStatus('Enter your Kite API key first (see instructions below).', 'error');
    return;
  }
  if (!backendUrl) {
    openSettings();
    showKiteStatus('Enter your backend URL first — this is the small server that securely completes the login (see instructions below).', 'error');
    return;
  }
  Store.setKiteApiKey(apiKey);
  localStorage.setItem(KITE_BACKEND_URL_KEY, backendUrl.replace(/\/$/, ''));

  // Clear the double-callback guard from any previous login attempt — this
  // is a genuinely NEW login starting, so the next callback should be
  // allowed to process normally.
  sessionStorage.removeItem('ml_kite_callback_handled');

  showKiteStatus('Opening Kite login… After you log in, you\'ll be redirected back here automatically.', 'info');
  localStorage.setItem('ml_kite_pending_key', apiKey);

  const loginUrl = `https://kite.zerodha.com/connect/login?api_key=${encodeURIComponent(apiKey)}&v=3`;
  window.open(loginUrl, '_self');
}

function priceStatusUpdate(text) {
  const el = $('#price-status');
  if (el) el.textContent = text;
}

// Called on page load to check if we've just returned from Kite OAuth.
// Only the holdings-import flow uses this now — prices no longer go
// through Kite at all, so there's no "intent" branching needed anymore.
function checkKiteOAuthCallback() {
  const params = new URLSearchParams(window.location.search);
  if (params.get('action') !== 'login' || params.get('status') !== 'success') return;

  // Guard against this running twice for the same login. Real-world testing
  // showed the exchange call sometimes fires twice — once correctly, then a
  // second time that Kite rejects (request_tokens are single-use, Kite's own
  // rule). The most likely cause is some combination of how mobile Chrome
  // handles back/forward navigation and this function re-running before the
  // URL cleanup below had fully taken effect. A session-scoped flag, checked
  // and set BEFORE any async work starts, closes that race entirely.
  if (sessionStorage.getItem('ml_kite_callback_handled') === 'true') {
    return;
  }
  sessionStorage.setItem('ml_kite_callback_handled', 'true');

  const requestToken = params.get('request_token');
  const apiKey = Store.getKiteApiKey() || localStorage.getItem('ml_kite_pending_key');
  const backendUrl = localStorage.getItem(KITE_BACKEND_URL_KEY);

  // Clean the URL immediately, synchronously, before anything else — so
  // there's no window where a re-render or navigation could re-read the
  // same request_token from the address bar.
  history.replaceState({}, '', window.location.pathname);

  if (!requestToken || !apiKey) {
    setTimeout(() => {
      openSettings();
      showKiteStatus('Login returned but request token or API key is missing. Try again.', 'error');
    }, 300);
    return;
  }
  if (!backendUrl) {
    setTimeout(() => {
      openSettings();
      showKiteStatus(
        `Login worked, but no backend URL is configured, so I can't safely complete it.\n\n` +
        `Request token (for reference): ${requestToken}\n\n` +
        `Enter your backend URL below, then try again.`,
        'error'
      );
    }, 300);
    return;
  }

  setTimeout(() => {
    openSettings();
    completeKiteLogin(requestToken, apiKey, backendUrl);
  }, 300);
}

async function completeKiteLogin(requestToken, apiKey, backendUrl) {
  showKiteStatus('Completing login and fetching your holdings…', 'info');

  let resp, data;
  try {
    resp = await fetch(`${backendUrl}/api/kite/exchange`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_token: requestToken }),
    });
    data = await resp.json();
  } catch (e) {
    showKiteStatus(`Could not reach your backend at ${backendUrl}. Check the URL is correct and the server is running.\n\n${e}`, 'error');
    return;
  }

  if (!resp.ok || data.status !== 'success') {
    showKiteStatus(`Backend reported an error:\n${data.error || JSON.stringify(data)}`, 'error');
    return;
  }

  const holdings = data.holdings || [];
  if (holdings.length === 0) {
    showKiteStatus('Logged in successfully, but Kite returned zero holdings.', 'error');
    return;
  }

  // Note: this path (holdings import) no longer stores the access_token
  // anywhere — the price button now does its own fresh login + immediate
  // one-time use of the token, never persisting it. See
  // completeKiteLoginForPrices for that flow.

  // Merge fetched tickers into the stock list, preserving tiers for any
  // ticker we already know about; new tickers default to "Watch".
  const existing = Store.getStocks();
  const existingByTicker = new Map(existing.map(([t, c, tier]) => [t.toUpperCase(), [t, c, tier]]));

  const merged = holdings.map(h => {
    const ticker = (h.ticker || '').toUpperCase();
    if (existingByTicker.has(ticker)) return existingByTicker.get(ticker);
    return [ticker, ticker, 'Watch'];
  });

  Store.setStocks(merged);
  $('#stocklist-input').value = merged.map(s => s.join(',')).join('\n');

  const userName = (data.user && data.user.user_name) || 'your account';
  showKiteStatus(
    `✓ Imported ${holdings.length} holdings from ${userName}'s Kite account. Closing settings and fetching today's news now…`,
    'success'
  );

  // Show the freshly imported holdings immediately on the main page (as a
  // plain list, before news has loaded) so there's instant visible feedback
  // that the import worked — then close settings and auto-trigger the full
  // news fetch, so the user doesn't have to do anything else manually.
  renderImportedHoldingsPreview(merged, userName);

  setTimeout(() => {
    closeSettings();
    fetchAllNews();
  }, 900);
}

function renderImportedHoldingsPreview(stocksList, userName) {
  const rows = stocksList.map(([ticker, company, tier]) =>
    `<div class="entry"><div class="entry-head"><div><span class="entry-name">${escapeHtml(company)}</span><span class="entry-ticker">${escapeHtml(ticker)}</span></div><span class="entry-badge fresh">${escapeHtml(tier)}</span></div></div>`
  ).join('');
  contentEl.innerHTML = `<div class="section">
    <div class="section-head"><span class="section-label">✓ Imported from ${escapeHtml(userName)}'s Kite account</span><div class="rule"></div></div>
    <div class="quiet" style="margin-bottom:8px">Fetching today's news for these now…</div>
    ${rows}
  </div>`;
}

function showKiteStatus(msg, type) {
  const el = $('#kite-status');
  if (!el) return;
  el.textContent = msg;
  el.style.display = 'block';
  el.className = 'kite-status kite-status-' + type;
}

// ---------- Sentiment classification ----------
// Word lists rebuilt after testing against 25 realistic Indian financial
// headlines showed only 32% accuracy — the original lists leaned on rare,
// dramatic words ("plunge", "soars", "crash") and missed the everyday
// words ("jump", "fall", "slip", "gain", "decline") that actually dominate
// real headlines. This version adds that common vocabulary while keeping
// the original specific phrases (which were accurate, just incomplete).
const NEGATIVE_WORDS = [
  // regulatory / legal / governance
  'fraud', 'scam', 'probe', 'investigat', 'raid', 'fir filed', 'sebi action',
  'sebi order', 'rbi restriction', 'rbi flags', 'rbi imposes', 'cbi', 'ed raid',
  'scrutiny', 'non-compliance', 'governance issue', 'accounting lapse', 'lapses',
  'show cause notice', 'irregularit',
  // financial distress
  'downgrade', 'default', 'bankrupt', 'insolven', 'liquidat', 'debt-laden',
  'debt trap', 'rating cut', 'outlook negative', 'restructuring debt',
  'fundraising delay', 'fundraise concern', 'cash crunch', 'going concern',
  // earnings / performance — common everyday phrasing
  'net loss', 'posts loss', 'loss widens', 'profit declin', 'profit falls',
  'profit drops', 'profit slips', 'profit dips', 'revenue falls', 'revenue declin',
  'misses estimate', 'falls short', 'below estimate', 'disappoint', 'muted outlook',
  'weak quarter', 'weak earnings', 'margin contraction', 'margin pressure',
  'margin squeeze', 'cost overrun', 'input cost', 'profit warning', 'lowered guidance',
  // everyday stock movement words — this is the category that was missing
  'shares fall', 'shares falls', 'shares slip', 'shares slips', 'shares slide',
  'shares slides', 'shares drop', 'shares drops', 'shares decline', 'shares tank',
  'shares tanks', 'shares tumble', 'shares crash', 'shares plunge', 'shares sink',
  'shares dip', 'shares dips', 'shares edge lower', 'shares trade lower',
  'stock falls', 'stock slips', 'stock slides', 'stock drops', 'stock declines',
  'stock tanks', 'stock tumbles', 'stock crashes', 'stock plunges', 'stock dips',
  '52-week low', 'hits low', 'multi-year low', 'underperform', 'sell rating',
  'red flag', 'concern over', 'warns of', 'cautious outlook', 'weak demand',
  'demand slowdown', 'sales decline', 'sales fall', 'sales drop',
  // leadership / operations
  'resign', 'steps down', 'quits', 'sacked', 'fired', 'arrest', 'lawsuit', 'sued',
  'penalty', 'fine imposed', 'ban', 'banned', 'halted', 'suspend', 'delisted',
  'strike', 'shutdown', 'shuts down', 'layoff', 'job cut', 'recall',
  'breach', 'hack', 'cyberattack', 'data leak', 'accident', 'fire breaks',
  'explosion', 'death', 'killed', 'protest', 'boycott', 'controversy',
  'stake sale concern', 'pledge shares', 'promoter sells', 'promoter pledg',
  'fii exit', 'fii selling', 'delay in', 'order cancel', 'contract terminat',
];

const POSITIVE_WORDS = [
  // earnings / performance — common everyday phrasing first
  'profit rises', 'profit rise', 'profit jumps', 'profit surges', 'profit soars',
  'profit grows', 'profit climbs', 'profit beats', 'revenue rises', 'revenue grows',
  'revenue jumps', 'revenue surges', 'beats estimate', 'beats street', 'tops estimate',
  'beat street view', 'strong quarter', 'strong earnings', 'strong show',
  'raises guidance', 'raises outlook', 'improved margin', 'margin expansion',
  'strong growth', 'robust growth', 'strong demand', 'demand surge',
  // everyday stock movement words — same gap as the negative list had
  'shares jump', 'shares jumps', 'shares rise', 'shares rises', 'shares gain',
  'shares gains', 'shares surge', 'shares surges', 'shares rally', 'shares rallies',
  'shares climb', 'shares climbs', 'shares soar', 'shares soars', 'shares advance',
  'shares advances', 'shares up', 'stock jumps', 'stock rises', 'stock gains',
  'stock surges', 'stock rallies', 'stock climbs', 'stock soars', 'stock advances',
  '52-week high', 'all-time high', 'record high', 'hits high', 'multi-year high',
  'outperform', 'buy rating', 'target price raised', 'upgrade', 'rating upgrade',
  'outlook positive', 'top gainer', 'best performer',
  // deals / corporate actions
  'wins order', 'wins contract', 'wins record', 'wins deal', 'secures order',
  'bags order', 'bags contract', 'new contract', 'gets nod', 'gets approval',
  'usfda nod', 'receives approval', 'expansion plan', 'capacity expansion',
  'buyback', 'dividend announce', 'special dividend', 'bonus issue', 'stock split',
  'partnership with', 'strategic tie-up', 'joint venture', 'acquisition complete',
  'foray into', 'launches', 'unveils', 'breakthrough', 'patent grant',
  'fii buying', 'institutional buying', 'promoter buys', 'stake increase',
  'debt-free', 'turns profitable', 'pre-sales',
  // these specific patterns catch real headlines where an amount sits
  // between the verb and "order" (e.g. "bags 300 MW wind order", "wins
  // Rs 5,000 crore order") without using a bare standalone "wins"/"bags"
  // match, which tested as a false-positive risk on cases like "bags a
  // fine" — narrower phrasing here trades a little recall for safety.
  'wind order', 'mw order', 'crore order', 'rs order', 'export order',
  'raises guidance', 'raises outlook', 'raises fy', 'raises revenue guidance',
];

function classifySentiment(title) {
  if (!title) return 'neutral';
  const lower = title.toLowerCase();
  const hasNegative = NEGATIVE_WORDS.some(w => lower.includes(w));
  const hasPositive = POSITIVE_WORDS.some(w => lower.includes(w));
  if (hasNegative && !hasPositive) return 'negative';
  if (hasPositive && !hasNegative) return 'positive';
  if (hasNegative && hasPositive) return 'negative';
  return 'neutral';
}

function classifyStockOverallSentiment(articles) {
  if (!articles || articles.length === 0) return null;
  const sentiments = articles.map(a => classifySentiment(a.title));
  if (sentiments.includes('negative')) return 'negative';
  if (sentiments.includes('positive')) return 'positive';
  return 'neutral';
}

// ---------- Fetching: via your own backend ----------
// Both free anonymous CORS proxies this app relied on stopped working:
// CodeTabs is currently rejecting requests with 400s for many users
// (a reported, ongoing issue with their free service, not specific to
// this app), and r.jina.ai explicitly blocks anonymous access to
// news.google.com due to abuse from other users of their shared service.
//
// News fetching now goes through your own backend instead (the same one
// used for Kite login) — it makes the request to Google directly, with
// no CORS restriction at all (CORS is purely a browser-side rule) and no
// shared anonymous-abuse exposure. This requires the backend URL to be
// set in Settings — the same field used for Kite login.

function getBackendUrl() {
  return localStorage.getItem(KITE_BACKEND_URL_KEY) || '';
}

async function fetchNewsViaBackend(company, maxArticles) {
  const backendUrl = getBackendUrl();
  if (!backendUrl) {
    return { articles: [], error: 'no-backend-configured' };
  }
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 12000);
    const resp = await fetch(`${backendUrl}/api/news?company=${encodeURIComponent(company)}`, { signal: controller.signal });
    clearTimeout(timer);
    const data = await resp.json();
    if (!resp.ok || data.status !== 'success') {
      return { articles: [], error: data.error || `backend returned HTTP ${resp.status}` };
    }
    return { articles: (data.articles || []).slice(0, maxArticles), error: null };
  } catch (e) {
    return { articles: [], error: e.message || String(e) };
  }
}

// ---------- Parallel batch fetcher ----------
// Fetches up to BATCH_SIZE stocks concurrently, then moves to the next batch,
// with a short pause between batches.
//
// Lowered from 8 to 4, with a 400ms gap added between batches. Free,
// unauthenticated proxy services (CodeTabs, r.jina.ai) are shared
// infrastructure with no published guarantee for sustained bursts —
// 8-at-a-time, 12 batches back-to-back from one device is the kind of
// pattern that gets silently throttled even without a documented limit.
// This trades some speed for reliability: roughly 96 stocks ÷ 4 × (fetch
// time + 400ms pause) — slower than the original aggressive batching, but
// much less likely to get rate-limited mid-run, which is the actual
// failure mode worth avoiding.
const BATCH_SIZE = 6;
const BATCH_PAUSE_MS = 200;

// Tracks which proxy actually served each successful response, and how
// many stocks got zero articles from every proxy. Surfaced in the status
// bar after a fetch completes, so "nothing showing up" becomes diagnosable
// instead of a silent mystery. (Declared at top of file with other state.)

async function fetchStockNews(ticker, company) {
  const { articles, error } = await fetchNewsViaBackend(company, 3);
  return { ticker, company, articles, error };
}

// (The old Kite-based fetchQuotes() helper was removed here. Prices now
// come from Yahoo Finance via the backend's /api/quotes — see
// fetchLatestPrices() above, which calls the backend directly and needs
// no access_token or Kite login at all.)

async function fetchAllNews() {
  const stocks = Store.getStocks();
  if (!stocks || stocks.length === 0) {
    openSettings();
    return;
  }
  if (!getBackendUrl()) {
    openSettings();
    showKiteStatus('News fetching needs your backend URL set below (the same one used for Kite login) — paste it in and try again.', 'error');
    return;
  }

  refreshBtn.classList.add('spinning');
  refreshLabel.textContent = 'Fetching…';
  renderLoadingSkeleton(stocks.length);

  const results = new Array(stocks.length);
  let completed = 0;
  const diagnostics = { errorCount: 0, emptyCount: 0, totalCount: stocks.length, lastError: null };

  // Your own backend has no anonymous-abuse exposure and no CORS
  // restriction, so a higher batch size than the old proxy-based approach
  // is safe here — Render's own connection limits are the real ceiling,
  // and 8 concurrent requests to your own server is comfortably under that.
  for (let batchStart = 0; batchStart < stocks.length; batchStart += BATCH_SIZE) {
    const batchEnd = Math.min(batchStart + BATCH_SIZE, stocks.length);
    const batch = stocks.slice(batchStart, batchEnd);

    const batchPromises = batch.map(async ([ticker, company, tier], batchIdx) => {
      const { articles, error } = await fetchStockNews(ticker, company);
      // Preserve any quote data already attached from a previous "Fetch
      // latest prices" tap, since news and prices are now fetched
      // independently and shouldn't wipe each other out.
      const existingQuote = newsData && newsData.results && newsData.results[batchStart + batchIdx]
        ? newsData.results[batchStart + batchIdx].quote
        : null;
      results[batchStart + batchIdx] = { ticker, company, tier, articles, quote: existingQuote || null };
      if (articles.length === 0) {
        diagnostics.emptyCount++;
        if (error) { diagnostics.errorCount++; diagnostics.lastError = error; }
      }
      completed++;
      refreshLabel.textContent = `Fetching… ${completed}/${stocks.length}`;
    });

    await Promise.all(batchPromises);

    if (batchEnd < stocks.length) {
      await new Promise(r => setTimeout(r, BATCH_PAUSE_MS));
    }
  }

  lastFetchDiagnostics = diagnostics;
  newsData = { fetchedAt: new Date().toISOString(), results };
  Store.setCache(newsData);

  refreshBtn.classList.remove('spinning');
  refreshLabel.textContent = "Fetch today's news";
  updateStatusBar();
  renderContent();
}

// ---------- Dedicated "Fetch latest prices" — separate, on-demand ----------
// Split out from the news fetch entirely. Originally prices were bundled
// into every news fetch automatically, but that coupling made a real bug
// Merges fetched quote data into whatever's currently displayed and
// re-renders. Called once, right after a fresh Kite login completes and
// quotes are fetched — not on a timer, not from stored state.
function applyFetchedQuotes(quotes) {
  const stocks = Store.getStocks();
  if (newsData && newsData.results) {
    for (const r of newsData.results) {
      const q = quotes[r.ticker];
      if (q && !q.error) r.quote = q; // per-symbol errors (bad/delisted ticker) are skipped, not stored as a "quote"
    }
    Store.setCache(newsData);
  } else {
    const results = stocks.map(([ticker, company, tier]) => {
      const q = quotes[ticker];
      return { ticker, company, tier, articles: [], quote: (q && !q.error) ? q : null };
    });
    newsData = { fetchedAt: new Date().toISOString(), results };
    Store.setCache(newsData);
  }
  updateStatusBar();
  renderContent();
}

// ---------- Single-stock lookup ----------
function getStockSuggestions(query) {
  const stocks = Store.getStocks();
  const q = query.trim().toLowerCase();
  if (!q) return [];
  return stocks
    .filter(([ticker, company]) =>
      ticker.toLowerCase().includes(q) || company.toLowerCase().includes(q))
    .slice(0, 6);
}

function renderSuggestions(query) {
  const matches = getStockSuggestions(query);
  if (!query.trim()) {
    lookupSuggestions.classList.remove('open');
    lookupSuggestions.innerHTML = '';
    return;
  }
  if (matches.length === 0) {
    lookupSuggestions.innerHTML = `<div class="suggestion-empty">No match in your stock list — press Enter to search "${escapeHtml(query)}" directly anyway.</div>`;
    lookupSuggestions.classList.add('open');
    return;
  }
  lookupSuggestions.innerHTML = matches.map(([ticker, company]) =>
    `<div class="suggestion-item" data-ticker="${escapeHtml(ticker)}" data-company="${escapeHtml(company)}">
      <span class="suggestion-name">${escapeHtml(company)}</span>
      <span class="suggestion-ticker">${escapeHtml(ticker)}</span>
    </div>`
  ).join('');
  lookupSuggestions.classList.add('open');

  lookupSuggestions.querySelectorAll('.suggestion-item').forEach(item => {
    item.addEventListener('click', () => {
      const ticker = item.dataset.ticker;
      const company = item.dataset.company;
      lookupInput.value = `${company} (${ticker})`;
      lookupSuggestions.classList.remove('open');
      runSingleStockLookup(ticker, company);
    });
  });
}

async function runSingleStockLookup(tickerTyped, companyTyped) {
  const stocks = Store.getStocks();
  const known = stocks.find(([t, c]) =>
    t.toLowerCase() === tickerTyped.toLowerCase() || c.toLowerCase() === companyTyped.toLowerCase());
  const searchTerm = known ? known[1] : companyTyped;
  const displayTicker = known ? known[0] : tickerTyped.toUpperCase();

  lookupResult.innerHTML = `<div class="lookup-result-card">
    <div class="lookup-result-head">
      <span class="lookup-result-title">${escapeHtml(searchTerm)}</span>
      <button class="lookup-close" id="lookup-close-btn">✕ Close</button>
    </div>
    <div class="lookup-loading">Fetching latest news for ${escapeHtml(displayTicker)}…</div>
  </div>`;
  $('#lookup-close-btn').addEventListener('click', clearLookupResult);

  let articles = [];
  let lookupError = null;
  try {
    const result = await fetchNewsViaBackend(searchTerm, 5);
    articles = result.articles;
    lookupError = result.error;
  } catch (e) { lookupError = e.message || String(e); }

  const stockObj = { ticker: displayTicker, company: searchTerm, tier: known ? known[2] : 'Watch', articles };
  const diagnoseLink = articles.length === 0
    ? `<button id="diagnose-btn" style="margin-top:10px;font-family:-apple-system,system-ui,sans-serif;font-size:11px;color:var(--ink-soft);background:none;border:1px solid var(--rule-strong);border-radius:6px;padding:5px 10px">🔍 See raw backend response (diagnose why)</button>`
    : '';
  const errorNote = lookupError
    ? `<div class="quiet" style="color:var(--clay)">Backend error: ${escapeHtml(lookupError)}</div>`
    : '';
  lookupResult.innerHTML = `<div class="lookup-result-card">
    <div class="lookup-result-head">
      <span class="lookup-result-title">${escapeHtml(searchTerm)} <span style="font-family:'SF Mono',monospace;font-size:11px;color:var(--ink-soft)">${escapeHtml(displayTicker)}</span></span>
      <button class="lookup-close" id="lookup-close-btn">✕ Close</button>
    </div>
    ${renderEntry(stockObj)}
    ${errorNote}
    ${diagnoseLink}
  </div>`;
  $('#lookup-close-btn').addEventListener('click', clearLookupResult);
  const diagBtn = document.getElementById('diagnose-btn');
  if (diagBtn) diagBtn.addEventListener('click', () => runDiagnosticCheck(searchTerm));
}

function clearLookupResult() {
  lookupResult.innerHTML = '';
  lookupInput.value = '';
  lookupSuggestions.classList.remove('open');
}

// ---------- Raw diagnostic viewer ----------
// Shows exactly what each proxy returns for one stock, unparsed — so a
// "no news found" report can be turned into something concrete to debug
// rather than a guess. Reachable via a small "diagnose" link that appears
// next to a stock once it shows "No recent news found".
async function runDiagnosticCheck(company) {
  lookupResult.innerHTML = `<div class="lookup-result-card">
    <div class="lookup-result-head">
      <span class="lookup-result-title">Diagnostic: ${escapeHtml(company)}</span>
      <button class="lookup-close" id="lookup-close-btn">✕ Close</button>
    </div>
    <div class="lookup-loading">Checking your backend directly…</div>
  </div>`;
  $('#lookup-close-btn').addEventListener('click', clearLookupResult);

  const backendUrl = getBackendUrl();
  let statusLine, snippet, requestUrl;

  if (!backendUrl) {
    statusLine = 'No backend URL configured';
    snippet = 'Set your backend URL in Settings (the same one used for Kite login) before fetching news.';
    requestUrl = '(none — backend URL is empty)';
  } else {
    requestUrl = `${backendUrl}/api/news?company=${encodeURIComponent(company)}`;
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 12000);
      const resp = await fetch(requestUrl, { signal: controller.signal });
      clearTimeout(timer);
      const text = await resp.text();
      let articleCount = 'n/a';
      try {
        const json = JSON.parse(text);
        articleCount = (json.articles || []).length;
      } catch (e) {}
      statusLine = `HTTP ${resp.status} · ${text.length} chars received · ${articleCount} articles parsed`;
      snippet = text.slice(0, 600);
    } catch (e) {
      statusLine = `Failed: ${e.message || e}`;
      snippet = '(no response — check the backend URL is correct and the server is running. Try opening ' +
                 (backendUrl ? `${backendUrl}/healthz` : '(no backend URL set)') + ' directly in a browser tab.)';
    }
  }

  lookupResult.innerHTML = `<div class="lookup-result-card">
    <div class="lookup-result-head">
      <span class="lookup-result-title">Diagnostic: ${escapeHtml(company)}</span>
      <button class="lookup-close" id="lookup-close-btn">✕ Close</button>
    </div>
    <div style="font-size:11px;color:var(--ink-soft);margin-bottom:10px">Request: ${escapeHtml(requestUrl)}</div>
    <div style="margin-bottom:14px">
      <div style="font-size:12px;color:var(--ink-soft);margin-bottom:6px">${escapeHtml(statusLine)}</div>
      <pre style="font-size:10px;background:var(--paper-dim);padding:8px;border-radius:6px;overflow-x:auto;white-space:pre-wrap;word-break:break-all;max-height:200px;overflow-y:auto">${escapeHtml(snippet)}</pre>
    </div>
  </div>`;
  $('#lookup-close-btn').addEventListener('click', clearLookupResult);
}

// ---------- Rendering ----------
function renderLoadingSkeleton(count) {
  let html = '<div class="section">';
  for (let i = 0; i < Math.min(count, 6); i++) {
    html += `<div class="skeleton-entry">
      <div class="skel-line" style="width:45%"></div>
      <div class="skel-line" style="width:85%"></div>
      <div class="skel-line" style="width:30%"></div>
    </div>`;
  }
  html += '</div>';
  contentEl.innerHTML = html;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str || '';
  return div.innerHTML;
}

function formatPublished(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return '';
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) + ' · ' +
         d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
}

function renderContent() {
  if (!newsData) {
    contentEl.innerHTML = `<div class="empty-state">
      <div class="glyph">☀︎</div>
      <h3>Good morning.</h3>
      <p>Tap "Fetch today's news" above to pull the latest headlines for every stock in your portfolio before the market opens.</p>
    </div>`;
    return;
  }

  let filtered = newsData.results;
  if (currentFilter === 'fresh') {
    filtered = filtered.filter(s => s.articles && s.articles.length > 0);
  } else if (currentFilter !== 'all') {
    filtered = filtered.filter(s => s.tier === currentFilter);
  }

  if (currentSentiment !== 'all') {
    filtered = filtered.filter(s => {
      const overall = classifyStockOverallSentiment(s.articles);
      return overall === currentSentiment;
    });
  }

  if (filtered.length === 0) {
    const sentimentNote = currentSentiment !== 'all' ? ` with ${currentSentiment} news` : '';
    contentEl.innerHTML = `<div class="empty-state">
      <div class="glyph">—</div>
      <h3>Nothing here</h3>
      <p>No stocks${sentimentNote} match this filter right now.</p>
    </div>`;
    return;
  }

  if (currentFilter === 'all' || currentFilter === 'fresh') {
    let html = '';
    for (const tier of TIER_ORDER) {
      const group = filtered.filter(s => s.tier === tier);
      if (!group.length) continue;
      html += `<div class="section">
        <div class="section-head"><span class="section-label tier-${tier.toLowerCase()}">${TIER_LABELS[tier]}</span><div class="rule"></div></div>
        ${group.map(renderEntry).join('')}
      </div>`;
    }
    contentEl.innerHTML = html;
  } else {
    contentEl.innerHTML = `<div class="section">${filtered.map(renderEntry).join('')}</div>`;
  }
}

function renderEntry(stock) {
  const hasNews = stock.articles && stock.articles.length > 0;
  const lead = hasNews ? stock.articles[0] : null;
  const rest = hasNews ? stock.articles.slice(1) : [];
  const overallSentiment = hasNews ? classifyStockOverallSentiment(stock.articles) : null;

  let body = '';
  if (hasNews) {
    const leadSentiment = classifySentiment(lead.title);
    body = `<div class="headline"><span class="sentiment-dot ${leadSentiment}"></span><a href="${escapeHtml(lead.url)}" target="_blank" rel="noopener">${escapeHtml(lead.title)}</a></div>
      <div class="article-meta">${escapeHtml(lead.source)} · ${formatPublished(lead.published)}</div>`;
    if (rest.length) {
      body += rest.map(a => {
        const s = classifySentiment(a.title);
        return `<div class="more-articles">
        <div class="sub-headline"><span class="sentiment-dot ${s}"></span><a href="${escapeHtml(a.url)}" target="_blank" rel="noopener" style="color:inherit;text-decoration:none;border-bottom:1px solid var(--rule-strong)">${escapeHtml(a.title)}</a></div>
        <div class="article-meta">${escapeHtml(a.source)} · ${formatPublished(a.published)}</div>
      </div>`;
      }).join('');
    }
  } else {
    body = `<div class="quiet">No recent news found</div>`;
  }

  const badgeHtml = hasNews
    ? (overallSentiment === 'negative'
        ? '<span class="entry-badge sent-badge-negative">⚠ Watch</span>'
        : overallSentiment === 'positive'
          ? '<span class="entry-badge sent-badge-positive">✓ Positive</span>'
          : '<span class="entry-badge fresh">News</span>')
    : '';

  // Price/change/volume/52wk only render if a quote came back for this
  // stock — fails silently and shows nothing if prices haven't been
  // fetched yet or this specific symbol had no data, rather than an
  // error inline on every single entry.
  let priceHtml = '';
  if (stock.quote && stock.quote.last_price != null) {
    const chg = stock.quote.change_pct;
    const chgClass = chg == null ? 'pnl-neu' : (chg > 0 ? 'pnl-pos' : (chg < 0 ? 'pnl-neg' : 'pnl-neu'));
    const chgSign = chg != null && chg > 0 ? '+' : '';

    let flagsHtml = '';
    if (stock.quote.volume_flag === 'high') {
      flagsHtml += `<span class="pressure-flag pressure-buy" title="Today's volume is ${stock.quote.volume_vs_avg_pct}% of the 20-day average">▲ high volume</span>`;
    } else if (stock.quote.volume_flag === 'low') {
      flagsHtml += `<span class="pressure-flag pressure-sell" title="Today's volume is ${stock.quote.volume_vs_avg_pct}% of the 20-day average">▼ low volume</span>`;
    }
    if (stock.quote.near_52wk_flag === 'near-high') {
      flagsHtml += `<span class="pressure-flag pressure-buy" title="Within 2% of the 52-week high of ₹${stock.quote.fifty_two_wk_high}">52wk high</span>`;
    } else if (stock.quote.near_52wk_flag === 'near-low') {
      flagsHtml += `<span class="pressure-flag pressure-sell" title="Within 2% of the 52-week low of ₹${stock.quote.fifty_two_wk_low}">52wk low</span>`;
    }

    priceHtml = `<div class="entry-price">₹${stock.quote.last_price.toFixed(2)} <span class="${chgClass}">${chg != null ? `${chgSign}${chg}%` : ''}</span>${flagsHtml}</div>`;
  }

  return `<div class="entry ${overallSentiment === 'negative' ? 'has-negative' : ''}">
    <div class="entry-head">
      <div><span class="entry-name">${escapeHtml(stock.company)}</span><span class="entry-ticker">${escapeHtml(stock.ticker)}</span>${priceHtml}</div>
      ${badgeHtml}
    </div>
    ${body}
  </div>`;
}

checkKiteOAuthCallback();
init();
