# -*- coding: utf-8 -*-
"""DBT Guardian — gera index.html único com 4 abas (stdlib only)."""
from __future__ import annotations

import html as H
import json


def _esc(s) -> str:
    return H.escape("" if s is None else str(s))


def _snippet_box(snippet: dict | None, sid: str) -> str:
    """Bloco copiável: só adições / guia de criar."""
    if not snippet or not snippet.get("text"):
        return ""
    label = _esc(snippet.get("label") or "Snippet")
    text = _esc(snippet.get("text") or "")
    place = snippet.get("place") or []
    exists = snippet.get("exists") or []
    attention = snippet.get("attention") or []
    meta = ""
    if place or exists or attention:
        bits = []
        if place:
            bits.append(
                "<span class=\"snip-meta\"><b>Colocar:</b> "
                + ", ".join(f"<code>{_esc(x)}</code>" for x in place[:10])
                + ("…" if len(place) > 10 else "")
                + "</span>"
            )
        if exists:
            bits.append(
                "<span class=\"snip-meta muted\"><b>Já na base:</b> "
                + ", ".join(f"<code>{_esc(x)}</code>" for x in exists[:8])
                + ("…" if len(exists) > 8 else "")
                + "</span>"
            )
        if attention:
            bits.append(
                "<span class=\"snip-meta warn\"><b>Atenção:</b> "
                + _esc(attention[0][:80])
                + ("…" if len(attention) > 1 or len(attention[0]) > 80 else "")
                + "</span>"
            )
        meta = "<div class=\"snip-metas\">" + "".join(bits) + "</div>"
    return f"""
<div class="snippet-box" data-snippet-id="{_esc(sid)}">
  <div class="snippet-head">
    <span class="snippet-label">{label}</span>
    <button type="button" class="btn-copy" data-copy-target="snip-{_esc(sid)}">Copiar</button>
  </div>
  {meta}
  <textarea class="snippet-text" id="snip-{_esc(sid)}" readonly rows="6">{text}</textarea>
</div>
"""


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
  {_snippet_box(c.get("snippet"), c["name"])}
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

    order_meta = session.get("order_meta") or {}
    notice = ""
    if order_meta.get("has_cycle") or any(
        w.get("code") == "DAG_CYCLE" for w in (session.get("warnings") or [])
    ):
        blocked = order_meta.get("blocked_by_cycle") or []
        notice = (
            '<div class="gate-banner blocked soft">'
            "<strong>Ciclo na DAG detectado</strong> — o dbt não compila com loop "
            "(ex. A→B→C→A). Veja <label for=\"t6\" class=\"gate-link\">Avisos</label> "
            "e o caminho no <label for=\"t4\" class=\"gate-link\">Fluxo</label>. "
            "Se a IA errou a ref, corrija manualmente e rode de novo."
            + (
                f" Nós no loop: {', '.join(f'<code>{_esc(n)}</code>' for n in blocked[:8])}."
                if blocked
                else ""
            )
            + "</div>"
        )

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
        snip = _snippet_box(c.get("snippet"), f"ordem-{c['name']}")
        jump = (
            f'<p class="jump-row">'
            f'<button type="button" class="jump-link" data-open-macro="{_esc(c["name"])}">'
            f"Abrir zoom do arquivo</button></p>"
        )
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
  {snip}
  {jump}
  <label class="check">
    <input type="checkbox" data-item="ordem::{_esc(c['name'])}"> Feito este passo
  </label>
</article>
"""
        )
    md = session.get("order_markdown") or ""
    roteiro = f"""
<div class="roteiro-box">
  <div class="snippet-head">
    <span class="snippet-label">Roteiro Markdown (Jira / VS Code)</span>
    <button type="button" class="btn-copy" data-copy-target="roteiro-md">Copiar roteiro</button>
  </div>
  <textarea class="snippet-text" id="roteiro-md" readonly rows="8">{_esc(md)}</textarea>
  <p class="hint">Também gravado em <code>output/roteiro.md</code>.</p>
</div>
"""
    return (
        notice
        + roteiro
        + '<p class="guide">Execute <strong>nesta ordem</strong> (dependências primeiro). '
        "Verde = criar arquivo · Âmbar = acrescer só o novo no arquivo que já existe. "
        "Use <strong>Copiar</strong> nos snippets — só adições, nunca reescreva o principal.</p>"
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
                "<p class=\"guide\">Prévia da sequência — abra <strong>Ordem</strong> para copiar snippets:</p>"
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

    # Taxonomia só se houver aviso (não polui a jornada)
    tax_step = ""
    if tax:
        lis = "".join(
            f"<li><strong>{_esc(w.get('label',''))}</strong> · "
            f"<code>{_esc(w.get('model',''))}</code>: {_esc(w.get('message',''))}"
            f"<br><span class=\"action\">→ {_esc(w.get('action',''))}</span></li>"
            for w in tax[:40]
        )
        tax_step = step(
            4 if not (add_only and attn) else 5,
            "Atenções de nome / tipo",
            len(tax),
            "<p class=\"guide\">Revise se o ZIP fugiu do padrão. Detalhe também na aba <strong>Atenções</strong>.</p>"
            f"<ul class=\"tax-list\">{lis}</ul>",
            "step-stop",
        )

    gold = """
<div class="gold-rule">
  <strong>Jornada do card — etapa por etapa</strong>
  <p>
    A IA/ZIP pode vir errada: use o Sentinel para ver o que criar/acrescer,
    <strong>refatore o SQL fino na base</strong>, depois valide com dbt e o <code>S</code>.
  </p>
</div>
<ol class="journey-steps">
  <li>
    <strong>1. Diff</strong> — no arquivo principal: o que <em>já existe</em> × o que <em>colocar</em>.
    <label for="t2" class="btn-go-order">Abrir Diff</label>
  </li>
  <li>
    <strong>2. Ordem</strong> — copie o snippet (<em>só a adição</em>); arquivos novos = copiar do workspace.
    <label for="t3" class="btn-go-order ghost">Abrir Ordem</label>
  </li>
  <li>
    <strong>3. Aplicar na base</strong> — colar só diferenças / criar arquivos. Se a IA errou, ajuste o SQL aqui.
  </li>
  <li>
    <strong>4. Fluxo / Avisos</strong> — confira ciclo na DAG (A→…→A), refs e sources.
    <label for="t4" class="btn-go-order ghost">Fluxo</label>
    <label for="t6" class="btn-go-order ghost">Avisos</label>
  </li>
  <li>
    <strong>5. dbt / SaaS / BQ</strong> — compile e valide de verdade (o Sentinel não executa dbt).
  </li>
  <li>
    <strong>6. Fechar</strong> — no terminal digite <strong>S</strong> → <code>pending.md</code> (o que ainda falta).
  </li>
</ol>
<p class="journey-cta">
  <label for="t2" class="btn-go-order">Começar pelo Diff</label>
  <label for="t3" class="btn-go-order ghost">Ir para Ordem</label>
</p>
"""

    parts = [
        gold,
        step(1, "Resolver bloqueios dos NOVOS", len(criticals), c_html, "step-block" if criticals else ""),
        step(2, "Criar arquivos novos", len(novos), create_html + order_html, "step-go" if novos else ""),
        step(3, "Acrescentar só o novo (arquivo já existe)", len(acres), append_html, "step-append" if acres else ""),
    ]
    if add_only:
        parts.append(policy_step)
    else:
        parts.append(policy_step)
    if tax_step:
        parts.append(tax_step)
    parts.append("""
<section class="step">
  <div class="step-head">
    <span class="step-num">✓</span>
    <h3>Validar SaaS + BigQuery e fechar</h3>
  </div>
  <p class="guide">Depois de executar a aba <strong>Ordem</strong>:</p>
  <label class="check"><input type="checkbox" data-item="__saas__"> SaaS OK</label>
  <label class="check"><input type="checkbox" data-item="__bq__"> BigQuery OK</label>
  <p class="hint">No terminal, <strong>S</strong> → o Guardian lista só o que ainda falta e grava o snapshot.</p>
</section>
""")
    return "".join(parts)


def _flow(session: dict) -> str:
    """Lineage escalável: colunas por camada, setas sob foco, zoom/busca."""
    lin = session.get("lineage") or {}
    nodes = lin.get("nodes") or []
    edges = lin.get("edges") or []
    if not nodes:
        return "<p class=\"empty\">Sem lineage para exibir. Rode a análise com base + workspace.</p>"

    layers = lin.get("layers") or []
    by_layer = {
        L: sorted(
            [n for n in nodes if n.get("layer") == L],
            key=lambda n: (int(n.get("lane_index") or 0), n.get("id") or ""),
        )
        for L in layers
    }

    compact = " compact" if len(nodes) >= 40 else ""
    lanes = []
    for L in layers:
        cards = []
        for n in by_layer.get(L) or []:
            vis = n.get("visual") or "exist"
            addn = int(n.get("add_count") or 0)
            kind = n.get("table_kind") or ""
            used_c = int(n.get("used_by_count") or len(n.get("used_by") or []))
            fan = f'<span class="ln-fan">→{used_c}</span>' if used_c > 1 else ""
            add_chip = f'<span class="ln-add">+{addn}</span>' if addn else ""
            kind_chip = f'<span class="ln-kind">{_esc(kind)}</span>' if kind else ""
            cards.append(
                f"""
<button type="button" class="ln-node vis-{_esc(vis)}" data-node="{_esc(n['id'])}"
  data-lane="{int(n.get('lane_index') or 0)}"
  title="{_esc(n.get('add_summary') or n['id'])}">
  <span class="ln-name">{_esc(n.get('label') or n['id'])}</span>
  <span class="ln-meta">{kind_chip}{add_chip}{fan}</span>
</button>"""
            )
        lanes.append(
            f"""
<div class="ln-lane" data-layer="{_esc(L)}">
  <h4>{_esc(L)} <span class="ln-lane-count">{len(cards)}</span></h4>
  <div class="ln-nodes">{''.join(cards)}</div>
</div>"""
        )

    edge_lis = "".join(
        f"<li><code>{_esc(e['from'])}</code> "
        f"<span class=\"arr\">alimenta →</span> "
        f"<code>{_esc(e['to'])}</code></li>"
        for e in edges[:120]
    )

    cycles = session.get("dag_cycles") or []
    cycle_html = ""
    if cycles:
        cycle_edges = set()
        for c in cycles:
            for e in c.get("cut_edges") or []:
                cycle_edges.add((e.get("from"), e.get("to")))
        cycle_lis = "".join(
            f"<li class=\"cycle-path\"><code>{_esc(c.get('path'))}</code>"
            f"<br><span class=\"muted\">{_esc(c.get('hint') or '')}</span></li>"
            for c in cycles[:8]
        )
        edge_cycle_lis = "".join(
            f"<li class=\"cycle-edge\"><code>{_esc(a)}</code> ↔ <code>{_esc(b)}</code></li>"
            for a, b in list(cycle_edges)[:20]
        )
        cycle_html = f"""
<div class="cycle-box" id="dag-cycles">
  <h3>Ciclo na DAG — dbt não compila</h3>
  <ul>{cycle_lis}</ul>
  <p class="hint">Arestas candidatas a cortar (remova uma ref):</p>
  <ul>{edge_cycle_lis or '<li>Ver caminho acima.</li>'}</ul>
  <p class="jump-row"><label for="t6" class="gate-link">Ver em Avisos</label></p>
</div>
"""

    n_count = len(nodes)
    e_count = len(edges)
    return f"""
{cycle_html}
<div class="lineage-wrap{compact}" id="lineage-wrap">
  <div class="ln-toolbar">
    <div class="ln-stats"><b>{n_count}</b> nós · <b>{e_count}</b> arestas</div>
    <label class="ln-search">Buscar
      <input type="search" id="ln-search" placeholder="nome do modelo…" autocomplete="off">
    </label>
    <label class="ln-toggle"><input type="checkbox" id="ln-all-edges"> Todas as setas</label>
    <div class="ln-zoom">
      <button type="button" id="ln-zoom-out" title="Diminuir">−</button>
      <button type="button" id="ln-zoom-reset" title="Reset">100%</button>
      <button type="button" id="ln-zoom-in" title="Aumentar">+</button>
    </div>
  </div>
  <div class="ln-legend">
    <span><i class="dot exist"></i> Cinza — já existe</span>
    <span><i class="dot new"></i> Verde — criar</span>
    <span><i class="dot append"></i> Âmbar — acrescer</span>
    <span><i class="dot locked"></i> Contorno — não reescrever</span>
  </div>
  <div class="ln-breadcrumb" id="ln-breadcrumb">
    Clique num card para destacar o caminho. Por padrão só setas do card / seleção (escala).
  </div>
  <div class="lineage-grid">
    <div class="ln-board-wrap" id="ln-board-wrap">
      <div class="ln-zoom-inner" id="ln-zoom-inner">
        <svg class="ln-svg" id="ln-svg" xmlns="http://www.w3.org/2000/svg"></svg>
        <div class="ln-board" id="ln-board">
          {''.join(lanes)}
        </div>
      </div>
    </div>
    <aside class="ln-panel" id="ln-panel" aria-live="polite">
      <div class="ln-panel-empty">
        <h3>Detalhe do lineage</h3>
        <p>Selecione um arquivo para ver: depende de → este → alimenta.</p>
      </div>
    </aside>
  </div>
  <details class="dep-list"><summary>Lista textual ({e_count} ligação(ões), amostra)</summary>
    <ul>{edge_lis or '<li>Sem ligações.</li>'}</ul>
  </details>
</div>
"""


def _macro(session: dict) -> str:
    """Visão MACRO: um arquivo no grafo corporativo (verde = o que o card adiciona)."""
    mac = session.get("macro") or {}
    focuses = mac.get("focuses") or []
    if not focuses:
        return (
            "<p class=\"empty\">Nenhum arquivo criar/acrescentar neste card — "
            "a visão macro aparece quando há algo novo a encaixar na base.</p>"
        )

    opts = []
    for f in focuses:
        mode = "Criar" if f.get("mode") == "create" else "Acrescentar"
        addn = f"+{f['add_count']}" if f.get("add_count") else ""
        opts.append(
            f'<option value="{_esc(f["id"])}">{_esc(f["label"])} — {mode} {addn}</option>'
        )

    return f"""
<div class="macro-wrap">
  <div class="macro-toolbar">
    <label class="macro-pick">Arquivo foco
      <select id="macro-focus">{''.join(opts)}</select>
    </label>
    <div class="ln-legend">
      <span><i class="dot exist"></i> Cinza — já na base (contexto)</span>
      <span><i class="dot new"></i> Verde — criar / itens novos do card</span>
      <span><i class="dot append"></i> Contorno verde — acrescer neste arquivo</span>
    </div>
  </div>
  <p class="guide" id="macro-subtitle">
    Escolha um arquivo e veja onde ele se encaixa na base.
    Verde = criar ou itens novos · cinza = já existe.
  </p>
  <p class="impact-line" id="macro-recompile" hidden></p>
  <div class="macro-addbar" id="macro-addbar" hidden></div>
  <div id="macro-snippet"></div>
  <p class="jump-row">
    <button type="button" class="jump-link" id="macro-to-lineage">Ver no fluxo do card</button>
  </p>
  <div class="lineage-grid">
    <div class="ln-board-wrap" id="macro-board-wrap">
      <svg class="ln-svg" id="macro-svg" xmlns="http://www.w3.org/2000/svg"></svg>
      <div class="ln-board" id="macro-board"></div>
    </div>
    <aside class="ln-panel" id="macro-panel" aria-live="polite">
      <div class="ln-panel-empty">
        <h3>Detalhe macro</h3>
        <p>Selecione um nó para ver o encaixe no grafo e o que será adicionado.</p>
      </div>
    </aside>
  </div>
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
  <span><i class="dot new"></i> criar / colocar</span>
  <span><i class="dot append"></i> acrescer no principal</span>
  <span><i class="dot block"></i> não reescrever</span>
  <span><i class="dot ok"></i> já igual</span>
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
  --bg0:#e8eef4;
  --bg1:#dce5ee;
  --ink:#0b1220;
  --muted:#5a6a7a;
  --panel:#f7fafc;
  --line:#c5d0dc;
  --new:#0f766e;
  --new-bg:#ccfbf1;
  --block:#b42318;
  --block-bg:#fdecea;
  --warn:#9a6700;
  --warn-bg:#fff6e0;
  --ok:#0f766e;
  --ok-bg:#ecfdf8;
  --info:#0369a1;
  --focus:#0284c7;
  --shadow:0 8px 28px rgba(11,18,32,.08);
  --mono: "Cascadia Code", Consolas, "Courier New", monospace;
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0;
  font-family: "Segoe UI", "Trebuchet MS", Candara, sans-serif;
  color:var(--ink);
  background:
    linear-gradient(180deg, rgba(15,118,110,.06), transparent 28%),
    repeating-linear-gradient(90deg, transparent, transparent 47px, rgba(11,18,32,.03) 48px),
    linear-gradient(180deg, var(--bg0), var(--bg1));
  min-height:100vh;
  font-size:16px;
  line-height:1.5;
  letter-spacing:.01em;
}}
header.app {{
  padding:1.35rem 1.6rem 1.1rem;
  border-bottom:1px solid var(--line);
  background:rgba(247,250,252,.92);
  backdrop-filter:blur(10px);
}}
header.app h1 {{
  margin:0;
  font-family: var(--mono);
  font-size:clamp(1.35rem, 2.4vw, 1.85rem);
  letter-spacing:-.03em;
  font-weight:700;
}}
header.app .brand-mark {{
  display:inline-block; width:.55rem; height:.55rem; border-radius:2px;
  background:var(--new); margin-right:.45rem; vertical-align:middle;
}}
header.app .sub {{ color:var(--muted); margin-top:.35rem; font-size:.95rem; }}
header.app .pitch {{
  margin-top:.55rem; font-family:var(--mono); font-size:.88rem;
  color:var(--new); font-weight:700;
}}
.progress {{
  margin-top:1rem; background:#d8e0e8; border-radius:999px; height:8px; overflow:hidden;
}}
.progress > span {{
  display:block; height:100%;
  background:linear-gradient(90deg, var(--new), #14b8a6);
  width:{pct}%; transition:width .35s ease;
}}
.legend {{
  display:flex; flex-wrap:wrap; gap:.85rem 1.4rem;
  margin-top:.9rem; color:var(--muted); font-size:.88rem;
  font-family:var(--mono);
}}
.dot {{
  display:inline-block; width:.65rem; height:.65rem; border-radius:2px;
  margin-right:.35rem; vertical-align:middle;
}}
.dot.new {{ background:var(--new); }}
.dot.block {{ background:var(--block); }}
.dot.ok {{ background:var(--ok); }}
.dot.append {{ background:#b45309; }}
.msg {{
  margin:1rem 1.5rem 0; padding:1rem 1.15rem; border-radius:12px;
  background:var(--panel); border:1px solid var(--line);
  box-shadow:var(--shadow); border-left:4px solid var(--focus);
  font-family:var(--mono); font-size:.9rem;
}}
.gold-rule {{
  background:linear-gradient(135deg, #ecfdf8, #f7fafc);
  border:1px solid #99f6e4; border-radius:12px;
  padding:1rem 1.2rem; margin-bottom:1.1rem;
}}
.gold-rule p {{ margin:.35rem 0 0; color:var(--muted); }}
.tag {{
  display:inline-block; padding:.05rem .45rem; border-radius:4px;
  font-weight:700; font-size:.85em; font-family:var(--mono);
}}
.tag.new {{ background:var(--new-bg); color:var(--new); }}
.tag.block {{ background:var(--block-bg); color:var(--block); }}
.tag.append {{ background:#fff7ed; color:#c2410c; }}
.tabs {{ display:flex; gap:.4rem; padding:1rem 1.5rem 0; flex-wrap:wrap; }}
.tabs label {{
  padding:.55rem .95rem; border-radius:8px; background:var(--panel);
  border:1px solid var(--line); cursor:pointer; color:var(--muted); user-select:none;
  box-shadow:var(--shadow); font-family:var(--mono); font-size:.82rem; font-weight:600;
  letter-spacing:.02em; text-transform:uppercase;
}}
.tabs input {{ display:none; }}
.panel {{ display:none; padding:1.25rem 1.5rem 3rem; }}
#t1:checked ~ .p1, #t2:checked ~ .p2, #t3:checked ~ .p3, #t4:checked ~ .p4, #t5:checked ~ .p5, #t6:checked ~ .p6 {{ display:block; }}
#t1:checked ~ nav.tabs label[for="t1"],
#t2:checked ~ nav.tabs label[for="t2"],
#t3:checked ~ nav.tabs label[for="t3"],
#t4:checked ~ nav.tabs label[for="t4"],
#t5:checked ~ nav.tabs label[for="t5"],
#t6:checked ~ nav.tabs label[for="t6"] {{
  color:#fff; border-color:var(--ink); background:var(--ink); font-weight:700;
}}
#t1:checked ~ nav.tabs label[for="t1"] {{
  background:var(--new); border-color:var(--new); color:#fff;
}}
#t2:checked ~ nav.tabs label[for="t2"] {{
  background:var(--new); border-color:var(--new); color:#fff;
}}
.gate-banner {{
  margin:0 0 1rem; padding:.75rem 1rem; border-radius:10px;
  border:1px solid var(--line); font-size:.95rem;
}}
.gate-banner.blocked {{ background:var(--block-bg); border-color:#fca5a5; color:var(--block); }}
.gate-banner.soft {{ margin:0 0 1rem; }}
.gate-link {{
  cursor:pointer; text-decoration:underline; font-weight:700; color:inherit;
}}
.cycle-box {{
  background:#fff1f2; border:1px solid #fecdd3; border-radius:12px;
  padding:1rem 1.15rem; margin-bottom:1rem;
}}
.cycle-box h3 {{ margin:0 0 .5rem; color:var(--block); }}
.cycle-path code {{ color:var(--block); font-weight:700; }}
.journey-steps {{
  list-style:none; margin:0 0 1rem; padding:0; display:grid; gap:.65rem;
}}
.journey-steps li {{
  background:var(--panel); border:1px solid var(--line); border-radius:12px;
  padding:.85rem 1rem; display:flex; flex-wrap:wrap; align-items:center; gap:.5rem .75rem;
}}
.journey-steps li strong {{ min-width:9rem; }}
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
  border-radius:14px; background:#f4f7fa; min-height:320px; max-height:72vh;
}}
.ln-zoom-inner {{
  position:relative; transform-origin:0 0; min-width:max-content;
}}
.ln-svg {{
  position:absolute; left:0; top:0; width:100%; height:100%;
  pointer-events:none; overflow:visible; z-index:1;
}}
.ln-svg path.edge {{
  fill:none; stroke:#94a3b8; stroke-width:1.5; opacity:.55;
}}
.ln-svg path.edge.hi {{
  stroke:#0f766e; stroke-width:2.5; opacity:1;
}}
.ln-svg path.edge.dim {{
  opacity:.08;
}}
.ln-svg path.edge.work {{
  stroke:#64748b; stroke-width:1.4; opacity:.4;
}}
.ln-toolbar {{
  display:flex; flex-wrap:wrap; gap:.65rem 1rem; align-items:center;
  margin:0 0 .75rem; padding:.65rem .85rem; border-radius:12px;
  background:var(--panel); border:1px solid var(--line);
}}
.ln-stats {{ font-family:var(--mono); font-size:.82rem; color:var(--muted); }}
.ln-stats b {{ color:var(--ink); }}
.ln-search {{ display:flex; flex-direction:column; gap:.25rem; font-size:.8rem; font-weight:700; }}
.ln-search input {{
  font:inherit; padding:.4rem .65rem; border-radius:8px; border:1px solid var(--line);
  min-width:min(100%, 220px); background:#fff;
}}
.ln-toggle {{ font-size:.85rem; font-weight:600; color:var(--muted); display:flex; gap:.4rem; align-items:center; }}
.ln-zoom {{ display:flex; gap:.25rem; }}
.ln-zoom button {{
  font:inherit; font-weight:700; cursor:pointer; min-width:2.1rem;
  padding:.35rem .55rem; border-radius:8px; border:1px solid var(--line);
  background:#fff; color:var(--ink);
}}
.ln-zoom button:hover {{ border-color:var(--new); color:var(--new); }}
.lineage-grid {{
  display:grid; grid-template-columns:minmax(0,1fr) minmax(240px,300px);
  gap:1rem; align-items:start;
}}
@media (max-width: 960px) {{
  .lineage-grid {{ grid-template-columns:1fr; }}
}}
.ln-breadcrumb {{
  margin:.5rem 0 .75rem; padding:.65rem .9rem; border-radius:10px;
  background:#ecfdf5; border:1px solid #a7f3d0; font-weight:700;
  font-family:var(--mono); font-size:.85rem;
  word-break:break-word;
}}
.domain-title {{
  margin:.85rem 0 .45rem; font-size:.95rem; color:var(--muted);
  font-weight:800; text-transform:uppercase; letter-spacing:.04em;
}}
.ln-fan {{
  font-size:.65rem; font-weight:800; padding:.1rem .35rem; border-radius:4px;
  background:#e2e8f0; color:#334155;
}}
.ln-lane-count {{
  font-weight:600; color:var(--muted); text-transform:none; letter-spacing:0;
}}
.macro-toolbar {{
  display:flex; flex-wrap:wrap; gap:.85rem 1.25rem; align-items:flex-end;
  margin-bottom:.65rem;
}}
.macro-pick {{
  display:flex; flex-direction:column; gap:.35rem; font-weight:700; font-size:.9rem;
}}
.macro-pick select {{
  font:inherit; padding:.45rem .7rem; border-radius:10px; border:1px solid var(--line);
  min-width:min(100%, 320px); background:var(--panel);
}}
.macro-addbar {{
  margin:.35rem 0 .85rem; padding:.65rem .9rem; border-radius:12px;
  background:#e5f5ec; border:1px solid #9dceb3; font-size:.92rem;
}}
.macro-addbar code {{ font-size:.88em; }}
.ln-node.vis-add {{
  background:linear-gradient(180deg, #f3f6f8, #eef2f5);
  border:2px solid #1f7a4d;
  box-shadow:0 0 0 3px rgba(31,122,77,.12);
}}
.ln-node.macro-focus {{
  outline:2px solid var(--focus); outline-offset:2px;
}}
.ln-svg path.edge.kind-new {{
  stroke:#1f7a4d; stroke-width:2.5; opacity:.95;
}}
.pill {{
  display:inline-block; font-size:.72rem; font-weight:800; padding:.12rem .45rem;
  border-radius:999px; background:#e8edf2; color:var(--muted); vertical-align:middle;
}}
.snippet-box, .roteiro-box {{
  margin:.75rem 0 1rem; padding:.75rem .85rem; border-radius:14px;
  background:linear-gradient(180deg, #f3faf6, #fffcf7);
  border:1px solid #b7dbc8; box-shadow:var(--shadow);
}}
.snippet-head {{
  display:flex; align-items:center; justify-content:space-between; gap:.75rem;
  margin-bottom:.45rem;
}}
.snippet-label {{ font-weight:800; color:var(--new); font-size:.9rem; }}
.btn-copy {{
  font:inherit; font-weight:700; font-size:.85rem; cursor:pointer;
  padding:.35rem .75rem; border-radius:999px; border:1px solid #7cbc9a;
  background:#dff3e8; color:#1f7a4d;
}}
.btn-copy:hover {{ background:#cfead9; }}
.btn-copy.copied {{ background:#1f7a4d; color:#fff; border-color:#1f7a4d; }}
.snippet-text {{
  width:100%; min-height:7rem; resize:vertical; font-family:Consolas, "Courier New", monospace;
  font-size:.82rem; line-height:1.45; padding:.65rem .7rem; border-radius:10px;
  border:1px solid #c5d9cc; background:#fff; color:var(--ink);
}}
.snip-metas {{ display:flex; flex-direction:column; gap:.25rem; margin-bottom:.5rem; font-size:.85rem; }}
.snip-meta.muted {{ color:var(--muted); }}
.snip-meta.warn {{ color:#9a6700; }}
.impact-line {{
  margin:.35rem 0 .75rem; padding:.65rem .9rem; border-radius:12px;
  background:#eef3f8; border:1px solid #c5d0db; font-size:.92rem;
}}
.impact-line code {{ font-size:.88em; }}
.jump-row {{ margin:.5rem 0; }}
.jump-link {{
  font:inherit; font-weight:700; font-size:.85rem; cursor:pointer;
  padding:.35rem .8rem; border-radius:999px; border:1px solid var(--line);
  background:var(--panel); color:var(--focus);
}}
.jump-link:hover {{ border-color:var(--focus); background:#eef3ff; }}
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
  display:flex; gap:.75rem; padding:1rem .85rem 1.2rem;
  position:relative; z-index:2; min-width:max-content;
}}
.ln-lane {{
  min-width:156px; max-width:188px; flex:0 0 auto;
  background:#fff; border:1px solid #dbe3ec;
  border-radius:12px; padding:.55rem .5rem .7rem;
}}
.ln-lane h4 {{
  position:sticky; top:0; z-index:3;
  margin:0 0 .55rem; padding:.35rem .4rem; border-radius:6px;
  background:#eef2f6; text-transform:uppercase; letter-spacing:.05em;
  font-size:.68rem; color:var(--muted); font-weight:800;
}}
.ln-nodes {{ display:flex; flex-direction:column; gap:.4rem; }}
.ln-node {{
  text-align:left; cursor:pointer; border-radius:8px; padding:.5rem .55rem;
  border:1px solid #c5ced8; background:#e8edf2; color:var(--ink);
  font:inherit; transition:border-color .12s ease, box-shadow .12s ease, opacity .12s;
}}
.ln-node:hover {{ border-color:#64748b; }}
.ln-node:focus {{ outline:2px solid var(--focus); outline-offset:1px; }}
.ln-node.vis-new {{
  background:#ecfdf5; border-color:#5eead4;
}}
.ln-node.vis-append {{
  background:#fff7ed; border-color:#fdba74;
}}
.ln-node.vis-exist {{
  background:#f1f5f9; border-color:#cbd5e1; color:#475569;
}}
.ln-node.vis-locked {{
  background:#f8fafc; border:1.5px dashed #fca5a5; color:#7f1d1d;
}}
.ln-node.vis-review {{
  background:#fffbeb; border:1.5px solid #fbbf24;
}}
.ln-node.active {{
  outline:2px solid #0f766e; outline-offset:1px;
  box-shadow:0 0 0 3px rgba(15,118,110,.18);
}}
.ln-node.dim {{ opacity:.28; }}
.ln-node.path {{ opacity:1; box-shadow:0 0 0 2px rgba(15,118,110,.28); }}
.ln-node.hidden-filter {{ display:none !important; }}
.ln-name {{
  display:block; font-weight:700; font-size:.8rem; font-family:var(--mono);
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:160px;
}}
.ln-meta {{ display:flex; gap:.25rem; flex-wrap:wrap; margin-top:.25rem; }}
.ln-kind, .ln-add {{
  font-size:.65rem; font-weight:800; padding:.08rem .32rem; border-radius:4px;
}}
.ln-kind {{ background:#e0e7ff; color:#3730a3; }}
.ln-add {{ background:var(--new-bg); color:var(--new); }}
.lineage-wrap.compact .ln-node {{ padding:.38rem .45rem; }}
.lineage-wrap.compact .ln-name {{ font-size:.72rem; max-width:140px; }}
.lineage-wrap.compact .ln-lane {{ min-width:138px; max-width:158px; }}
.ln-panel {{
  background:var(--panel); border:1px solid var(--line); border-radius:14px;
  padding:1rem 1.1rem; box-shadow:var(--shadow); min-height:280px;
  position:sticky; top:.75rem; max-height:72vh; overflow:auto;
}}
.ln-panel h3 {{ margin:0 0 .5rem; font-family:Georgia, "Palatino Linotype", serif; font-size:1.05rem; }}
.ln-panel .kv {{ margin:.35rem 0; color:var(--muted); font-size:.9rem; }}
.ln-panel .kv b {{ color:var(--ink); }}
.ln-panel .path-chain {{
  background:#f1f5f9; border-radius:8px; padding:.55rem .65rem;
  font-family:var(--mono); font-size:.78rem;
  word-break:break-word; margin:.45rem 0 0.75rem;
}}
.ln-panel-empty {{ color:var(--muted); }}
.pipeline {{
  margin:1rem 1.5rem 0; padding:.9rem 1.1rem; border-radius:10px;
  background:var(--panel); border:1px solid var(--line);
  display:flex; flex-wrap:wrap; gap:.35rem .55rem; align-items:center;
  font-family:var(--mono); font-size:.8rem; box-shadow:var(--shadow);
}}
.pipeline .pipe-step {{
  padding:.25rem .55rem; border-radius:4px; background:#eef2f6; color:var(--muted); font-weight:700;
}}
.pipeline .pipe-step.on {{
  background:var(--new-bg); color:var(--new);
}}
.pipeline .pipe-arrow {{ color:var(--line); font-weight:700; }}
.btn-go-order {{
  display:inline-block; cursor:pointer; font-weight:700; font-size:.85rem;
  padding:.5rem .95rem; border-radius:6px; border:1px solid var(--new);
  background:var(--new); color:#fff; text-decoration:none; font-family:var(--mono);
  text-transform:uppercase; letter-spacing:.03em;
}}
.btn-go-order:hover {{ filter:brightness(1.06); }}
.btn-go-order.ghost {{
  background:transparent; color:var(--new);
}}
.journey-cta {{ margin:.85rem 0 1.1rem; display:flex; flex-wrap:wrap; gap:.5rem; }}
nav.tabs label[for="t2"] {{
  border-color:#99f6e4;
}}
</style>
</head>
<body>
<header class="app">
  <h1><span class="brand-mark"></span>DBT Sentinel</h1>
  <div class="pitch">diff card × base · só o que falta colocar · base read-only</div>
  <div class="sub">Card <strong>{card}</strong> · {_esc(session.get('timestamp',''))}</div>
  <div class="sub" style="margin-top:.25rem">
    Base <code>{_esc(session.get('base_path',''))}</code>
    {(" · " + _esc(", ".join(session.get("domains_scanned") or []))) if session.get("domains_scanned") else ""}
  </div>
  <div class="progress" title="Referência visual"><span></span></div>
  {legend}
  <div class="stats">
    <div class="stat hl-new">Criar: <b>{s.get('novo', 0)}</b></div>
    <div class="stat hl-append">Acrescentar: <b>{s.get('acrescentar', 0)}</b></div>
    <div class="stat hl-block">Não alterar: <b>{s.get('nao_alterar', 0)}</b></div>
    <div class="stat">Bloqueios: <b>{s.get('critical', 0)}</b></div>
    <div class="stat">Ciclos: <b>{s.get('cycle_count', 0)}</b></div>
  </div>
</header>

{"<div class='msg'>" + _esc(msg) + "</div>" if msg else ""}

<div class="pipeline">
  <span class="pipe-step on">1 Resumo (etapas)</span>
  <span class="pipe-arrow">→</span>
  <span class="pipe-step on">2 Diff</span>
  <span class="pipe-arrow">→</span>
  <span class="pipe-step on">3 Ordem (só adição)</span>
  <span class="pipe-arrow">→</span>
  <span class="pipe-step">4 dbt / SaaS / BQ → S</span>
  <label for="t2" class="btn-go-order" style="margin-left:auto">Abrir Diff</label>
</div>

<details class="help">
  <summary>Seu fluxo</summary>
  <ol>
    <li>Recebe o card no Jira e extrai o ZIP no <code>workspace/</code>.</li>
    <li>Abra <strong>Resumo</strong>: siga as etapas na ordem.</li>
    <li><strong>Diff</strong>: no arquivo principal, veja o que <em>já existe</em> e o que <em>precisa colocar</em>.</li>
    <li><strong>Ordem</strong>: copie o snippet e acrescente só as diferenças (não reescreva o arquivo).</li>
    <li>Se a IA errou o SQL, refatore na base e valide com dbt. <strong>Avisos</strong> / <strong>Fluxo</strong> ajudam com ciclo e refs.</li>
    <li>No terminal: <strong>S</strong> para fechar o card e gerar <code>pending.md</code>.</li>
  </ol>
</details>

<input type="radio" name="tab" id="t1" checked>
<input type="radio" name="tab" id="t2">
<input type="radio" name="tab" id="t3">
<input type="radio" name="tab" id="t4">
<input type="radio" name="tab" id="t5">
<input type="radio" name="tab" id="t6">
<nav class="tabs">
  <label for="t1">Resumo</label>
  <label for="t2">Diff</label>
  <label for="t3">Ordem</label>
  <label for="t4">Fluxo</label>
  <label for="t5">Zoom</label>
  <label for="t6">Avisos{(" " + str(len(session.get("warnings") or []))) if session.get("warnings") else ""}</label>
</nav>

<section class="panel p1">
  <h2>Resumo — o que fazer neste card</h2>
  <p class="hint">Siga as etapas abaixo. Depois use Diff e Ordem para copiar só o que falta.</p>
  {_wizard(session)}
</section>

<section class="panel p2">
  <h2>Diff — o que existe × o que colocar</h2>
  <p class="hint">
    Compare com o arquivo principal da base: <strong>já existe</strong> vs <strong>acrescentar</strong>.
    Não reescreva o SQL antigo — só as diferenças do card.
  </p>
  {_cards(session['checklist'], add_only)}
  {_igual_section(session['checklist'])}
</section>

<section class="panel p3">
  <h2>Ordem de aplicação</h2>
  <p class="hint">Depois do Diff: copie o roteiro/snippet e aplique nesta sequência. Em seguida rode o dbt.</p>
  {_ordem(session)}
</section>

<section class="panel p4">
  <h2>Fluxo do card</h2>
  <p class="hint">Dependências deste pacote. Clique → Zoom no arquivo.</p>
  {_flow(session)}
</section>

<section class="panel p5">
  <h2>Zoom — arquivo na base</h2>
  <p class="hint">Um arquivo no centro: o que já está na base, o que o card adiciona, o que recompilar depois.</p>
  {_macro(session)}
</section>

<section class="panel p6">
  <h2>Avisos</h2>
  <p class="hint">Ciclos na DAG, refs, sources, taxonomia e política — use quando a IA/ZIP vier estranha.</p>
  {_alerts(session)}
</section>

<footer>
  DBT Sentinel · base somente leitura · só adições · stdlib
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

function openTab(tid) {{
  const el = document.getElementById(tid);
  if (el) el.checked = true;
}}
function openMacro(id) {{
  openTab("t5");
  const sel = document.getElementById("macro-focus");
  if (sel) {{
    sel.value = id;
    sel.dispatchEvent(new Event("change"));
  }}
  setTimeout(() => {{
    const wrap = document.getElementById("macro-board-wrap");
    if (wrap) wrap.scrollIntoView({{ behavior: "smooth", block: "start" }});
  }}, 60);
}}
function openLineage(id) {{
  openTab("t4");
  setTimeout(() => {{
    const btn = document.querySelector('#ln-board .ln-node[data-node="' + id.replace(/"/g, '') + '"]');
    if (btn) {{
      btn.click();
      btn.scrollIntoView({{ behavior: "smooth", block: "center" }});
    }}
  }}, 80);
}}
document.addEventListener("click", (ev) => {{
  const t = ev.target;
  if (!(t instanceof Element)) return;
  const copyBtn = t.closest(".btn-copy");
  if (copyBtn) {{
    const tid = copyBtn.getAttribute("data-copy-target");
    const area = tid ? document.getElementById(tid) : null;
    const text = area ? area.value : "";
    const done = () => {{
      copyBtn.classList.add("copied");
      const old = copyBtn.textContent;
      copyBtn.textContent = "Copiado";
      setTimeout(() => {{ copyBtn.classList.remove("copied"); copyBtn.textContent = old; }}, 1200);
    }};
    if (navigator.clipboard && navigator.clipboard.writeText) {{
      navigator.clipboard.writeText(text).then(done).catch(() => {{
        if (area) {{ area.select(); document.execCommand("copy"); done(); }}
      }});
    }} else if (area) {{
      area.select();
      document.execCommand("copy");
      done();
    }}
    return;
  }}
  const mac = t.closest("[data-open-macro]");
  if (mac) {{
    openMacro(mac.getAttribute("data-open-macro"));
    return;
  }}
  const lin = t.closest("[data-open-lineage]");
  if (lin) {{
    openLineage(lin.getAttribute("data-open-lineage"));
  }}
}});

(function lineageUI() {{
  const LIN = S.lineage || {{}};
  const nodes = LIN.nodes || [];
  const edges = LIN.edges || [];
  if (!nodes.length) return;
  const byId = {{}};
  nodes.forEach(n => {{ byId[n.id] = n; }});
  const workIds = new Set(
    nodes.filter(n => n.visual === "new" || n.visual === "append").map(n => n.id)
  );
  const panel = document.getElementById("ln-panel");
  const crumb = document.getElementById("ln-breadcrumb");
  const wrap = document.getElementById("ln-board-wrap");
  const board = document.getElementById("ln-board");
  const zoomInner = document.getElementById("ln-zoom-inner");
  const svg = document.getElementById("ln-svg");
  const searchEl = document.getElementById("ln-search");
  const allEdgesEl = document.getElementById("ln-all-edges");
  const zoomIn = document.getElementById("ln-zoom-in");
  const zoomOut = document.getElementById("ln-zoom-out");
  const zoomReset = document.getElementById("ln-zoom-reset");
  if (!board || !wrap || !svg) return;
  const buttons = board.querySelectorAll(".ln-node");
  let activeId = null;
  let hoverId = null;
  let showAll = false;
  let zoom = 1;
  let drawTimer = null;
  const posCache = {{}};

  function esc(s) {{
    return String(s == null ? "" : s)
      .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
      .replace(/"/g,"&quot;");
  }}

  function elFor(id) {{
    const safe = String(id).replace(/\\\\/g, "\\\\\\\\").replace(/"/g, '\\\\"');
    return board.querySelector('.ln-node[data-node="' + safe + '"]');
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

  function workEdgeKeys() {{
    const keys = new Set();
    edges.forEach(e => {{
      if (workIds.has(e.from) || workIds.has(e.to)) keys.add(e.from + ">>" + e.to);
    }});
    return keys;
  }}

  function measurePositions() {{
    const wr = wrap.getBoundingClientRect();
    Object.keys(posCache).forEach(k => delete posCache[k]);
    board.querySelectorAll(".ln-node").forEach(el => {{
      if (el.classList.contains("hidden-filter")) return;
      const id = el.getAttribute("data-node");
      const r = el.getBoundingClientRect();
      posCache[id] = {{
        x1: r.right - wr.left + wrap.scrollLeft,
        y1: r.top + r.height / 2 - wr.top + wrap.scrollTop,
        x2: r.left - wr.left + wrap.scrollLeft,
        y2: r.top + r.height / 2 - wr.top + wrap.scrollTop,
      }};
    }});
  }}

  function applyZoom() {{
    if (!zoomInner) return;
    zoomInner.style.transform = "scale(" + zoom + ")";
    if (zoomReset) zoomReset.textContent = Math.round(zoom * 100) + "%";
    scheduleDraw();
  }}

  function scheduleDraw() {{
    if (drawTimer) clearTimeout(drawTimer);
    drawTimer = setTimeout(() => requestAnimationFrame(drawEdges), 40);
  }}

  function drawEdges() {{
    if (!svg || !wrap || !board) return;
    const focusId = activeId || hoverId;
    const hi = focusId ? pathEdges(focusId) : null;
    const workKeys = (!focusId && !showAll) ? workEdgeKeys() : null;

    const bw = board.scrollWidth;
    const bh = Math.max(board.scrollHeight, wrap.clientHeight);
    svg.setAttribute("width", bw);
    svg.setAttribute("height", bh);
    svg.style.width = bw + "px";
    svg.style.height = bh + "px";
    while (svg.firstChild) svg.removeChild(svg.firstChild);

    measurePositions();

    edges.forEach(e => {{
      const key = e.from + ">>" + e.to;
      let cls = "edge";
      if (showAll && hi) {{
        cls += hi.has(key) ? " hi" : " dim";
      }} else if (showAll) {{
        cls += " work";
      }} else if (hi) {{
        if (!hi.has(key)) return;
        cls += " hi";
      }} else if (workKeys) {{
        if (!workKeys.has(key)) return;
        cls += " work";
      }} else {{
        return;
      }}
      const a = posCache[e.from];
      const b = posCache[e.to];
      if (!a || !b) return;
      const x1 = a.x1, y1 = a.y1, x2 = b.x2, y2 = b.y2;
      const dx = Math.max(36, Math.abs(x2 - x1) * 0.4);
      const d = (x2 >= x1)
        ? ("M " + x1 + " " + y1 + " C " + (x1 + dx) + " " + y1 + ", " + (x2 - dx) + " " + y2 + ", " + x2 + " " + y2)
        : ("M " + x1 + " " + y1 + " C " + (x1 + 50) + " " + (y1 - 30) + ", " + (x2 - 50) + " " + (y2 + 30) + ", " + x2 + " " + y2);
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", d);
      path.setAttribute("class", cls);
      svg.appendChild(path);
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

    const chain = [...(n.upstream || []).slice(-6), n.id];
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
        + (n.depends_on_count > n.depends_on.length ? " …" : "")
      : "—";
    const usedBy = (n.used_by && n.used_by.length)
      ? n.used_by.map(esc).join("  ·  ")
        + (n.used_by_count > n.used_by.length ? " …" : "")
      : "—";

    let ignored = "";
    if (n.ignored_changes && n.ignored_changes.length) {{
      ignored = "<p class='stop-line'>Não aplique no principal</p><ul class='add-list muted'>" +
        n.ignored_changes.map(x => "<li>" + esc(x) + "</li>").join("") + "</ul>";
    }}

    const macFocuses = ((S.macro || {{}}).focuses || []).map(f => f.id);
    const jumpMacro = macFocuses.indexOf(id) >= 0
      ? "<p class='jump-row'><button type='button' class='jump-link' data-open-macro='" +
        esc(id) + "'>Abrir zoom do arquivo</button></p>"
      : "";

    panel.innerHTML =
      "<h3>" + esc(n.label || n.id) + "</h3>" +
      jumpMacro +
      "<div class='kv'><b>Status:</b> " + esc(visLabel) + "</div>" +
      "<div class='kv'><b>Camada:</b> " + esc(n.layer || "—") +
        (n.table_kind ? " · <b>Tipo:</b> " + esc(n.table_kind) : "") + "</div>" +
      "<div class='kv'><b>Caminho:</b> <code>" + esc(n.path || "—") + "</code></div>" +
      (n.domain ? "<div class='kv'><b>Negócio:</b> " + esc(n.domain) + "</div>" : "") +
      "<div class='kv'><b>Política:</b> " + esc(policy) + "</div>" +
      "<p class='guide'>" + esc(n.add_summary || "") + "</p>" +
      "<p><strong>Caminho</strong></p>" +
      "<div class='path-chain'>" + chain.map(esc).join(" → ") + "</div>" +
      "<p><strong>Depende de (←)</strong></p>" +
      "<div class='path-chain'>" + depends + "</div>" +
      "<p><strong>Alimenta (→)</strong></p>" +
      "<div class='path-chain'>" + usedBy + "</div>" +
      "<p><strong>Itens a adicionar (" + (n.add_count || 0) + ")</strong></p>" +
      renderItems(n.add_items) +
      ignored;
    scheduleDraw();
  }}

  buttons.forEach(btn => {{
    btn.addEventListener("click", () => show(btn.getAttribute("data-node")));
    btn.addEventListener("mouseenter", () => {{
      hoverId = btn.getAttribute("data-node");
      if (!activeId) scheduleDraw();
    }});
    btn.addEventListener("mouseleave", () => {{
      hoverId = null;
      if (!activeId) scheduleDraw();
    }});
  }});

  if (wrap) wrap.addEventListener("scroll", scheduleDraw, {{ passive: true }});
  window.addEventListener("resize", scheduleDraw);
  document.querySelectorAll("nav.tabs label").forEach(lab => {{
    lab.addEventListener("click", () => setTimeout(scheduleDraw, 60));
  }});

  if (allEdgesEl) {{
    allEdgesEl.addEventListener("change", () => {{
      showAll = !!allEdgesEl.checked;
      scheduleDraw();
    }});
  }}
  if (searchEl) {{
    searchEl.addEventListener("input", () => {{
      const q = (searchEl.value || "").trim().toLowerCase();
      buttons.forEach(btn => {{
        const id = (btn.getAttribute("data-node") || "").toLowerCase();
        const hit = !q || id.indexOf(q) >= 0;
        btn.classList.toggle("hidden-filter", !hit);
      }});
      scheduleDraw();
    }});
  }}
  if (zoomIn) zoomIn.addEventListener("click", () => {{ zoom = Math.min(1.6, zoom + 0.1); applyZoom(); }});
  if (zoomOut) zoomOut.addEventListener("click", () => {{ zoom = Math.max(0.55, zoom - 0.1); applyZoom(); }});
  if (zoomReset) zoomReset.addEventListener("click", () => {{ zoom = 1; applyZoom(); }});

  const firstNew = nodes.find(n => n.visual === "new")
    || nodes.find(n => n.visual === "append")
    || nodes[0];
  if (firstNew) show(firstNew.id);
  else scheduleDraw();
  setTimeout(scheduleDraw, 120);
}})();

(function macroUI() {{
  const MAC = S.macro || {{}};
  const byFocus = MAC.by_focus || {{}};
  const sel = document.getElementById("macro-focus");
  const board = document.getElementById("macro-board");
  const wrap = document.getElementById("macro-board-wrap");
  const svg = document.getElementById("macro-svg");
  const panel = document.getElementById("macro-panel");
  const sub = document.getElementById("macro-subtitle");
  const addbar = document.getElementById("macro-addbar");
  const recompileEl = document.getElementById("macro-recompile");
  const snipHost = document.getElementById("macro-snippet");
  const toLin = document.getElementById("macro-to-lineage");
  if (!sel || !board || !Object.keys(byFocus).length) return;

  let view = null;
  let activeId = null;

  function esc(s) {{
    return String(s == null ? "" : s)
      .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
      .replace(/"/g,"&quot;");
  }}

  function elFor(id) {{
    const safe = String(id).replace(/\\\\/g, "\\\\\\\\").replace(/"/g, '\\\\"');
    return board.querySelector('.ln-node[data-node="' + safe + '"]');
  }}

  function renderItems(list) {{
    if (!list || !list.length) return "<p class='empty'>Nenhum item novo neste nó.</p>";
    return "<ul class='add-list'>" + list.map(it => {{
      const typ = it.dbt_type ? " → <em>" + esc(it.dbt_type) + "</em>" : "";
      return "<li><span class='chip'>" + esc(it.kind) + "</span> <code>" +
        esc(it.name) + "</code>" + typ + "</li>";
    }}).join("") + "</ul>";
  }}

  function drawEdges() {{
    if (!svg || !wrap || !view) return;
    const wr = wrap.getBoundingClientRect();
    const bw = board.scrollWidth;
    const bh = Math.max(board.scrollHeight, wrap.clientHeight);
    svg.setAttribute("width", bw);
    svg.setAttribute("height", bh);
    svg.style.width = bw + "px";
    svg.style.height = bh + "px";
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    (view.edges || []).forEach(e => {{
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
      const d = "M " + x1 + " " + y1 + " C " + (x1 + dx) + " " + y1 + ", " +
        (x2 - dx) + " " + y2 + ", " + x2 + " " + y2;
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", d);
      path.setAttribute("class", "edge" + (e.kind === "new" ? " kind-new" : ""));
      if (activeId && e.from !== activeId && e.to !== activeId) path.classList.add("dim");
      else if (activeId) path.classList.add("hi");
      svg.appendChild(path);
    }});
  }}

  function showNode(id) {{
    if (!view || !panel) return;
    const n = (view.nodes || []).find(x => x.id === id);
    if (!n) return;
    activeId = id;
    board.querySelectorAll(".ln-node").forEach(btn => {{
      const bid = btn.getAttribute("data-node");
      btn.classList.toggle("active", bid === id);
      btn.classList.toggle("dim", bid !== id && bid !== view.focus);
    }});
    const modeLabel = n.visual === "new"
      ? "Criar (arquivo novo)"
      : (n.visual === "add"
        ? "Acrescentar só o novo (já na base)"
        : "Contexto corporativo");
    panel.innerHTML =
      "<h3>" + esc(n.label) + (n.focus ? " · foco" : "") + "</h3>" +
      "<div class='kv'><b>Papel:</b> " + esc(modeLabel) + "</div>" +
      "<div class='kv'><b>Origem:</b> " + esc(n.origin || "—") +
        " · <b>Camada:</b> " + esc(n.layer || "—") + "</div>" +
      "<p class='guide'>" + esc(n.hint || "") + "</p>" +
      "<p><strong>Depende de (←)</strong></p>" +
      "<div class='path-chain'>" +
        ((n.depends_on && n.depends_on.length) ? n.depends_on.map(esc).join(" · ") : "—") +
      "</div>" +
      "<p><strong>Alimenta (→)</strong></p>" +
      "<div class='path-chain'>" +
        ((n.used_by && n.used_by.length) ? n.used_by.map(esc).join(" · ") : "—") +
      "</div>" +
      (n.visual === "add" || n.visual === "new"
        ? ("<p><strong>O que o card adiciona (" + (n.add_count || 0) + ")</strong></p>" +
           renderItems(n.add_items))
        : "") +
      ((n.base_columns && n.base_columns.length)
        ? "<p><strong>Já na base</strong></p><p><code>" +
          n.base_columns.map(esc).join("</code>, <code>") + "</code></p>"
        : "");
    requestAnimationFrame(drawEdges);
  }}

  function renderFocus(fid) {{
    view = byFocus[fid];
    if (!view) return;
    activeId = view.focus;
    if (sub) sub.textContent = view.subtitle || "";
    if (recompileEl) {{
      const rc = (view.recompile || []).filter(x => !String(x).startsWith("source."));
      if (rc.length) {{
        recompileEl.hidden = false;
        recompileEl.innerHTML = "<strong>Se aplicar neste arquivo, recompilar depois:</strong> " +
          rc.map(x => "<code>" + esc(x) + "</code>").join(" · ");
      }} else {{
        recompileEl.hidden = false;
        recompileEl.innerHTML = "<strong>Recompilar depois:</strong> ninguém depende deste arquivo ainda.";
      }}
    }}
    if (snipHost) {{
      const sn = view.snippet;
      if (sn && sn.text) {{
        const sid = "macro-" + String(view.focus).replace(/[^\\w.-]/g, "_");
        snipHost.innerHTML =
          "<div class='snippet-box'>" +
          "<div class='snippet-head'><span class='snippet-label'>" + esc(sn.label || "Snippet") +
          "</span><button type='button' class='btn-copy' data-copy-target='" + sid +
          "'>Copiar</button></div>" +
          "<textarea class='snippet-text' id='" + sid + "' readonly rows='6'>" +
          esc(sn.text) + "</textarea></div>";
      }} else {{
        snipHost.innerHTML = "";
      }}
    }}
    if (toLin) {{
      toLin.setAttribute("data-open-lineage", view.focus);
      toLin.onclick = () => openLineage(view.focus);
    }}
    if (addbar) {{
      const items = view.add_items || [];
      if (items.length) {{
        addbar.hidden = false;
        addbar.innerHTML = "<strong>Verde neste foco:</strong> " +
          items.slice(0, 12).map(it =>
            "<code>" + esc(it.name) + "</code>").join(" · ") +
          (items.length > 12 ? " …" : "");
      }} else if (view.mode === "create") {{
        addbar.hidden = false;
        addbar.innerHTML = "<strong>Verde:</strong> o arquivo <code>" +
          esc(view.focus) + "</code> inteiro será criado neste encaixe.";
      }} else {{
        addbar.hidden = true;
        addbar.innerHTML = "";
      }}
    }}
    const layers = view.layers || [];
    const byLayer = {{}};
    layers.forEach(L => {{ byLayer[L] = []; }});
    (view.nodes || []).forEach(n => {{
      const L = n.layer || "other";
      if (!byLayer[L]) byLayer[L] = [];
      byLayer[L].push(n);
    }});
    board.innerHTML = layers.map(L => {{
      const cards = (byLayer[L] || []).map(n => {{
        const kind = n.table_kind
          ? "<span class='ln-kind'>" + esc(n.table_kind) + "</span>" : "";
        const addn = n.add_count
          ? "<span class='ln-add'>+" + n.add_count + "</span>" : "";
        const foc = n.focus ? " macro-focus" : "";
        return "<button type='button' class='ln-node vis-" + esc(n.visual) + foc +
          "' data-node='" + esc(n.id) + "'>" +
          "<span class='ln-name'>" + esc(n.label) + "</span>" +
          "<span class='ln-meta'>" + kind + addn + "</span></button>";
      }}).join("");
      return "<div class='ln-lane' data-layer='" + esc(L) + "'>" +
        "<h4>" + esc(L) + "</h4><div class='ln-nodes'>" + cards + "</div></div>";
    }}).join("");

    board.querySelectorAll(".ln-node").forEach(btn => {{
      btn.addEventListener("click", () => showNode(btn.getAttribute("data-node")));
    }});
    showNode(view.focus);
    setTimeout(drawEdges, 60);
  }}

  sel.addEventListener("change", () => renderFocus(sel.value));
  if (wrap) wrap.addEventListener("scroll", () => drawEdges());
  window.addEventListener("resize", () => drawEdges());
  document.querySelectorAll("nav.tabs label").forEach(lab => {{
    lab.addEventListener("click", () => setTimeout(drawEdges, 80));
  }});

  const initial = MAC.default || sel.value;
  if (initial) {{
    sel.value = initial;
    renderFocus(initial);
  }}
}})();
</script>
</body>
</html>
"""
