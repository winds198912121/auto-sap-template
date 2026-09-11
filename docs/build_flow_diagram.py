#!/usr/bin/env python3
"""Generate the operations-flow architecture diagram (SAP Fiori / S/4 style).

Outputs:
  docs/system_flow.svg   - standalone diagram (README / docs embedding)
  docs/system_flow.html  - Fiori-styled page with the diagram + KPI tiles

Run:  uv run python docs/build_flow_diagram.py
"""
from __future__ import annotations

import html
from pathlib import Path

OUT = Path(__file__).resolve().parent

W, H = 1680, 978

C = dict(
    shell="#1e3a5f", ink="#0f1c2e", ink2="#33465c", mut="#64748b",
    card="#ffffff", line="#dbe3ec",
    blue="#0070f2", blue_dk="#1e3a5f",
    orange="#e76500", green="#1b7f3b", indigo="#5d36ff", teal="#0e8b8b",
    red="#c0392b", amber="#b7791f",
    human="#fff8f0", pipe="#f4f8ff", sap="#f3fbf6", guard="#f7f4ff", state="#fafcff",
)

FONT = ("'72','72full','IBM Plex Sans','Hiragino Sans','Hiragino Kaku Gothic ProN',"
        "'Yu Gothic UI','PingFang SC','Segoe UI','Noto Sans JP',sans-serif")
MONO = "Menlo,Consolas,'SFMono-Regular','DejaVu Sans Mono',monospace"

STATUS = [
    ("CREATE", "#1d7a8a"), ("UPDATE", "#0e6b8a"), ("SKIP", "#64748b"),
    ("CONFLICT", "#c0392b"), ("BLOCKED", "#6d3b9e"), ("ERROR", "#b91c1c"),
]
RESULT = [
    ("SUCCESS", "#1b7f3b"), ("RUNNING", "#0070f2"), ("RETRYING", "#b7791f"),
    ("SKIPPED", "#64748b"), ("FAILED", "#c0392b"), ("MANUAL", "#7c3aed"),
    ("BLOCKED", "#6d3b9e"), ("ABORTED", "#7f1d1d"),
]


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def tw(s: str, size: float) -> float:
    """Rough advance width (errs on the wide side: CJK = 1em, caps = 0.7em)."""
    w = 0.0
    for ch in s:
        o = ord(ch)
        if o > 0x2E7F:
            w += size
        elif ch.isupper():
            w += size * 0.70
        elif ch in " .,:;'|il!()[]/·-":
            w += size * 0.36
        elif ch.isdigit() or ch.islower():
            w += size * 0.58
        else:
            w += size * 0.65
    return w * 1.015


def wrap(s: str, maxw: float, size: float) -> list[str]:
    # CJK closing punctuation must not start a line -> glue it to the current one
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


def t(x: float, y: float, s: str, size=10.3, fill=C["ink2"], weight="400",
      anchor="start", font=FONT, ls=0) -> str:
    extra = f' letter-spacing="{ls}"' if ls else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{font}" font-size="{size}" '
            f'fill="{fill}" font-weight="{weight}" text-anchor="{anchor}"{extra}>'
            f'{esc(s)}</text>')


def chip(x: float, y: float, label: str, fill: str, size=9.5, h=15, pad=8) -> str:
    w = tw(label, size) + pad * 2
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h}" rx="7.5" fill="{fill}"/>'
            f'<text x="{x + w / 2:.1f}" y="{y + h - 4.6:.1f}" font-family="{FONT}" '
            f'font-size="{size}" fill="#fff" font-weight="600" text-anchor="middle">{esc(label)}</text>')


def band(y: float, h: float, fill: str, accent: str, title: str, note: str = "") -> str:
    o = [f'<rect x="20" y="{y}" width="1640" height="{h}" rx="14" fill="{fill}" '
         f'stroke="{C["line"]}"/>',
         f'<rect x="20" y="{y}" width="5" height="{h}" rx="2.5" fill="{accent}"/>',
         chip(40, y + 10, title, accent, size=10, h=17, pad=10)]
    if note:
        nx = 40 + tw(title, 10) + 34
        if nx + tw(note, 10) > 1644:
            WARN.append(f"band note overflow: {note!r}")
        o.append(t(nx, y + 22.5, note, 10, C["mut"]))
    return "".join(o)


WARN: list[str] = []


def node(x: float, y: float, w: float, h: float, accent: str, title: str,
         tag: str, file_: str, body: str, dashed=False) -> str:
    # --- layout self-check (fails loudly instead of silently overlapping) ---
    chipw = tw(tag, 9) + 16
    tw_title = tw(title, 12.4)
    avail = w - 28 - chipw - 8
    if tw_title > avail:
        WARN.append(f"title overflow {w:.0f}px box: {title!r} "
                    f"({tw_title:.0f} > {avail:.0f})")
    if tw(file_, 9.7) > w - 32:
        WARN.append(f"file overflow: {file_!r} ({tw(file_, 9.7):.0f} > {w - 32:.0f})")
    lines = wrap(body, w - 38, 10.3)
    bottom = y + 59 + (len(lines) - 1) * 13.6 + 4
    if bottom > y + h:
        WARN.append(f"body overflow in {title!r}: {len(lines)} lines, "
                    f"need {bottom - y:.0f}px / have {h}px")
        for ln in lines:
            WARN.append(f"      | {ln}  [{tw(ln, 10.3):.0f}px]")
        WARN.append(f"      | (max line width {w - 38:.0f}px)")
    o = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="#fff" '
         f'stroke="{C["line"]}"{" stroke-dasharray=\"5 4\"" if dashed else ""}/>',
         f'<rect x="{x}" y="{y + 7}" width="5" height="{h - 14}" rx="2.5" fill="{accent}"/>']
    o.append(t(x + 16, y + 23, title, 12.4, C["blue_dk"], "600"))
    tw_ = tw(tag, 9)
    o.append(chip(x + w - 12 - (tw_ + 16), y + 9, tag, accent, size=9, h=14, pad=8))
    o.append(t(x + 16, y + 40, file_, 9.7, accent, "600", font=MONO))
    for i, ln in enumerate(lines):
        o.append(t(x + 16, y + 59 + i * 13.6, ln, 10.3, C["ink2"]))
    return "".join(o)


def arrow(x1, y1, x2, y2, color="#8fa3ba", dbl=False, w=1.6, dash=False) -> str:
    d = f'<path d="M{x1},{y1} L{x2},{y2}" stroke="{color}" stroke-width="{w}" fill="none"' \
        f'{" stroke-dasharray=\"5 4\"" if dash else ""} marker-end="url(#ah)"/>'
    if dbl:
        d += f'<path d="M{x2},{y2} L{x1},{y1}" stroke="{color}" stroke-width="{w}" ' \
             f'fill="none" marker-end="url(#ah)"/>'
    return d


def path(d: str, color="#8fa3ba", w=1.6, dash=False) -> str:
    return (f'<path d="{d}" stroke="{color}" stroke-width="{w}" fill="none" '
            f'marker-end="url(#ah)"{" stroke-dasharray=\"5 4\"" if dash else ""}/>')


svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" '
       f'height="{H}" class="flow" role="img" aria-label="SAP Config Automation operations flow">',
       f'<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
       f'markerHeight="6" orient="auto-start-reverse">'
       f'<path d="M0,1 L9,5 L0,9 z" fill="#8fa3ba"/></marker>'
       f'<marker id="ahr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
       f'markerHeight="6" orient="auto-start-reverse">'
       f'<path d="M0,1 L9,5 L0,9 z" fill="{C["green"]}"/></marker>'
       f'<marker id="ahb" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
       f'markerHeight="6" orient="auto-start-reverse">'
       f'<path d="M0,1 L9,5 L0,9 z" fill="{C["blue"]}"/></marker></defs>',
       f'<rect width="{W}" height="{H}" fill="#f5f6f7"/>']

# ---- shell bar -------------------------------------------------------------
svg.append(f'<rect x="0" y="0" width="{W}" height="54" fill="{C["shell"]}"/>')
svg.append(t(22, 29, "SAP Config Automation", 17, "#fff", "700"))
svg.append(t(22, 45, "運用フロー構成図 — Configuration as Code: Template → Plan → 承認 → Apply（Mock）→ 検証 → 証跡",
             11.5, "#c9d8e8"))
svg.append(chip(1400, 12, "adapter: MOCK SAP GUI", "#0e6b3a", size=10.5, h=17, pad=11))
svg.append(chip(1560, 12, "実 SAP 非接続", "#8a5a00", size=10.5, h=17, pad=11))

Y = {}
# ---- lane 1: human ---------------------------------------------------------
YA, HA = 74, 144
svg.append(band(YA, HA, C["human"], C["orange"], "LANE 1 · 人間（コンサルタント / 運用担当）",
                "ヒューマンインザループ：承認と例外処理だけを人が持つ"))
Y["A"] = 100
svg.append(node(44, Y["A"], 240, 104, C["orange"], "① 業務テンプレート作成", "HUMAN",
                "templates/*.yaml",
                "顧客変数と設定ステップ（OB13 / OB29 / OBY6 / OX02 / OX10）を YAML で記述。"
                "資格情報・SQL・GUI制御ID の記載はスキーマが拒否する。"))
svg.append(node(584, Y["A"], 240, 104, C["orange"], "④ 承認（人）", "APPROVE",
                "run.py apply --approve …",
                "UPDATE・CONFLICT・needs_approval の項目を1件ずつ承認。CONFLICT は明示 override が必須。"
                "未承認は MANUAL として人間キューに残る。"))
svg.append(node(1124, Y["A"], 240, 104, C["orange"], "例外：人間キュー / KILL", "QUEUE",
                "runs/<run_id>/KILL",
                "読み戻し不一致や権限・入力・競合エラーは自動リトライせず停止。"
                "KILL マーカーで残ステップを ABORTED にする。"))
svg.append(node(1394, Y["A"], 240, 104, C["orange"], "⑧ レポート確認 / KB 承認", "REVIEW",
                "report.md · error_kb/pending.json",
                "PoC 指標とエラー分類表を確認。未知エラーは consultant の承認後にのみルール化される。"))

# ---- lane 2: pipeline ------------------------------------------------------
YB, HB = 258, 212
svg.append(band(YB, HB, C["pipe"], C["blue"], "LANE 2 · 自動化パイプライン（本マシン / Python）",
                "read-only な Plan と、承認ゲート付き Apply の状態機械"))
Y["B"] = 280
BX = [44, 314, 584, 854, 1124, 1394]
BW, BH = 240, 164
svg.append(node(BX[0], Y["B"], BW, BH, C["blue"], "② Load & Validate", "INPUT",
                "schema/*.json · sapcfg/load.py",
                "JSON Schema で構造検証（必須項目・型・パターン）。\n"
                "続いてセマンティック検査で資格情報・SQL・GUI制御ID を拒否。\n"
                "{{var}} を顧客変数の値へ解決。1件でも不正なら Plan へ進まず停止。"))
svg.append(node(BX[1], Y["B"], BW, BH, C["blue"], "③ Plan（差分・読取専用）", "PLAN",
                "sapcfg/planner.py → plan.json",
                "依存関係を DAG 化しトポロジカル順に整列。\n"
                "現状と比較し、差分を CREATE / UPDATE / SKIP / CONFLICT / BLOCKED / ERROR "
                "として理由付きで出力。\n"
                "SKIP ＝ 一致（冪等）。SAP は1バイトも変更しない。"))
svg.append(node(BX[2], Y["B"], BW, BH, C["blue"], "④ 承認ゲート（強制）", "GATE",
                "sapcfg/orchestrator.py",
                "gate = UPDATE / CONFLICT / needs_approval。\n"
                "各行の実行直前に承認の有無を確認し、未承認なら1ステップも実行しない（MANUAL）。\n"
                "実行前に target の system / client 三重チェックと kill switch を確認。"))
svg.append(node(BX[3], Y["B"], BW, BH, C["blue"], "⑤ Apply 実行（状態機械）", "APPLY",
                "orchestrator.py · steps/fi_basic.py",
                "1項目ごとに：現状読取 → 画面操作 → 保存。\n"
                "attempts ≤ 3（初回＋自動リトライ2回）。\n"
                "リトライ可：LOCK / TRANSIENT / NAVIGATION のみ。\n"
                "結果：SUCCESS / FAILED / MANUAL / BLOCKED / ABORTED。"))
svg.append(node(BX[4], Y["B"], BW, BH, C["blue"], "⑥ 読み戻し検証", "VERIFY",
                "sapcfg/verify.py",
                "保存後の実値を eq / neq / contains / in / regex で期待値と比較。\n"
                "SKIP は Plan 時点で verified 扱い。\n"
                "不一致は FAILED（リトライしない）→ 人間キュー。\n"
                "＝「本当に書けたか」を必ず実値で確かめる。"))
svg.append(node(BX[5], Y["B"], BW, BH, C["blue"], "⑦ 証跡 & レポート", "STORE · REPORT",
                "sapcfg/store.py · reporter.py",
                "runs/<run_id>/ に plan.json・events.jsonl（全イベント）・run.sqlite（再開可）・"
                "evidence/*.svg（画面証跡）・report.md。\n"
                "再実行では SUCCESS をスキップし、途中から再開できる。"))

# ---- lane 3: SAP side ------------------------------------------------------
YC, HC = 524, 152
svg.append(band(YC, HC, C["sap"], C["green"], "LANE 3 · SAP 側（Phase 1 = Mock SAP GUI）",
                "このマシンから出る唯一の接続先。実 SAP DB への書き込みコードは存在しない"))
Y["C"] = 546
svg.append(node(44, Y["C"], 740, 96, C["green"], "Phase 2 ロードマップ：実 SAP GUI Scripting チャネル",
                "ROADMAP", "sapcfg/gui/win_gui.py（Windows 専用）",
                "① Windows ＋ SAP GUI Scripting 有効化、② SAPCFG_ALLOW_REAL_SAP=1、"
                "③ client release ごとに画面マップを1回記録。3条件が揃うまで import すら不可。\n"
                "揃った後は、同じ template → plan → 承認 → apply が実機を対象にする"
                "（Transport 連携は Phase 3）。", dashed=True))
svg.append(node(854, Y["C"], 240, 96, C["green"], "Mock SAP GUI ドライバ", "MOCK",
                "sapcfg/gui/mock.py",
                "画面カタログ通りに歩進し、in-process の設定ストアを更新。"
                "障害注入（例：E071K ロック）でリトライ経路も再現できる。"))
svg.append(node(1124, Y["C"], 240, 96, C["green"], "設定ストア（読取対象）", "STATE",
                "in-process（実 SAP 非接続）",
                "読み戻し検証が参照する唯一の状態。実 SAP DB への INSERT / UPDATE SQL は"
                "コード上に存在しない。"))

# ---- lane 4: guard rails ---------------------------------------------------
YD, HD = 702, 124
svg.append(band(YD, HD, C["guard"], C["indigo"], "LANE 4 · 横断ガードレール（Plan / Apply の全ステップに適用）"))
Y["D"] = 734
GX = [44, 447, 850, 1253]
GW, GH = 383, 80
guards = [
    ("Kill Switch（即時中断）", "runs/KILL マーカー / .kill_switch / SAPCFG_KILL_SWITCH=1 "
     "→ 残りのステップをすべて ABORTED にする。"),
    ("Target 三重チェック（§8）", "各ステップ実行の直前に system / client をプラン対象と照合。"
     "不一致なら run 全体を ABORTED にする。"),
    ("アダプタ・ガードと入力の禁止事項", "win_gui.py は Windows ＋ SAPCFG_ALLOW_REAL_SAP=1 が"
     "無ければ import 不可。テンプレートに資格情報・SQL・制御ID は書けない。"),
    ("Error KB（§7.2）＋ 26 オフライン単体テスト", "未知エラーは pending.json へ起案"
     "（auto_fix_allowed=false / High リスク / 要コンサル承認）。"),
]
for x, (title, body) in zip(GX, guards):
    svg.append(f'<rect x="{x}" y="{Y["D"]}" width="{GW}" height="{GH}" rx="10" fill="#fff" '
               f'stroke="{C["line"]}"/>')
    svg.append(f'<rect x="{x}" y="{Y["D"]}" width="{GW}" height="4" rx="2" fill="{C["indigo"]}"/>')
    svg.append(t(x + 14, Y["D"] + 23, title, 11.6, C["blue_dk"], "600"))
    glines = wrap(body, GW - 34, 10.1)
    if len(glines) > 3:
        WARN.append(f"guard card body truncated: {title!r} ({len(glines)} lines > 3)")
    for i, ln in enumerate(glines[:3]):
        svg.append(t(x + 14, Y["D"] + 40 + i * 13.2, ln, 10.1, C["ink2"]))

# ---- lane 5: states + commands --------------------------------------------
YE, HE = 844, 110
svg.append(band(YE, HE, C["state"], C["mut"], "LANE 5 · 状態カタログと操作"))
svg.append(t(44, YE + 46, "Plan の差分：", 10.4, C["ink2"], "600"))
CMDX = 950
x = 44 + tw("Plan の差分：", 10.4) + 6
for label, col in STATUS:
    svg.append(chip(x, YE + 34, label, col, size=9.5, h=16, pad=9))
    x += tw(label, 9.5) + 16 + 6
svg.append(t(44, YE + 74, "実行の結果：", 10.4, C["ink2"], "600"))
x = 44 + tw("実行の結果：", 10.4) + 6
for label, col in RESULT:
    svg.append(chip(x, YE + 62, label, col, size=9.5, h=16, pad=9))
    x += tw(label, 9.5) + 16 + 6
if x > CMDX - 30:
    WARN.append(f"state chips row overflow: ends at x={x:.0f}, CLI block starts at {CMDX}")


svg.append(t(CMDX, YE + 27, "CLI", 10.4, C["blue_dk"], "700"))
cmds = [
    "uv run python run.py plan                                  # 差分のみ（書き込みなし）",
    "uv run python run.py apply --run <run_id> --approve <item_id>",
    "uv run python run.py report --run <run_id>   /   run.py demo",
    "uv run python webui/server.py --port 8912    # コンソール（SAP Fiori 風 UI）",
]
for i, c in enumerate(cmds):
    y = YE + 44 + i * 15
    svg.append(f'<rect x="{CMDX}" y="{y - 10.6}" width="686" height="14.4" rx="4" fill="#eef3fa"/>')
    svg.append(t(CMDX + 7, y, c, 9.6, "#2456a6", font=MONO))

# ---- connectors ------------------------------------------------------------
A_HUM, B_TOP, B_BOT = Y["A"], Y["B"], Y["B"] + BH
B_MID = Y["B"] + 60
svg.append(arrow(164, A_HUM + 104, 164, B_TOP))                       # A1 -> B1
svg.append(arrow(680, B_TOP, 680, A_HUM + 104, C["orange"]))          # B3 -> A2 (request)
svg.append(t(672, 242, "承認要求", 9.6, C["orange"], "600", anchor="end"))
svg.append(arrow(728, A_HUM + 104, 728, B_TOP, C["orange"]))          # A2 -> B3 (grant)
svg.append(t(736, 242, "承認 + consent", 9.6, C["orange"], "600"))
svg.append(arrow(1244, B_TOP, 1244, A_HUM + 104, C["orange"]))        # B5 -> A3
svg.append(t(1252, 242, "不一致 → 人間キュー", 9.6, C["orange"], "600"))
svg.append(arrow(1514, B_TOP, 1514, A_HUM + 104, C["orange"]))        # B6 -> A4
svg.append(t(1522, 242, "report.md", 9.6, C["orange"], "600"))

for i in range(5):                                                    # B chain
    svg.append(arrow(BX[i] + BW + 2, B_MID, BX[i + 1] - 2, B_MID, C["blue"]))
svg.append(path(f"M1180,{B_BOT} V500 H1046 V{B_BOT}", C["amber"], 1.8, dash=True))  # retry loop
svg.append(t(1105, 494, "自動リトライ ≤ 2", 10, C["amber"], "600", anchor="middle"))
svg.append(arrow(900, B_BOT, 900, Y["C"], C["green"], dbl=True))      # B4 <-> mock GUI
svg.append(t(906, 498, "GUI 操作 / 状態読取", 9.6, C["green"], "600"))
svg.append(arrow(1290, Y["C"], 1290, B_BOT, C["green"]))              # store -> verify
svg.append(t(1296, 498, "読み戻し値", 9.6, C["green"], "600"))

svg.append("</svg>")
SVG = "\n".join(svg)

(OUT / "system_flow.svg").write_text(
    '<?xml version="1.0" encoding="UTF-8"?>\n' + SVG + "\n", encoding="utf-8")

# ---- HTML page (Fiori Horizon-ish) ----------------------------------------
HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>SAP Config Automation · 運用フロー構成図</title>
<style>
  :root{
    --brand:#0070f2; --brand-dk:#1e3a5f; --bg:#f5f6f7; --card:#fff; --line:#dbe3ec;
    --ink:#0f1c2e; --ink2:#33465c; --mut:#64748b; --green:#1b7f3b; --amber:#b7791f;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font:14px/1.6 '72','IBM Plex Sans',-apple-system,'Hiragino Sans','Yu Gothic UI','PingFang SC','Segoe UI',sans-serif}
  .shell{height:44px;background:var(--brand-dk);color:#fff;display:flex;align-items:center;
    gap:12px;padding:0 16px;position:sticky;top:0;z-index:10}
  .shell .brand{font-weight:700;font-size:14px;letter-spacing:.2px}
  .shell .sep{width:1px;height:20px;background:rgba(255,255,255,.25)}
  .shell .crumb{font-size:13px;color:#c9d8e8}
  .shell .grow{flex:1}
  .badge{font-size:11px;padding:2px 9px;border-radius:99px;background:rgba(255,255,255,.16)}
  .badge.ok{background:#0e6b3a}
  .page{max-width:1740px;margin:0 auto;padding:18px 20px 40px}
  .hdr{display:flex;align-items:flex-start;gap:16px;flex-wrap:wrap;margin:6px 0 14px}
  .hdr h1{margin:0 0 4px;font-size:22px;font-weight:600;color:var(--brand-dk)}
  .hdr p{margin:0;color:var(--ink2);font-size:13.5px;max-width:1040px}
  .btns{display:flex;gap:8px;flex-wrap:wrap;margin-left:auto}
  a.act,button.act{display:inline-flex;align-items:center;gap:6px;height:34px;padding:0 16px;
    border-radius:8px;border:1px solid transparent;background:var(--brand);color:#fff;
    font:600 13.5px inherit;cursor:pointer;text-decoration:none}
  a.act.ghost,button.act.ghost{background:#fff;color:var(--brand);border-color:var(--brand)}
  a.act:focus-visible,button.act:focus-visible{outline:2px solid var(--brand-dk);outline-offset:2px}
  .tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin:0 0 14px}
  .tile{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;
    box-shadow:0 1px 3px rgba(15,28,46,.05)}
  .tile .l{font-size:11.5px;color:var(--mut);text-transform:uppercase;letter-spacing:.4px}
  .tile .v{font-size:19px;font-weight:600;color:var(--brand);margin:3px 0 2px}
  .tile .s{font-size:12px;color:var(--ink2)}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;
    box-shadow:0 1px 3px rgba(15,28,46,.05)}
  .card h2{margin:2px 0 10px;font-size:15px;color:var(--brand-dk);font-weight:600}
  .card p.lead{margin:0 0 10px;color:var(--ink2);font-size:12.8px}
  svg.flow{width:100%;height:auto;display:block}
  .legend{display:flex;gap:18px;flex-wrap:wrap;margin-top:12px;font-size:12px;color:var(--ink2)}
  .legend b{color:var(--brand-dk)}
  footer{color:#8aa0b8;font-size:11.5px;padding:14px 2px}
</style>
</head>
<body>
<div class="shell">
  <span class="brand">SAP Config Automation</span>
  <span class="sep"></span>
  <span class="crumb">運用フロー構成図</span>
  <span class="grow"></span>
  <span class="badge ok">adapter: MOCK SAP GUI</span>
  <span class="badge">Phase 1 · 実 SAP 非接続</span>
</div>
<div class="page">
  <div class="hdr">
    <div>
      <h1>運用フロー構成図 — Configuration as Code</h1>
      <p>標準 SAP カスタマイズ（OB13 / OB29 / OBY6 / OX02 / OX10 など）をテンプレート（YAML）として
      コード化し、<b>検証 → Plan（読み取り専用の差分） → 人による per-item 承認 → Apply（状態機械） →
      読み戻し検証 → 証跡とレポート</b> の順に流すパイプラインです。Phase 1 の実行先は
      in-process の Mock SAP GUI だけで、実 SAP へは接続しません。</p>
    </div>
    <div class="btns">
      <a class="act" href="system_flow.svg" download>SVG をダウンロード</a>
      <button class="act ghost" onclick="window.print()">印刷 / PDF</button>
    </div>
  </div>

  <div class="tiles">
    <div class="tile"><div class="l">人の判断が必要な箇所</div><div class="v">3</div>
      <div class="s">テンプレート作成・per-item 承認・例外/レポート確認</div></div>
    <div class="tile"><div class="l">自動リトライ上限</div><div class="v">2 回</div>
      <div class="s">LOCK / TRANSIENT / NAVIGATION のみ。他は人間キューへ</div></div>
    <div class="tile"><div class="l">読み戻し検証</div><div class="v">全キー項目</div>
      <div class="s">eq / neq / contains / in / regex で保存後の実値を比較</div></div>
    <div class="tile"><div class="l">証跡</div><div class="v">100% 保存</div>
      <div class="s">plan.json・events.jsonl・run.sqlite・evidence/*.svg・report.md</div></div>
    <div class="tile"><div class="l">オフライン単体テスト</div><div class="v">26 件</div>
      <div class="s">unittest・Mock データ・ネットワーク不要</div></div>
  </div>

  <div class="card">
    <h2>End-to-end flow（実行主体 / レイヤ別）</h2>
    <p class="lead">青＝パイプライン、橙＝人のアクション、緑＝SAP 側（Mock）、紫＝全ステップに効く横断ガードレール。
      点線の矢印は自動リトライ、実線は通常の流れです。</p>
    __SVG__
    <div class="legend">
      <span><b>冪等性：</b>一致すれば SKIP（SKIPPED_IDEMPOTENT）、再実行時は SUCCESS を飛ばして再開</span>
      <span><b>有限の自己修復：</b>一時エラーのみリトライ、境界を超えたら必ず人へ</span>
      <span><b>可監査性：</b>before / after 値と分類済みメッセージを全件保存</span>
    </div>
  </div>
  <footer>SAP Config Automation · docs/build_flow_diagram.py が生成 / デザイントークンは
    docs/system_flow.svg と webui/index.html で共通（SAP S/4 系の Fiori 風スタイル）。</footer>
</div>
</body>
</html>
"""
(OUT / "system_flow.html").write_text(HTML.replace("__SVG__", SVG), encoding="utf-8")
print("wrote:", OUT / "system_flow.svg", OUT / "system_flow.html")
if WARN:
    print("\n! layout warnings (self-check):")
    for wmsg in WARN:
        print("  -", wmsg)
    raise SystemExit(1)
print("layout self-check: OK (no text overflow)")
