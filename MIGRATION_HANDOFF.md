# 別PC・別セッションへの引き継ぎ（2026-09-19）

このファイルを新しいCodexセッションの最初に読ませてください。コードはGitHubにありますが、**人間が入力した補正DBはGitに含まれません**。完全に引き継ぐには「Git clone」と「補正DBの別経路でのコピー」の両方が必要です。

## 最優先で移すもの

| 種類 | 現PCでの場所 | Git管理 | 新PCでの扱い |
| --- | --- | --- | --- |
| コード・この文書 | `C:\Projects\python\road_speed_map` | あり | `https://github.com/shimat/road_speed_map.git` をclone |
| 手入力した補正・観測 | `data/overrides.sqlite3` | **なし** | SQLiteのバックアップを安全な私的経路でコピー。新PCの同じ相対パスに置く |
| 前処理済み道路 | `data/processed/`（約120 MiB） | なし | コピーすれば起動が早い。なければ前処理で再生成 |
| 北海道OSM原本 | `data/source/hokkaido-latest.osm.pbf`（約180 MiB） | なし | 任意。再ダウンロード可能 |
| JARTIC等の取得キャッシュ | `data/cache/`（約20 MiB） | なし | 任意。再取得可能 |

2026-09-19時点の補正DBには、速度補正 **307行**、道路構造観測 **249行** がある。多くは画面上で結合した道路区間を元セグメントへ一括保存した結果であり、行数は確認作業の回数ではない。DBには証拠URLやメモが含まれる可能性があるため、**公開GitHubリポジトリに追加しない**。`.gitignore` で除外している。

### 補正DBの安全な持ち出し

SQLiteはWALモードなので、アプリ稼働中に `.sqlite3` だけを単純コピーすると最新の変更が抜けるおそれがある。現PCでリポジトリを開き、次を実行して一貫したスナップショットを作る。出力先の `data/cache/` はGit対象外。

```powershell
uv run python -c "import sqlite3; s=sqlite3.connect('data/overrides.sqlite3'); d=sqlite3.connect('data/cache/overrides-migration.sqlite3'); s.backup(d); d.close(); s.close()"
```

**2026-09-19 07:27 JST時点のスナップショットは現PCに作成済み**で、上記307行・249行を確認した。この `data/cache/overrides-migration.sqlite3`（約254 KiB）をUSBメモリ等の私的な経路で新PCへ運び、新PCでは**アプリを起動する前に** `data/overrides.sqlite3` として配置する。既に新PCで補正を入力した場合は上書きせず、別途マージ方針を決めること。バックアップ後に旧PCで編集を続けた場合は、移行直前にもう一度バックアップする。GitHubにはこのスナップショットは存在しない。

## 新PCのセットアップ

Windows PowerShellを想定する。Python 3.11以上、Git、`uv` を用意する。GitHub認証は**`shimat` を使用し、`shima_sansan` は絶対に使わない**。push前に `gh auth status` と `gh api user --jq .login` で確認する。旧PCではGitHub CLIの有効アカウントが一時 `shima_sansan` になっていたため、`gh auth switch --hostname github.com --user shimat` で切り替えてからpushした。新PCでは認証状態を改めて確認すること。

```powershell
git clone https://github.com/shimat/road_speed_map.git
cd road_speed_map
uv sync --extra dev
```

上の補正DBを移す。前処理済みの `data/processed/` を移さない場合は、インターネット接続のある環境で次を実行する。Geofabrikの北海道PBFを取得し、JARTICデータとの対応付けも行うため時間がかかる。`--region "札幌市周辺"` で札幌のみ先に作ることもできる。

```powershell
uv run python scripts/prepare_regions.py
uv run streamlit run app.py
```

既定のローカルURLは `http://localhost:8501/`。MapLibre本体はunpkgのCDN、背景地図はOpenStreetMapのタイルからブラウザが取得するため、その接続も必要。前処理の更新が必要なときだけ `--refresh-pbf` / `--refresh-jartic` を使う。通常の再実行は既存PBF・抽出済みParquetを再利用する。

テスト：

```powershell
uv run python -m unittest discover -s tests
uv run ruff check .
```

## 何を作ったか・ユーザーの意図

目的は道路ごとの最高速度を、**根拠と確度を混同せず**可視化するPoC。現時点は札幌市周辺を主対象に、旭川市周辺・函館市周辺も前処理済み。将来は全国展開を視野に入れるが、タイトルに「札幌」は入れない。ユーザーはPythonとC#に習熟している。道路の太さや色、根拠表示の可読性、道路クリック後の操作速度を重視する。

データ優先順位はREADMEに詳しい。大筋は、(1)人間が標識を確認した速度補正、(2)JARTIC指定速度のOSM道路への自動対応、(3)OSMの数値 `maxspeed`、(4)人間が確認した道路構造からの法定速度候補、(5)OSMの道路構造・道路種別からの推定、(6)不明。**「データのみ」「知見を追加」「推定候補をレビュー」**は区別する。標識がある場合はその速度を補正できる。標識を確認できない場合は、中央線・車両通行帯・上下線分離の有無などを「観測事実」として記録し、30/60 km/hの法定速度候補を算出する。中央線があるように見えるだけで60 km/hと断定したり、生活道路の道路種別だけで30 km/hを確定扱いしたりしない。

JARTICの自動対応は道路位置・方向によるヒューリスティックで、原典値そのものとは異なる。並走道路や交差点で誤対応し得る。JARTIC原典線は検証用の別表示であり、通常表示では目立たせない。推定線は細く半透明、原典値・人間による補正は太く不透明。ただし薄すぎるとOSM背景に埋もれるため、現在は背景を淡くし、推定線を3px/60%、人間の道路構造観測線を4px/82%にしている。

## 実装の要所

| ファイル | 役割 |
| --- | --- |
| `app.py` | Streamlit UI、表示モード、データ読込、補正反映、PyDeckとMapLibreの切替 |
| `road_speed_map/config.py` | 地域範囲、色、凡例 |
| `scripts/prepare_regions.py` | Geofabrik PBF取得、道路抽出、JARTIC対応、Parquet生成 |
| `road_speed_map/osm.py`, `prepared.py` | OSM取得・解析、前処理済み道路の入出力 |
| `road_speed_map/jartic.py`, `matching.py` | JARTIC原典の取得・解析とOSM道路への自動対応 |
| `road_speed_map/speeds.py` | 根拠の優先順位と速度候補の算定 |
| `road_speed_map/display.py` | 連続区間の結合と表示用簡略化 |
| `road_speed_map/overrides.py` | SQLiteの速度補正・道路構造観測 |
| `road_speed_map/maplibre.py` | gzip GeoJSON生成、地図から来た編集のDB保存・削除 |
| `road_speed_map/map_component.py` | Streamlit Components v2 + MapLibre GL JS の高速編集地図 |
| `tests/` | コア処理とMapLibre側のPython処理のテスト |

札幌市周辺はサイドバーの「高速編集地図（試作）」が既定でON。道路クリックだけではStreamlitの再実行をせず、地図内の編集フォームを開く。保存・削除のときだけPythonに通知してDBを更新し、再描画する。結合した表示区間の編集は元の全セグメントに一括反映する。JARTIC原典線を表示するとき、または高速編集をOFFにすると、従来のPyDeck表示へ戻る。旭川・函館の高速編集は未対応。

編集フォームは、道路位置によって地図からはみ出さないよう**地図左上に固定**し、本文をスクロール可能にした。閉じる方法はフォーム内の「×」、地図の余白クリック、Esc。黒い縁取りは選択道路を示す。直近のUI修正（左上固定）はPythonテストと静的チェックは通っているが、**ユーザーによる実画面での最終確認はまだ受けていない**。次のセッションではまず小さい画面・下端の道路・長いメモでスクロールとボタン表示を確認する。

## 既知の制約・次の課題

- 速度の「確定」は標識等の実地証拠または原典の値を意味する。ただしJARTIC→OSMの自動対応は誤対応し得るので過信しない。
- OSM属性による30/60 km/hは推定候補。中央線や標識の有無をOSMだけで一律に確定できない。方向別・時間帯別規制、高速道路の車種別速度は単一線で表現しきれず「不明」にすることがある。
- ストリートビューから標識を自動検出する構想は未実装。画像利用規約や撮影時期、認識精度の検討が必要。
- 高速編集の保存ボタンから実DBへの一連の画面操作は、Python側の単体テスト（テンポラリDB）では確認済みだが、ブラウザでの長時間・大量編集の検証はまだ十分ではない。
- OSM原本を更新すると道路分割やセグメントIDが変わり、既存補正が対応しなくなる可能性がある。PBF更新前に補正DBをバックアップし、再対応の要否を確認すること。
- 札幌市周辺でも初回の道路読込・結合・ブラウザ転送には時間がかかる。クリック時の無駄なStreamlit再実行だけを先に解消した。全国規模はベクトルタイル等の別構成を検討する。

## 2026-09-19時点の検証とGit

- `main` の直前の機能コミットは `97a89f6 Add fast MapLibre road editing prototype`。
- その試作に対して `python -m unittest discover -s tests` は全32件成功、Ruffも成功。
- この文書の作成前は作業ツリーがクリーン。GitHubの送信先は `https://github.com/shimat/road_speed_map.git`。
- 別PCでpushするときも、認証ユーザー `shimat` と送信先の両方を毎回確認する。旧PCではデフォルトのGit credential helperが別アカウントを使う恐れがあったため、機能コミットのpush時にはコマンド単位で `gh auth git-credential` を指定した。認証トークンをコード・文書・ログへ貼らない。

新しいセッションへの依頼例：`MIGRATION_HANDOFF.md と README.md を読んで、data/overrides.sqlite3 があるか、テストが通るか確認してください。その後、編集フォームのスクロールと保存動作を実画面で検証してください。GitHub操作は shimat のみを使ってください。`
