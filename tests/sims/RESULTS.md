# Sim results: the pack's default bot (run 2026-10-21)

Same sims as QR-3 / CLAUDE-1 / JQ-1 in Quincy1247/trading-bots: SPY + QQQ, $5,000 paper account,
rising / flat / falling markets x calm / fear volatility, 200 years each, plus a real-data replay.

## The bot being tested (pack defaults, nothing changed)

- 15-minute opening-range breakout on 5-minute bars, **stock, long only** (no options, no puts, no shorts)
- Buy the first bar closing above the range high (bar end 9:45 to 15:30) (`trader-entry`)
- Stop = range midpoint, target = 2R, out by 15:55 (`trader-exit`, its own `compute()`)
- Size = `trader-budget`'s own `size_trade()`: $50 max loss per trade (1% of $5k), 75% position cap,
  $4,000 max order; max 3 trades/day, $150 daily max loss (`trader-risk`)
- Fills: buy at signal + $0.01, stop sells $0.01 worse, 15:55 exit $0.01 worse
- PDT = the realistic one for a $5k account (Alpaca: max 3 day trades per 5 market days). The pack's own
  `pdt_guard` is OFF by default, so "noPDT" is what the pack would try to do.

Check: the sim's entries match the pack's own `entry.py` on all 59 real TSLA sessions (0 mismatches).

## 200-year synthetic sims (PDT = realistic)

| market | vol | trades/wk | win % | $/mo | avg yr | typical yr | bad yr (p10) | max DD typical / worst |
|---|---|---|---|---|---|---|---|---|
| rising | calm | 2.8 | 38% | +$2.54 | +0.6% | +0.3% | -3.4% | -3.1% / -8.0% |
| rising | fear | 2.8 | 37% | +$2.93 | +0.7% | -0.1% | -6.3% | -5.8% / -14.4% |
| flat | calm | 2.8 | 36% | -$0.67 | -0.2% | -0.4% | -4.3% | -3.5% / -8.4% |
| flat | fear | 2.8 | 37% | -$0.10 | -0.0% | -0.5% | -7.4% | -5.9% / -15.5% |
| falling | calm | 2.8 | 35% | -$4.12 | -1.0% | -1.1% | -5.2% | -3.7% / -10.3% |
| falling | fear | 2.8 | 36% | -$3.45 | -0.8% | -1.0% | -8.5% | -6.2% / -15.4% |

Without the PDT limit it trades ~7.4/wk with the same per-trade results (about double the $/mo either way,
up to -$9.57/mo in falling markets, worst drawdown -23.9%). Full table: run `python3 dts_sim.py 200`.

## Real data (TSLA 5m, 59 sessions, Jul 27 to Oct 19 2026, from the repo's fixtures)

- PDT: 28 trades, 36% win, avg -0.13R, **-$40 (-0.8%)**, max DD -4.9%
- noPDT: 33 trades, 36% win, avg -0.17R, **-$108 (-2.2%)**, max DD -4.1%

## Bottom line

About break-even: +1% a year at best (rising), -1% in falling markets, and slightly losing on the only
real data. Small risk ($50/trade) means small swings. It only buys, so it cannot use down days.
Like the other bots' notes say: synthetic data cannot show an intraday edge (a random walk gives this
bot exactly 0R before costs, verified), so a real SPY/QQQ multi-year backtest is the real test.

Sim note: an earlier draft filled stops/targets exactly at their price inside synthetic bars, which gave a
random walk a fake +0.06R/trade (stops hit ~2x as often as targets). Synthetic fills now use the
price where the level was crossed; real-data replays still fill at the level, as a live stop would.

Run: `cd tests/sims && python3 dts_sim.py 200 && python3 real_check.py` (needs numpy).
