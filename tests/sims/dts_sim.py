"""Sim for the day-trader-skill pack's default bot, run the same way as the QR-3 / CLAUDE-1 / JQ-1 sims.

Default pack rules (no config changes): 15-min opening-range breakout on 5m bars, long only, stock (no options).
Trigger = first bar after the range (bar end 9:45..15:30) closing above the range high (trader-entry).
Stop = range midpoint, target = 2R (trader-exit, its own compute()). Size = trader-budget's own size_trade():
$50 max loss/trade, 75% position cap, $4,000 max order, 10% cash buffer. Max 3 trades/day, $150 daily max loss
(trader-risk). Bracket order; flat at 15:55. Symbols SPY + QQQ (same as the other bots). $5,000 account.

Fills: buy at trigger close + $0.01; stop = stop-market (fills at min(stop, bar open) - $0.01);
target = limit (fills at target); stop and target in the same bar -> stop (conservative); 15:55 exit at the
15:50 bar close - $0.01. PDT variant: <$25k account = max 3 day trades per rolling 5 market days.
"""
import importlib.util
import math
from decimal import Decimal
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load(folder, name):
    spec = importlib.util.spec_from_file_location("t_" + name, os.path.join(ROOT, folder, name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


EXIT = _load("trader-exit", "exit")
SIZE = _load("trader-budget", "size")
CFG = dict(SIZE.DEFAULTS)
SLIP = 0.01
N_OR = 3              # 9:30, 9:35, 9:40
FIRST_SLOT = 3        # bar 9:45-9:50 (end 9:50 >= 9:45)
LAST_SLOT = 70        # bar 15:25-15:30 (end 15:30 <= 15:30)
FLAT_SLOT = 76        # bar 15:50-15:55 -> out at its close
BARS = 78


def plan_day(o, h, l, c):
    """Entry + exit plan for one session (arrays of 78 bars). None if no trade."""
    orh, orl = h[:N_OR].max(), l[:N_OR].min()
    orh, orl = round(float(orh), 2), round(float(orl), 2)
    hit = np.nonzero(c[FIRST_SLOT:LAST_SLOT + 1] > orh)[0]
    if not len(hit):
        return None
    k = FIRST_SLOT + int(hit[0])
    entry = round(float(c[k]), 2)
    try:
        p = EXIT.compute(entry, "or_mid", None, "r", Decimal(2), or_high=orh, or_low=orl)
    except EXIT.PlanError:
        return None
    return k, float(p["entry"]), float(p["stop"]), float(p["target"])


def run_trade(o, h, l, c, k, entry, stop, target, path=None):
    fill = entry + SLIP
    if path is not None:
        # synthetic: exit at the sub-step price where the level is crossed (martingale-neutral; filling
        # exactly at the level would hand a random walk a fake edge, since stops hit ~2x as often as targets)
        for j in range(k + 1, FLAT_SLOT + 1):
            for p in path[j]:
                if p <= stop:
                    return p - SLIP, fill
                if p >= target:
                    return p, fill
        return c[FLAT_SLOT] - SLIP, fill
    for j in range(k + 1, FLAT_SLOT + 1):
        if l[j] <= stop:
            return min(stop, o[j]) - SLIP, fill
        if h[j] >= target:
            return max(target, o[j]) if o[j] > target else target, fill
    return c[FLAT_SLOT] - SLIP, fill


def sim_days(days, equity0=5000.0, pdt=False):
    """days: list (per market day) of dict sym -> (o,h,l,c). Returns trades list and daily equity."""
    eq = equity0
    curve, trades, dt_window = [], [], []
    for d, bars in enumerate(days):
        dt_window = [x for x in dt_window if x > d - 5]
        cands = []
        for sym, b in bars.items():
            p = plan_day(*b[:4])
            if p:
                cands.append((p[0], sym, p))
        cands.sort()
        cash, loss_used, n = eq, 0.0, 0
        for k, sym, (k, entry, stop, target) in cands:
            if n >= CFG["max_trades_per_day"] or (pdt and len(dt_window) >= 3):
                break
            s = SIZE.size_trade({"symbol": sym, "entry": entry, "stop": stop, "target": target}, CFG,
                                budget=eq, cash=cash)
            if s["refusal"] or s["qty"] <= 0 or loss_used + s["max_loss"] > CFG["max_daily_loss_usd"] + 0.01:
                continue
            o, h, l, c = bars[sym][:4]
            out, fill = run_trade(o, h, l, c, k, entry, stop, target, *bars[sym][4:])
            pnl = (out - fill) * s["qty"]
            trades.append((d, sym, s["qty"], fill, out, pnl, (out - fill) / (fill - stop)))
            cash -= s["cost"]
            loss_used += s["max_loss"]
            n += 1
            eq += pnl
            dt_window.append(d)
        curve.append(eq)
    return trades, np.array(curve)


# ------------------------------------------------------------------ synthetic SPY/QQQ 5m sessions

REGIMES = {"rising": 0.15, "flat": 0.0, "falling": -0.20}
VOLS = {"calm": (0.15, 0.20), "fear": (0.28, 0.36)}       # annualized (SPY, QQQ)


def synth_year(rng, mu, vols, start=(560.0, 480.0), days=252):
    """One year of correlated SPY/QQQ 5m bars. U-shaped intraday vol, t(4) tails, overnight gaps."""
    u = np.linspace(-1, 1, BARS)
    shape = 1 + 1.2 * u ** 2
    shape /= np.sqrt((shape ** 2).mean())
    px = list(start)
    out = []
    for _ in range(days):
        z = rng.standard_t(4, size=(BARS * 4 + 1, 2)) / math.sqrt(2.0)
        z[:, 1] = 0.9 * z[:, 0] + math.sqrt(1 - 0.81) * z[:, 1]
        day = {}
        for i, sym in enumerate(("SPY", "QQQ")):
            sd = vols[i] / math.sqrt(252)
            gap = z[0, i] * sd * math.sqrt(0.3)
            sub = z[1:, i] * sd * math.sqrt(0.7 / (BARS * 4)) * np.repeat(shape, 4)
            drift = (mu - 0.5 * vols[i] ** 2) / 252
            path = px[i] * np.exp(gap + drift * 0.3 + np.cumsum(sub + drift * 0.7 / (BARS * 4)))
            p = path.reshape(BARS, 4)
            prev = np.concatenate([[px[i] * math.exp(gap)], p[:-1, -1]])
            o, c = prev, p[:, -1]
            h = np.maximum(p.max(1), o)
            l = np.minimum(p.min(1), o)
            day[sym] = (np.round(o, 2), np.round(h, 2), np.round(l, 2), np.round(c, 2), np.round(p, 2))
            px[i] = float(c[-1])
        out.append(day)
    return out


def synthetic(years=200, seed=7):
    rows = []
    for rname, mu in REGIMES.items():
        for vname, vols in VOLS.items():
            rng = np.random.default_rng(seed)
            res = {}
            yrs = [synth_year(rng, mu, vols) for _ in range(years)]
            for pdt in (False, True):
                trades, curve = [], []
                # each year is its own $5k account (independent paths), like the other bots' 200-yr sims
                for y in yrs:
                    t, cv = sim_days(y, pdt=pdt)
                    trades += t
                    curve.append(cv)
                # stats per independent year
                cv = np.array(curve)
                yret = cv[:, -1] / 5000 - 1
                dd = [(np.concatenate([[5000], c]) / np.maximum.accumulate(np.concatenate([[5000], c])) - 1).min()
                      for c in cv]
                pnl = np.array([t[5] for t in trades])
                res[pdt] = dict(trades_wk=len(trades) / (years * 52), win=(pnl > 0).mean(),
                                avg_R=float(np.mean([t[6] for t in trades])), usd_mo=pnl.sum() / (years * 12),
                                yr_avg=yret.mean(), yr_med=np.median(yret), yr_p10=np.percentile(yret, 10),
                                dd_med=np.median(dd), dd_worst=min(dd))
            rows.append((rname, vname, res))
            print(rname, vname, flush=True)
    return rows


if __name__ == "__main__":
    yrs = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    for rname, vname, res in synthetic(yrs):
        for pdt, r in res.items():
            print("%-8s %-5s %-6s trades/wk %.2f  win %4.0f%%  avgR %+.2f  $/mo %+7.2f  yr avg %+6.1f%%  "
                  "typical %+6.1f%%  bad-yr(p10) %+6.1f%%  maxDD typ %5.1f%% worst %5.1f%%" % (
                      rname, vname, "PDT" if pdt else "noPDT", r["trades_wk"], 100 * r["win"], r["avg_R"],
                      r["usd_mo"], 100 * r["yr_avg"], 100 * r["yr_med"], 100 * r["yr_p10"],
                      100 * r["dd_med"], 100 * r["dd_worst"]))
