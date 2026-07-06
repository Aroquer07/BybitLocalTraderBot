import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PineTS } from "pinets";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

function sampleCandles(n = 120) {
  const out = [];
  let price = 1.1;
  const start = Date.now() - n * 5 * 60_000;
  for (let i = 0; i < n; i++) {
    const o = price;
    const h = price + 0.01;
    const l = price - 0.01;
    const c = price + (i % 2 === 0 ? 0.002 : -0.002);
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

async function runSimple() {
  const pineTS = new PineTS(sampleCandles(80));
  const { plots } = await pineTS.run(`
//@version=5
indicator("EMA test")
plot(ta.ema(close, 9), "EMA9")
plot(ta.ema(close, 21), "EMA21")
`);
  console.log("simple plots:", Object.keys(plots));
  const ema9 = plots["EMA9"]?.data?.slice(-3);
  console.log("EMA9 last 3:", ema9);
}

async function runSniper() {
  const path = resolve(root, "indicators/sniper entry");
  let source = readFileSync(path, "utf8");
  // PineTS compat: duplicate '_' destructure + security sem feed MTF no snapshot
  source = source.replace("[_, _, adx] = ta.dmi(14, 14)", "[diPlus, diMinus, adx] = ta.dmi(14, 14)");
  source = source.replace(
    /rsi5m\s*=\s*request\.security\([^)]+\)/,
    "rsi5m   = ta.rsi(close, 14)",
  );
  const pineTS = new PineTS(sampleCandles(120));
  try {
    const result = await pineTS.run(source);
    console.log("sniper keys:", Object.keys(result));
    console.log("sniper plots:", Object.keys(result.plots ?? {}));
    for (const k of Object.keys(result.plots ?? {})) {
      const d = result.plots[k]?.data;
      if (d?.length) {
        console.log(`  ${k}: ${d.length} pts, last=`, JSON.stringify(d[d.length - 1]).slice(0, 150));
      }
    }
  } catch (err) {
    console.error("sniper error:", err.message?.slice(0, 800));
  }
}

async function runBreakout() {
  const path = resolve(root, "indicators/breakout Probability");
  const source = readFileSync(path, "utf8");
  const pineTS = new PineTS(sampleCandles(120));
  try {
    const result = await pineTS.run(source);
    console.log("breakout keys:", Object.keys(result));
    console.log("breakout plots:", Object.keys(result.plots ?? {}));
  } catch (err) {
    console.error("breakout error:", err.message?.slice(0, 500));
  }
}

await runSimple();
await runSniper();
await runBreakout();
