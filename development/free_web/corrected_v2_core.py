from itertools import combinations, permutations
import math
import numpy as np
import pandas as pd
MAX_BUDGET=10000
UNIT=100
UMAREN_TOP_N=5
SANREN_TOP_N=8
TARGET_RETURN=10000
EPS=1e-12

def normalize(x):
    x = np.asarray(x, dtype=float)
    x = np.clip(x, EPS, None)

    s = x.sum()

    if s <= 0:
        return np.repeat(
            1.0 / len(x),
            len(x),
        )

    return x / s

def pl_order_probability(strength, order):

    remaining = list(
        range(len(strength))
    )

    p = 1.0

    for chosen in order:

        denom = sum(
            strength[j]
            for j in remaining
        )

        if denom <= 0:
            return 0.0

        p *= (
            strength[chosen]
            / denom
        )

        remaining.remove(chosen)

    return p

def pair_key(a, b):

    a, b = sorted(
        [int(a), int(b)]
    )

    return f"{a:02d}{b:02d}"

def triple_key(a, b, c):

    a, b, c = sorted(
        [
            int(a),
            int(b),
            int(c),
        ]
    )

    return (
        f"{a:02d}"
        f"{b:02d}"
        f"{c:02d}"
    )

def generate_combinations(pred):
    combo_rows = []
    race_groups = list(
        pred.groupby("race_code")
    )
    for race_no, (
        race_code,
        g,
    ) in enumerate(
        race_groups,
        start=1,
    ):

        g = g.reset_index(
            drop=True
        )

        horses = (
            pd.to_numeric(
                g["umaban"],
                errors="coerce",
            )
            .astype(int)
            .to_numpy()
        )

        win = normalize(
            g["win_probability"]
            .to_numpy(dtype=float)
        )

        top3 = normalize(
            g["top3_probability"]
            .to_numpy(dtype=float)
        )

        strength = normalize(
            np.sqrt(
                win * top3
            )
        )


        # ========================================================
        # UMAREN
        # ========================================================

        pair_raw = []

        for i, j in combinations(
            range(len(g)),
            2,
        ):

            p = (
                pl_order_probability(
                    strength,
                    (i, j),
                )
                +
                pl_order_probability(
                    strength,
                    (j, i),
                )
            )

            pair_raw.append(
                (
                    i,
                    j,
                    p,
                )
            )

        pair_total = sum(
            x[2]
            for x in pair_raw
        )

        for i, j, p in pair_raw:

            combo_rows.append(
                {
                    "race_code":
                        race_code,

                    "bet_type":
                        "umaren",

                    "kumiban":
                        pair_key(
                            horses[i],
                            horses[j],
                        ),

                    "ai_probability":
                        p / pair_total,
                }
            )


        # ========================================================
        # SANRENPUKU
        # ========================================================

        triple_raw = []

        for combo in combinations(
            range(len(g)),
            3,
        ):

            p = 0.0

            for order in permutations(
                combo
            ):

                p += (
                    pl_order_probability(
                        strength,
                        order,
                    )
                )

            triple_raw.append(
                (
                    combo,
                    p,
                )
            )

        triple_total = sum(
            x[1]
            for x in triple_raw
        )

        for combo, p in triple_raw:

            combo_rows.append(
                {
                    "race_code":
                        race_code,

                    "bet_type":
                        "sanrenpuku",

                    "kumiban":
                        triple_key(
                            horses[combo[0]],
                            horses[combo[1]],
                            horses[combo[2]],
                        ),

                    "ai_probability":
                        p / triple_total,
                }
            )

        if race_no % 500 == 0:

            print(
                f"  {race_no:,}/3,455 races"
            )
    combo = pd.DataFrame(
        combo_rows
    )
    return combo

def allocate(combo):
    combo=combo.copy()
    combo["ev"]=combo["ai_probability"]*combo["decimal_odds"]
    candidate_parts = []
    for bet_type, top_n in [
        (
            "umaren",
            UMAREN_TOP_N,
        ),
        (
            "sanrenpuku",
            SANREN_TOP_N,
        ),
    ]:

        q = combo[
            combo["bet_type"]
            == bet_type
        ].copy()

        q = q.sort_values(
            [
                "race_code",
                "ai_probability",
                "kumiban",
            ],
            ascending=[
                True,
                False,
                True,
            ],
        )

        q["probability_rank"] = (
            q.groupby(
                "race_code"
            )
            .cumcount()
            + 1
        )

        q = q[
            q["probability_rank"]
            <= top_n
        ]

        candidate_parts.append(q)
    candidates = pd.concat(
        candidate_parts,
        ignore_index=True,
    )
    candidates["min_units"] = np.ceil(
        TARGET_RETURN
        /
        candidates["decimal_odds"]
        /
        UNIT
    ).astype(int)
    candidates["min_units"] = (
        candidates["min_units"]
        .clip(lower=1)
    )
    candidates["min_stake"] = (
        candidates["min_units"]
        * UNIT
    )
    candidates = candidates[
        candidates["min_stake"]
        <= MAX_BUDGET
    ].copy()
    candidates["allocation_weight"] = (
        candidates["ai_probability"]
        * np.sqrt(
            np.maximum(
                candidates["ev"],
                0.01,
            )
        )
    )
    selected_rows = []
    for race_code, g in candidates.groupby("race_code"):

        # AI probability is the primary ordering.
        g = g.sort_values(
            [
                "ai_probability",
                "allocation_weight",
                "kumiban",
            ],
            ascending=[
                False,
                False,
                True,
            ],
        ).copy()

        retained = []
        used = 0

        # First guarantee the minimum stake required
        # for >= 10,000 yen return if this ticket alone hits.
        for _, row in g.iterrows():

            stake = int(
                row["min_stake"]
            )

            if (
                used + stake
                <= MAX_BUDGET
            ):

                retained.append(
                    {
                        **row.to_dict(),
                        "stake": stake,
                    }
                )

                used += stake

        if not retained:
            continue

        remaining = (
            MAX_BUDGET - used
        )

        # Allocate remaining money according to frozen V2 weight.
        if remaining >= UNIT:

            extra_units = (
                remaining // UNIT
            )

            total_weight = sum(
                max(
                    float(r["allocation_weight"]),
                    0.0,
                )
                for r in retained
            )

            if total_weight > 0:

                ideal = [
                    extra_units
                    * max(
                        float(r["allocation_weight"]),
                        0.0,
                    )
                    / total_weight
                    for r in retained
                ]

                floor_units = [
                    int(math.floor(x))
                    for x in ideal
                ]

                for r, units in zip(
                    retained,
                    floor_units,
                ):

                    r["stake"] += (
                        units * UNIT
                    )

                leftover = (
                    extra_units
                    - sum(floor_units)
                )

                order = sorted(
                    range(len(retained)),
                    key=lambda i: (
                        ideal[i]
                        - floor_units[i],
                        retained[i]["ai_probability"],
                        retained[i]["allocation_weight"],
                        str(retained[i]["kumiban"]),
                    ),
                    reverse=True,
                )

                for i in order[:leftover]:

                    retained[i]["stake"] += UNIT

        selected_rows.extend(
            retained
        )
    selected = pd.DataFrame(
        selected_rows
    )
    return selected
