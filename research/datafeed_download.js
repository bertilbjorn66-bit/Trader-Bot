#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const { getHistoricRates } = require('dukascopy-node');

const DEFAULT_PAIRS = [
  'eurusd', 'gbpusd', 'usdjpy', 'audusd', 'usdcad', 'usdchf', 'nzdusd', 'eurjpy', 'gbpjpy',
];

function parseArgs(argv) {
  const args = {
    start: '2020-01-01T00:00:00.000Z',
    end: new Date().toISOString(),
    pairs: DEFAULT_PAIRS.join(','),
    outDir: '.data/empirical_feed',
  };
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (token === '--start') args.start = argv[++i];
    else if (token === '--end') args.end = argv[++i];
    else if (token === '--pairs') args.pairs = argv[++i];
    else if (token === '--out-dir') args.outDir = argv[++i];
    else throw new Error(`Unknown argument: ${token}`);
  }
  return args;
}

function monthStarts(startDate, endDate) {
  const cursor = new Date(Date.UTC(startDate.getUTCFullYear(), startDate.getUTCMonth(), 1));
  const result = [];
  while (cursor < endDate) {
    result.push(new Date(cursor));
    cursor.setUTCMonth(cursor.getUTCMonth() + 1);
  }
  return result;
}

function aggregateToTenMinutes(rows) {
  const buckets = new Map();
  for (const row of rows) {
    const ts = Number(row[0]);
    const bucket = Math.floor(ts / 600000) * 600000;
    const offset = ts - bucket;
    const open = Number(row[1]);
    const high = Number(row[2]);
    const low = Number(row[3]);
    const close = Number(row[4]);
    if (!Number.isFinite(ts) || ![open, high, low, close].every(Number.isFinite)) continue;
    if (offset !== 0 && offset !== 300000) continue;
    const current = buckets.get(bucket) || {
      timestamp: bucket,
      open: null,
      high: -Infinity,
      low: Infinity,
      close: null,
      seen: new Set(),
    };
    if (offset === 0) current.open = open;
    current.high = Math.max(current.high, high);
    current.low = Math.min(current.low, low);
    if (offset === 300000) current.close = close;
    current.seen.add(offset);
    buckets.set(bucket, current);
  }

  return [...buckets.values()]
    .filter((bar) => bar.seen.has(0) && bar.seen.has(300000) && bar.open !== null && bar.close !== null)
    .sort((a, b) => a.timestamp - b.timestamp)
    .map(({ seen, ...bar }) => bar);
}

function indexRows(rows) {
  const map = new Map();
  for (const row of rows) map.set(Number(row.timestamp), row);
  return map;
}

async function fetchMonth(instrument, from, to, priceType) {
  return getHistoricRates({
    instrument,
    dates: { from, to },
    timeframe: 'm5',
    priceType,
    format: 'array',
    volumes: false,
    ignoreFlats: true,
    batchSize: 10,
    pauseBetweenBatchesMs: 1500,
    retryCount: 6,
    pauseBetweenRetriesMs: 5000,
    retryOnEmpty: true,
    failAfterRetryCount: true,
  });
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const start = new Date(args.start);
  const end = new Date(args.end);
  if (Number.isNaN(start.valueOf()) || Number.isNaN(end.valueOf()) || start >= end) {
    throw new Error('start/end must be valid UTC timestamps with start < end');
  }
  const pairs = args.pairs.split(',').map((x) => x.trim().toLowerCase()).filter(Boolean);
  fs.mkdirSync(args.outDir, { recursive: true });

  for (const instrument of pairs) {
    const outputPath = path.join(args.outDir, `${instrument}.jsonl`);
    fs.rmSync(outputPath, { force: true });
    const stream = fs.createWriteStream(outputPath, { encoding: 'utf8' });
    try {
      for (const month of monthStarts(start, end)) {
        const monthEnd = new Date(Date.UTC(month.getUTCFullYear(), month.getUTCMonth() + 1, 1));
        const from = month < start ? start : month;
        const to = monthEnd > end ? end : monthEnd;
        const bidRaw = await fetchMonth(instrument, from, to, 'bid');
        const askRaw = await fetchMonth(instrument, from, to, 'ask');
        const bidMap = indexRows(aggregateToTenMinutes(bidRaw));
        const askMap = indexRows(aggregateToTenMinutes(askRaw));
        const bars = [];
        for (const timestamp of [...bidMap.keys()].sort((a, b) => a - b)) {
          const b = bidMap.get(timestamp);
          const a = askMap.get(timestamp);
          if (!a) continue;
          bars.push({
            timestamp,
            bid_open: b.open,
            bid_high: b.high,
            bid_low: b.low,
            bid_close: b.close,
            ask_open: a.open,
            ask_high: a.high,
            ask_low: a.low,
            ask_close: a.close,
          });
        }
        const line = JSON.stringify({ month_start: month.toISOString(), bars }) + '\n';
        if (!stream.write(line)) await new Promise((resolve) => stream.once('drain', resolve));
      }
    } finally {
      await new Promise((resolve, reject) => {
        stream.end((err) => (err ? reject(err) : resolve()));
      });
    }
  }
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
