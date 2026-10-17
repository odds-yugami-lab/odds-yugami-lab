# Methodology

公開可能な予測・購入ルールと検証方針を記録します。

## corrected V2 (historical, through 2026-10-17)

- AI確率を購入候補選択の主軸とする
- 馬連: AI確率上位5点
- 3連複: AI確率上位8点
- オッズは候補選択の主役ではなく、候補内の資金配分に利用
- 単独的中時に原則10,000円以上の払戻となる最低購入額を設定
- 1レース合計10,000円

ルール変更を行う場合は、過去の記録を書き換えず、新しいバージョンとして区別します。

## balanced A v2 (from 2026-10-18)

- No fixed count or bet-type budget split; consider every quinella and trifecta-box combination.
- Budget 10,000 JPY, tickets in 100 JPY units, each individual payout if hit >= 10,000 JPY.
- Risk control: maximum 1,000 JPY per ticket, except that the minimum stake needed for the payout floor is allowed without extra allocation.
- Balance robust expected-return proxy and union hit chance; cap odds at 50x only in the optimization proxy, never in actual odds or settlement.
- Store rule identifier as balanced_A_v2. Historical records remain unchanged; simulations and live outcomes are separately tracked.
