/** Ajustes mínimos para PineTS rodar nossos .pine em snapshot (sem alterar o arquivo original). */

export function preprocessSniperPine(source: string): string {
  let s = source;
  s = s.replace(/\/\/@version=6/, "//@version=5");
  s = s.replace(
    'rsi5m   = request.security(syminfo.tickerid, "5", ta.rsi(close, 14))',
    "rsi5m   = ta.rsi(close, 14)",
  );
  s = s.replace("[m, s, _] = ta.macd(close, 12, 26, 9)", "[m, s, macdHist] = ta.macd(close, 12, 26, 9)");
  s = s.replace("[_, _, adx] = ta.dmi(14, 14)", "[diPlus, diMinus, adx] = ta.dmi(14, 14)");
  // Só TP1–TP3 no replay (bot não usa TP4/TP5)
  s = s.replace(
    /t1\s*:=.*\n\s*t2\s*:=.*\n\s*t3\s*:=.*/,
    "t1  := triggerBuy ? entryP + (risk * 1.2) : entryP - (risk * 1.2)\n    t2  := triggerBuy ? entryP + (risk * 2.0) : entryP - (risk * 2.0)\n    t3  := triggerBuy ? entryP + (risk * 3.0) : entryP - (risk * 3.0)",
  );
  s = s.replace(
    /lT4 := line\.new\([\s\S]*?\n\s*lT5 := line\.new\([\s\S]*?\n/,
    "",
  );
  s = s.replace(
    /label\.set_xy\(lbT4[\s\S]*?label\.set_xy\(lbT5[\s\S]*?\n/,
    "",
  );
  return s;
}

/** Sniper usa 3 TPs (alinhado ao bot e trade_validation). */
export const SNIPER_TP_COUNT = 3;

export const PINE_FILES_BY_STRATEGY: Record<string, string[]> = {
  sniper: ["sniper entry", "breakout Probability"],
  combined: ["sniper entry", "breakout Probability", "trend speed analyzer"],
  imba: ["ALGO", "Kalman"],
};

export function pineFilesForSnapshot(
  entryStrategy?: string,
  activeIndicators?: string[],
): string[] {
  if (activeIndicators?.length) {
    const map: Record<string, string> = {
      sniper: "sniper entry",
      breakout_probability: "breakout Probability",
      trend_speed: "trend speed analyzer",
      range_detector: "Range detector",
    };
    return activeIndicators.map((n) => map[n] ?? n).filter(Boolean);
  }
  return PINE_FILES_BY_STRATEGY[entryStrategy ?? "sniper"] ?? PINE_FILES_BY_STRATEGY.sniper;
}
