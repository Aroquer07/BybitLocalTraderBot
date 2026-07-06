import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PineTS } from "pinets";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

export function preprocessSniperPine(source) {
  let s = source;
  s = s.replace(/\/\/@version=6/, "//@version=5");
  s = s.replace(
    'rsi5m   = request.security(syminfo.tickerid, "5", ta.rsi(close, 14))',
    "rsi5m   = ta.rsi(close, 14)",
  );
  s = s.replace("[m, s, _] = ta.macd(close, 12, 26, 9)", "[m, s, macdHist] = ta.macd(close, 12, 26, 9)");
  s = s.replace("[_, _, adx] = ta.dmi(14, 14)", "[diPlus, diMinus, adx] = ta.dmi(14, 14)");
  return s;
}

function sampleCandles(n = 120) {
  const out = [];
  let price = 1.1;
  const start = Date.now() - n * 5 * 60_000;
  for (let i = 0; i < n; i++) {
    const o = price;
    const h = price + 0.012;
    const l = price - 0.012;
    const c = price + (Math.sin(i / 8) * 0.004);
    out.push({
      open: o,
      high: h,
      low: l,
      close: c,
      volume: 1000 + i * 10,
      openTime: start + i * 5 * 60_000,
    });
    price = c;
  }
  return out;
}

const raw = readFileSync(resolve(root, "indicators/sniper entry"), "utf8");
const source = preprocessSniperPine(raw);
const pineTS = new PineTS(sampleCandles(120));

try {
  const result = await pineTS.run(source);
  console.log("OK plots:", Object.keys(result.plots));
  for (const k of Object.keys(result.plots)) {
    const d = result.plots[k]?.data;
    if (!d?.length) continue;
    console.log(`\n${k} (${d.length}):`);
    console.log(JSON.stringify(d.slice(-2), null, 2).slice(0, 1200));
  }
} catch (e) {
  console.error("FAIL:", e.message);
}
