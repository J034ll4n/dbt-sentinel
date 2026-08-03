# -*- coding: utf-8 -*-
"""DBT Guardian — gera index.html único com 4 abas (stdlib only)."""
from __future__ import annotations

import html as H
import json


def _esc(s) -> str:
    return H.escape("" if s is None else str(s))


def _badge(status: str, add_only: bool = True, policy_action: str | None = None) -> str:
    action = policy_action or ""
    if add_only and action:
        cls = {
            "create": "new",
            "append": "append",
            "skip": "block",
            "review": "warn",
            "exists": "ok",
            "observe": "block",
        }.get(action, "ok")
        labels = {
            "create": "Criar",
            "append": "Acrescentar",
            "skip": "Não alterar",
            "review": "Revisar",
            "exists": "Já na base",
            "observe": "Não alterar",
        }
        return f'<span class="badge {cls}">{_esc(labels.get(action, action))}</span>'
    if add_only:
        cls = {
            "NOVO": "new",
            "ALTERADO": "block",
            "REMOVIDO": "block",
            "RENOMEADO": "warn",
            "IGUAL": "ok",
        }.get(status, "ok")
        labels = {
            "NOVO": "Criar",
            "ALTERADO": "Não alterar",
            "REMOVIDO": "Não remover",
            "RENOMEADO": "Revisar",
            "IGUAL": "Já na base",
        }
    else:
        cls = {
            "NOVO": "new",
            "ALTERADO": "warn",
            "REMOVIDO": "block",
            "RENOMEADO": "rename",
            "IGUAL": "ok",
        }.get(status, "ok")
        labels = {
            "NOVO": "Criar",
            "ALTERADO": "Atualizar",
            "REMOVIDO": "Verificar",
            "RENOMEADO": "Nome diferente",
            "IGUAL": "Pronto",
        }
    return f'<span class="badge {cls}">{_esc(labels.get(status, status))}</span>'


def _sev(sev: str) -> str:
    cls = {"critical": "block", "warning": "warn", "info": "info", "safe": "ok"}.get(sev, "info")
    return f'<span class="badge {cls}">{_esc(sev)}</span>'


def _kind_chip(kind: str | None) -> str:
    if not kind:
        return ""
    labels = {"F": "Fato (F)", "DIB": "Dimensão (DIB)", "AGGR": "Agregada (AGGR)"}
    return f'<span class="chip kind">{_esc(labels.get(kind, kind))}</span>'


def _add_items_block(c: dict, open_attr: str = "") -> str:
    """Resumo + lista expansível dos itens a acrescer."""
    n = int(c.get("add_count") or 0)
    summary = c.get("add_summary") or ""
    items = c.get("add_items") or []
    ignored = c.get("ignored_changes") or []
    action = c.get("policy_action") or ""

    if action == "create" or c.get("status") == "NOVO":
        head = f"Você vai adicionar <strong>{n}</strong> item(ns) neste arquivo novo."
    elif action == "append":
        head = (
            f"Acrescente <strong>+{n}</strong> item(ns) NOVO(S) neste arquivo que já existe — "
            f"clique para ver a lista. <em>Não reescreva o resto.</em>"
        )
    elif c.get("exists_in_base"):
        head = "Arquivo já existe — nada novo para acrescer com segurança."
    else:
        head = summary or f"{n} item(ns)"

    body = ""
    if items:
        lis = "".join(
            "<li>"
            f"<span class=\"chip\">{_esc(it.get('kind',''))}</span> "
            f"<code>{_esc(it.get('name',''))}</code>"
            + (
                f" → <em>{_esc(it.get('dbt_type'))}</em>"
                if it.get("dbt_type")
                else ""
            )
            + "</li>"
            for it in items
        )
        body = f"<ul class=\"add-list\">{lis}</ul>"
    else:
        body = "<p class=\"empty\">Nenhum item novo listado.</p>"

    ign = ""
    if ignored:
        il = "".join(f"<li>{_esc(x)}</li>" for x in ignored[:12])
        ign = (
            "<p class=\"stop-line\">Não aplique isto no principal (ignore):</p>"
            f"<ul class=\"add-list muted\">{il}</ul>"
        )

    return f"""
<details class="add-box" {open_attr}>
  <summary>{head}</summary>
  <p class="hint">{_esc(summary)}</p>
  {body}
  {ign}
</details>
"""


def _one_card(c: dict, add_only: bool = True) -> str:
    action = c.get("policy_action") or ""
    match_html = ""
    if c.get("match_name"):
        score = int((c.get("match_score") or 0) * 100)
        match_html = (
            f"<p class=\"match\"><strong>Na base use:</strong> "
            f"<code>{_esc(c['match_name'])}</code> "
            f"({score}%) — não crie duplicado.</p>"
        )

    impact = ""
    if action in {"create", "append"} and c.get("impact"):
        lis = "".join(f"<li>{_esc(i)}</li>" for i in c["impact"][:12])
        impact = f"<p><strong>Depois usa:</strong></p><ul>{lis}</ul>"

    deps = c.get("upstream") or []
    up = ""
    if deps:
        chain = " → ".join(_esc(x) for x in deps[-8:])
        up = (
            f"<p class=\"flow-mini\"><strong>Depende de:</strong> {chain} "
            f"→ <code>{_esc(c['name'])}</code></p>"
        )

    do_check = action in {"create", "append"} or not add_only
    check_html = ""
    if do_check:
        done = "checked" if c.get("done") else ""
        cid = _esc(c["name"])
        label = (
            "Marquei como criado no DBT"
            if action == "create"
            else "Marquei os itens novos como acrescentados"
        )
        check_html = f"""
  <label class="check">
    <input type="checkbox" data-item="{cid}" {done}> {_esc(label)}
  </label>"""

    guide = ""
    if action == "append":
        guide = (
            '<p class="append-line">Ação: acrescente <strong>só</strong> os itens novos do card. '
            "Não substitua o código antigo.</p>"
        )
    elif add_only and action in {"skip", "review", "observe"}:
        guide = (
            '<p class="stop-line">Não reescreva o código do arquivo principal '
            "(mesmo que o ZIP mostre erros).</p>"
        )

    open_attr = "open" if action in {"create", "append"} and (c.get("add_count") or 0) else ""
    cid = _esc(c["name"])
    return f"""
<article class="card status-{_esc(c['status'].lower())} action-{_esc(action or 'none')}" id="file-{cid}">
  <header>
    {_badge(c['status'], add_only, action)}
    {_kind_chip(c.get('table_kind'))}
    <h3>{cid}</h3>
  </header>
  <p class="hint">{_esc(c.get('hint',''))}</p>
  {guide}
  {_add_items_block(c, open_attr)}
  {match_html}
  <p><strong>Caminho:</strong> <code title="{_esc(c.get('path',''))}">{_esc(c.get('path',''))}</code></p>
  <p><strong>Camada:</strong> {_esc(c.get('layer',''))}
     {(" · <strong>Negócio:</strong> " + _esc(c['domain'])) if c.get('domain') else ""}
     · <strong>Ordem:</strong> {_esc(c.get('suggested_order', '—'))}</p>
  {up}
  {impact}
  {check_html}
</article>
"""


def _cards(checklist: list, add_only: bool = True) -> str:
    criar = [c for c in checklist if (c.get("policy_action") or ("create" if c["status"] == "NOVO" else "")) == "create"]
    acres = [c for c in checklist if c.get("policy_action") == "append"]
    revisar = [
        c for c in checklist
        if c.get("policy_action") in {"review", "skip", "observe"}
        or (c["status"] in {"REMOVIDO", "RENOMEADO", "ALTERADO"} and c.get("policy_action") not in {"create", "append", "exists"})
    ]
    seen = {c["name"] for c in criar} | {c["name"] for c in acres}
    revisar = [c for c in revisar if c["name"] not in seen]

    def by_domain(items: list) -> list[tuple[str, list]]:
        groups: dict[str, list] = {}
        for c in items:
            d = c.get("domain") or "(sem domínio)"
            groups.setdefault(d, []).append(c)
        # ordenar: domínios nomeados primeiro
        keys = sorted(groups.keys(), key=lambda k: (k.startswith("("), k.lower()))
        return [(k, groups[k]) for k in keys]

    def section(title, subtitle, items, cls=""):
        if not items and cls != "sec-criar":
            return ""
        if not items:
            body = '<p class="ok-msg">Nenhum arquivo neste grupo.</p>'
        else:
            chunks = []
            grouped = by_domain(items)
            multi = len(grouped) > 1
            for dom, subset in grouped:
                grid = '<div class="grid">' + "\n".join(_one_card(c, add_only) for c in subset) + "</div>"
                if multi:
                    chunks.append(
                        f'<div class="domain-block"><h4 class="domain-title">Negócio: {_esc(dom)} '
                        f'<span class="pill">{len(subset)}</span></h4>{grid}</div>'
                    )
                else:
                    chunks.append(grid)
            body = "\n".join(chunks)
        return f"""
<section class="file-sec {cls}">
  <h3>{_esc(title)} <span class="pill">{len(items)}</span></h3>
  <p class="hint">{_esc(subtitle)}</p>
  {body}
</section>
"""

    parts = [
        section(
            "1. Criar",
            "Arquivos que ainda não existem na base — pode criar por completo.",
            criar,
            "sec-criar",
        ),
        section(
            "2. Acrescentar (só o novo)",
            "Arquivo já existe: acrescente APENAS os itens novos do card. Não reescreva o restante.",
            acres,
            "sec-append",
        ),
        section(
            "3. Atenção / Revisar / Não alterar",
            "Não reescreva o principal. Revise nomes diferentes ou mudanças sem itens novos.",
            revisar,
            "sec-review",
        ),
    ]
    html = "\n".join(p for p in parts if p)
    return html or '<p class="empty">Nada pendente — todos os arquivos estão sincronizados.</p>'


def _igual_section(checklist: list) -> str:
    iguais = [c for c in checklist if c["status"] == "IGUAL"]
    if not iguais:
        return ""
    lis = "".join(
        f"<li><code>{_esc(c['name'])}</code> — {_esc(c.get('path',''))}</li>"
        for c in iguais[:50]
    )
    more = f"<li>… e mais {len(iguais)-50}</li>" if len(iguais) > 50 else ""
    return f"""
<details class="ok-box">
  <summary>Já na base — nada a fazer ({len(iguais)} arquivo(s))</summary>
  <ul>{lis}{more}</ul>
</details>
"""


def _ordem(session: dict) -> str:
    """Aba: o que executar em ordem (criar + acrescentar)."""
    order_names = session.get("order") or []
    by_name = {c["name"]: c for c in session.get("checklist") or []}
    actionable = []
    for n in order_names:
        c = by_name.get(n)
        if not c:
            continue
        if c.get("policy_action") in {"create", "append"}:
            actionable.append(c)
    # incluir append/create que não entraram na topo order
    seen = {c["name"] for c in actionable}
    for c in session.get("checklist") or []:
        if c.get("policy_action") in {"create", "append"} and c["name"] not in seen:
            actionable.append(c)
            seen.add(c["name"])

    if not actionable:
        return '<p class="ok-msg">Nada para executar neste card.</p>'

    steps = []
    for i, c in enumerate(actionable, 1):
        action = c.get("policy_action")
        verb = "CRIAR arquivo" if action == "create" else "ACRESCENTAR itens em"
        n = int(c.get("add_count") or 0)
        items = c.get("add_items") or []
        item_lis = ""
        if items:
            item_lis = (
                "<ul class=\"add-list\">"
                + "".join(
                    f"<li><span class=\"chip\">{_esc(it.get('kind',''))}</span> "
                    f"<code>{_esc(it.get('name',''))}</code>"
                    + (f" → {_esc(it.get('dbt_type'))}" if it.get("dbt_type") else "")
                    + "</li>"
                    for it in items[:20]
                )
                + "</ul>"
            )
        deps = c.get("upstream") or []
        dep_html = (
            "<p class=\"flow-mini\"><strong>Depende de:</strong> "
            + (" → ".join(f"<code>{_esc(d)}</code>" for d in deps[-6:]) or "—")
            + "</p>"
        )
        target = c.get("match_name") or c["name"]
        steps.append(
            f"""
<article class="order-step action-{_esc(action)}">
  <div class="step-head">
    <span class="step-num">{i}</span>
    {_badge(c['status'], True, action)}
    <h3>{_esc(verb)} <code>{_esc(target)}</code></h3>
  </div>
  <p class="hint">{_esc(c.get('add_summary') or c.get('hint',''))}</p>
  <p><strong>Path:</strong> <code>{_esc(c.get('path',''))}</code>
     · <strong>Itens:</strong> +{n}</p>
  {dep_html}
  {item_lis}
  <label class="check">
    <input type="checkbox" data-item="ordem::{_esc(c['name'])}"> Feito este passo
  </label>
</article>
"""
        )
    return (
        '<p class="guide">Execute <strong>nesta ordem</strong> (dependências primeiro). '
        "Verde = criar arquivo · Âmbar = acrescer só o novo no arquivo que já existe.</p>"
        + "\n".join(steps)
    )


def _wizard(session: dict) -> str:
    s = session["summary"]
    add_only = session.get("add_only", True)
    criticals = [
        w for w in session["warnings"]
        if w["severity"] == "critical" and not w.get("policy")
    ]
    tax = [
        w for w in session["warnings"]
        if w.get("label") == "Taxonomia" or "DIB" in (w.get("label") or "")
        or "AGGR" in (w.get("label") or "") or w.get("label") == "Fato (F)"
        or "Dimensão" in (w.get("label") or "") or "Agregada" in (w.get("label") or "")
    ]
    novos = [c for c in session["checklist"] if c.get("policy_action") == "create"]
    acres = [c for c in session["checklist"] if c.get("policy_action") == "append"]
    skip = [c for c in session["checklist"] if c.get("policy_action") == "skip"]
    revisar = [c for c in session["checklist"] if c.get("policy_action") == "review"]
    alts = [c for c in session["checklist"] if c["status"] == "ALTERADO"]
    rems = [c for c in session["checklist"] if c["status"] == "REMOVIDO"]
    renames = [c for c in session["checklist"] if c["status"] == "RENOMEADO"]

    def step(num, title, count, items_html, cls=""):
        if count == 0:
            mark = "ok"
            mark_txt = "Pronto"
        else:
            mark = "todo"
            mark_txt = f"{count} item(ns)"
        return f"""
<section class="step {cls}">
  <div class="step-head">
    <span class="step-num">{num}</span>
    <h3>{_esc(title)}</h3>
    <span class="pill {mark}">{mark_txt}</span>
  </div>
  {items_html}
</section>
"""

    def mini(items, empty_msg):
        if not items:
            return f"<p class=\"ok-msg\">{_esc(empty_msg)}</p>"
        lis = "".join(
            f"<li><code>{_esc(i['name'])}</code>"
            + (f" <span class=\"chip kind\">{_esc(i.get('table_kind'))}</span>" if i.get("table_kind") else "")
            + (
                f" <span class=\"chip addn\">+{int(i.get('add_count') or 0)} itens</span>"
                if i.get("add_count")
                else ""
            )
            + f" → <code>{_esc(i['path'])}</code>"
            + (
                f" <em>(= {_esc(i.get('match_name'))})</em>"
                if i.get("match_name")
                else ""
            )
            + (
                f"<div class=\"mini-sum\">{_esc(i.get('add_summary',''))}</div>"
                if i.get("add_summary")
                else ""
            )
            + "</li>"
            for i in items
        )
        return f"<ul class=\"action-list\">{lis}</ul>"

    # Passo 1 — bloqueios reais (refs etc.)
    if criticals:
        lis = "".join(
            f"<li><strong>{_esc(w['model'])}:</strong> {_esc(w['message'])}"
            f"<br><span class=\"action\">→ {_esc(w.get('action',''))}</span></li>"
            for w in criticals
        )
        c_html = f"<ul class=\"block-list\">{lis}</ul>"
    else:
        c_html = "<p class=\"ok-msg\">Nenhum bloqueio técnico nos arquivos novos.</p>"

    order = session.get("order") or []
    order_html = ""
    work = novos + acres
    if order and work:
        work_set = {n["name"] for n in work}
        ordered = [n for n in order if n in work_set]
        if ordered:
            lis = "".join(f"<li>{i+1}. <code>{_esc(n)}</code></li>" for i, n in enumerate(ordered))
            order_html = (
                "<p class=\"guide\">Veja a aba <strong>Ordem</strong> para o passo a passo completo. "
                "Prévia:</p>"
                f"<ol class=\"order-list\">{lis}</ol>"
            )

    create_html = mini(novos, "Nenhum arquivo novo neste card.")
    if novos:
        create_html = (
            "<p class=\"guide\">Arquivos que <strong>ainda não existem</strong> — pode criar por completo.</p>"
            + create_html
        )

    append_html = mini(acres, "Nenhum acrescento neste card.")
    if acres:
        append_html = (
            "<p class=\"guide\">Arquivo já existe: acrescente <strong>somente</strong> os itens novos "
            "listados (não reescreva o SQL antigo).</p>"
            + append_html
        )

    attn = skip + revisar
    if add_only:
        if attn:
            attn_html = (
                "<p class=\"stop-line\">Sem itens novos seguros, ou precisa revisar nome/remoção. "
                "<strong>Não reescreva o principal.</strong></p>"
                + mini(attn, "")
            )
        else:
            attn_html = "<p class=\"ok-msg\">Nada neste grupo.</p>"
        policy_step = step(
            4,
            "Atenção / Não alterar / Revisar",
            len(attn),
            attn_html,
            "step-stop" if attn else "",
        )
    else:
        policy_step = step(
            4,
            "Atualizar / nomes / verificar",
            len(alts) + len(rems) + len(renames),
            mini(alts, "Nada para atualizar.")
            + mini(renames, "Nenhum nome diferente.")
            + mini(rems, "Nada para verificar."),
        )

    # Taxonomia
    if tax:
        lis = "".join(
            f"<li><strong>{_esc(w.get('label',''))}</strong> · "
            f"<code>{_esc(w.get('model',''))}</code>: {_esc(w.get('message',''))}"
            f"<br><span class=\"action\">→ {_esc(w.get('action',''))}</span></li>"
            for w in tax[:40]
        )
        tax_html = (
            "<p class=\"guide\">Se a IA/ZIP fugiu da taxonomia, aparece aqui. "
            "Nomes: minúsculas, <code>_</code>, máx. 35. Tipos: F / DIB / AGGR. "
            "Colunas: prefixo → tipo (id→integer, nm→string, …).</p>"
            f"<ul class=\"tax-list\">{lis}</ul>"
        )
        tax_count = len(tax)
    else:
        tax_html = "<p class=\"ok-msg\">Sem alertas de taxonomia nos arquivos novos.</p>"
        tax_count = 0

    gold = ""
    if add_only:
        gold = """
<div class="gold-rule">
  <strong>Regra de ouro</strong>
  <p>
    <span class="tag new">Criar</span> o que é arquivo novo ·
    <span class="tag append">Acrescentar</span> só itens novos em arquivo que já existe ·
    <span class="tag block">Não reescrever</span> o código antigo (mesmo com erros no ZIP).
  </p>
</div>
"""

    return (
        gold
        + step(1, "Resolver bloqueios dos NOVOS", len(criticals), c_html, "step-block" if criticals else "")
        + step(2, "Criar arquivos novos", len(novos), create_html + order_html, "step-go" if novos else "")
        + step(3, "Acrescentar só o novo (arquivo já existe)", len(acres), append_html, "step-append" if acres else "")
        + policy_step
        + step(5, "Conferir taxonomia (nome e tipos)", tax_count, tax_html)
        + """
<section class="step">
  <div class="step-head">
    <span class="step-num">6</span>
    <h3>Validar no SaaS e BigQuery</h3>
  </div>
  <p class="guide">Depois de criar/acrescentar no DBT (siga a aba <strong>Ordem</strong>):</p>
  <label class="check"><input type="checkbox" data-item="__saas__"> SaaS OK — validei no ambiente SaaS</label>
  <label class="check"><input type="checkbox" data-item="__bq__"> BQ OK — validei no BigQuery</label>
  <p class="hint">No terminal, responda <strong>S</strong>: o Guardian re-lê a base, mostra a verificação final
  (criados / acrescentados / faltando) e só então grava o snapshot.</p>
</section>
"""
    )


def _flow(session: dict) -> str:
    """Lineage com setas SVG que se dividem (1→N) + breadcrumb ao clicar."""
    lin = session.get("lineage") or {}
    nodes = lin.get("nodes") or []
    edges = lin.get("edges") or []
    if not nodes:
        return "<p class=\"empty\">Sem lineage para exibir. Rode a análise com base + workspace.</p>"

    layers = lin.get("layers") or []
    by_layer = {L: [n for n in nodes if n.get("layer") == L] for L in layers}

    lanes = []
    for idx, L in enumerate(layers):
        cards = []
        for n in by_layer.get(L) or []:
            vis = n.get("visual") or "exist"
            addn = int(n.get("add_count") or 0)
            kind = n.get("table_kind") or ""
            used = n.get("used_by") or []
            fan = f'<span class="ln-fan">→ {len(used)}</span>' if len(used) > 1 else ""
            add_chip = f'<span class="ln-add">+{addn}</span>' if addn else ""
            kind_chip = f'<span class="ln-kind">{_esc(kind)}</span>' if kind else ""
            cards.append(
                f"""
<button type="button" class="ln-node vis-{_esc(vis)}" data-node="{_esc(n['id'])}"
  id="lnb-{_esc(n['id']).replace('.', '_')}"
  title="{_esc(n.get('add_summary') or n['id'])}">
  <span class="ln-name">{_esc(n.get('label') or n['id'])}</span>
  <span class="ln-meta">{kind_chip}{add_chip}{fan}</span>
</button>"""
            )
        lanes.append(
            f"""
<div class="ln-lane" data-layer="{_esc(L)}">
  <h4>{_esc(L)}</h4>
  <div class="ln-nodes">{''.join(cards)}</div>
</div>"""
        )

    edge_lis = "".join(
        f"<li><code>{_esc(e['from'])}</code> "
        f"<span class=\"arr\">alimenta →</span> "
        f"<code>{_esc(e['to'])}</code></li>"
        for e in edges[:80]
    )

    return f"""
<div class="lineage-wrap">
  <div class="ln-legend">
    <span><i class="dot exist"></i> Cinza — já existe</span>
    <span><i class="dot new"></i> Verde — criar</span>
    <span><i class="dot append"></i> Âmbar — acrescer</span>
    <span><i class="dot locked"></i> Contorno — não reescrever</span>
  </div>
  <div class="ln-breadcrumb" id="ln-breadcrumb">Clique num card para ver o caminho: origem → … → destino</div>
  <p class="guide">
    As setas saem do card de origem e <strong>se dividem</strong> quando ele alimenta vários.
    Ex.: <code>stg_carros</code> → <code>dib_carro</code> e → <code>f_evento_manutencao</code>.
  </p>
  <div class="lineage-grid">
    <div class="ln-board-wrap" id="ln-board-wrap">
      <svg class="ln-svg" id="ln-svg" xmlns="http://www.w3.org/2000/svg"></svg>
      <div class="ln-board" id="ln-board">
        {''.join(lanes)}
      </div>
    </div>
    <aside class="ln-panel" id="ln-panel" aria-live="polite">
      <div class="ln-panel-empty">
        <h3>Detalhe do lineage</h3>
        <p>Selecione um arquivo para ver: depende de → este → alimenta (com setas).</p>
      </div>
    </aside>
  </div>
  <details class="dep-list"><summary>Lista textual ({len(edges)} ligação(ões))</summary>
    <ul>{edge_lis or '<li>Sem ligações.</li>'}</ul>
  </details>
</div>
"""


def _alerts(session: dict) -> str:
    warnings = session.get("warnings") or []
    if not warnings:
        w_html = "<p class=\"ok-msg\">Nenhum alerta nesta sessão.</p>"
    else:
        blocks = []
        for w in warnings:
            action = (
                f"<p class=\"action\"><strong>O que fazer:</strong> {_esc(w.get('action',''))}</p>"
                if w.get("action")
                else ""
            )
            pol = ' <span class="chip">política</span>' if w.get("policy") else ""
            blocks.append(
                f"""
<article class="card alert-{_esc(w['severity'])}">
  <header>{_sev(w['severity'])} <strong>{_esc(w.get('label',''))}</strong>{pol}
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
            f"(críticos: {_esc(t.get('critical_count',0))}, "
            f"pendentes: {_esc(t.get('pending_count', t.get('warning_count',0)))})</li>"
            for t in timeline[-20:]
        )
        t_html = f"<h3>Histórico de cards</h3><ul>{lis}</ul>"
    else:
        t_html = (
            "<h3>Histórico de cards</h3>"
            "<p class=\"empty\">Nenhum snapshot ainda. Finalize um card com S no terminal.</p>"
        )

    return w_html + t_html


def render(session: dict) -> str:
    s = session["summary"]
    add_only = session.get("add_only", True)
    total = s.get("novo", 0) + s.get("igual", 0) if add_only else (
        s.get("pending", 0) + s.get("igual", 0)
    )
    done_auto = s.get("igual", 0)
    # progresso: foco em quantos novos vs já ok na base (só visual)
    work = s.get("novo", 0) if add_only else s.get("pending", 0)
    pct = 100 if work == 0 else int(100 * done_auto / max(total, 1))
    msg = session.get("message") or ""
    card = _esc(session.get("card_id", "CARD"))
    data = (
        json.dumps(session, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )

    legend = """
<div class="legend">
  <span><i class="dot new"></i> Verde = criar arquivo novo</span>
  <span><i class="dot append"></i> Âmbar = acrescer só o novo</span>
  <span><i class="dot block"></i> Vermelho = não reescrever</span>
  <span><i class="dot ok"></i> Neutro = já igual</span>
</div>
""" if add_only else ""

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DBT Guardian — {card}</title>
<style>
:root {{
  --bg0:#f3f1eb;
  --bg1:#e7eef2;
  --ink:#1c2430;
  --muted:#5c6b7a;
  --panel:#fffcf7;
  --line:#d5dde6;
  --new:#1f7a4d;
  --new-bg:#e5f5ec;
  --block:#b42318;
  --block-bg:#fdecea;
  --warn:#9a6700;
  --warn-bg:#fff6e0;
  --ok:#3d6b5a;
  --ok-bg:#eef6f2;
  --info:#3d5a80;
  --focus:#2f6fed;
  --shadow:0 10px 30px rgba(28,36,48,.06);
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0;
  font-family: Candara, "Segoe UI", "Trebuchet MS", sans-serif;
  color:var(--ink);
  background:
    radial-gradient(900px 420px at 8% -10%, #d9ebe3 0%, transparent 55%),
    radial-gradient(700px 380px at 100% 0%, #d5e4f2 0%, transparent 50%),
    linear-gradient(180deg, var(--bg0), var(--bg1));
  min-height:100vh;
  font-size:17px;
  line-height:1.55;
}}
header.app {{
  padding:1.6rem 1.6rem 1.2rem;
  border-bottom:1px solid var(--line);
  background:rgba(255,252,247,.82);
  backdrop-filter:blur(8px);
}}
header.app h1 {{
  margin:0;
  font-family: "Palatino Linotype", "Book Antiqua", Georgia, serif;
  font-size:clamp(1.8rem, 3vw, 2.4rem);
  letter-spacing:-.02em;
  font-weight:700;
}}
header.app .sub {{ color:var(--muted); margin-top:.35rem; }}
.progress {{
  margin-top:1rem; background:#e8edf2; border-radius:999px; height:10px; overflow:hidden;
}}
.progress > span {{
  display:block; height:100%;
  background:linear-gradient(90deg, var(--new), #3daa6d);
  width:{pct}%; transition:width .35s ease;
}}
.legend {{
  display:flex; flex-wrap:wrap; gap:.85rem 1.4rem;
  margin-top:.9rem; color:var(--muted); font-size:.92rem;
}}
.dot {{
  display:inline-block; width:.7rem; height:.7rem; border-radius:50%;
  margin-right:.35rem; vertical-align:middle;
}}
.dot.new {{ background:var(--new); }}
.dot.block {{ background:var(--block); }}
.dot.ok {{ background:var(--ok); }}
.msg {{
  margin:1rem 1.5rem 0; padding:1rem 1.15rem; border-radius:14px;
  background:var(--panel); border:1px solid var(--line);
  box-shadow:var(--shadow); border-left:5px solid var(--focus);
}}
.gold-rule {{
  background:linear-gradient(135deg, #e8f6ee, #f7faf8);
  border:1px solid #b7dbc8; border-radius:16px;
  padding:1rem 1.2rem; margin-bottom:1.1rem;
}}
.gold-rule p {{ margin:.35rem 0 0; color:var(--muted); }}
.tag {{
  display:inline-block; padding:.05rem .45rem; border-radius:6px;
  font-weight:700; font-size:.85em;
}}
.tag.new {{ background:var(--new-bg); color:var(--new); }}
.tag.block {{ background:var(--block-bg); color:var(--block); }}
.tabs {{ display:flex; gap:.5rem; padding:1rem 1.5rem 0; flex-wrap:wrap; }}
.tabs label {{
  padding:.6rem 1.05rem; border-radius:12px; background:var(--panel);
  border:1px solid var(--line); cursor:pointer; color:var(--muted); user-select:none;
  box-shadow:var(--shadow);
}}
.tabs input {{ display:none; }}
.tabs input:checked + label {{
  color:var(--ink); border-color:var(--new); background:var(--new-bg); font-weight:700;
}}
.panel {{ display:none; padding:1.25rem 1.5rem 3rem; }}
#t1:checked ~ .p1, #t2:checked ~ .p2, #t3:checked ~ .p3, #t4:checked ~ .p4, #t5:checked ~ .p5 {{ display:block; }}
.grid {{ display:grid; gap:1rem; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); }}
.card {{
  background:var(--panel); border:1px solid var(--line); border-radius:16px;
  padding:1rem 1.15rem; box-shadow:var(--shadow);
  border-top:4px solid var(--muted);
}}
.card.status-novo {{ border-top-color:var(--new); background:linear-gradient(180deg, var(--new-bg), var(--panel) 42%); }}
.card.status-alterado, .card.status-renomeado, .card.status-removido {{
  border-top-color:var(--block); background:linear-gradient(180deg, var(--block-bg), var(--panel) 45%);
}}
.card.alert-critical {{ border-top-color:var(--block); }}
.card.alert-warning {{ border-top-color:var(--warn); }}
.card.alert-info {{ border-top-color:var(--info); }}
.card.alert-safe {{ border-top-color:var(--new); }}
.card h3 {{ margin:.3rem 0; font-size:1.12rem; font-family:Georgia, "Palatino Linotype", serif; }}
.card header {{ display:flex; align-items:center; gap:.55rem; flex-wrap:wrap; }}
.hint {{ color:var(--muted); margin:.4rem 0 .7rem; }}
.guide {{ color:var(--ink); margin:.2rem 0 .7rem; }}
.stop-line {{
  color:var(--block); font-weight:700; background:var(--block-bg);
  padding:.45rem .65rem; border-radius:8px;
}}
.badge {{
  display:inline-block; padding:.18rem .55rem; border-radius:7px; font-size:.75rem;
  font-weight:800; text-transform:uppercase; letter-spacing:.04em; color:#fff;
}}
.badge.ok {{ background:var(--ok); }}
.badge.new {{ background:var(--new); }}
.badge.warn {{ background:var(--warn); }}
.badge.block {{ background:var(--block); }}
.badge.rename {{ background:#6b4f9a; }}
.badge.info {{ background:var(--info); }}
.chip {{
  display:inline-block; padding:.1rem .45rem; border-radius:999px;
  background:#eef2f6; color:var(--muted); font-size:.78rem; font-weight:700;
}}
.chip.kind {{ background:#e7f0ff; color:#274c77; }}
.match {{ color:#5b3d7a; }}
.step {{
  background:var(--panel); border:1px solid var(--line); border-radius:16px;
  padding:1.1rem 1.25rem; margin-bottom:1rem; box-shadow:var(--shadow);
}}
.step.step-block {{ border-color:#f0b4ae; }}
.step.step-go {{ border-color:#9dceb3; }}
.step.step-stop {{ border-color:#f0b4ae; }}
.step-head {{ display:flex; align-items:center; gap:.7rem; flex-wrap:wrap; margin-bottom:.55rem; }}
.step-head h3 {{ margin:0; font-size:1.15rem; }}
.step-num {{
  width:1.85rem; height:1.85rem; border-radius:50%;
  display:inline-flex; align-items:center; justify-content:center;
  background:var(--ink); color:#fff; font-weight:800; font-size:.9rem;
}}
.pill {{
  font-size:.78rem; font-weight:700; margin-left:auto;
  padding:.2rem .55rem; border-radius:999px; background:#eef2f6; color:var(--muted);
}}
.pill.ok {{ background:var(--ok-bg); color:var(--ok); }}
.pill.todo {{ background:var(--warn-bg); color:var(--warn); }}
.check {{ display:block; margin:.55rem 0; cursor:pointer; }}
.check input {{ transform:scale(1.15); margin-right:.45rem; }}
code {{
  background:#eef2f6; padding:.12rem .4rem; border-radius:5px; font-size:.9em;
  word-break:break-all;
}}
.chain {{
  background:var(--panel); border:1px solid var(--line); border-radius:12px;
  padding:.85rem 1rem; margin-bottom:.7rem; overflow-x:auto; box-shadow:var(--shadow);
}}
.layer {{ margin-bottom:1.2rem; }}
.nodes {{ display:flex; flex-wrap:wrap; gap:.5rem; }}
.node {{
  background:#fff; border:1px solid var(--line); border-radius:10px;
  padding:.4rem .65rem;
}}
.ok-box {{ margin-top:1.2rem; color:var(--muted); }}
.ok-msg {{ color:var(--new); font-weight:600; }}
.empty {{ color:var(--muted); }}
.block-list {{ color:var(--block); }}
.action {{ color:var(--muted); font-size:.92em; }}
.action-list li, .tax-list li, .order-list li {{ margin:.35rem 0; }}
.stats {{ display:flex; flex-wrap:wrap; gap:.55rem; margin-top:.85rem; }}
.stat {{
  background:var(--panel); border:1px solid var(--line); border-radius:10px;
  padding:.4rem .75rem; font-size:.9rem; box-shadow:var(--shadow);
}}
.stat b {{ color:var(--ink); }}
.stat.hl-new {{ border-color:#9dceb3; background:var(--new-bg); }}
.stat.hl-block {{ border-color:#f0b4ae; background:var(--block-bg); }}
details.help {{
  margin:1rem 1.5rem; color:var(--muted);
  background:var(--panel); border:1px solid var(--line); border-radius:14px;
  padding:.7rem 1rem; box-shadow:var(--shadow);
}}
details.help summary {{ cursor:pointer; color:var(--ink); font-weight:700; }}
ul, ol {{ padding-left:1.2rem; }}
footer {{
  padding:1rem 1.5rem 2rem; color:var(--muted); font-size:.85rem;
  border-top:1px solid var(--line);
}}
.badge.append {{ background:#b45309; }}
.badge.warn {{ background:var(--warn); }}
.tag.append {{ background:#fff4e5; color:#9a3412; }}
.append-line {{
  color:#9a3412; font-weight:700; background:#fff4e5;
  padding:.45rem .65rem; border-radius:8px;
}}
.card.action-append {{ border-top-color:#b45309; background:linear-gradient(180deg, #fff4e5, var(--panel) 42%); }}
.card.action-create {{ border-top-color:var(--new); }}
.file-sec {{ margin-bottom:1.5rem; }}
.file-sec h3 {{ margin:0 0 .35rem; font-family:Georgia, "Palatino Linotype", serif; }}
.order-step {{
  background:var(--panel); border:1px solid var(--line); border-radius:16px;
  padding:1rem 1.15rem; margin-bottom:.85rem; box-shadow:var(--shadow);
}}
.order-step.action-create {{ border-left:5px solid var(--new); }}
.order-step.action-append {{ border-left:5px solid #b45309; }}
.step.step-append {{ border-color:#f0c28a; }}
.ln-node.vis-append {{
  background:linear-gradient(180deg, #fff4e5, #fffaf3);
  border-color:#e0a35a;
}}
.ln-arrow {{
  display:flex; align-items:center; justify-content:center;
  font-size:1.6rem; color:var(--muted); font-weight:800; padding:0 .15rem;
  flex:0 0 auto; align-self:center;
}}
.ln-board-wrap {{
  position:relative; overflow:auto; border:1px solid var(--line);
  border-radius:16px; background:rgba(255,252,247,.55); min-height:280px;
}}
.ln-svg {{
  position:absolute; left:0; top:0; width:100%; height:100%;
  pointer-events:none; overflow:visible; z-index:1;
}}
.ln-svg path.edge {{
  fill:none; stroke:#8a96a5; stroke-width:2; opacity:.75;
}}
.ln-svg path.edge.hi {{
  stroke:#1f7a4d; stroke-width:3; opacity:1;
}}
.ln-svg path.edge.dim {{
  opacity:.15;
}}
.ln-breadcrumb {{
  margin:.5rem 0 .75rem; padding:.65rem .9rem; border-radius:12px;
  background:#eef6f2; border:1px solid #b7dbc8; font-weight:700;
  font-family:Consolas, "Courier New", monospace; font-size:.9rem;
  word-break:break-word;
}}
.domain-title {{
  margin:.85rem 0 .45rem; font-size:.95rem; color:var(--muted);
  font-weight:800; text-transform:uppercase; letter-spacing:.04em;
}}
.ln-fan {{
  font-size:.7rem; font-weight:800; padding:.1rem .4rem; border-radius:999px;
  background:#e7f0ff; color:#274c77;
}}
.ln-deps {{
  display:block; font-size:.68rem; color:var(--muted); margin-bottom:.25rem;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:100%;
}}
.ln-deps.muted {{ opacity:.7; }}
.dot.append {{ background:#b45309; }}
.dep-list {{
  margin-top:1rem; background:var(--panel); border:1px solid var(--line);
  border-radius:14px; padding:.7rem 1rem; box-shadow:var(--shadow);
}}
.dep-list summary {{ cursor:pointer; font-weight:700; }}
.dep-list .arr {{ color:var(--muted); font-weight:700; margin:0 .35rem; }}
.stat.hl-append {{ border-color:#f0c28a; background:#fff4e5; }}
.ln-board {{
  display:flex; gap:.85rem; padding:1rem .85rem 1.2rem;
  position:relative; z-index:2; min-width:max-content;
}}
.ln-lane {{
  min-width:168px; max-width:200px; flex:0 0 auto;
  background:rgba(255,252,247,.85); border:1px solid var(--line);
  border-radius:16px; padding:.7rem .65rem;
}}
.ln-lane h4 {{
  margin:0 0 .65rem; text-transform:uppercase; letter-spacing:.06em;
  font-size:.72rem; color:var(--muted); font-weight:800;
}}
.ln-nodes {{ display:flex; flex-direction:column; gap:.5rem; }}
.ln-node {{
  text-align:left; cursor:pointer; border-radius:12px; padding:.65rem .7rem;
  border:1px solid #c5ced8; background:#e8edf2; color:var(--ink);
  font:inherit; transition:transform .15s ease, box-shadow .15s ease, border-color .15s;
  box-shadow:0 4px 12px rgba(28,36,48,.04);
}}
.ln-node:hover {{ transform:translateY(-1px); border-color:#9aa8b8; }}
.ln-node:focus {{ outline:2px solid var(--focus); outline-offset:2px; }}
.ln-node.vis-new {{
  background:linear-gradient(180deg, #dff3e8, #f3faf6);
  border-color:#7cbc9a; box-shadow:0 6px 16px rgba(31,122,77,.12);
}}
.ln-node.vis-exist {{
  background:#e9eef3; border-color:#c2cad4; color:#3d4a58;
}}
.ln-node.vis-locked {{
  background:#f3f1f0; border:1.5px dashed #c9857e; color:#5c403c;
}}
.ln-node.vis-review {{
  background:#fff8e8; border:1.5px solid #d4a017;
}}
.ln-node.active {{
  outline:2px solid var(--focus); outline-offset:2px;
  box-shadow:0 0 0 4px rgba(47,111,237,.15);
}}
.ln-node.dim {{ opacity:.35; }}
.ln-node.path {{ opacity:1; box-shadow:0 0 0 2px rgba(31,122,77,.35); }}
.ln-name {{ display:block; font-weight:700; font-size:.92rem; word-break:break-all; }}
.ln-meta {{ display:flex; gap:.35rem; flex-wrap:wrap; margin-top:.35rem; }}
.ln-kind, .ln-add {{
  font-size:.7rem; font-weight:800; padding:.1rem .4rem; border-radius:999px;
}}
.ln-kind {{ background:#e7f0ff; color:#274c77; }}
.ln-add {{ background:var(--new-bg); color:var(--new); }}
.ln-panel {{
  background:var(--panel); border:1px solid var(--line); border-radius:16px;
  padding:1.1rem 1.2rem; box-shadow:var(--shadow); min-height:320px;
  position:sticky; top:.75rem;
}}
.ln-panel h3 {{ margin:0 0 .5rem; font-family:Georgia, "Palatino Linotype", serif; }}
.ln-panel .kv {{ margin:.35rem 0; color:var(--muted); font-size:.92rem; }}
.ln-panel .kv b {{ color:var(--ink); }}
.ln-panel .path-chain {{
  background:#f0f4f8; border-radius:10px; padding:.65rem .75rem;
  font-family:Consolas, "Courier New", monospace; font-size:.82rem;
  word-break:break-word; margin:.55rem 0 0.85rem;
}}
.ln-panel-empty {{ color:var(--muted); }}
</style>
</head>
<body>
<header class="app">
  <h1>DBT Guardian</h1>
  <div class="sub">Card <strong>{card}</strong> · {_esc(session.get('timestamp',''))}</div>
  <div class="sub" style="margin-top:.35rem">
    Base: <code>{_esc(session.get('base_path',''))}</code>
    {(" · Negócios: " + _esc(", ".join(session.get("domains_scanned") or []))) if session.get("domains_scanned") else ""}
  </div>
  <div class="progress" title="Referência visual"><span></span></div>
  {legend}
  <div class="stats">
    <div class="stat hl-new">Criar: <b>{s.get('novo', 0)}</b></div>
    <div class="stat hl-append">Acrescentar: <b>{s.get('acrescentar', 0)}</b></div>
    <div class="stat hl-block">Não alterar: <b>{s.get('nao_alterar', 0)}</b></div>
    <div class="stat">Revisar: <b>{s.get('revisar', 0)}</b></div>
    <div class="stat">Já na base: <b>{s.get('igual', 0)}</b></div>
    <div class="stat">Bloqueios: <b>{s.get('critical', 0)}</b></div>
    <div class="stat">Pendentes: <b>{s.get('pending', 0)}</b></div>
  </div>
</header>

{"<div class='msg'>" + _esc(msg) + "</div>" if msg else ""}

<details class="help" open>
  <summary>Como usar (1 minuto)</summary>
  <ol>
    <li><strong>Criar</strong> = arquivo que ainda não existe.</li>
    <li><strong>Acrescentar</strong> = arquivo já existe; coloque só os itens NOVOS do card (não reescreva o resto).</li>
    <li>Abra a aba <strong>Ordem</strong> e execute os passos na sequência.</li>
    <li>No <strong>Lineage</strong>, veja quem alimenta quem (A → B).</li>
    <li>Valide SaaS + BigQuery → no terminal digite <strong>S</strong>.</li>
  </ol>
</details>

<input type="radio" name="tab" id="t1" checked>
<input type="radio" name="tab" id="t2">
<input type="radio" name="tab" id="t3">
<input type="radio" name="tab" id="t4">
<input type="radio" name="tab" id="t5">
<nav class="tabs">
  <label for="t1">Assistente</label>
  <label for="t2">Ordem</label>
  <label for="t3">Arquivos</label>
  <label for="t4">Lineage</label>
  <label for="t5">Alertas</label>
</nav>

<section class="panel p1">
  <h2>O que fazer agora</h2>
  {_wizard(session)}
</section>

<section class="panel p2">
  <h2>Executar nesta ordem</h2>
  {_ordem(session)}
</section>

<section class="panel p3">
  <h2>Checklist de arquivos</h2>
  <p class="hint">Separado em: Criar → Acrescentar → Atenção/Revisar.</p>
  {_cards(session['checklist'], add_only)}
  {_igual_section(session['checklist'])}
</section>

<section class="panel p4">
  <h2>Lineage</h2>
  <p class="hint">← depende de · → alimenta · clique no nó para o caminho completo.</p>
  {_flow(session)}
</section>

<section class="panel p5">
  <h2>Alertas</h2>
  <p class="hint">Taxonomia, acrescento e avisos de política.</p>
  {_alerts(session)}
</section>

<footer>
  DBT Guardian · somente leitura no repositório DBT · política padrão: só adicionar o novo · stdlib
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

(function lineageUI() {{
  const LIN = S.lineage || {{}};
  const nodes = LIN.nodes || [];
  const edges = LIN.edges || [];
  if (!nodes.length) return;
  const byId = {{}};
  nodes.forEach(n => {{ byId[n.id] = n; }});
  const panel = document.getElementById("ln-panel");
  const crumb = document.getElementById("ln-breadcrumb");
  const wrap = document.getElementById("ln-board-wrap");
  const board = document.getElementById("ln-board");
  const svg = document.getElementById("ln-svg");
  const buttons = document.querySelectorAll(".ln-node");
  let activeId = null;

  function esc(s) {{
    return String(s == null ? "" : s)
      .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
      .replace(/"/g,"&quot;");
  }}

  function elFor(id) {{
    const safe = String(id).replace(/\\\\/g, "\\\\\\\\").replace(/"/g, '\\\\"');
    return document.querySelector('.ln-node[data-node="' + safe + '"]');
  }}

  function neighbors(id) {{
    const up = new Set((byId[id] && byId[id].upstream) || []);
    const down = new Set((byId[id] && byId[id].downstream) || []);
    edges.forEach(e => {{
      if (e.to === id) up.add(e.from);
      if (e.from === id) down.add(e.to);
    }});
    return {{ up, down }};
  }}

  function pathEdges(id) {{
    const {{ up, down }} = neighbors(id);
    const pathSet = new Set([id, ...up, ...down]);
    const keys = new Set();
    edges.forEach(e => {{
      if (pathSet.has(e.from) && pathSet.has(e.to)) keys.add(e.from + ">>" + e.to);
    }});
    return keys;
  }}

  function drawEdges() {{
    if (!svg || !wrap || !board) return;
    const wr = wrap.getBoundingClientRect();
    const bw = board.scrollWidth;
    const bh = Math.max(board.scrollHeight, wrap.clientHeight);
    svg.setAttribute("width", bw);
    svg.setAttribute("height", bh);
    svg.style.width = bw + "px";
    svg.style.height = bh + "px";
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    const hi = activeId ? pathEdges(activeId) : null;

    edges.forEach(e => {{
      const a = elFor(e.from);
      const b = elFor(e.to);
      if (!a || !b) return;
      const ra = a.getBoundingClientRect();
      const rb = b.getBoundingClientRect();
      const x1 = ra.right - wr.left + wrap.scrollLeft;
      const y1 = ra.top + ra.height / 2 - wr.top + wrap.scrollTop;
      const x2 = rb.left - wr.left + wrap.scrollLeft;
      const y2 = rb.top + rb.height / 2 - wr.top + wrap.scrollTop;
      const dx = Math.max(40, (x2 - x1) * 0.45);
      const d = "M " + x1 + " " + y1 + " C " + (x1 + dx) + " " + y1 + ", " + (x2 - dx) + " " + y2 + ", " + x2 + " " + y2;
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", d);
      path.setAttribute("class", "edge");
      const key = e.from + ">>" + e.to;
      if (hi) {{
        if (hi.has(key)) path.classList.add("hi");
        else path.classList.add("dim");
      }}
      // ponta da seta
      const marker = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
      const ang = Math.atan2(y2 - y1, x2 - x1);
      const ah = 7;
      const ax = x2 - Math.cos(ang) * 2;
      const ay = y2 - Math.sin(ang) * 2;
      const p1 = (ax) + "," + (ay);
      const p2 = (x2 - Math.cos(ang - 0.4) * ah) + "," + (y2 - Math.sin(ang - 0.4) * ah);
      const p3 = (x2 - Math.cos(ang + 0.4) * ah) + "," + (y2 - Math.sin(ang + 0.4) * ah);
      marker.setAttribute("points", p1 + " " + p2 + " " + p3);
      marker.setAttribute("class", "edge");
      if (hi) {{
        marker.setAttribute("fill", hi.has(key) ? "#1f7a4d" : "#c5ced8");
        marker.style.opacity = hi.has(key) ? "1" : "0.2";
      }} else {{
        marker.setAttribute("fill", "#8a96a5");
      }}
      svg.appendChild(path);
      svg.appendChild(marker);
    }});
  }}

  function renderItems(list) {{
    if (!list || !list.length) return "<p class='empty'>Nenhum item novo.</p>";
    return "<ul class='add-list'>" + list.map(it => {{
      const typ = it.dbt_type ? " → <em>" + esc(it.dbt_type) + "</em>" : "";
      return "<li><span class='chip'>" + esc(it.kind) + "</span> <code>" +
        esc(it.name) + "</code>" + typ + "</li>";
    }}).join("") + "</ul>";
  }}

  function show(id) {{
    const n = byId[id];
    if (!n || !panel) return;
    activeId = id;
    const {{ up, down }} = neighbors(id);
    buttons.forEach(btn => {{
      const bid = btn.getAttribute("data-node");
      btn.classList.toggle("active", bid === id);
      const onPath = bid === id || up.has(bid) || down.has(bid);
      btn.classList.toggle("dim", !onPath);
      btn.classList.toggle("path", onPath && bid !== id);
    }});

    const chain = [...(n.upstream || []), n.id];
    if (crumb) crumb.textContent = chain.join("  →  ");

    const visLabel = n.visual === "new"
      ? "Criar (arquivo novo)"
      : (n.visual === "append"
        ? "Acrescentar só o novo"
        : (n.visual === "locked"
          ? "Não reescrever"
          : (n.visual === "review" ? "Revisar" : "Já na base")));
    const policy = n.policy_action === "create"
      ? "Pode criar o arquivo completo."
      : (n.policy_action === "append"
        ? "Acrescente SOMENTE os itens novos do card. Não reescreva o código antigo."
        : "NÃO reescreva o arquivo principal.");

    const depends = (n.depends_on && n.depends_on.length)
      ? n.depends_on.map(esc).join(" → ")
      : ((n.upstream || []).map(esc).join(" → ") || "—");
    const usedBy = (n.used_by && n.used_by.length)
      ? n.used_by.map(esc).join("  ·  ")
      : ((n.downstream || []).slice(0, 12).map(esc).join("  ·  ") || "—");

    let ignored = "";
    if (n.ignored_changes && n.ignored_changes.length) {{
      ignored = "<p class='stop-line'>Não aplique no principal</p><ul class='add-list muted'>" +
        n.ignored_changes.map(x => "<li>" + esc(x) + "</li>").join("") + "</ul>";
    }}

    const fanOut = (n.used_by || []).length > 1
      ? "<p class='guide'><strong>Este card se divide em " + n.used_by.length +
        " saídas:</strong> " + n.used_by.map(esc).join(", ") + "</p>"
      : "";

    panel.innerHTML =
      "<h3>" + esc(n.label || n.id) + "</h3>" +
      "<div class='kv'><b>Status:</b> " + esc(visLabel) + "</div>" +
      "<div class='kv'><b>Camada:</b> " + esc(n.layer || "—") +
        (n.table_kind ? " · <b>Tipo:</b> " + esc(n.table_kind) : "") + "</div>" +
      "<div class='kv'><b>Caminho:</b> <code>" + esc(n.path || "—") + "</code></div>" +
      (n.domain ? "<div class='kv'><b>Negócio:</b> " + esc(n.domain) + "</div>" : "") +
      "<div class='kv'><b>Política:</b> " + esc(policy) + "</div>" +
      "<p class='guide'>" + esc(n.add_summary || "") + "</p>" +
      fanOut +
      "<p><strong>Caminho (breadcrumb)</strong></p>" +
      "<div class='path-chain'>" + chain.map(esc).join(" → ") + "</div>" +
      "<p><strong>Depende de (←)</strong></p>" +
      "<div class='path-chain'>" + depends + "</div>" +
      "<p><strong>Alimenta (→) — setas que saem daqui</strong></p>" +
      "<div class='path-chain'>" + usedBy + "</div>" +
      "<p><strong>Itens a adicionar (" + (n.add_count || 0) + ")</strong></p>" +
      renderItems(n.add_items) +
      ignored +
      "<p><strong>Colunas no card</strong></p>" +
      ((n.columns && n.columns.length)
        ? "<p><code>" + n.columns.map(esc).join("</code>, <code>") + "</code></p>"
        : "<p class='empty'>Sem colunas detectadas no SELECT.</p>") +
      ((n.base_columns && n.base_columns.length)
        ? "<p><strong>Colunas já na base</strong></p><p><code>" +
          n.base_columns.map(esc).join("</code>, <code>") + "</code></p>"
        : "");
    requestAnimationFrame(drawEdges);
  }}

  buttons.forEach(btn => {{
    btn.addEventListener("click", () => show(btn.getAttribute("data-node")));
  }});
  if (wrap) wrap.addEventListener("scroll", () => drawEdges());
  window.addEventListener("resize", () => drawEdges());
  // redesenha ao abrir a aba Lineage
  document.querySelectorAll("nav.tabs label").forEach(lab => {{
    lab.addEventListener("click", () => setTimeout(drawEdges, 50));
  }});

  const firstNew = nodes.find(n => n.visual === "new")
    || nodes.find(n => n.visual === "append")
    || nodes[0];
  if (firstNew) show(firstNew.id);
  else drawEdges();
  setTimeout(drawEdges, 100);
}})();
</script>
</body>
</html>
"""
