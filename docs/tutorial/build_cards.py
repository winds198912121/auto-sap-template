#!/usr/bin/env python3
"""Generate the image version of the tutorial (docs/tutorial/cards/*.png).

Each card is one A4-portrait page rendered from HTML by headless Chrome, so the
whole image set can be regenerated after any UI change:

    python3 docs/tutorial/build_cards.py

Requirements: Google Chrome (or Chromium) + the screenshots in
docs/tutorial/screenshots/ (captured from the running console).
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
HERE = Path(__file__).resolve().parent
CARDS_DIR = HERE / "cards"
W, H = 1240, 1754  # A4 portrait @ ~150dpi

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    shutil.which("google-chrome") or "",
    shutil.which("chromium") or "",
]

CSS = """
@page { size: %(W)dpx %(H)dpx; margin: 0; }
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{width:%(W)dpx;height:%(H)dpx;background:#fff;color:#0f1c2e;
  font:20px/1.62 -apple-system,"Hiragino Sans","Hiragino Kaku Gothic ProN","Yu Gothic",sans-serif}
.page{padding:56px 64px 44px;display:flex;flex-direction:column;height:%(H)dpx}
.top{display:flex;align-items:center;gap:14px;border-bottom:3px solid #1e3a5f;padding-bottom:12px}
.brand{font-weight:800;letter-spacing:.06em;color:#1e3a5f;font-size:21px}
.pill{font-size:15px;padding:3px 12px;border-radius:99px;background:#eaf0f8;color:#2456a6;font-weight:700}
.pill.mock{background:#0e6b3a;color:#fff}
.kicker{margin-top:26px;font-size:19px;font-weight:800;color:#2456a6;letter-spacing:.04em}
h1{margin:6px 0 4px;font-size:41px;line-height:1.24;color:#1e3a5f}
h2{margin:22px 0 8px;font-size:24px;color:#1e3a5f}
p{margin:8px 0}
.lead{font-size:21px;color:#33465c}
ul,ol{margin:8px 0 8px 26px;padding:0}
li{margin:7px 0}
b,strong{color:#1e3a5f}
code,.mono{font-family:Menlo,Consolas,monospace}
code{background:#eef3fa;border:1px solid #dbe3ec;border-radius:6px;padding:1px 7px;font-size:18px}
pre{background:#0f1c2e;color:#cfe3ff;border-radius:14px;padding:18px 22px;margin:10px 0;
  font:17px/1.55 Menlo,Consolas,monospace;white-space:pre-wrap;word-break:break-word}
pre .c{color:#8fe3a8}
pre .d{color:#ffd98a}
.shot{width:100%%;border:1px solid #c9d4e0;border-radius:14px;display:block;margin:10px 0}
.shotcap{font-size:16px;color:#64748b;margin:-4px 0 6px}
.row{display:flex;gap:20px;align-items:flex-start}
.col{flex:1;min-width:0}
table{border-collapse:collapse;width:100%%;font-size:18px;margin:8px 0}
th,td{border-bottom:1px solid #dbe3ec;padding:7px 9px;text-align:left;vertical-align:top}
th{background:#f7fafd;color:#52637a;font-size:17px}
.box{background:#f7fafd;border:1px solid #dbe3ec;border-left:6px solid #2456a6;border-radius:12px;padding:14px 18px;margin:12px 0}
.box.warn{background:#fffaf0;border-left-color:#b7791f}
.box.safe{background:#f2fbf5;border-left-color:#1b7f3b}
.st{font-weight:800;padding:2px 9px;border-radius:6px;font-size:15px;color:#fff;white-space:nowrap}
.CREATE{background:#1d7a8a}.UPDATE{background:#0e6b8a}.SKIP{background:#64748b}
.CONFLICT{background:#c0392b}.BLOCKED{background:#6d3b9e}.ERROR{background:#b91c1c}
.SUCCESS{background:#1b7f3b}.RETRYING{background:#b7791f}.FAILED{background:#c0392b}
.foot{margin-top:auto;padding-top:14px;border-top:1px solid #dbe3ec;display:flex;
  font-size:16px;color:#64748b;gap:14px;align-items:center}
.foot .grow{flex:1}
.cover{justify-content:center;text-align:left}
.cover h1{font-size:56px;line-height:1.18}
.cover .sub{font-size:23px;color:#33465c;margin-top:10px}
""" % dict(W=W, H=H)


def page(card: dict, idx: int, total: int) -> str:
    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"/>
<style>{CSS}</style></head><body><div class="page {card.get('cls','')}">
  <div class="top">
    <span class="brand">🖥️ SAP Config Automation</span>
    <span class="pill mock">MOCK のみ・実システム非接続</span>
    <span style="flex:1"></span>
    <span class="pill">Phase 1 · Plan + Mock</span>
  </div>
  <div class="kicker">{card['kicker']}</div>
  <h1>{card['title']}</h1>
  {card['body']}
  <div class="foot">
    <span>auto-sap-template 使い方ガイド（画像版）</span>
    <span class="grow"></span>
    <span class="mono">winds198912121/auto-sap-template</span>
    <span class="mono">P{idx:02d} / {total:02d}</span>
  </div>
</div></body></html>"""


CARDS: list[dict] = [
    # ---------------------------------------------------------------- cover
    dict(slug="00_cover", cls="cover", kicker="USAGE GUIDE · 画像版（全 13 枚）", title="SAP GUI 設定自動化<br/>auto-sap-template 使い方ガイド",
         body="""
<p class="sub">業務テンプレート（YAML 2 ファイル）を書くだけで、<br/>
<b>検証 → 依存解決 → Plan diff → 承認 → Mock SAP GUI で適用 → 読み戻し検証 → レポート</b><br/>
までを 1 本のパイプラインで実行します。</p>
<img class="shot" src="../flow.png" alt="flow"/>
<p class="lead" style="margin-top:6px">テキスト版は <code>docs/TUTORIAL.md</code>、画像 1 枚 = 1 ステップの早見表はこのカード群です。</p>
"""),

    # ---------------------------------------------------------------- 1 全体像
    dict(slug="01_overview", kicker="1 · 全体像", title="5 分でわかる仕組み",
         body="""
<img class="shot" src="../flow.png" alt="flow"/>
<table>
<tr><th>段階</th><th>やること</th><th>実際の担当</th></tr>
<tr><td>① テンプレート</td><td>顧客変数 + 設定ステップ（YAML）を書く</td><td><code>templates/*.yaml</code></td></tr>
<tr><td>② 検証</td><td>JSON Schema + 意味チェック（認証情報・SQL・GUI コントロール ID 禁止）</td><td><code>sapcfg/load.py</code></td></tr>
<tr><td>③ Plan（読み取り専用）</td><td>依存 DAG → トポロジカル順 → 現状と diff</td><td><code>sapcfg/planner.py</code></td></tr>
<tr><td>④ 承認</td><td>項目ごとに人がチェック（上書き系は必須）</td><td>コンソール / CLI</td></tr>
<tr><td>⑤ 適用（Mock）</td><td>疑似 SAP GUI を画面操作 → エラー分類 → 限定リトライ → 読み戻し検証</td><td><code>sapcfg/orchestrator.py</code></td></tr>
<tr><td>⑥ 証跡・レポート</td><td>plan.json / events.jsonl / run.sqlite / evidence/*.svg / report.md</td><td><code>sapcfg/store.py</code></td></tr>
</table>
<div class="box safe"><b>この Phase 1 は実 SAP に一切接続しません。</b> 適用先はプロセス内の Mock SAP GUI のみ。
実 GUI Scripting アダプタは Windows 専用で、macOS では import すらできません。</div>
"""),

    # ---------------------------------------------------------------- 2 準備
    dict(slug="02_install", kicker="2 · 準備", title="インストールと疎通確認（3 コマンド）",
         body="""
<p><b>必要な環境</b>: macOS / Linux / Windows · Python 3.11 以上 · <code>uv</code>（無くても pip で可）</p>
<pre><span class="c">$</span> git clone https://github.com/winds198912121/auto-sap-template.git
<span class="c">$</span> cd auto-sap-template
<span class="c">$</span> uv sync                     <span class="d"># PyYAML + jsonschema のみ（軽量）</span>
<span class="c">$</span> uv run python -m unittest discover -s tests
..........................................................
----------------------------------------------------------------------
Ran 26 tests in 1.4s

OK</pre>
<table>
<tr><th>ディレクトリ</th><th>中身</th></tr>
<tr><td><code>schema/</code></td><td>テンプレート構造の JSON Schema（顧客変数 / 設定ステップ）</td></tr>
<tr><td><code>templates/</code></td><td>サンプル業務テンプレート（OB13 / OB29 / OBY6 / OX02 / OX10）</td></tr>
<tr><td><code>sapcfg/</code></td><td>本体ライブラリ（load / planner / orchestrator / verify / store / gui）</td></tr>
<tr><td><code>webui/</code></td><td>可視化コンソール（localhost:8912・Mock 専用）</td></tr>
<tr><td><code>run.py</code></td><td>CLI（plan / apply / report / demo）</td></tr>
</table>
<div class="box"><b>テストが通れば環境は完成。</b> ここまでで実 SAP への接続設定は一切不要です。</div>
"""),

    # ---------------------------------------------------------------- 3 起動
    dict(slug="03_console", kicker="3 · 起動", title="コンソールを開いて 60 秒で 1 周する",
         body="""
<pre><span class="c">$</span> uv run python webui/server.py --port 8912
   →  ブラウザで http://localhost:8912</pre>
<img class="shot" src="../screenshots/01_overview.png" alt="overview"/>
<p class="shotcap">① 概要タブ：左メニューが 1→7 の順序そのもの。シナリオ切替（clean / 競合 / リトライ / 権限 / 未知エラー）もここ。</p>
<div class="box"><b>60 秒クイックスタート</b>
<ol style="margin-top:6px">
<li>左メニュー <b>3 テンプレート</b> → 2 ファイルを選び「読み込み &amp; 検証」</li>
<li><b>4 プラン</b> → 「⚙ プラン生成」で diff を確認</li>
<li>承認が必要な項目にチェック + 下の同意チェックを ON</li>
<li>「▶ 適用実行（MOCK）」→ 疑似 SAP GUI とイベントログをライブで観察</li>
<li><b>6 レポート</b> を開く</li>
</ol></div>
"""),

    # ---------------------------------------------------------------- 4 検証
    dict(slug="04_validate", kicker="4 · コンソール：検証", title="テンプレート読込 & スキーマ検証",
         body="""
<img class="shot" src="../screenshots/03_template.png" alt="template"/>
<p class="shotcap">② テンプレート &amp; スキーマ：検証 PASS、解決済み変数、5 件の設定項目が表示される。</p>
<ul>
<li><b>status: PASS</b> = JSON Schema（構造）+ 意味チェック（禁止事項）を通過</li>
<li>変数 <code>{{chart_of_accounts}}</code> などは <b>Plan 生成時に解決</b>される</li>
<li>テンプレートを間違えると（変数ファイルとステップファイルの取り違え等）ここで止まる</li>
</ul>
<div class="box warn"><b>テンプレートに書いてはいけないもの</b>（Schema が拒否）
認証情報 / パスワード · 生 SQL · SAP GUI のコントロール ID。
書けるのは<b>業務意図</b>と<b>意味的なパラメータ</b>だけです。</div>
"""),

    # ---------------------------------------------------------------- 5 プラン
    dict(slug="05_plan", kicker="5 · コンソール：Plan", title="差分（diff）の読み方",
         body="""
<img class="shot" src="../screenshots/04_plan.png" alt="plan"/>
<p class="shotcap">③ プラン：依存グラフ・実行順序・ステータス・理由・承認要否が並ぶ。SAP 側は読むだけ（書き込みなし）。</p>
<table>
<tr><th>状態</th><th>意味</th><th>既定の扱い</th></tr>
<tr><td><span class="st CREATE">CREATE</span></td><td>SAP に存在しない → 新規作成</td><td>実行</td></tr>
<tr><td><span class="st UPDATE">UPDATE</span></td><td>存在するが値が違う</td><td>要承認（上書き）</td></tr>
<tr><td><span class="st SKIP">SKIP</span></td><td>既に一致（冪等）</td><td>何もしない</td></tr>
<tr><td><span class="st CONFLICT">CONFLICT</span></td><td>既存値がテンプレートと矛盾</td><td>明示 override が無い限り停止</td></tr>
<tr><td><span class="st BLOCKED">BLOCKED</span></td><td>依存が失敗/未承認</td><td>実行しない</td></tr>
<tr><td><span class="st ERROR">ERROR</span></td><td>検証・依存解決に失敗</td><td>実行しない</td></tr>
</table>
<p>結果は <code>runs/&lt;run_id&gt;/plan.json</code> に保存され、同じ plan に対してのみ適用できます。</p>
"""),

    # ---------------------------------------------------------------- 6 承認
    dict(slug="06_approval", kicker="6 · コンソール：承認ゲート", title="人の承認が無い限り 1 ステップも動かない",
         body="""
<img class="shot" src="../screenshots/05_gate.png" alt="gate"/>
<p class="shotcap">④ 適用ゲート：希望値と現在値を並べて確認 → チェック → 同意 → 実行。</p>
<ul>
<li><code>human_approval: true</code> の項目（例：OX02 会社コード→会社の割当）は<b>必ず承認待ち</b>になる</li>
<li>上書き（UPDATE / CONFLICT）も同様に承認が要る</li>
<li>同意チェック（「mock SAP のみに対する実行であることを理解しています」）が OFF の間は実行ボタンが押せない</li>
<li>未承認のまま適用すると、その項目だけ <b>ヒューマンキュー行き</b>（他は実行される）</li>
</ul>
<pre><span class="d"># CLI で承認する場合</span>
uv run python run.py apply --run &lt;run_id&gt; --approve assign_cc_company
uv run python run.py apply --run &lt;run_id&gt; --approve-all</pre>
"""),

    # ---------------------------------------------------------------- 7 適用
    dict(slug="07_apply", kicker="7 · コンソール：適用", title="Mock SAP GUI を操作して、読み戻して検証する",
         body="""
<img class="shot" src="../screenshots/06_run_live.png" alt="run"/>
<p class="shotcap">⑤ 適用：左に疑似 SAP GUI 画面、右にイベントログ。全画面が SVG 証跡として保存される。</p>
<table>
<tr><th>動作</th><th>内容</th></tr>
<tr><td>対象再確認</td><td>各ステップ直前に S4D/100 を再チェック（不一致なら ABORTED）</td></tr>
<tr><td>エラー分類</td><td>メッセージ → LOCK / TRANSIENT / NAVIGATION / PERMISSION / INPUT / …</td></tr>
<tr><td>限定リトライ</td><td>LOCK・TRANSIENT・NAVIGATION のみ最大 2 回（下の例は 1 回で回復）</td></tr>
<tr><td>読み戻し検証</td><td>保存後に再読込して期待値と比較（eq / neq / contains / in / regex）</td></tr>
</table>
<div class="row">
  <div class="col"><img class="shot" src="../evidence_oby6.png" alt="oby6"/></div>
  <div class="col"><img class="shot" src="../evidence_ox10.png" alt="ox10"/></div>
</div>
<p class="shotcap">証跡に残る画面キャプチャ（OBY6 / OX10）。<code>[LOCK] Table E071K is locked…</code> → リトライ → SUCCESS（attempts=2, verified=1）。</p>
"""),

    # ---------------------------------------------------------------- 8 レポート
    dict(slug="08_report", kicker="8 · コンソール：レポート", title="レポートと実行フォルダ（監査証跡）",
         body="""
<img class="shot" src="../screenshots/08_report.png" alt="report"/>
<p class="shotcap">⑥ レポート：プラン集計・ステップ結果・エラー分類・PoC 指標が Markdown で出る。</p>
<pre>runs/&lt;run_id&gt;/
├── plan.json      <span class="d">プラン diff（どの run でも再確認可能）</span>
├── events.jsonl   <span class="d">全イベントの追記型監査ログ（入力/操作/画面/メッセージ/リトライ/結果）</span>
├── run.sqlite     <span class="d">ステップ単位の状態（再実行時は SUCCESS をスキップ）</span>
├── evidence/*.svg <span class="d">画面証跡（1 操作 1 枚）</span>
└── report.md      <span class="d">Markdown レポート</span></pre>
<table>
<tr><th>PoC 指標</th><th>例（サンプル実行）</th></tr>
<tr><td>読み戻し検証カバレッジ</td><td>5/5 = 100%</td></tr>
<tr><td>初回成功</td><td>4/5 = 80%（1 件はロックで 1 回リトライ）</td></tr>
<tr><td>冪等性</td><td>再実行で全 SKIP（SAP 側を変更しない）</td></tr>
</table>
"""),

    # ---------------------------------------------------------------- 9 CLI
    dict(slug="09_cli", kicker="9 · CLI", title="コンソールと同じ流れをコマンドで",
         body="""
<pre><span class="c">$</span> uv run python run.py plan
loading bundle: example_customer_vars.yaml + example_config_steps.yaml
plan written: runs/20260912-074149-b89f2e/plan.json

[+] # 1 coa_jp             CREATE    no existing entry in SAP
[+] # 2 fv_jp              CREATE    no existing entry in SAP
[+] # 3 cc_jp01            CREATE    no existing entry in SAP
[+] # 4 assign_cc_company  CREATE    no existing entry in SAP  (requires approval)
[+] # 5 plant_jp10         CREATE    no existing entry in SAP

[plan mode complete - nothing was modified in SAP (mock read-only)]

<span class="c">$</span> uv run python run.py apply --run 20260912-074149-b89f2e \
                              --approve assign_cc_company
step states: coa_jp=SUCCESS, fv_jp=SUCCESS, cc_jp01=SUCCESS,
             assign_cc_company=SUCCESS, plant_jp10=SUCCESS

<span class="c">$</span> uv run python run.py report --run 20260912-074149-b89f2e   <span class="d"># Markdown を stdout へ</span>

<span class="c">$</span> uv run python run.py demo    <span class="d"># 障害を注入した end-to-end（ロック→リトライ→検証）</span></pre>
<table>
<tr><th>コマンド</th><th>用途</th></tr>
<tr><td><code>plan</code></td><td>検証 + 依存解決 + diff（読み取り専用）</td></tr>
<tr><td><code>apply --run &lt;id&gt;</code></td><td>既存プランに対する承認付き適用（Mock のみ）</td></tr>
<tr><td><code>report --run &lt;id&gt;</code></td><td>Markdown レポート出力</td></tr>
<tr><td><code>demo</code></td><td>障害注入つき通しデモ（動作確認に最適）</td></tr>
</table>
"""),

    # ---------------------------------------------------------------- 10 自作テンプレート
    dict(slug="10_my_template", kicker="10 · 自作テンプレート", title="自分の案件テンプレートを作る",
         body="""
<p>必要なのは <b>YAML 2 ファイル</b>だけ。<code>templates/example_*.yaml</code> をコピーして値を差し替えます。</p>
<pre><span class="d"># ① 顧客変数（案件ごとに変える値だけ）</span>  templates/my_customer_vars.yaml
template_id: MY_PROJECT_BASE
customer: CUSTOMER_B
target: {environment: DEV, sap_system: S4D, client: "100", language: JA}
variables:
  company_code: JP02
  chart_of_accounts: YCOA
  fiscal_year_variant: K4
  plant: JP20

<span class="d"># ② 設定ステップ（業務意図・依存関係・検証スコープ）</span>  templates/my_config_steps.yaml
config_items:
  - id: cc_jp02
    kind: company_code_global_params
    title: "会社コード JP02 基本データ (OBY6)"
    transaction: OBY6
    depends_on: [coa_jp, fv_jp]
    params:
      company_code: "{{company_code}}"
      chart_of_accounts: "{{chart_of_accounts}}"
    on_existing: require_match      <span class="d"># skip_if_match / require_match</span>
    verify: {scope: [company_name, currency, chart_of_accounts]}</pre>
<ul>
<li>新規トランザクションを足すときは <code>sapcfg/steps/</code> に画面カタログ + ハンドラを追加（設計書 §4.3）</li>
<li>まず <code>plan</code> だけ流して diff を確認 → 問題なければ承認して適用、が安全な進め方</li>
</ul>
"""),

    # ---------------------------------------------------------------- 11 エラーと復旧
    dict(slug="11_errors", kicker="11 · エラー分類と復旧", title="どこまで自動で直すか",
         body="""
<table>
<tr><th>分類</th><th>例</th><th>動作</th><th>リスク</th></tr>
<tr><td><b>LOCK</b></td><td>オブジェクトが他ユーザにロック</td><td>最大 2 回リトライ</td><td>低</td></tr>
<tr><td><b>TRANSIENT</b></td><td>GUI タイムアウト・一時切断</td><td>最大 2 回リトライ</td><td>低</td></tr>
<tr><td><b>NAVIGATION</b></td><td>想定外の初期画面復帰</td><td>最大 2 回リトライ</td><td>低</td></tr>
<tr><td><b>ALREADY_EXISTS</b></td><td>既に作成済み</td><td>読み戻して比較（skip / conflict）</td><td>低</td></tr>
<tr><td><b>INPUT</b></td><td>桁数・書式・ドメイン違反</td><td>リトライせず人へ</td><td>中</td></tr>
<tr><td><b>PERMISSION</b></td><td>権限不足（SU53）</td><td>リトライせず人へ</td><td>高</td></tr>
<tr><td><b>BUSINESS_CONFLICT</b></td><td>既存値がテンプレートと矛盾</td><td>リトライせず人へ</td><td>高</td></tr>
<tr><td><b>UNKNOWN</b></td><td>未知のメッセージ</td><td>停止 → 人が承認（Error KB へ提案）</td><td>高</td></tr>
</table>
<div class="box"><b>Error Knowledge Base（§7.2）</b>：未知エラーは自動修正されず、<code>error_kb/</code> に
「auto_fix_allowed=false / High」で提案され、コンサルタント承認後にルール化されます。ルールは
<code>error_rules/default_rules.yaml</code> でバージョン管理。</div>
<div class="box warn"><b>困ったとき</b>
<ul style="margin:6px 0 0">
<li><code>Address already in use</code> → 別ポート（<code>--port 8913</code>）</li>
<li>プランが <code>CONFLICT</code> だらけ → シナリオを <b>clean</b> に戻す（前回の Mock 状態が残っている）</li>
<li>適用が止まる → 承認チェックと同意チェック、そして <code>KILL</code> マーカー／<code>SAPCFG_KILL_SWITCH</code> を確認</li>
<li>想定外を全部止めたい → <code>touch .kill_switch</code> で以降のステップは ABORTED</li>
</ul></div>
"""),

    # ---------------------------------------------------------------- 12 まとめ
    dict(slug="12_next", kicker="12 · 安全設計と次の一歩", title="なぜ実システムに触らない設計なのか",
         body="""
<div class="box safe"><b>コードで強制している安全策</b>
<ul style="margin:6px 0 0">
<li>実 SAP GUI アダプタは Windows 専用 + <code>SAPCFG_ALLOW_REAL_SAP=1</code> が無いと import 不可（macOS では不可）</li>
<li>Plan は読み取り専用ビューに対してのみ diff を取る</li>
<li>適用は既存プラン + 項目ごとの承認が必須（上書き系は既定でヒューマンキュー）</li>
<li>SAP テーブルへの直接 DB 書き込みコードは存在しない</li>
<li>接続先は各ステップ直前に再確認（不一致なら ABORTED）</li>
</ul></div>
<h2>次の一歩（ロードマップ）</h2>
<ol>
<li><b>あなたの実テンプレート</b>を <code>templates/</code> に投入して Plan を回す（適用は承認制のまま）</li>
<li>Windows + GUI Scripting 有効環境で <b>実アダプタ</b>の画面マップを記録（1 クライアントリリース 1 回）</li>
<li>その後、読み取り専用の RFC/レポート検証 → 移送（Transport）へ拡張</li>
</ol>
<h2>リンク</h2>
<ul>
<li>テキスト版チュートリアル：<code>docs/TUTORIAL.md</code></li>
<li>運用フロー図（SVG）：<code>docs/system_flow.svg</code></li>
<li>リポジトリ：<span class="mono">https://github.com/winds198912121/auto-sap-template</span></li>
</ul>
<p class="lead">まずは <code>uv run python run.py demo</code> の 1 本を流してみてください。Mock なので何度失敗しても安全です。</p>
"""),
]


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if c and Path(c).exists():
            return c
    raise SystemExit("Chrome/Chromium not found - install it or pass a path")


def main() -> None:
    chrome = find_chrome()
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    total = len(CARDS)
    # HTML lives next to the images so relative <img src="../flow.png"> resolves
    with tempfile.TemporaryDirectory(dir=HERE, prefix=".build-") as td:
        tmp = Path(td)
        for i, card in enumerate(CARDS, start=1):
            html = tmp / f"card{i:02d}.html"
            html.write_text(page(card, i, total), encoding="utf-8")
            out = CARDS_DIR / f"{card['slug']}.png"
            subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                            f"--window-size={W},{H}", "--force-device-scale-factor=1",
                            "--virtual-time-budget=4000", f"--screenshot={out}", html.as_uri()],
                           check=True, capture_output=True)
            print(f"  {out.relative_to(HERE.parent.parent)}")
    print(f"{total} cards written to docs/tutorial/cards/")


if __name__ == "__main__":
    main()
