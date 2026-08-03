# -*- coding: utf-8 -*-
"""DBT Guardian — gera index.html único com 4 abas (stdlib only)."""
from __future__ import annotations

import html as H
import json


def _esc(s) -> str:
    return H.escape("" if s is None else str(s))


def _badge(status: str) -> str:
    cls = {
        "NOVO": "new",
        "ALTERADO": "warn",
        "REMOVIDO": "block",
        "IGUAL": "ok",
    }.get(status, "ok")
    labels = {
        "NOVO": "Criar",
        "ALTERADO": "Atualizar",
        "REMOVIDO": "Verificar",
        "IGUAL": "Pronto",
    }
    return f'<span class="badge {cls}">{_esc(labels.get(status, status))}</span>'


def _sev(sev: str) -> str:
    cls = {"critical": "block", "warning": "warn", "info": "info", "safe": "ok"}.get(sev, "info")
    return f'<span class="badge {cls}">{_esc(sev)}</span>'


def _cards(checklist: list) -> str:
    parts = []
    for c in checklist:
        if c["status"] == "IGUAL":
            continue
        diff_html = ""
        if c.get("diff"):
            items = "".join(f"<li>{_esc(d)}</li>" for d in c["diff"])
            diff_html = f"<p><strong>O que mudou:</strong></p><ul>{items}</ul>"
        impact = ""
        if c.get("impact"):
            lis = "".join(f"<li>{_esc(i)}</li>" for i in c["impact"][:12])
            impact = f"<p><strong>Se alterar, estes podem quebrar:</strong></p><ul>{lis}</ul>"
        elif c["status"] in {"ALTERADO", "REMOVIDO"}:
            impact = "<p><em>Ninguém depende deste arquivo.</em></p>"

        done = "checked" if c.get("done") else ""
        cid = _esc(c["name"])
        parts.append(
            f"""
<article class="card status-{_esc(c['status'].lower())}">
  <header>
    {_badge(c['status'])}
    <h3>{cid}</h3>
  </header>
  <p class="hint">{_esc(c.get('hint',''))}</p>
  <p><strong>Onde:</strong> <code title="{_esc(c.get('path',''))}">{_esc(c.get('path',''))}</code></p>
  <p><strong>Camada:</strong> {_esc(c.get('layer',''))}
     · <strong>Ordem sugerida:</strong> {_esc(c.get('suggested_order', '—'))}</p>
  {diff_html}
  {impact}
  <label class="check">
    <input type="checkbox" data-item="{cid}" {done}> Marcar feito
  </label>
</article>
"""
        )
    if not parts:
        return '<p class="empty">Nada pendente — todos os arquivos estão sincronizados.</p>'
    return "\n".join(parts)


def _igual_section(checklist: list) -> str:
    iguais = [c for c in checklist if c["status"] == "IGUAL"]
    if not iguais:
        return ""
    lis = "".join(f"<li><code>{_esc(c['name'])}</code> — {_esc(c.get('path',''))}</li>" for c in iguais[:50])
    more = f"<li>… e mais {len(iguais)-50}</li>" if len(iguais) > 50 else ""
    return f"""
<details class="ok-box">
  <summary>Pronto — nada a fazer ({len(iguais)} arquivo(s))</summary>
  <ul>{lis}{more}</ul>
</details>
"""


def _wizard(session: dict) -> str:
    s = session["summary"]
    criticals = [w for w in session["warnings"] if w["severity"] == "critical"]
    novos = [c for c in session["checklist"] if c["status"] == "NOVO"]
    alts = [c for c in session["checklist"] if c["status"] == "ALTERADO"]
    rems = [c for c in session["checklist"] if c["status"] == "REMOVIDO"]

    def step(num, title, count, items_html, cls=""):
        mark = "✓" if count == 0 else f"{count} pendente(s)"
        return f"""
<section class="step {cls}">
  <h3>Passo {num} — {title} <span class="pill">{mark}</span></h3>
  {items_html}
</section>
"""

    c_html = "<p class=\"ok-msg\">Nenhum bloqueio. Pode seguir.</p>"
    if criticals:
        lis = "".join(
            f"<li><strong>{_esc(w['model'])}:</strong> {_esc(w['message'])}</li>"
            for w in criticals
        )
        c_html = f"<ul class=\"block-list\">{lis}</ul>"

    def mini(items, verb):
        if not items:
            return f"<p class=\"ok-msg\">Nenhum arquivo para {verb}.</p>"
        lis = "".join(
            f"<li><code>{_esc(i['name'])}</code> → <code>{_esc(i['path'])}</code></li>"
            for i in items
        )
        return f"<ul>{lis}</ul>"

    order = session.get("order") or []
    order_html = ""
    if order:
        lis = "".join(f"<li>{i+1}. <code>{_esc(n)}</code></li>" for i, n in enumerate(order))
        order_html = f"<p><strong>Ordem sugerida (do início ao fim do fluxo):</strong></p><ol>{lis}</ol>"

    return (
        step(1, "Resolver bloqueios", s["critical"], c_html, "step-block" if s["critical"] else "")
        + step(2, "Criar arquivos novos", len(novos), mini(novos, "criar") + order_html)
        + step(3, "Atualizar / verificar existentes", len(alts) + len(rems),
               mini(alts, "atualizar") + mini(rems, "verificar"))
        + """
<section class="step">
  <h3>Passo 4 — Validar no SaaS e BigQuery</h3>
  <p>Depois de copiar/atualizar os arquivos no projeto DBT:</p>
  <label class="check"><input type="checkbox" data-item="__saas__"> SaaS OK — validei no ambiente SaaS</label>
  <label class="check"><input type="checkbox" data-item="__bq__"> BQ OK — validei no BigQuery</label>
</section>
"""
    )


def _flow(session: dict) -> str:
    chains = session.get("flow_chains") or []
    if not chains:
        # fallback: listar por camada
        layers = {}
        for c in session["checklist"]:
            if c["status"] == "REMOVIDO":
                continue
            layers.setdefault(c["layer"], []).append(c)
        order_layers = ["source", "seed", "sample", "staging", "intermediate", "aggregate", "mart", "other"]
        parts = []
        for lay in order_layers:
            if lay not in layers:
                continue
            badges = " ".join(
                f'<span class="node">{_badge(x["status"])} {_esc(x["name"])}</span>'
                for x in layers[lay]
            )
            parts.append(f"<div class=\"layer\"><h4>{_esc(lay)}</h4><div class=\"nodes\">{badges}</div></div>")
        return "\n".join(parts) or "<p class=\"empty\">Sem fluxo para exibir.</p>"

    return "".join(
        f'<div class="chain"><code>{_esc(ch)}</code></div>' for ch in chains
    )


def _alerts(session: dict) -> str:
    warnings = session.get("warnings") or []
    if not warnings:
        w_html = "<p class=\"ok-msg\">Nenhum alerta nesta sessão.</p>"
    else:
        blocks = []
        for w in warnings:
            action = f"<p class=\"action\"><strong>O que fazer:</strong> {_esc(w.get('action',''))}</p>" if w.get("action") else ""
            blocks.append(
                f"""
<article class="card alert-{_esc(w['severity'])}">
  <header>{_sev(w['severity'])} <strong>{_esc(w.get('label',''))}</strong>
    — <code>{_esc(w.get('model',''))}</code></header>
  <p>{_esc(w.get('message',''))}</p>
  {action}
</article>
"""
            )
        w_html = "\n".join(blocks)

    timeline = session.get("timeline") or []
    if timeline:
        lis = "".join(
            f"<li><strong>{_esc(t.get('card_id',''))}</strong> — {_esc(t.get('timestamp',''))} "
            f"(críticos: {_esc(t.get('critical_count',0))}, pendentes: {_esc(t.get('pending_count', t.get('warning_count',0)))})</li>"
            for t in timeline[-20:]
        )
        t_html = f"<h3>Histórico de cards</h3><ul>{lis}</ul>"
    else:
        t_html = "<h3>Histórico de cards</h3><p class=\"empty\">Nenhum snapshot ainda. Finalize um card com S no terminal.</p>"

    return w_html + t_html


def render(session: dict) -> str:
    s = session["summary"]
    total = s["pending"] + s["igual"]
    done_auto = s["igual"]
    pct = int(100 * done_auto / total) if total else 100
    msg = session.get("message") or ""
    card = _esc(session.get("card_id", "CARD"))
    data = json.dumps(session, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DBT Guardian — {card}</title>
<style>
:root {{
  --bg:#1a1f2e; --panel:#232a3b; --text:#e8ecf4; --muted:#9aa3b5;
  --ok:#3d9a6a; --new:#3b82c4; --warn:#d4a017; --block:#d64545; --info:#6b7c93;
  --line:#2e3648; --focus:#5b8def;
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0; font-family: "Segoe UI", "Trebuchet MS", sans-serif;
  background: linear-gradient(160deg, #141824 0%, #1a1f2e 40%, #1e2838 100%);
  color:var(--text); min-height:100vh; font-size:16px; line-height:1.5;
}}
header.app {{
  padding:1.25rem 1.5rem; border-bottom:1px solid var(--line);
  background:rgba(0,0,0,.25);
}}
header.app h1 {{ margin:0 0 .35rem; font-size:1.6rem; letter-spacing:.02em; }}
header.app .sub {{ color:var(--muted); }}
.progress {{
  margin-top:.85rem; background:#0f131c; border-radius:8px; height:14px; overflow:hidden;
  border:1px solid var(--line);
}}
.progress > span {{
  display:block; height:100%; background:linear-gradient(90deg, var(--ok), #4fc08d);
  width:{pct}%; transition:width .3s;
}}
.msg {{
  margin:1rem 1.5rem 0; padding:.85rem 1rem; border-radius:10px;
  background:var(--panel); border-left:4px solid var(--focus);
}}
.tabs {{ display:flex; gap:.5rem; padding:1rem 1.5rem 0; flex-wrap:wrap; }}
.tabs label {{
  padding:.55rem 1rem; border-radius:999px; background:var(--panel);
  border:1px solid var(--line); cursor:pointer; color:var(--muted); user-select:none;
}}
.tabs input {{ display:none; }}
.tabs input:checked + label {{
  color:#fff; border-color:var(--focus); background:#2a3550; font-weight:600;
}}
.panel {{ display:none; padding:1.25rem 1.5rem 3rem; }}
#t1:checked ~ .p1, #t2:checked ~ .p2, #t3:checked ~ .p3, #t4:checked ~ .p4 {{ display:block; }}
.grid {{ display:grid; gap:1rem; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); }}
.card {{
  background:var(--panel); border:1px solid var(--line); border-radius:12px;
  padding:1rem 1.1rem; border-top:3px solid var(--muted);
}}
.card.status-novo {{ border-top-color:var(--new); }}
.card.status-alterado {{ border-top-color:var(--warn); }}
.card.status-removido {{ border-top-color:var(--block); }}
.card.alert-critical {{ border-top-color:var(--block); }}
.card.alert-warning {{ border-top-color:var(--warn); }}
.card.alert-info {{ border-top-color:var(--info); }}
.card.alert-safe {{ border-top-color:var(--ok); }}
.card h3 {{ margin:.35rem 0; font-size:1.15rem; }}
.card header {{ display:flex; align-items:center; gap:.6rem; flex-wrap:wrap; }}
.hint {{ color:var(--muted); margin:.4rem 0 .7rem; }}
.badge {{
  display:inline-block; padding:.15rem .55rem; border-radius:6px; font-size:.78rem;
  font-weight:700; text-transform:uppercase; letter-spacing:.04em; color:#fff;
}}
.badge.ok {{ background:var(--ok); }}
.badge.new {{ background:var(--new); }}
.badge.warn {{ background:var(--warn); color:#1a1a1a; }}
.badge.block {{ background:var(--block); }}
.badge.info {{ background:var(--info); }}
.step {{
  background:var(--panel); border:1px solid var(--line); border-radius:12px;
  padding:1rem 1.2rem; margin-bottom:1rem;
}}
.step.step-block {{ border-color:var(--block); }}
.pill {{
  font-size:.8rem; font-weight:600; color:var(--muted); margin-left:.4rem;
}}
.check {{ display:block; margin:.55rem 0; cursor:pointer; }}
.check input {{ transform:scale(1.2); margin-right:.45rem; }}
code {{
  background:#0f131c; padding:.1rem .35rem; border-radius:4px; font-size:.9em;
  word-break:break-all;
}}
.chain {{
  background:var(--panel); border:1px solid var(--line); border-radius:10px;
  padding:.85rem 1rem; margin-bottom:.7rem; overflow-x:auto;
}}
.layer {{ margin-bottom:1.2rem; }}
.nodes {{ display:flex; flex-wrap:wrap; gap:.5rem; }}
.node {{
  background:#0f131c; border:1px solid var(--line); border-radius:8px;
  padding:.4rem .65rem;
}}
.ok-box {{ margin-top:1.2rem; color:var(--muted); }}
.ok-msg {{ color:var(--ok); }}
.empty {{ color:var(--muted); }}
.block-list {{ color:#ffb4b4; }}
.stats {{ display:flex; flex-wrap:wrap; gap:.6rem; margin-top:.75rem; }}
.stat {{
  background:#0f131c; border:1px solid var(--line); border-radius:8px;
  padding:.4rem .75rem; font-size:.9rem;
}}
.stat b {{ color:#fff; }}
details.help {{ margin:1rem 1.5rem; color:var(--muted); }}
details.help summary {{ cursor:pointer; color:var(--text); font-weight:600; }}
ul, ol {{ padding-left:1.2rem; }}
.action {{ color:var(--muted); }}
footer {{
  padding:1rem 1.5rem 2rem; color:var(--muted); font-size:.85rem;
  border-top:1px solid var(--line);
}}
</style>
</head>
<body>
<header class="app">
  <h1>DBT Guardian</h1>
  <div class="sub">Card <strong>{card}</strong> · {_esc(session.get('timestamp',''))}</div>
  <div class="progress" title="Arquivos já iguais / total"><span></span></div>
  <div class="stats">
    <div class="stat">Criar: <b>{s['novo']}</b></div>
    <div class="stat">Atualizar: <b>{s['alterado']}</b></div>
    <div class="stat">Verificar: <b>{s['removido']}</b></div>
    <div class="stat">Pronto: <b>{s['igual']}</b></div>
    <div class="stat">Bloqueios: <b>{s['critical']}</b></div>
    <div class="stat">Pendentes: <b>{s['pending']}</b></div>
  </div>
</header>

{"<div class='msg'>" + _esc(msg) + "</div>" if msg else ""}

<details class="help">
  <summary>Como usar (leia em 30 segundos)</summary>
  <ol>
    <li>Veja o <strong>Passo 1</strong> — resolva bloqueios (vermelho) primeiro.</li>
    <li>No <strong>Passo 2</strong>, crie os arquivos novos na ordem sugerida (source → sample → stg → int → agg).</li>
    <li>No <strong>Passo 3</strong>, atualize arquivos que já existem (veja o que mudou no card).</li>
    <li>Marque cada item como feito na aba <strong>Arquivos</strong>.</li>
    <li>Valide no SaaS e no BigQuery (Passo 4).</li>
    <li>No terminal, responda <strong>S</strong> para gravar o snapshot do card.</li>
  </ol>
</details>

<input type="radio" name="tab" id="t1" checked>
<input type="radio" name="tab" id="t2">
<input type="radio" name="tab" id="t3">
<input type="radio" name="tab" id="t4">
<nav class="tabs">
  <label for="t1">Assistente</label>
  <label for="t2">Arquivos</label>
  <label for="t3">Fluxo</label>
  <label for="t4">Alertas</label>
</nav>

<section class="panel p1">
  <h2>O que fazer agora</h2>
  {_wizard(session)}
</section>

<section class="panel p2">
  <h2>Checklist de arquivos</h2>
  <p class="hint">Cada card = uma ação. Marque feito após copiar/atualizar no projeto DBT.</p>
  <div class="grid">
    {_cards(session['checklist'])}
  </div>
  {_igual_section(session['checklist'])}
</section>

<section class="panel p3">
  <h2>Fluxo de dados</h2>
  <p class="hint">Caminho sugerido: origem → amostra (1%) → staging → intermediário → final.</p>
  {_flow(session)}
</section>

<section class="panel p4">
  <h2>Alertas</h2>
  {_alerts(session)}
</section>

<footer>
  DBT Guardian · somente leitura no repositório DBT · Python stdlib · sem pip/npm
</footer>

<script>
const S = {data};
const KEY = "dbt_guardian_" + (S.card_id || "card");
function load() {{
  try {{ return JSON.parse(localStorage.getItem(KEY) || "{{}}"); }} catch(e) {{ return {{}}; }}
}}
function save(st) {{ localStorage.setItem(KEY, JSON.stringify(st)); }}
(function() {{
  const st = load();
  document.querySelectorAll("input[data-item]").forEach(el => {{
    const id = el.getAttribute("data-item");
    if (st[id]) el.checked = true;
    el.addEventListener("change", () => {{
      st[id] = el.checked;
      save(st);
    }});
  }});
}})();
</script>
</body>
</html>
"""
