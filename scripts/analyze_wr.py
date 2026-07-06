import json
from collections import Counter, defaultdict
from pathlib import Path

raw = json.loads(Path("data/trades.json").read_text(encoding="utf-8"))
trades = raw["trades"] if isinstance(raw, dict) and "trades" in raw else raw
closed = [t for t in trades if t.get("status") == "closed"]
wins = [t for t in closed if (t.get("pnl_pct") or 0) > 0]
losses = [t for t in closed if (t.get("pnl_pct") or 0) < 0]
print("=== TRADES ===")
if closed:
    print(f"closed={len(closed)} W={len(wins)} L={len(losses)} WR={len(wins)/len(closed)*100:.1f}%")
    if wins:
        print(f"avg win: {sum(t.get('pnl_pct',0) for t in wins)/len(wins):.3f}%")
    if losses:
        print(f"avg loss: {sum(t.get('pnl_pct',0) for t in losses)/len(losses):.3f}%")

for src in sorted(set(t.get("source") for t in closed)):
    c = [t for t in closed if t.get("source") == src]
    w = sum(1 for t in c if (t.get("pnl_pct") or 0) > 0)
    print(f"  {src}: {len(c)} WR={w/len(c)*100:.1f}%")

print("=== CONFIDENCE ===")
for lo in range(50, 100, 10):
    hi = lo + 10
    c = [t for t in closed if lo <= (t.get("confidence") or 0) * 100 < hi]
    if not c:
        continue
    w = sum(1 for t in c if (t.get("pnl_pct") or 0) > 0)
    print(f"  {lo}-{hi}%: {w}/{len(c)} = {w/len(c)*100:.0f}%")

print("=== LEVERAGE ===")
for lev in [10, 15, 20, 25, 30, 50]:
    c = [t for t in closed if (t.get("leverage") or 0) == lev]
    if len(c) < 2:
        continue
    w = sum(1 for t in c if (t.get("pnl_pct") or 0) > 0)
    print(f"  {lev}x: {w}/{len(c)} = {w/len(c)*100:.0f}%")

print("=== FEATURES (with data) ===")
fam = defaultdict(lambda: [0, 0])
conf_b = defaultdict(lambda: [0, 0])
kalman_bad = [0, 0]
for t in closed:
    feat = t.get("probability_features") or {}
    win = (t.get("pnl_pct") or 0) > 0
    pk = feat.get("pattern_name") or "none"
    if win:
        fam[pk][0] += 1
    else:
        fam[pk][1] += 1
    cb = feat.get("confluence_score")
    if cb is not None:
        b = f"{int(cb)//10*10}"
        if win:
            conf_b[b][0] += 1
        else:
            conf_b[b][1] += 1
    ks = feat.get("kalman_signal")
    if ks and (
        (t.get("direction") == "LONG" and ks == "bearish")
        or (t.get("direction") == "SHORT" and ks == "bullish")
    ):
        if win:
            kalman_bad[0] += 1
        else:
            kalman_bad[1] += 1

for k, (w, l) in sorted(fam.items(), key=lambda x: -(x[1][0] + x[1][1]))[:10]:
    if w + l >= 2:
        print(f"  pattern {k}: {w}W/{l}L = {w/(w+l)*100:.0f}%")
for b in sorted(conf_b):
    w, l = conf_b[b]
    if w + l >= 2:
        print(f"  confluence {b}: {w}W/{l}L = {w/(w+l)*100:.0f}%")
if sum(kalman_bad):
    print(f"  kalman contra: {kalman_bad[0]}W/{kalman_bad[1]}L")

rej_path = Path("data/rejections.json")
if rej_path.exists():
    rej_raw = json.loads(rej_path.read_text(encoding="utf-8"))
    rej = rej_raw if isinstance(rej_raw, list) else rej_raw.get("rejections", [])
    stages = Counter(r.get("stage") for r in rej[-300:])
    print("=== REJECTIONS last 300 ===")
    for s, n in stages.most_common():
        print(f"  {s}: {n}")
