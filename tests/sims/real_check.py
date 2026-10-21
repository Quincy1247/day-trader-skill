"""Parity check vs the pack's own entry.py on real Yahoo 5m fixtures, then a real-data replay."""
import datetime as D
import gzip
import json
import sys

import numpy as np

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dts_sim as S

ENTRY = S._load("trader-entry", "entry")
FIX = os.path.join(S.ROOT, "tests", "fixtures") + "/"


def sessions(chart_json):
    if not (chart_json.get("chart") or {}).get("result"):
        return {}
    r = chart_json["chart"]["result"][0]
    if "timestamp" not in r:
        return {}
    q = r["indicators"]["quote"][0]
    days = {}
    for i, ts in enumerate(r["timestamp"]):
        if None in (q["open"][i], q["high"][i], q["low"][i], q["close"][i]):
            continue
        et = ENTRY.to_eastern(D.datetime.fromtimestamp(ts, D.timezone.utc).replace(tzinfo=None))
        if et.second:
            continue
        slot = (et.hour * 60 + et.minute - 570) // 5
        if 0 <= slot < S.BARS:
            days.setdefault(et.date(), {})[slot] = (q["open"][i], q["high"][i], q["low"][i], q["close"][i])
    out = {}
    for d, b in days.items():
        if len(b) == S.BARS:
            a = np.array([b[k] for k in range(S.BARS)], float)
            out[d] = tuple(a[:, j] for j in range(4))
    return out


def parity(chart, sym):
    ok = bad = 0
    for d, (o, h, l, c) in sessions(chart).items():
        now = ENTRY.eastern_to_utc(D.datetime.combine(d, D.time(15, 31)))
        res = ENTRY.evaluate(ENTRY.parse_chart(json.dumps(chart), sym), now)
        mine = S.plan_day(o, h, l, c)
        theirs = res.get("trigger")
        same = (mine is None and theirs is None) or (
            mine is not None and theirs is not None and abs(mine[1] - theirs["price"]) < 0.005)
        # plan_day can also return None when exit.compute refuses (risk < 0.05%) while entry triggered
        if not same and theirs and mine is None:
            try:
                orr = res["opening_range"]
                S.EXIT.compute(theirs["price"], "or_mid", None, "r", S.Decimal(2), or_high=orr["high"], or_low=orr["low"])
            except S.EXIT.PlanError:
                same = True
        ok += bool(same)
        bad += not same
        if not same:
            print("MISMATCH", sym, d, mine, theirs)
    return ok, bad


if __name__ == "__main__":
    tsla = json.load(gzip.open(FIX + "trader-timemachine/TSLA-60d5m.json.gz", "rt"))
    print("TSLA parity (days ok, mismatches):", parity(tsla, "TSLA"))
    wall = json.load(gzip.open(FIX + "trader-scanner/wall5m-2026-10-19.json.gz", "rt"))
    tot = [0, 0]
    for sym, ch in wall.items():
        a, b = parity(ch, sym)
        tot[0] += a; tot[1] += b
    print("234-stock 2026-10-19 parity:", tot)

    # real replay 1: TSLA, every full session in the fixture, $5k account, default rules
    ts = sessions(tsla)
    days = [{"TSLA": ts[d]} for d in sorted(ts)]
    for pdt in (False, True):
        tr, cv = S.sim_days(days, pdt=pdt)
        pnl = np.array([t[5] for t in tr])
        eq = np.concatenate([[5000], cv])
        print("TSLA %d sessions %s: trades %d (%.1f/wk) win %.0f%% avgR %+.2f  P&L $%+.2f (%+.2f%%)  maxDD %.1f%%" % (
            len(days), "PDT" if pdt else "noPDT", len(tr), len(tr) / (len(days) / 5), 100 * (pnl > 0).mean(),
            np.mean([t[6] for t in tr]), pnl.sum(), 100 * (cv[-1] / 5000 - 1),
            100 * (eq / np.maximum.accumulate(eq) - 1).min()))
    # real replay 2: every one of the 234 stocks on 2026-10-19, one trade each, $50 risk
    rs = []
    for sym, ch in wall.items():
        s = sessions(ch)
        for d, b in s.items():
            tr, _ = S.sim_days([{sym: b}])
            rs += [t[6] for t in tr]
    rs = np.array(rs)
    print("2026-10-19, 234 stocks: %d trades, win %.0f%%, avg %+.2fR (= $%+.2f per $50-risk trade)" % (
        len(rs), 100 * (rs > 0).mean(), rs.mean(), 50 * rs.mean()))
