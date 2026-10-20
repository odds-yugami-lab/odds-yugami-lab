# 無料予想の実行手順（2026-10-20更新）

追加料金なし。モデル・履歴は非公開。2026-10-18以降の本番買い目配分は balanced_A_v3（最低必要額・実オッズ方式）。旧corrected V2と試作balanced A v1/v2は保存・区別する。

## クラウド一括実行（2026-10-20・現行）

下記の過去の個別手順を手作業でつなぎ直さず、一括実行を入口にする。
1. 対象ブランチの先頭commitを確定し、`development/free_web/` 直下の全Pythonと `connector_bridge.js` を同じcommitから取得する。モデルZIP・履歴ZIPはLibraryの最新バージョンを取得・展開する。モデル依存に加えてSciPyの `milp` が必要。ユーザーのPCは使用しない。
2. JRA公式の当日平地GⅠ/GⅡ/GⅢ一覧と正式発走時刻を確認。予約は14:55（15:35以前）、15:05（15:36～15:42）、15:10（15:43以降）に分担し、正確な発走時刻で振り分ける。対象なしと公式で確認できたときだけ通知を省略する。15:45という予約名だけで15:40のレースを重複処理しない。
3. `connector_bridge.js` は `new Function('tools', source)(tools)` でロードし、返された `.run({cmd,workdir})` を実行する。`cmd` は `python3 -u operation_runner.py live --race <16桁> --window <00:00-15:35|15:36-15:42|15:43-23:59> --model-dir <モデル展開先> --history-dir <履歴展開先> --output <ローカル結果JSON>`。必要な既知血統の照合資料は非公開の `--pedigree <parquet>` で指定する。コードや設定の取得だけで実行成功としない。
4. `live_pipeline` は履歴SHA256、更新対象の開催日欠落、公開前走の全頭照合、当日正式出走と全発売中オッズ、52項目、配分、計算終了時点の鮮度を確認する。非開催日の空白は公式月別カレンダーJSONで確認し、平日だから非開催と決めつけない。履歴が実開催日分不足していたら停止し、無断でcoverageを書き進めない。
5. `operation_runner.GitHub` が同一固定ブランチの完全なtreeで存在確認し、新規保存または同一原本の再利用を行う。コミット/ブランチの本文・blob SHA・祖先関係・サーバー時刻を照合する。原本とreceiptの両方の保存を終えた後にだけチャット一覧・X草稿を返す。既存原本がある再実行では再推論・上書きをしない。締切は原本・receipt・表示のすべて発走12分前まで。
6. `connector_bridge` で `python3 -u operation_runner.py settle --race <16桁> --output <ローカル結果JSON>` を実行する。公式払戻を実取得し、保存された原本とreceiptを認証して仮想収支を `results/free52` に保存・読み戻す。実購入の有無は予想成績の計算条件ではない。X送信・馬券購入はしない。
7. 失敗時はローカル結果JSONに工程・エラー・未完了を記録し、GitHubが利用できれば `incidents/operation_runs/<日付>/` に新規保存して照合する。エラーログ保存に失敗した場合も隠さない。未保存・締切超過を「公開完了」と通知しない。

過去テストは `--test-only --run-id <一意名>` で `publication_tests` 配下にだけ保存し、X草稿は返さず本番成績にも入れない。`test_operation_runner.py` は保存失敗・期限・再実行・改変拒否を検証する。10月20日の実GitHub往復テストは `publication_tests/repair_20261020/`、要約は `validation/operation_repair_20261020.json`。

## balanced_A_v3 最低必要額・実オッズ選別方式（2026-10-18以降）
- `development/free_web/balanced_A_v3.py` が選定・配分プログラム。`pre_race_record.py` は v3 の `allocate_balanced` を使用し、確率生成は変更しない。旧 `balanced_A_v1.py`、`balanced_A_v2.py`、`corrected_v2_core.py` は過去方式として不変。
- まず実際に取得した全馬連・全3連複のオッズとAI的中確率を掛け、**期待回収倍率=ai_probability×decimal_odds** を算出。評価用の50倍等のオッズ上限は一切設けない。
- 候補となる全買い目について、選択時の購入額を厳密に **ceil(10000/(100×decimal_odds))×100円（最低100円）** に固定する。100倍以上の全買い目は選択されても100円のみとし、同じ馬券への追加投資は禁止。
- 買い目数と馬連・3連複の比率に固定上限・下限を設けない。購入したい券の期待払戻評価Eと、購入馬券のどれかが当たるモデル確率Hの双方を使い、整数最適化で選定する。重複する馬連・3連複の同時的中はHで重複計上しない。複数の重みからE×H比で選び、真の大域最適性は保証しない。
- 仮想予算は毎回合計10,000円、100円単位。選択された各券の単独的中時払戻は10,000円以上。毎券の追加投資=0円を計算結果で検証し、選定額合計が10,000円に一致しない場合はエラーで停止する。
- 「最低額のみ」という原則と「合計1万円」を両立できない入力のとき、暗黙に追加投資したり旧A方式で上書きせず、計算不能として理由を報告する。今後の例外規則は事前承認の上で別バージョンにする。
- schema_version=5、allocation_rule=balanced_A_v3、allocation_core_sha256、最低額のみの確認、実オッズによる期待払戻、重複調整済み的中確率、solver情報を発走前原本に記録する。
- 発売中全オッズ・正式出走情報・発走12分前までのGitHubコミットとreceipt保存は本番で別途検証する。GitHub Actionsの過去2戦は**確定オッズによる事後検証**であり、実戦成績と混ぜない。2026-10-17富士Sほか旧方式の予測・結果・receiptは変更しない。

## GitHub保存先・検証・障害時の手順（2026-10-17追記）
- free52の現在の検証・実行記録が保存されているブランチは `dev/free-windows-probe-20261011`。事前記録・receipt・結果記録は同一ブランチで読み書きし、`main` の404を「事前記録なし」と解釈しない。ブランチは処理前に明示して固定し、GitHub API呼び出し時に `branch` / `ref` を指定する。
- 事前記録 `predictions/free52/<race_code>.json` とreceipt `predictions/free52_receipts/<race_code>.json` は新規保存のみ。保存前に対象ブランチで存在確認を行い、既存ファイルは変更しない。結果記録 `results/free52/<race_code>.json` も同じrace_codeが既存なら内容を読んで照合し、二重計上しない。
- 書き込み応答のcommit SHAを受け取るだけでは成功とみなさない。(1)対象ブランチからfetch_fileできる、(2)commit指定で同じ内容を取得できる、(3)期待した本文またはハッシュと一致する、(4)そのコミットが対象ブランチの履歴に存在する、を確認してから「保存済み」と表示する。事前予測は発走前時刻の検証も別途必須。
- 403/404/409/422等の応答、書き込み確認不一致、タイムアウト、権限失効はエラー種別・操作・パス・ブランチを報告する。再試行前に必ず存在確認・ハッシュ照合を行い、同じ結果を重複登録しない。失敗時は結果を別ファイルとして手元に退避し「GitHub未保存」と明記する。発走後に事前記録を新規作成・改変しない。
- `main` と開発ブランチは2026-10-17時点で履歴が分岐している。無確認でのforce push、mainへのref書き換え、自動マージをしない。移行が必要なら両方の変更を確認し、適切なレビューと安全なマージ方法を選ぶ。
- モデル識別子・事前予想commit・receipt・公式確認状況・実購入確認状況を結果に保持し、旧方式/新free52方式と仮想/実購入成績を混ぜない。

## X公開ゲートと事後復旧（2026-10-18運用補強）
- 予測算出とGitHubへの事前保存は別工程。Work/チャットでの予想確定、X投稿、GitHub API書込要求は、GitHubの事前保存成功を意味しない。対象ブランチに当該レースの `predictions/free52/<race_code>.json` と `predictions/free52_receipts/<race_code>.json` が両方存在し、commit指定/branch指定の読戻し・内容一致・期限内コミット・祖先関係を確認するまで、GitHub事前公開済みや本番記録確定と表示しない。
- `publication.confirm(...)` は今後X文面を返さない（3番目はNone）。receiptをcanonical JSONでGitHubにcommitし、対象ブランチとreceipt commitそれぞれから完全一致の本文を取得、コミットが対象ブランチの履歴に存在することを確認した後、`publication.x_draft_after_receipt(...)` のゲートを通過した場合だけX草案を表示する。GitHub上に両ファイルがあっても期限を超過していたら本番予測として認定しない。
- 2026-10-20にChatGPTクラウド用の `operation_runner.py` と `connector_bridge.js` を追加。一括処理の過去テストはGitHub保存・receipt・読み戻し・公式収支まで通過した。GitHub Actionsの回顧的検証ジョブは本番予測ジョブではない。発売中データを用いる本番での期限内完走は、次回レースで別に確認する。
- 期限内のGitHub保存・receiptが欠けたまま発走した場合、事前原本を遡及して作成しない。旧原本・旧receipt・旧収支を変更しない。 `development/free_web/incidents/<race_code>.json` に「事後インシデント」として時刻のある外部証拠、判明した確定結果、欠損、未検証事項を記す。原本が完全に復元できた場合も元の事前予測ではなく証拠付復元記録として別管理し、本番回収率への算入は既定の保存期限条件を満たすことを独立検証した場合に限る。
- 2026-10-18 秋華賞 `2026101808040711`：15:19:52 JSTの発走前予想は別作業環境の記録要約にあり、ユーザーはX投稿・馬連的中を報告。上記GitHub事前原本/receiptは発走後の監査時に欠損。その後ユーザーから元の30点を取得し、仮想払戻11,200円・利益1,200円・回収率112%を `incidents/2026101808040711_recovered_settlement.json` に別保存済み。発走前GitHub原本・receiptの存在は未確認のままであり、遡及原本は作成しない。公式着順・配当はJRA公式で検証済み。詳細は `incidents/2026101808040711.json` に保存。事前予測の事実まで「存在しない」と断定しない。

## 予想
1. LibraryのJRA_free_model_52_20261013.zip、JRA_free_history_20261012.zipを取得・展開する。coverage_manifest.jsonの履歴更新日を確認し、開催が追加された場合は無料結果と確定出走情報からhistory_bridgeで履歴を追記する。元のファイルは上書きしない。更新した履歴は同じLibraryファイルの新しいバージョンとして保存する。
2. 無料の当日出馬表と、JRA公式で確認した全頭の出走/取消/除外情報を取得する。出馬表の****や馬体重未発表だけで取消を推定しない。entry_changesの完全なhorse_statusesを作る。確認できなければverified=trueを設定しない。
3. 前走通過順位から取得した脚質を出典付きで準備する。feature_pipeline.assembleを実行し、prediction_ready=trueであることを確認する。新しい騎手・取消に合わせて過去成績を再計算する。
4. 馬連・3連複全組合せをodds.parseで取得する。この関数だけではverified_liveにならない。取得ページが発売中で当該レースに対応し、更新時刻・取得時刻・公式出走情報と整合することを実際に確認する。発走前であることを時計で確認する。未確認のまま状態を書き換えない。
5. pre_race_record.prepareで52項目の推論とbalanced_A_v3配分を実行する（確率生成には従来のcorrected_v2_core.generate_combinationsを使用し、allocateのみ切替）。購入点数の上限・下限を固定しない。全馬連・3連複を候補とし、期待払戻Eと1点以上的中する確率Hを同時に評価する混合整数最適化。予算1万円、100円単位、各買い目が単独的中時に1万円以上払戻となる最低額を厳守。solverの解は近似であり大域最適保証なし。計算・検証失敗なら本番予想の完了扱いにせず、旧corrected V2やbalanced_A_v1/v2へ黙ってフォールバックしない。publication.requestでGitHub保存要求を作る。content_sha256とtest_onlyはGitHub create_fileへの引数から除く。
6. 対象pathをfetch_fileして存在確認する。既存なら上書きせず確認済み事前記録を参照する。404で存在しなければcreate_fileする。commit_shaを取得し、fetch_file(ref=commit_sha)のcontentとfetch_commitのcreated_atを確認してpublication.confirmへ渡す。保存/確認/提示のいずれも発走12分前を超えたら事前予想の完了を宣言しない。
7. confirmのreceiptはpredictions/free52_receipts/<race_code>.jsonに新規保存する。記録本体を後から書き換えない。チャット用一覧とX投稿文を提示する。Xへ送信しない。test_onlyの記録にはX投稿文を作らない。

## 答え合わせ
事前記録とreceiptを読み、commit指定で同一内容を確認する。JRA公式の確定払戻と返還対象を取得する。無料補助ページのsettlement.parse_payoutsは未照合の候補として扱い、official_verified=trueを未確認で設定しない。settlement.settleのrecordとpublicationには保存済み本体とreceiptを渡し、結果をresults/free52/<race_code>.jsonへ新規保存する。test_onlyの記録は実戦成績から除外し、後付けの再予想はしない。

## 未接続・未検証
取得・モデル計算・保存・receipt・表示・公式収支は一括処理へ接続済み。未検証は、実際の当日取消表示、発売中オッズを使った自動実行、締切までの本番完走。手順や予約の設定だけでは完走の証拠にしない。地方・海外・直線等の前走未解決は引き続き停止理由であり、推測・古い前走への代替をしない。

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

