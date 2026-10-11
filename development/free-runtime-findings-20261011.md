# 追加費用ゼロでの実行環境調査（2026-10-11）

状態：計算部品は作成済み。PC不要の週次データ取得・予想公開は未完成。

## 実際に確認したこと

公開リポジトリの標準Windows runnerで検証処理を起動し、JRA-VAN公式64bit SDKをダウンロード・展開できた。修正後の実行は成功。

[検証実行](https://github.com/odds-yugami-lab/odds-yugami-lab/actions/runs/38117916838)

認証、利用キー登録、JV-Linkのインストール、競馬データ取得は実施していない。学習済みモデル・内部データはリポジトリに保存していない。この処理に定期実行は設定していない。

## 継続取得への障害

GitHub公式資料では各ジョブは新しい実行環境になる。
JRA-VAN公式FAQでは、設定済み利用キーを別PCで使った場合や再インストール後に認証エラーになり、再発行が必要と説明されている。
この組合せから、同じキーを毎回の新規Windowsに設定する方式は、そのまま週次運用として採用できないと判断する。GitHub環境で実際にキー認証を試した結果ではなく、公式仕様からの判断。

公開Webの出馬表・オッズだけでは、全馬の調教履歴や学習時と同一定義の過去集計まで揃うことは未確認。抜けた特徴量を任意のゼロ値や推測値で埋めて完成扱いしない。

## 今後の必要事項

- 追加費用なしの安定したデータ入口を確定する。
- 元の特徴量生成SQLと同一定義を再現する。
- 発走前スナップショット、組合せオッズ、予想確定時刻を記録する。
- 記録成功を確認してX投稿文を生成する。
- GitHubのscheduleは遅延し得るため、発走12分前の開始だけに依存せず、先に起動して締切を検査する。

## 公式資料

- [無料Windows runner・毎ジョブ新規環境](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job)
- [JRA-VANのキー認証エラー](https://support.jra-van.jp/jravan/detail?id=30&site=SVKNEGBV)
- [利用キー再発行回数制限](https://support.jra-van.jp/jravan/detail?category=29&id=423&site=SVKNEGBV)
- [公式SDK](https://developer.jra-van.jp/t/topic/45)
- [GitHub schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
