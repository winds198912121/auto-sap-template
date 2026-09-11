#!/usr/bin/env python3
"""運用フロー構成図（SAP GUI 画面風格 / ja + en）を生成する。

デザインはローカルスキル `sap-gui-screen`（= SAP-GUI界面设计模版 V1.0）に準拠:
  五層構造 L1 メニューバー #D9E5F2 → L2 システムツールバー #9DB9D9 → L3 タイトル #F2F2F2
        → L4 アプリケーションツールバー #AECAEC → L5 データ領域 #F2F2F2
  配色 #C0C0C0 / #AECAEC / #C5D9F1 / #ECECEC / #F0F0F0 / #FFFF80 / #0000FF / #008000 / #FF0000
  フォント Tahoma, Arial（ja は MS Gothic / Hiragino にフォールバック）
  角丸なし・1px #808080 罫線・SAP 標準ボタン（F8/F3/Ctrl+S/F12/F1）・メッセージ種別 S/W/E/I/A

出力:
  docs/system_flow.ja.svg / .ja.html / .ja.png / system_flow_diagram.ja.png
  docs/system_flow.en.svg / .en.html / .en.png / system_flow_diagram.en.png

Run:  python3 docs/build_flow_diagram.py
"""
from __future__ import annotations

import html
from pathlib import Path

OUT = Path(__file__).resolve().parent

# --------------------------------------------------------------------------- palette (skill §颜色体系)
C = dict(
    l1="#D9E5F2", l2="#9DB9D9", l3="#F2F2F2", l4="#AECAEC", l5="#F2F2F2",
    grey="#C0C0C0", face="#D4D0E1", btnface="#D4D0C8", alv="#AECAEC", header="#ECECEC",
    filter="#C5D9F1", label="#F0F0F0", disabled="#E0E0E0", search="#FFFF80",
    link="#0000FF", err="#FF0000", ok="#008000", ink="#000000", ink2="#333333",
    ink3="#666666", ink4="#999999", line="#808080", white="#FFFFFF",
)
F = ("Tahoma,Arial,'MS Gothic','Hiragino Kaku Gothic ProN','Yu Gothic UI',"
     "'Noto Sans JP',sans-serif")
MONO = "'Courier New',Menlo,Consolas,monospace"     # OK-code 欄のみ等幅

W = 1680
L1H, L2H, L3H, L4H = 18, 26, 22, 28
DATA_TOP = L1H + L2H + L3H + L4H          # 94
H = 1026
MSG_Y = 1002

# band geometry (y, height)
BA, BB, BC, BD, BE = 114, 298, 564, 742, 884
HA, HB, HC, HD, HE = 144, 212, 152, 124, 110
BX = [44, 314, 584, 854, 1124, 1394]
BW = 240
ABOX = BA + 26          # 140
BBOX = BB + 22          # 320
CBOX = BC + 22          # 586
DBOX = BD + 32          # 774
BW_H, BH = 240, 164
GX = [44, 447, 850, 1253]
GW, GH = 383, 80

WARN: list[str] = []


# --------------------------------------------------------------------------- text helpers
def esc(s: str) -> str:
    return html.escape(s, quote=True)


def tw(s: str, size: float) -> float:
    """Advance-width estimate (Tahoma/Arial, errs wide)."""
    w = 0.0
    for ch in s:
        o = ord(ch)
        if o > 0x2E7F:
            w += size                      # CJK = full width
        elif ch.isupper():
            w += size * 0.72
        elif ch in " .,:;'|il!()[]/<>·-":
            w += size * 0.36
        elif ch.isdigit() or ch.islower():
            w += size * 0.56
        else:
            w += size * 0.66
    return w * 1.02


def wrap(s: str, maxw: float, size: float) -> list[str]:
    no_start = "。、，．）」』】》〉！？：；・ー…"
    out: list[str] = []
    for para in s.split("\n"):
        cur, last_space = "", -1
        for ch in para:
            if ch == " ":
                last_space = len(cur)
            if ch in no_start and cur:
                cur += ch
                continue
            if tw(cur + ch, size) > maxw and cur:
                if last_space > len(cur) * 0.5:
                    out.append(cur[:last_space])
                    cur = cur[last_space + 1:] + ch
                else:
                    out.append(cur)
                    cur = ch
                last_space = -1
            else:
                cur += ch
        out.append(cur)
    return [x for x in out if x != ""] or [""]


def t(x, y, s, size=9, fill=C["ink2"], weight="400", anchor="start", font=F) -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{font}" font-size="{size}" '
            f'fill="{fill}" font-weight="{weight}" text-anchor="{anchor}">{esc(s)}</text>')


def box(x, y, w, h, fill=C["white"], stroke=C["line"], sw=1) -> str:
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')


# --------------------------------------------------------------------------- SAP widgets
def glyph(kind: str, cx: float, cy: float, s: float = 12) -> str:
    """16px-class SAP icon glyph, drawn as thin black lines (S_B_* / S_F_*)."""
    k, st = kind, f'stroke="{C["ink"]}" stroke-width="1.3" fill="none"'
    h = s / 2
    if k == "check":      # S_F_OKAY / 実行
        return (f'<path d="M{cx-h},{cy} L{cx-h/3},{cy+h*0.6} L{cx+h},{cy-h*0.7}" {st}/>')
    if k == "back":       # S_CRBACK F3
        return (f'<path d="M{cx+h},{cy-h*0.7} L{cx-h*0.6},{cy-h*0.7} L{cx-h*0.6},{cy+h} '
                f'M{cx-h},{cy+h*0.15} L{cx-h*0.6},{cy-h*0.7} L{cx-h},{cy-h*1.4}" {st}/>')
    if k == "cancel":     # S_B_CANC F12
        return (f'<path d="M{cx-h},{cy-h} L{cx+h},{cy+h} M{cx+h},{cy-h} L{cx-h},{cy+h}" {st}/>')
    if k == "save":       # S_F_SAVE Ctrl+S (floppy)
        return (f'<path d="M{cx-h},{cy-h} h{s*0.6} l{h*0.8},{h*0.8} v{h*1.2} h{-s*1.4} z" {st}/>'
                f'<path d="M{cx-h*0.55},{cy-h} v{h*0.75} h{s*0.6} v{-h*0.75}" {st}/>')
    if k == "print":      # 印刷
        return (f'<path d="M{cx-h*0.8},{cy-h*0.4} h{s*0.8} v{h*0.8} h{-s*0.8} z" {st}/>'
                f'<path d="M{cx-h*0.45},{cy+h*0.4} v{h*0.6} h{s*0.45} v{-h*0.6} z" {st}/>')
    if k == "find":       # 検索
        return (f'<circle cx="{cx-h*0.25}" cy="{cy-h*0.25}" r="{h*0.65}" {st}/>'
                f'<path d="M{cx+h*0.25},{cy+h*0.25} L{cx+h},{cy+h}" {st}/>')
    if k == "home":       # ファーストページ
        return (f'<path d="M{cx-h},{cy} L{cx},{cy-h} L{cx+h},{cy} M{cx-h*0.6},{cy} v{h*0.9} '
                f'h{s*0.6} v{-h*0.9}" {st}/>')
    if k == "help":       # S_DIHELP F1
        return (f'<circle cx="{cx}" cy="{cy}" r="{h}" {st}/>'
                f'<text x="{cx}" y="{cy+h*0.55}" font-family="{F}" font-size="{s*0.85}" '
                f'fill="{C["ink"]}" text-anchor="middle">?</text>')
    if k == "first":      # ファーストページ
        return (f'<path d="M{cx-h},{cy-h} v{s} M{cx-h*0.3},{cy-h} l{h*0.9},{h} M{cx-h*0.3},{cy+h} '
                f'l{h*0.9},{-h}" {st}/>')
    if k == "last":       # 最終ページ
        return (f'<path d="M{cx+h},{cy-h} v{s} M{cx+h*0.3},{cy-h} l{-h*0.9},{h} M{cx+h*0.3},{cy+h} '
                f'l{-h*0.9},{-h}" {st}/>')
    if k == "layout":     # レイアウト
        return (f'<path d="M{cx-h},{cy-h} h{s} v{s} h{-s} z M{cx-h},{cy-h*0.1} h{s} '
                f'M{cx-h*0.15},{cy-h} v{s}" {st}/>')
    return ""


def sap_btn(x: float, y: float, label: str, fkey: str = "", icon: str = "",
            h: float = 22, fill: str = None, ink: str = None, size: float = 9) -> float:
    face = fill or C["btnface"]
    inkc = ink or C["ink"]
    w = 7 + (14 if icon else 0) + (4 if icon and label else 0) + tw(label, size)
    if fkey:
        w += 6 + tw(f"({fkey})", 8)
    w += 8
    o = [box(x, y, w, h, face, C["line"]),
         f'<path d="M{x + 1},{y + h - 1} L{x + 1},{y + 1} L{x + w - 1},{y + 1}" '
         f'stroke="{C["white"]}" stroke-width="1" fill="none"/>']
    tx = x + 7
    if icon:
        o.append(glyph(icon, tx + 6, y + h / 2, 12))
        tx += 18
    o.append(t(tx, y + h / 2 + 3.3, label, size, inkc))
    if fkey:
        o.append(t(x + w - 8 - tw(f"({fkey})", 8), y + h / 2 + 3, f"({fkey})", 8, C["ink3"]))
    return x + w + 4, "".join(o)


def chip(x, y, label, fill, size=8, h=13, pad=6) -> str:
    w = tw(label, size) + pad * 2
    return (box(x, y, w, h, fill, C["line"]) +
            t(x + w / 2, y + h - 3.6, label, size, C["ink"], "700", anchor="middle"))


def band(y, h, fill, title, note="") -> str:
    o = [box(20, y, 1640, h, C["white"], C["line"]),
         f'<rect x="20" y="{y}" width="1640" height="22" fill="{fill}" '
         f'stroke="{C["line"]}" stroke-width="1"/>',
         t(30, y + 15, title, 9, C["ink"], "700")]
    if note:
        nx = 30 + tw(title, 9) + 16
        if nx + tw(note, 8) > 1650:
            WARN.append(f"band note overflow: {note!r}")
        o.append(t(nx, y + 15, note, 8, C["ink2"]))
    return "".join(o)


def node(x, y, w, h, tone, title, tag, file, body, dashed=False) -> str:
    chipw = tw(tag, 8) + 12
    avail = w - 28 - chipw - 8
    if tw(title, 12) > avail and tw(title, 9) > avail:
        WARN.append(f"title overflow {w:.0f}px box: {title!r}")
    tsize = 12 if tw(title, 12) <= avail else 9
    if tw(file, 9) > w - 26:
        WARN.append(f"file overflow: {file!r}")
    lines = wrap(body, w - 26, 9)
    bottom = y + 52 + (len(lines) - 1) * 12 + 3
    if bottom > y + h:
        WARN.append(f"body overflow in {title!r}: {len(lines)} lines, "
                    f"need {bottom - y:.0f}px / have {h}px")
        WARN.extend(f"      | {ln}  [{tw(ln, 9):.0f}px]" for ln in lines)
        WARN.append(f"      | (max line width {w - 26:.0f}px)")
    o = [box(x, y, w, h, C["white"], C["line"]),
         f'<rect x="{x}" y="{y}" width="{w}" height="4" fill="{tone}" '
         f'stroke="{C["line"]}" stroke-width="1"/>']
    if dashed:
        o.append(f'<rect x="{x + 0.5}" y="{y + 0.5}" width="{w - 1}" height="{h - 1}" '
                 f'fill="none" stroke="{C["ink3"]}" stroke-width="1" stroke-dasharray="4 3"/>')
    o.append(t(x + 10, y + 20, title, tsize, C["ink"], "700"))
    o.append(chip(x + w - 10 - chipw, y + 6, tag, C["header"], 8, 13, 6))
    o.append(f'<path d="M{x + 1},{y + 24} H{x + w - 1}" stroke="{tone}" stroke-width="1"/>')
    o.append(t(x + 10, y + 37, file, 9, C["link"]))
    for i, ln in enumerate(lines):
        o.append(t(x + 10, y + 52 + i * 12, ln, 9, C["ink2"]))
    return "".join(o)


def arrow(x1, y1, x2, y2, color=None, dbl=False, dash=False) -> str:
    col = color or C["line"]
    da = ' stroke-dasharray="4 3"' if dash else ""
    d = (f'<path d="M{x1},{y1} L{x2},{y2}" stroke="{col}" stroke-width="1" fill="none"{da} '
         f'marker-end="url(#ah)"/>')
    if dbl:
        d += (f'<path d="M{x2},{y2} L{x1},{y1}" stroke="{col}" stroke-width="1" fill="none" '
              f'marker-end="url(#ah)"/>')
    return d


def curve(d, color=None, dash=True, w=1) -> str:
    da = ' stroke-dasharray="4 3"' if dash else ""
    return (f'<path d="{d}" stroke="{color or C["ink3"]}" stroke-width="{w}" fill="none"{da} '
            f'marker-end="url(#ah)"/>')


def alv(x, y, w, header: list[tuple[str, float]], rows: list[list[str]],
        rh=16, hh=20) -> str:
    o = [box(x, y, w, hh + rh * len(rows), C["white"], C["line"]),
         f'<rect x="{x}" y="{y}" width="{w}" height="{hh}" fill="{C["header"]}" '
         f'stroke="{C["line"]}" stroke-width="1"/>']
    cx = x
    for (name, cw) in header:
        o.append(t(cx + 6, y + 14, name, 9, C["ink"], "700"))
        if cx > x:
            o.append(f'<path d="M{cx},{y} V{y + hh + rh * len(rows)}" stroke="{C["line"]}"/>')
        cx += cw
    for i, row in enumerate(rows):
        ry = y + hh + i * rh
        o.append(f'<rect x="{x + 1}" y="{ry}" width="{w - 2}" height="{rh}" '
                 f'fill="{C["filter"] if i % 2 == 0 else C["white"]}"/>')
        cx = x
        for j, (cell, (_, cw)) in enumerate(zip(row, header)):
            o.append(t(cx + 6, ry + 12, cell, 9, C["ink"] if j == 0 else C["ink2"]))
            cx += cw
    return "".join(o)


def state_cell(x, y, label, color, w=0) -> str:
    w = w or tw(label, 8) + 16
    return (box(x, y, w, 16, C["white"], C["line"]) +
            f'<rect x="{x + 1}" y="{y + 1}" width="3" height="14" fill="{color}"/>' +
            t(x + w / 2 + 2, y + 11.4, label, 8, C["ink"], "700", anchor="middle"))


PLAN_STATUS = [("CREATE", "#1D7A8A"), ("UPDATE", "#0E6B8A"), ("SKIP", "#808080"),
               ("CONFLICT", C["err"]), ("BLOCKED", "#6D3B9E"), ("ERROR", "#B91C1C")]
STEP_RESULT = [("SUCCESS", C["ok"]), ("RUNNING", C["link"]), ("RETRYING", "#B7791F"),
               ("SKIPPED", "#808080"), ("FAILED", C["err"]), ("MANUAL", "#7C3AED"),
               ("BLOCKED", "#6D3B9E"), ("ABORTED", "#7F1D1D")]

# --------------------------------------------------------------------------- texts (ja / en)
TX = {
 "ja": dict(
  htmltitle="SAP Config Automation — 運用フロー構成図 [JA]",
  wintitle="SAP Config Automation  ·  運用フロー構成図  [SAP GUI 五層モック]",
  menu=["プログラム(P)", "編集(E)", "移動(G)", "お気に入り(F)", "システム(Y)", "ヘルプ(H)"],
  menu_right="SAP Config Automation 1.0",
  okcode="SAPCFG_PLAN",
  l3="SAPCFG_FLOW  —  運用フロー構成図（Configuration as Code / Plan + Mock）",
  l3r="システム: MOCK   クライアント: 100   ユーザー: SAPCFG",
  appbar=[("実行", "F8", "check"), ("戻る", "F3", "back"), ("保存", "Ctrl+S", "save"),
          ("取消", "F12", "cancel"), ("印刷", "", "print"), ("ヘルプ", "F1", "help")],
  appbar_badge="PLAN-ONLY / MOCK",
  l2_badge=[("adapter: MOCK SAP GUI", C["ok"]), ("実 SAP 非接続", "#8A5A00")],
  bands={
   "A": ("LANE 1 · 人（コンサルタント / 運用担当）", "承認と例外処理だけを人が持つ"),
   "B": ("LANE 2 · 自動化パイプライン（本マシン / Python）", "読み取り専用の Plan と、承認ゲート付き Apply"),
   "C": ("LANE 3 · SAP 側（Phase 1 = Mock SAP GUI）", "接続先はこの 1 つだけ。実 SAP DB への書き込みコードは無い"),
   "D": ("LANE 4 · 横断ガードレール", "Plan / Apply の全ステップに適用"),
   "E": ("LANE 5 · 状態カタログと操作", "Plan の差分 / 実行結果 / コマンド"),
  },
  n_A1=dict(title="① 業務テンプレート作成", tag="HUMAN", file="templates/*.yaml",
            body="顧客変数と設定ステップ（OB13 / OB29 / OBY6 / OX02 / OX10）を YAML で記述。"
                 "資格情報・SQL・GUI制御ID の記載はスキーマが拒否する。"),
  n_A2=dict(title="④ 承認（人）", tag="APPROVE", file="run.py apply --approve …",
            body="UPDATE・CONFLICT・needs_approval を 1 件ずつ承認。CONFLICT は明示 override 必須。"
                 "未承認は MANUAL として人間キューに残る。"),
  n_A3=dict(title="例外：人間キュー / KILL", tag="QUEUE", file="runs/<run_id>/KILL",
            body="読み戻し不一致や権限・入力・競合エラーは自動リトライせず停止。"
                 "KILL マーカーで残ステップを ABORTED にする。"),
  n_A4=dict(title="⑧ レポート確認 / KB 承認", tag="REVIEW", file="report.md · error_kb/pending.json",
            body="PoC 指標とエラー分類表を確認。未知エラーは consultant の承認後にのみルール化される。"),
  n_B1=dict(title="② Load & Validate", tag="INPUT", file="schema/*.json · sapcfg/load.py",
            body="JSON Schema で構造検証（必須項目・型・パターン）。\n次のセマンティック検査で資格情報・"
                 "SQL・GUI制御ID を拒否。{{var}} を顧客変数へ解決。\n1 件でも不正なら Plan へ進まず停止する。"),
  n_B2=dict(title="③ Plan（差分・読取専用）", tag="PLAN", file="sapcfg/planner.py → plan.json",
            body="依存関係を DAG 化しトポロジカル順に整列。\n現状と比較し、差分を CREATE / UPDATE / SKIP / "
                 "CONFLICT / BLOCKED / ERROR として理由付きで出力。\nSKIP ＝ 一致（冪等）。SAP は変更しない。"),
  n_B3=dict(title="④ 承認ゲート（強制）", tag="GATE", file="sapcfg/orchestrator.py",
            body="gate = UPDATE / CONFLICT / needs_approval。\n各行の実行直前に承認を確認し、未承認なら"
                 "1 ステップも実行しない（MANUAL）。\n実行前に system / client の三重チェックと kill switch を確認。"),
  n_B4=dict(title="⑤ Apply 実行（状態機械）", tag="APPLY", file="orchestrator.py · steps/fi_basic.py",
            body="1 項目ごとに：現状読取 → 画面操作 → 保存。\nattempts ≦ 3（初回＋自動リトライ 2 回）。"
                 "リトライ可：LOCK / TRANSIENT / NAVIGATION のみ。\n結果：SUCCESS / FAILED / MANUAL / "
                 "BLOCKED / ABORTED。"),
  n_B5=dict(title="⑥ 読み戻し検証", tag="VERIFY", file="sapcfg/verify.py",
            body="保存後の実値を eq / neq / contains / in / regex で期待値と比較。\nSKIP は Plan 時点で "
                 "verified 扱い。\n不一致は FAILED（リトライしない）→ 人間キュー。\n＝「本当に書けたか」を実値で確かめる。"),
  n_B6=dict(title="⑦ 証跡 & レポート", tag="STORE · REPORT", file="sapcfg/store.py · reporter.py",
            body="runs/<run_id>/ に plan.json・events.jsonl（全イベント）・run.sqlite（再開可）・"
                 "evidence/*.svg（画面証跡）・report.md。\n再実行では SUCCESS をスキップし途中から再開できる。"),
  n_C0=dict(title="Phase 2 ロードマップ：実 SAP GUI Scripting", tag="ROADMAP",
            file="sapcfg/gui/win_gui.py（Windows 専用）",
            body="① Windows ＋ SAP GUI Scripting 有効化、② SAPCFG_ALLOW_REAL_SAP=1、"
                 "③ client release ごとに画面マップを 1 回記録。\n3 条件が揃うまで import すら不可。"
                 "揃った後は同じ template → plan → 承認 → apply が実機を対象にする（Transport は Phase 3）。"),
  n_C1=dict(title="Mock SAP GUI ドライバ", tag="MOCK", file="sapcfg/gui/mock.py",
            body="画面カタログ通りに歩進し、in-process の設定ストアを更新。"
                 "障害注入（例：E071K ロック）でリトライ経路も再現できる。"),
  n_C2=dict(title="設定ストア（読取対象）", tag="STATE", file="in-process（実 SAP 非接続）",
            body="読み戻し検証が参照する唯一の状態。実 SAP DB への INSERT / UPDATE SQL はコード上に存在しない。"),
  guards=[("Kill Switch（即時中断）",
           "runs/KILL マーカー / .kill_switch / SAPCFG_KILL_SWITCH=1 → 残りのステップを ABORTED にする。"),
          ("Target 三重チェック",
           "各ステップ実行の直前に system / client をプラン対象と照合。不一致なら run 全体を ABORTED。"),
          ("アダプタ・ガードと入力の禁止事項",
           "win_gui.py は Windows ＋ SAPCFG_ALLOW_REAL_SAP=1 が無ければ import 不可。"
           "テンプレートに資格情報・SQL・制御ID は書けない。"),
          ("Error KB ＋ 26 オフライン単体テスト",
           "未知エラーは pending.json へ起案（auto_fix_allowed=false / High / 要コンサル承認）。")],
  e_plan="Plan の差分：", e_result="実行の結果：",
  e_alv_h=[("コマンド", 396), ("説明", 294)],
  e_alv=[("uv run python run.py plan", "差分のみ（書き込みなし）"),
         ("uv run python run.py apply --run <run_id> --approve <item_id>", "承認済み項目のみ実行"),
         ("uv run python run.py report --run <run_id>", "Markdown レポートを出力"),
         ("uv run python webui/server.py --port 8912", "Web コンソール（本画面の実体）")],
  msg="(I)  情報：Phase 1 は Mock SAP GUI のみ。実 SAP / 実 DB への接続・書き込みは行いません。",
  ar_req="承認要求", ar_grant="承認 + consent", ar_mismatch="不一致 → 人間キュー",
  ar_report="report.md", ar_retry="自動リトライ ≦ 2", ar_gui="GUI 操作 / 状態読取", ar_read="読み戻し値",
  dl="SVG をダウンロード", pr="印刷 / PDF", lang_switch="English", lang_switch_href="system_flow.en.html",
  spec="SAP GUI 五層レイアウト（L1 メニューバー / L2 システムツールバー / L3 タイトル / "
       "L4 アプリケーションツールバー / L5 データ領域）準拠のモック。配色・罫線・ボタンは "
       "SAP-GUI界面設計模版 V1.0（#D9E5F2 / #9DB9D9 / #AECAEC / #ECECEC / #808080・Tahoma 9pt）",
 ),
 "en": dict(
  htmltitle="SAP Config Automation — Operations flow [EN]",
  wintitle="SAP Config Automation  ·  Operations flow  [SAP GUI 5-layer mock]",
  menu=["Program(P)", "Edit(E)", "Goto(G)", "Favorites(F)", "System(Y)", "Help(H)"],
  menu_right="SAP Config Automation 1.0",
  okcode="SAPCFG_PLAN",
  l3="SAPCFG_FLOW  —  Operations flow (Configuration as Code / Plan + Mock)",
  l3r="System: MOCK   Client: 100   User: SAPCFG",
  appbar=[("Execute", "F8", "check"), ("Back", "F3", "back"), ("Save", "Ctrl+S", "save"),
          ("Cancel", "F12", "cancel"), ("Print", "", "print"), ("Help", "F1", "help")],
  appbar_badge="PLAN-ONLY / MOCK",
  l2_badge=[("adapter: MOCK SAP GUI", C["ok"]), ("no real-SAP connection", "#8A5A00")],
  bands={
   "A": ("LANE 1 · People (consultant / operations)", "only approvals and exceptions stay with humans"),
   "B": ("LANE 2 · Automation pipeline (this machine / Python)", "read-only Plan + gated Apply"),
   "C": ("LANE 3 · SAP side (Phase 1 = Mock SAP GUI)", "the only endpoint; no code writes to a real SAP DB"),
   "D": ("LANE 4 · Cross-cutting guard rails", "applied to every Plan / Apply step"),
   "E": ("LANE 5 · State catalog and commands", "plan diff / step results / CLI"),
  },
  n_A1=dict(title="① Author the template", tag="HUMAN", file="templates/*.yaml",
            body="Customer variables and config steps (OB13 / OB29 / OBY6 / OX02 / OX10) in YAML. "
                 "Credentials, SQL and GUI control-IDs are rejected by the schema."),
  n_A2=dict(title="④ Approval (human)", tag="APPROVE", file="run.py apply --approve …",
            body="Approve UPDATE / CONFLICT / needs_approval one by one; CONFLICT needs an explicit "
                 "override. Unapproved items stay in the human queue as MANUAL."),
  n_A3=dict(title="Exception: queue / KILL", tag="QUEUE", file="runs/<run_id>/KILL",
            body="Read-back mismatches and permission / input / conflict errors never retry - they "
                 "stop here. The KILL marker turns remaining steps into ABORTED."),
  n_A4=dict(title="⑧ Review report / KB", tag="REVIEW", file="report.md · error_kb/pending.json",
            body="Check PoC metrics and the error-classification table. Unknown errors become rules "
                 "only after a consultant approves them."),
  n_B1=dict(title="② Load & Validate", tag="INPUT", file="schema/*.json · sapcfg/load.py",
            body="Structural validation against JSON Schema (required, types, patterns). "
                 "Semantic checks reject credentials / SQL / control-IDs.\n"
                 "{{var}} is resolved from the customer variables. One bad item stops the run."),
  n_B2=dict(title="③ Plan (diff, read-only)", tag="PLAN", file="sapcfg/planner.py → plan.json",
            body="Dependencies become a DAG, sorted topologically.\nCompared with current state, every "
                 "diff is emitted as CREATE / UPDATE / SKIP / CONFLICT / BLOCKED / ERROR with a reason.\n"
                 "SKIP = already matching (idempotent). SAP is not touched."),
  n_B3=dict(title="④ Approval gate", tag="GATE", file="sapcfg/orchestrator.py",
            body="gate = UPDATE / CONFLICT / needs_approval.\nApproval is checked right before each item "
                 "runs; without it not one step executes (MANUAL).\nTarget system/client triple-check "
                 "and kill switch are verified first."),
  n_B4=dict(title="⑤ Apply (state machine)", tag="APPLY", file="orchestrator.py · steps/fi_basic.py",
            body="Per item: read current state -> drive the screens -> save.\nattempts <= 3 (initial + 2 "
                 "auto retries); retry only for LOCK / TRANSIENT / NAVIGATION.\n"
                 "Result: SUCCESS / FAILED / MANUAL / BLOCKED / ABORTED."),
  n_B5=dict(title="⑥ Read-back verification", tag="VERIFY", file="sapcfg/verify.py",
            body="Persisted values are compared with expectations via eq / neq / contains / in / regex.\n"
                 "SKIP counts as verified at plan time.\nA mismatch is FAILED (no retry) -> human queue.\n"
                 "Proof that it really persisted."),
  n_B6=dict(title="⑦ Evidence & report", tag="STORE · REPORT", file="sapcfg/store.py · reporter.py",
            body="runs/<run_id>/ holds plan.json, events.jsonl (every event), run.sqlite (resumable), "
                 "evidence/*.svg (screen shots) and report.md.\nRe-runs skip SUCCESS items and resume mid-way."),
  n_C0=dict(title="Phase 2 roadmap: real SAP GUI Scripting", tag="ROADMAP",
            file="sapcfg/gui/win_gui.py (Windows only)",
            body="1) Windows with GUI Scripting enabled, 2) SAPCFG_ALLOW_REAL_SAP=1, "
                 "3) screen maps recorded once per client release.\nUntil all three hold the module "
                 "cannot even be imported. Then the same template -> plan -> approval -> apply targets "
                 "the real system (Transport = Phase 3)."),
  n_C1=dict(title="Mock SAP GUI driver", tag="MOCK", file="sapcfg/gui/mock.py",
            body="Walks the screen catalog and updates the in-process config store. Fault injection "
                 "(e.g. an E071K lock) reproduces the retry path."),
  n_C2=dict(title="Config store (read-back)", tag="STATE", file="in-process (no real SAP)",
            body="The only state read-back verification looks at. No INSERT / UPDATE SQL against a real "
                 "SAP DB exists anywhere in the code."),
  guards=[("Kill switch (immediate stop)",
           "runs/KILL marker / .kill_switch / SAPCFG_KILL_SWITCH=1 -> all remaining steps become ABORTED."),
          ("Target triple-check",
           "Right before every step, system / client are compared with the planned target; a mismatch "
           "aborts the whole run."),
          ("Adapter guard / forbidden inputs",
           "win_gui.py cannot be imported without Windows + SAPCFG_ALLOW_REAL_SAP=1. Templates may not "
           "contain credentials, SQL or control-IDs."),
          ("Error KB + 26 offline unit tests",
           "Unknown errors are proposed to pending.json (auto_fix_allowed=false / High / needs approval).")],
  e_plan="Plan statuses:", e_result="Step results:",
  e_alv_h=[("Command", 396), ("Description", 294)],
  e_alv=[("uv run python run.py plan", "diff only (no writes)"),
         ("uv run python run.py apply --run <run_id> --approve <item_id>", "execute approved items only"),
         ("uv run python run.py report --run <run_id>", "print the Markdown report"),
         ("uv run python webui/server.py --port 8912", "web console (the real screen)")],
  msg="(I)  Info: Phase 1 runs against the Mock SAP GUI only. It never connects to or writes to a real SAP system.",
  ar_req="approval request", ar_grant="approval + consent", ar_mismatch="mismatch -> human queue",
  ar_report="report.md", ar_retry="auto-retry <= 2", ar_gui="GUI ops / state read", ar_read="read-back values",
  dl="Download SVG", pr="Print / PDF", lang_switch="日本語", lang_switch_href="system_flow.ja.html",
  spec="Mock built on the SAP GUI five-layer layout (L1 menu bar / L2 system toolbar / L3 title / "
       "L4 application toolbar / L5 data area). Colours, rules and buttons follow "
       "SAP-GUI界面设计模版 V1.0 (#D9E5F2 / #9DB9D9 / #AECAEC / #ECECEC / #808080, Tahoma 9pt).",
 ),
}

SYS_ICONS = [("check", "Enter"), ("back", "F3"), ("cancel", "F12"), ("save", "Ctrl+S"),
             ("print", "Ctrl+P"), ("find", "Ctrl+F"), ("home", "Home"), ("first", "First"),
             ("last", "Last"), ("help", "F1"), ("layout", "Layout")]


# --------------------------------------------------------------------------- SVG builder
def build_svg(lang: str) -> str:
    T = TX[lang]
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" '
         f'height="{H}" class="flow" role="img" aria-label="SAP Config Automation flow ({lang})">',
         f'<defs><marker id="ah" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" '
         f'markerHeight="6" orient="auto-start-reverse">'
         f'<path d="M0,1 L7,4 L0,7 z" fill="{C["line"]}"/></marker></defs>',
         f'<rect width="{W}" height="{H}" fill="{C["l5"]}"/>']

    # ---- L1 menu bar ----------------------------------------------------
    s.append(f'<rect x="0" y="0" width="{W}" height="{L1H}" fill="{C["l1"]}"/>')
    x = 8
    for item in T["menu"]:
        s.append(t(x, 12.5, item, 8, C["ink3"]))
        x += tw(item, 8) + 16
    s.append(t(W - 8, 12.5, T["menu_right"], 8, C["ink3"], anchor="end"))

    # ---- L2 system toolbar ---------------------------------------------
    s.append(f'<rect x="0" y="{L1H}" width="{W}" height="{L2H}" fill="{C["l2"]}"/>')
    icy = L1H + L2H / 2
    s.append(glyph("check", 20, icy, 13))
    ox = 34
    s.append(f'<rect x="{ox}" y="{L1H + 4}" width="190" height="18" fill="{C["white"]}" '
             f'stroke="{C["line"]}"/>')
    s.append(t(ox + 5, L1H + 16.5, T["okcode"], 9, C["ink"]))
    s.append(f'<path d="M{ox + 174},{L1H + 11} l9,0 l-4.5,5 z" fill="{C["ink"]}"/>')
    ix = ox + 198
    for kind, tip in SYS_ICONS:
        s.append(f'<rect x="{ix:.0f}" y="{L1H + 3}" width="22" height="20" fill="#E8EFF7" '
                 f'stroke="{C["line"]}"><title>{esc(tip)}</title></rect>')
        s.append(glyph(kind, ix + 11, icy, 12))
        ix += 24
    bx = W - 8
    for label, col in reversed(T["l2_badge"]):
        wch = tw(label, 9) + 16
        s.append(box(bx - wch, L1H + 4, wch, 18, C["white"], C["line"]))
        s.append(t(bx - wch / 2, L1H + 16.5, label, 9, col, "700", anchor="middle"))
        bx -= wch + 6

    # ---- L3 title bar ---------------------------------------------------
    ty = L1H + L2H
    s.append(f'<rect x="0" y="{ty}" width="{W}" height="{L3H}" fill="{C["l3"]}"/>')
    s.append(t(10, ty + 16, T["l3"], 12, C["ink"], "700"))
    s.append(t(W - 10, ty + 15, T["l3r"], 8, C["ink3"], anchor="end"))

    # ---- L4 application toolbar ----------------------------------------
    ay = ty + L3H
    s.append(f'<rect x="0" y="{ay}" width="{W}" height="{L4H}" fill="{C["l4"]}"/>')
    x = 8
    for label, fkey, icon in T["appbar"]:
        x, f = sap_btn(x, ay + 3, label, fkey, icon, 22)
        s.append(f)
    badge = T["appbar_badge"]
    bwd = tw(badge, 9) + 18
    s.append(box(W - 8 - bwd, ay + 3, bwd, 22, C["search"], C["line"]))
    s.append(t(W - 8 - bwd / 2, ay + 17.5, badge, 9, C["ink"], "700", anchor="middle"))

    # ---- L5 data area: lanes -------------------------------------------
    for key, fill in (("A", C["header"]), ("B", C["alv"]), ("C", C["filter"]),
                      ("D", C["disabled"]), ("E", C["label"])):
        y = {"A": BA, "B": BB, "C": BC, "D": BD, "E": BE}[key]
        h = {"A": HA, "B": HB, "C": HC, "D": HD, "E": HE}[key]
        s.append(band(y, h, fill, T["bands"][key][0], T["bands"][key][1]))

    N = T
    s.append(node(44, ABOX, BW, 104, C["header"], **N["n_A1"]))
    s.append(node(584, ABOX, BW, 104, C["header"], **N["n_A2"]))
    s.append(node(1124, ABOX, BW, 104, C["header"], **N["n_A3"]))
    s.append(node(1394, ABOX, BW, 104, C["header"], **N["n_A4"]))
    for i, k in enumerate(("n_B1", "n_B2", "n_B3", "n_B4", "n_B5", "n_B6")):
        s.append(node(BX[i], BBOX, BW, BH, C["alv"], **N[k]))
    s.append(node(44, CBOX, 740, 96, C["filter"], dashed=True, **N["n_C0"]))
    s.append(node(854, CBOX, BW, 96, C["filter"], **N["n_C1"]))
    s.append(node(1124, CBOX, BW, 96, C["filter"], **N["n_C2"]))

    # ---- L5: guard rails (ALV-header style cards) ----------------------
    for x0, (gt, gb) in zip(GX, N["guards"]):
        s.append(box(x0, DBOX, GW, GH, C["white"], C["line"]))
        s.append(f'<rect x="{x0}" y="{DBOX}" width="{GW}" height="18" fill="{C["header"]}" '
                 f'stroke="{C["line"]}"/>')
        s.append(t(x0 + 8, DBOX + 13, gt, 9, C["ink"], "700"))
        glines = wrap(gb, GW - 18, 9)
        if len(glines) > 3:
            WARN.append(f"guard card truncated: {gt!r} ({len(glines)} lines > 3)")
        for i, ln in enumerate(glines[:3]):
            s.append(t(x0 + 8, DBOX + 32 + i * 12, ln, 9, C["ink2"]))

    # ---- L5: states (left) + command list (ALV, right) -----------------
    s.append(t(44, BE + 42, T["e_plan"], 9, C["ink"], "700"))
    cx = 44 + tw(T["e_plan"], 9) + 6
    for label, col in PLAN_STATUS:
        s.append(state_cell(cx, BE + 34, label, col))
        cx += tw(label, 8) + 22
    s.append(t(44, BE + 70, T["e_result"], 9, C["ink"], "700"))
    cx = 44 + tw(T["e_result"], 9) + 6
    for label, col in STEP_RESULT:
        s.append(state_cell(cx, BE + 62, label, col))
        cx += tw(label, 8) + 22
    if cx > 940:
        WARN.append(f"state cells overflow into the ALV area: x={cx:.0f}")
    s.append(alv(950, BE + 22, 690, T["e_alv_h"], [list(r) for r in T["e_alv"]]))

    # ---- connectors ----------------------------------------------------
    s.append(arrow(164, ABOX + 104, 164, BBOX))
    s.append(arrow(680, BBOX, 680, ABOX + 104))
    s.append(t(674, BA + 158, T["ar_req"], 8, C["ink"], anchor="end"))
    s.append(arrow(728, ABOX + 104, 728, BBOX))
    s.append(t(736, BA + 158, T["ar_grant"], 8, C["ink"]))
    s.append(arrow(1244, BBOX, 1244, ABOX + 104))
    s.append(t(1252, BA + 158, T["ar_mismatch"], 8, C["ink"]))
    s.append(arrow(1514, BBOX, 1514, ABOX + 104))
    s.append(t(1522, BA + 158, T["ar_report"], 8, C["ink"]))
    for i in range(5):
        s.append(arrow(BX[i] + BW + 2, BBOX + 60, BX[i + 1] - 2, BBOX + 60))
    bbot = BBOX + BH
    s.append(curve(f"M1180,{bbot} V540 H1046 V{bbot}"))
    s.append(t(1105, 534, T["ar_retry"], 8, C["ink"], "700", anchor="middle"))
    s.append(arrow(900, bbot, 900, CBOX, dbl=True))
    s.append(t(906, 538, T["ar_gui"], 8, C["ink"]))
    s.append(arrow(1290, CBOX, 1290, bbot))
    s.append(t(1296, 538, T["ar_read"], 8, C["ink"]))

    # ---- message line (C604 情報) -------------------------------------
    s.append(box(20, MSG_Y, 1640, 16, C["white"], C["line"]))
    s.append(f'<rect x="21" y="{MSG_Y + 1}" width="3" height="14" fill="{C["link"]}"/>')
    s.append(t(32, MSG_Y + 11.5, T["msg"], 9, C["ink2"]))

    # ---- layer separators + window border ------------------------------
    for y in (L1H, L1H + L2H, L1H + L2H + L3H, DATA_TOP):
        s.append(f'<path d="M0,{y} H{W}" stroke="{C["line"]}" stroke-width="1"/>')
    s.append(f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" fill="none" '
             f'stroke="{C["line"]}"/>')
    s.append("</svg>")
    return "\n".join(s)


HTML = """<!DOCTYPE html>
<html lang="__LANG__">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>__HTMLTITLE__</title>
<style>
  *{box-sizing:border-box}
  body{margin:0;padding:14px;background:#D4D0C8;color:#000;
    font:11px Tahoma,Arial,'MS Gothic','Hiragino Kaku Gothic ProN','Yu Gothic UI',sans-serif}
  .win{max-width:1740px;margin:0 auto;background:#D4D0C8;border:1px solid #808080;
    padding:2px;box-shadow:2px 2px 0 rgba(0,0,0,.22)}
  .winbar{display:flex;align-items:center;gap:8px;background:#000080;color:#fff;
    font:700 12px Tahoma,Arial,'MS Gothic',sans-serif;padding:3px 6px}
  .winbar .grow{flex:1}
  .wbtn{width:18px;height:14px;display:inline-flex;align-items:center;justify-content:center;
    background:#D4D0C8;border:1px solid #fff;border-right-color:#808080;
    border-bottom-color:#808080;color:#000;font:700 9px Tahoma,sans-serif}
  .client{background:#F2F2F2;border:1px solid #808080}
  svg.flow{width:100%;height:auto;display:block}
  .tools{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-top:8px;padding:4px;
    background:#D4D0C8;border:1px solid #fff;border-right-color:#808080;border-bottom-color:#808080}
  .sbtn{display:inline-block;background:#D4D0C8;color:#000;cursor:pointer;text-decoration:none;
    border:1px solid #808080;border-top-color:#fff;border-left-color:#fff;
    font:9px Tahoma,Arial,'MS Gothic',sans-serif;padding:3px 10px}
  .sbtn:hover{background:#E4E0D8}
  .note{font:8px Tahoma,Arial,'MS Gothic',sans-serif;color:#666;margin:8px 2px 0;max-width:1250px;
    line-height:1.7}
  @media print{body{background:#fff;padding:0}.win{box-shadow:none;max-width:none}.tools{display:none}}
</style>
</head>
<body>
<div class="win">
  <div class="winbar"><span>__WINTITLE__</span><span class="grow"></span>
    <span class="wbtn">_</span><span class="wbtn">&#9633;</span><span class="wbtn">&#10005;</span></div>
  <div class="client">
__SVG__
  </div>
  <div class="tools">
    <a class="sbtn" href="system_flow.__LANG__.svg" download>__DL__</a>
    <button class="sbtn" onclick="window.print()">__PR__</button>
    <a class="sbtn" href="__SWITCH_HREF__">__SWITCH__</a>
  </div>
  <p class="note">__SPEC__<br/>
    generated by docs/build_flow_diagram.py &#183; style: skill `sap-gui-screen` (SAP-GUI界面设计模版 V1.0)
  </p>
</div>
</body>
</html>
"""


def build_html(lang: str, svg: str) -> str:
    T = TX[lang]
    return (HTML.replace("__SVG__", svg).replace("__LANG__", lang)
            .replace("__HTMLTITLE__", esc(T["htmltitle"]))
            .replace("__WINTITLE__", esc(T["wintitle"]))
            .replace("__DL__", T["dl"]).replace("__PR__", T["pr"])
            .replace("__SWITCH__", T["lang_switch"])
            .replace("__SWITCH_HREF__", T["lang_switch_href"])
            .replace("__SPEC__", T["spec"]))


def main() -> None:
    for lang in ("ja", "en"):
        svg = build_svg(lang)
        (OUT / f"system_flow.{lang}.svg").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n' + svg + "\n", encoding="utf-8")
        (OUT / f"system_flow.{lang}.html").write_text(build_html(lang, svg), encoding="utf-8")
        print(f"wrote: system_flow.{lang}.svg  system_flow.{lang}.html")
        if lang == "ja":
            # 互換エイリアス: docs/TUTORIAL.md / TUTORIAL-IMAGES.md が docs/system_flow.svg を参照している
            (OUT / "system_flow.svg").write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n' + svg + "\n", encoding="utf-8")
            (OUT / "system_flow.html").write_text(build_html(lang, svg), encoding="utf-8")
            print("wrote: system_flow.svg  system_flow.html  (JA alias for existing links)")
    if WARN:
        print("\n! layout warnings (self-check):")
        for m in WARN:
            print("  -", m)
        raise SystemExit(1)
    print("layout self-check: OK (no text overflow)")


if __name__ == "__main__":
    main()
