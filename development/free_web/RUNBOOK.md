# 無料予想の実行手順（2026-10-13）

追加料金なし。モデル・履歴は非公開。2026-10-18以降の本番買い目配分は balanced_A_v2（集中リスク抑制型）。2026-10-17までのcorrected V2と試作balanced A v1は別方式として保存・区別する。

## balanced_A_v2 本番導入（2026-10-18）
- `development/free_web/balanced_A_v2.py` が新規の購入選定・配分実装。旧 `corrected_v2_core.py` および旧 `balanced_A_v1.py` は変更しない。 `pre_race_record.prepare` は v2 の `allocate_balanced` を呼び出す。確率生成は同一 `corrected_v2_core.generate_combinations` を使用。
- 馬連・3連複すべての組み合わせを候補にする。購入点数の固定上限・下限、券種別の固定予算比率はなし。
- バランス目的関数は推定払戻の保守的な代理評価と、1点以上的中するモデル確率。極端なオッズが最適化を支配しないよう、代理評価用オッズ上限50倍を適用する。これは評価式だけの上限であり、購入時オッズと実際の払戻、精算に使うオッズを改ざんしない。真の期待払戻とは区別する。
- 集中リスク対策として、各馬券に対する追加配分の上限を1,000円とする。ただし最低払戻条件を満たすため必要な購入額が1,000円を超える買い目は、その必要最低額まで許容し、それ以上は追加投資しない。買い目数の上限ではない。
- 合計10,000円、100円単位、すべての購入馬券の単独的中時払戻が購入時オッズで10,000円以上であることは従来どおり必須。
- 算出は複数の線形混合整数最適化を比較する近似。採用した重み、集中上限、評価用オッズ上限、最大投資額、推定的中機会、計算器の状態を `allocation_audit` として原本に付記。全体の大域最適解とは表現しない。
- 新原本はschema_version=4、allocation_rule=balanced_A_v2。既存の発走前原本は不変。実績は corrected V2／balanced A v1検証／balanced A v2 に区分。
- GitHub Actionsの2レース再計算は確定オッズの事後検証であり、本番の事前的中やキャリブレーションを保証しない。全件オッズ、正式出走・取消・馬体重、発走12分前のコミット/receipt保存は当日に実証し、旧方式へ自動フォールバックしない。

## GitHub保存先・検証・障害時の手順（2026-10-17追記）
- free52の現在の検証・実行記録が保存されているブランチは `dev/free-windows-probe-20261011`。事前記録・receipt・結果記録は同一ブランチで読み書きし、`main` の404を「事前記録なし」と解釈しない。ブランチは処理前に明示して固定し、GitHub API呼び出し時に `branch` / `ref` を指定する。
- 事前記録 `predictions/free52/<race_code>.json` とreceipt `predictions/free52_receipts/<race_code>.json` は新規保存のみ。保存前に対象ブランチで存在確認を行い、既存ファイルは変更しない。結果記録 `results/free52/<race_code>.json` も同じrace_codeが既存なら内容を読んで照合し、二重計上しない。
- 書き込み応答のcommit SHAを受け取るだけでは成功とみなさない。(1)対象ブランチからfetch_fileできる、(2)commit指定で同じ内容を取得できる、(3)期待した本文またはハッシュと一致する、(4)そのコミットが対象ブランチの履歴に存在する、を確認してから「保存済み」と表示する。事前予測は発走前時刻の検証も別途必須。
- 403/404/409/422等の応答、書き込み確認不一致、タイムアウト、権限失効はエラー種別・操作・パス・ブランチを報告する。再試行前に必ず存在確認・ハッシュ照合を行い、同じ結果を重複登録しない。失敗時は結果を別ファイルとして手元に退避し「GitHub未保存」と明記する。発走後に事前記録を新規作成・改変しない。
- `main` と開発ブランチは2026-10-17時点で履歴が分岐している。無確認でのforce push、mainへのref書き換え、自動マージをしない。移行が必要なら両方の変更を確認し、適切なレビューと安全なマージ方法を選ぶ。
- モデル識別子・事前予想commit・receipt・公式確認状況・実購入確認状況を結果に保持し、旧方式/新free52方式と仮想/実購入成績を混ぜない。

## 予想
1. LibraryのJRA_free_model_52_20261013.zip、JRA_free_history_20261012.zipを取得・展開する。coverage_manifest.jsonの履歴更新日を確認し、開催が追加された場合は無料結果と確定出走情報からhistory_bridgeで履歴を追記する。元のファイルは上書きしない。更新した履歴は同じLibraryファイルの新しいバージョンとして保存する。
2. 無料の当日出馬表と、JRA公式で確認した全頭の出走/取消/除外情報を取得する。出馬表の****や馬体重未発表だけで取消を推定しない。entry_changesの完全なhorse_statusesを作る。確認できなければverified=trueを設定しない。
3. 前走通過順位から取得した脚質を出典付きで準備する。feature_pipeline.assembleを実行し、prediction_ready=trueであることを確認する。新しい騎手・取消に合わせて過去成績を再計算する。
4. 馬連・3連複全組合せをodds.parseで取得する。この関数だけではverified_liveにならない。取得ページが発売中で当該レースに対応し、更新時刻・取得時刻・公式出走情報と整合することを実際に確認する。発走前であることを時計で確認する。未確認のまま状態を書き換えない。
5. pre_race_record.prepareで52項目の推論とbalanced_A_v2配分を実行する（確率生成には従来のcorrected_v2_core.generate_combinationsを使用し、allocateのみ切替）。購入点数の上限・下限を固定しない。全馬連・3連複を候補とし、期待払戻Eと1点以上的中する確率Hを同時に評価する混合整数最適化。予算1万円、100円単位、各買い目が単独的中時に1万円以上払戻となる最低額を厳守。solverの解は近似であり大域最適保証なし。計算・検証失敗なら本番予想の完了扱いにせず、旧corrected V2やbalanced_A_v1へ黙ってフォールバックしない。publication.requestでGitHub保存要求を作る。content_sha256とtest_onlyはGitHub create_fileへの引数から除く。
6. 対象pathをfetch_fileして存在確認する。既存なら上書きせず確認済み事前記録を参照する。404で存在しなければcreate_fileする。commit_shaを取得し、fetch_file(ref=commit_sha)のcontentとfetch_commitのcreated_atを確認してpublication.confirmへ渡す。保存/確認/提示のいずれも発走12分前を超えたら事前予想の完了を宣言しない。
7. confirmのreceiptはpredictions/free52_receipts/<race_code>.jsonに新規保存する。記録本体を後から書き換えない。チャット用一覧とX投稿文を提示する。Xへ送信しない。test_onlyの記録にはX投稿文を作らない。

## 答え合わせ
事前記録とreceiptを読み、commit指定で同一内容を確認する。JRA公式の確定払戻と返還対象を取得する。無料補助ページのsettlement.parse_payoutsは未照合の候補として扱い、official_verified=trueを未確認で設定しない。settlement.settleのrecordとpublicationには保存済み本体とreceiptを渡し、結果をresults/free52/<race_code>.jsonへ新規保存する。test_onlyの記録は実戦成績から除外し、後付けの再予想はしない。

## 未接続・未検証
当日のJRA公式出走/取消情報の自動取得、発売中オッズの実証、公式払戻の自動取得、本番での期限内完走。手順の設定は運用完成の証拠ではない。対象時刻は現行15:30/15:40/15:45枠で、他の発走時刻の全重賞対応は未確認。

## 取得処理の接続更新
- source_bundle.acquire(race_code, official_entry_url)で当日の公式出馬表、無料出馬表、馬連・3連複全組合せオッズを取得する。official_entry_urlは実際のJRA出馬表リンクから解決し、チェックサム付きURLを推測しない。公式出馬表の過去ページを当日確認に使用しない。
- official_entries.match_free_entriesで馬番・騎手・調教師・馬体重を照合する。地方所属など公式IDがない場合は名前を厳密に照合する。取消をオッズ欠落だけで決めない。
- source_bundleのofficial_participationをfeature_pipeline.assembleのparticipation_snapshotへ渡す。entry_page、entry_retrieved_at、odds_snapshotsもそれぞれ後続処理へ渡す。脚質履歴と最新の過去履歴が別途必要。
- official_results.fetch_for_race(race_code)で公式重賞一覧から結果ページを選択し、GⅠ・GⅡ・GⅢの払戻と返還対象を取得する。対応ページが未公開・未対応なら未確定と報告する。
- 過去GⅡ18頭の公式出馬表照合とGⅠ/GⅡ/GⅢの公式結果取得を確認済み。source_bundleの当日発売中実行、実際の公式取消行、当日発走12分前の完走は未検証。

## 地方所属馬の前走補完
JRA結果履歴だけでは最新の地方出走が欠ける馬がある。local_previous.reference_from_jraで現在の公式出馬表の前走日・競馬場・着順・距離・馬体重を取得し、対応するNAR公式RaceMarkTableを検索で解決する。local_previous.resolveで照合して前走9項目を作り、feature_pipeline.assembleのprevious_overridesへ渡す。ネオトキオの大井ダート右回りは実データで一致し再計算を確認。結果URL自動解決、他の地方場、海外は未対応。地方IDをJRA馬IDとして使わない。最新の前走があるのに古いJRA前走を黙って採用しない。

## 前走9項目の公開情報取得更新
source_bundleが返すofficial_entry_pageからpublic_previous.acquireを呼ぶと、公式出馬表の実リンクを使ってJRA前走の9項目を取得できる。取得したevidenceをfeature_pipelineのprevious_overridesへ渡す。未解決馬は理由を確認し、地方はlocal_previousによる照合、海外・直線等の未対応項目は未解決として扱う。スワンS18頭ではJRA17頭とNAR大井1頭を公開情報から再作成し、前走の保存済み値を使わず全969組→13点10000円→GitHub保存確認→表示→公式収支計算を確認済み。確定オッズによる過去テストであり、source_bundleの発売中実行やpre_race_record.prepareの本番実行の証明ではない。前走結果取得に時間がかかった場合は出馬表/取消/オッズを再取得し、90秒制限を満たすまで古いsnapshotで公開しない。

## 残作業1～3の接続（2026-10-13）
1. 富士S14登録馬、秋華賞18登録馬の前走脚質と過去成績をprepare_upcomingで作成済み。登録段階なので枠・馬番・騎手・頭数・馬体重・発走時刻の未発表は保持する。騎手未発表時にjockey_priorの0を実績として使わず未確定にする。秋華賞の38/40/42個の非欠損値の差は、過去出走0に伴う正当な欠損率も含む。
2. entry_link_resolver.resolveが公式重賞一覧→レース案内→出馬表案内→実際のCNAME付きリンクをたどる。現在の2レースは公式案内から10月15日公開予定を自動確認。source_bundle.acquire(race_code)はこのresolverを使用する。未公開・別レース・曖昧なリンクでは予想を進めない。公開後の実物リンク取得は公開後に再確認する。
3. scheduled_preflightを新しい定期実行環境でテストする一回限りのタスクを設定した。設定したこととテスト成功は別。validation/scheduled_latest_preflight_20261013.jsonの実際の保存確認をもって結果を評価する。

非公開のJRA_preflight_bundle_20261013.zip（libfile_523561f810dc8191a5d491be95ae5902）には32頭の事前準備、過去テスト用の公式/無料出馬表と公開取得済み前走18頭、過去データ由来のpedigree_lookup.parquetを保存した。未来の実行で必要ならmaterializeし、fixtures/pedigree_lookup.parquetをfeature_pipelineのpedigree_pathsに追加する。出走情報は当日必ず更新し、準備済み登録馬を確定出走馬として使わない。ZIPや内部履歴を公開GitHubに載せない。

## 公式出馬表の公開後確認（2026-10-15）
公式重賞一覧から両レース案内をたどり、案内ページに直接公開されたaccessDリンクの取得に対応。富士S14頭、秋華賞17頭の公式出馬表を実際に取得して、馬ID・馬名・騎手・調教師・日付・開催・発走時刻を解析した。現時点は枠順発表前で枠・馬番・馬体重は空欄。official_entries.parse(..., preliminary=True)は準備段階専用でverified=Falseを返し、本番のparseは引き続き当日発走前の有効な馬番を要求する。過去テスト扱いに切り替えて未来の出馬表を本番確認済みとしない。登録18頭の秋華賞と現在の出馬表17頭を混同せず、当日は公式出馬表を再取得する。発売中オッズ、当日の馬体重・取消、発走12分前までの完走は未検証のまま。詳細はvalidation/official_entry_connection_20261015.json。
