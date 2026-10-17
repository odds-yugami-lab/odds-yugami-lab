"""Deterministic synthetic tests for balanced_A_v1 (not a live racing test)."""
import math
import time
import numpy as np
import pandas as pd
from balanced_A_v1 import allocate_balanced, _ordered_outcomes

def check(n):
    rng = np.random.default_rng(2026)
    win = rng.dirichlet(np.ones(n) * 1.7)
    top3 = np.minimum(win * 3 + rng.uniform(0, .07, n), 1.)
    horses = pd.DataFrame({'umaban': range(1, n + 1),
                           'win_probability': win, 'top3_probability': top3})
    probs = {}
    for p, pair_type, pair_key, triple_type, triple_key in _ordered_outcomes(horses):
        probs[pair_type, pair_key] = probs.get((pair_type, pair_key), 0) + p
        probs[triple_type, triple_key] = probs.get((triple_type, triple_key), 0) + p
    odds = pd.DataFrame([
        {'race_code': '0000000000000001', 'bet_type': typ, 'kumiban': key,
         'ai_probability': p,
         'decimal_odds': round(float(np.clip((1 / p) * rng.lognormal(-.24, .38),
                                            1.01, 2000.)), 1)}
        for (typ, key), p in probs.items()
    ])
    for typ in ('umaren', 'sanrenpuku'):
        sel = odds.bet_type == typ
        odds.loc[sel, 'ai_probability'] /= odds.loc[sel, 'ai_probability'].sum()
    start = time.monotonic()
    chosen, audit = allocate_balanced(
        odds, horses, time_limit_per_solve=1.2, weights=(.08, .3, .55, .85, 1.)
    )
    assert len(chosen) > 0
    assert int(chosen.stake.sum()) == 10000
    assert (chosen.stake % 100 == 0).all()
    assert (chosen.stake * chosen.decimal_odds >= 10000 - 1e-6).all()
    assert audit['ticket_count'] == len(chosen)
    assert audit['rule'] == 'balanced_A_v1'
    assert 0 < audit['probability_any_win'] <= 1
    print(f'n={n} tickets={len(chosen)} E={audit["expected_payout_yen"]:.0f} '
          f'H={audit["probability_any_win"]:.2%} seconds={time.monotonic()-start:.3f}')

if __name__ == '__main__':
    for n in (8, 14, 17, 18):
        check(n)
