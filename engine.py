# -*- coding: utf-8 -*-
"""DBT Guardian — motor de análise (stdlib only)."""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter, defaultdict, deque
from datetime import datetime

IGNORE_DIRS = {".git", "target", "dbt_packages", "logs", "__pycache__", ".venv", "node_modules"}
EXTS = {".sql", ".yml", ".yaml", ".csv"}

RE_REF = re.compile(r"""\{\{\s*ref\s*\(\s*['"]([^'"]+)['"]\s*\)\s*\}\}""", re.I)
RE_SOURCE = re.compile(
    r"""\{\{\s*source\s*\(\s*['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]\s*\)\s*\}\}""",
    re.I,
)
RE_JOIN = re.compile(r"\b((?:LEFT|RIGHT|INNER|FULL|CROSS)\s+JOIN|JOIN)\b", re.I)
RE_CAST = re.compile(r"\b((?:SAFE_|TRY_)?CAST)\s*\(", re.I)
RE_COMMENT_LINE = re.compile(r"--[^\n]*")
RE_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.S)
RE_SELECT_COLS = re.compile(
    r"(?:^|,)\s*(?:[\w.]+\.)?(\w+)\s*(?:,|$)",
    re.M,
)

LAYER_MAP = (
    ("staging", "staging"),
    ("stg", "staging"),
    ("sample", "sample"),
    ("intermediate", "intermediate"),
    ("int", "intermediate"),
    ("mart", "mart"),
    ("aggregate", "aggregate"),
    ("agg", "aggregate"),
    ("seed", "seed"),
    ("macro", "macro"),
    ("source", "source"),
)

ACTION_LABEL = {
    "NOVO": "Criar arquivo",
    "ALTERADO": "Atualizar arquivo",
    "REMOVIDO": "Verificar remoção",
    "IGUAL": "Pronto",
}

ACTION_HINT = {
    "NOVO": "Este arquivo ainda não existe no projeto. Copie do workspace para o caminho indicado.",
    "ALTERADO": "Este arquivo já existe e mudou. Aplique as alterações no arquivo do projeto.",
    "REMOVIDO": "Este arquivo sumiu do pacote. Confirme se a remoção é intencional.",
    "IGUAL": "Nada a fazer — já está igual ao projeto.",
}


def _strip_comments(text: str) -> str:
    text = RE_COMMENT_BLOCK.sub(" ", text)
    text = RE_COMMENT_LINE.sub(" ", text)
    return text


def detect_layer(rel_path: str) -> str:
    low = rel_path.replace("\\", "/").lower()
    for key, layer in LAYER_MAP:
        if f"/{key}/" in f"/{low}/" or f"/{key}_" in f"/{low}":
            return layer
    name = os.path.basename(low)
    for key, layer in LAYER_MAP:
        if name.startswith(key + "_") or name.startswith(key + "."):
            return layer
    return "other"


def layer_order(layer: str) -> int:
    order = {
        "source": 1,
        "seed": 2,
        "sample": 3,
        "staging": 4,
        "intermediate": 5,
        "aggregate": 6,
        "mart": 7,
        "macro": 8,
        "other": 9,
    }
    return order.get(layer, 9)


def scan_dir(root: str) -> list[str]:
    found = []
    if not root or not os.path.isdir(root):
        return found
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            if ext in EXTS:
                found.append(os.path.join(dirpath, name))
    return found


def parse_sql(text: str) -> dict:
    clean = _strip_comments(text)
    refs = sorted(set(RE_REF.findall(clean)))
    sources = sorted(set((a, b) for a, b in RE_SOURCE.findall(clean)))
    joins = sorted(set(j.upper().replace("  ", " ") for j in RE_JOIN.findall(clean)))
    casts = sorted(set(c.upper() for c in RE_CAST.findall(clean)))
    # heurística leve de colunas no SELECT
    cols = []
    m = re.search(r"\bselect\b(.*?)\bfrom\b", clean, re.I | re.S)
    if m:
        chunk = m.group(1)
        # evita pegar * sozinho como coluna
        for c in RE_SELECT_COLS.findall(chunk):
            if c.lower() not in {"as", "on", "and", "or", "case", "when", "then", "else", "end"}:
                cols.append(c.lower())
        cols = sorted(set(cols))[:40]
    return {
        "refs": refs,
        "sources": [list(s) for s in sources],
        "joins": joins,
        "casts": casts,
        "columns": cols,
    }


def parse_yaml(text: str) -> dict:
    """Parser YAML mínimo via regex — sem PyYAML."""
    sources = []
    models = []
    # sources: - name: schema / tables: - name: table
    for block in re.finditer(
        r"(?ms)^\s*-\s*name:\s*([^\n#]+).*?(?=^\s*-\s*name:|\Z)",
        text,
    ):
        chunk = block.group(0)
        schema = block.group(1).strip().strip("\"'")
        tables = re.findall(r"(?m)^\s+-\s*name:\s*([^\n#]+)", chunk)
        if tables:
            for t in tables:
                sources.append([schema, t.strip().strip("\"'")])
        else:
            models.append(schema)
    # fallback: procurar source/table soltos
    if not sources:
        for m in re.finditer(
            r"(?ms)name:\s*([^\n]+).*?tables:.*?(?=^\S|\Z)",
            text,
        ):
            schema = m.group(1).strip().strip("\"'")
            for t in re.findall(r"(?m)^\s+-\s*name:\s*([^\n#]+)", m.group(0)):
                sources.append([schema, t.strip().strip("\"'")])
    return {
        "refs": [],
        "sources": sources,
        "joins": [],
        "casts": [],
        "columns": models,
        "yaml_models": models,
    }


def structural_hash(model: dict) -> str:
    payload = {
        "refs": model.get("refs", []),
        "sources": model.get("sources", []),
        "joins": [j.upper() for j in model.get("joins", [])],
        "casts": [c.upper() for c in model.get("casts", [])],
        "columns": [c.lower() for c in model.get("columns", [])],
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def parse_file(path: str, root: str) -> dict | None:
    rel = os.path.relpath(path, root).replace("\\", "/")
    name = os.path.splitext(os.path.basename(path))[0]
    ext = os.path.splitext(path)[1].lower()
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None

    if ext == ".sql":
        parsed = parse_sql(text)
        kind = "model"
    elif ext in {".yml", ".yaml"}:
        parsed = parse_yaml(text)
        kind = "yaml"
        if parsed.get("sources"):
            kind = "source"
    elif ext == ".csv":
        parsed = {"refs": [], "sources": [], "joins": [], "casts": [], "columns": []}
        kind = "seed"
    else:
        return None

    model = {
        "name": name,
        "path": rel,
        "abs_path": path,
        "type": kind,
        "layer": detect_layer(rel),
        "refs": parsed.get("refs", []),
        "sources": parsed.get("sources", []),
        "joins": parsed.get("joins", []),
        "casts": parsed.get("casts", []),
        "columns": parsed.get("columns", []),
    }
    model["hash"] = structural_hash(model)
    return model


def load_project(root: str) -> dict[str, dict]:
    models: dict[str, dict] = {}
    for path in scan_dir(root):
        m = parse_file(path, root)
        if not m:
            continue
        # chave única: nome; se colisão, preferir .sql
        key = m["name"]
        if key in models and models[key]["type"] == "model" and m["type"] != "model":
            continue
        models[key] = m
    return models


def _set_diff(a: list, b: list) -> tuple[list, list]:
    sa, sb = set(map(_norm, a)), set(map(_norm, b))
    added = sorted(sb - sa)
    removed = sorted(sa - sb)
    return added, removed


def _norm(x):
    if isinstance(x, (list, tuple)):
        return tuple(x)
    return x


def semantic_diff(base: dict, ws: dict) -> list[str]:
    lines = []
    for field, label in (
        ("refs", "referência"),
        ("sources", "origem"),
        ("columns", "coluna"),
        ("joins", "join"),
        ("casts", "cast"),
    ):
        added, removed = _set_diff(base.get(field, []), ws.get(field, []))
        for item in added:
            lines.append(f"+ {label} {item} adicionada")
        for item in removed:
            lines.append(f"- {label} {item} removida")
    return lines


def compare(base: dict, ws: dict, detect_removed: bool = False) -> list[dict]:
    """Compara workspace (ZIP) contra a base.

    Por padrão só avalia arquivos do workspace (ZIP parcial do Jira).
    REMOVIDO só aparece se detect_removed=True.
    """
    names = set(ws)
    if detect_removed:
        names |= set(base)

    def sort_key(n):
        m = ws.get(n) or base.get(n) or {}
        return (layer_order(m.get("layer", "other")), n)

    items = []
    for name in sorted(names, key=sort_key):
        b, w = base.get(name), ws.get(name)
        if w and not b:
            status, model, diff = "NOVO", w, []
        elif b and not w:
            if not detect_removed:
                continue
            status, model, diff = "REMOVIDO", b, []
        elif b and w:
            if b["hash"] == w["hash"]:
                status, diff = "IGUAL", []
            else:
                status, diff = "ALTERADO", semantic_diff(b, w)
            model = w
        else:
            continue

        if status == "NOVO":
            target = w["path"]
        elif b:
            target = b["path"]
        else:
            target = model["path"]

        items.append({
            "name": name,
            "status": status,
            "label": ACTION_LABEL[status],
            "hint": ACTION_HINT[status],
            "path": target,
            "layer": model.get("layer", "other"),
            "layer_order": layer_order(model.get("layer", "other")),
            "type": model.get("type", "model"),
            "diff": diff,
            "refs": model.get("refs", []),
            "sources": model.get("sources", []),
            "hash": model.get("hash", ""),
            "done": status == "IGUAL",
        })
    return items


def build_graph(models: dict) -> dict:
    """Adjacency: name -> {refs, dependents}."""
    graph = {name: {"refs": list(m.get("refs", [])), "dependents": []} for name, m in models.items()}
    # sources como nós virtuais
    for name, m in models.items():
        for schema, table in m.get("sources", []):
            src = f"source.{schema}.{table}"
            if src not in graph:
                graph[src] = {"refs": [], "dependents": []}
            if src not in graph[name]["refs"]:
                graph[name]["refs"].append(src)
    for name, node in graph.items():
        for ref in node["refs"]:
            if ref in graph and name not in graph[ref]["dependents"]:
                graph[ref]["dependents"].append(name)
    return graph


def find_cycles(graph: dict) -> list[list[str]]:
    cycles = []
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    stack = []

    def dfs(u):
        color[u] = GRAY
        stack.append(u)
        for v in graph[u]["refs"]:
            if v not in graph:
                continue
            if color[v] == GRAY:
                if v in stack:
                    i = stack.index(v)
                    cycles.append(stack[i:] + [v])
            elif color[v] == WHITE:
                dfs(v)
        stack.pop()
        color[u] = BLACK

    for n in graph:
        if color[n] == WHITE:
            dfs(n)
    # dedup
    seen = set()
    unique = []
    for c in cycles:
        key = tuple(sorted(c[:-1])) if c else ()
        if key and key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def downstream(graph: dict, name: str) -> list[str]:
    if name not in graph:
        return []
    out = []
    seen = set()
    q = deque(graph[name]["dependents"])
    while q:
        n = q.popleft()
        if n in seen:
            continue
        seen.add(n)
        out.append(n)
        q.extend(graph.get(n, {}).get("dependents", []))
    return out


def topo_order(checklist: list[dict], graph: dict) -> list[str]:
    pending = [c["name"] for c in checklist if c["status"] in {"NOVO", "ALTERADO"}]
    pending_set = set(pending)
    indeg = {n: 0 for n in pending}
    for n in pending:
        for r in graph.get(n, {}).get("refs", []):
            if r in pending_set:
                indeg[n] = indeg.get(n, 0) + 1
    q = deque(sorted([n for n, d in indeg.items() if d == 0]))
    order = []
    while q:
        n = q.popleft()
        order.append(n)
        for dep in graph.get(n, {}).get("dependents", []):
            if dep in indeg:
                indeg[dep] -= 1
                if indeg[dep] == 0:
                    q.append(dep)
    for n in pending:
        if n not in order:
            order.append(n)
    return order


def learn_patterns(base: dict) -> dict:
    prefixes = Counter()
    by_layer = defaultdict(Counter)
    for m in base.values():
        name = m["name"]
        layer = m.get("layer", "other")
        if "_" in name:
            prefixes[name.split("_", 1)[0] + "_"] += 1
            by_layer[layer][name.split("_", 1)[0] + "_"] += 1
        for c in m.get("casts", []):
            by_layer["casts"][c.upper()] += 1
    return {
        "prefixes": dict(prefixes.most_common(20)),
        "by_layer": {k: dict(v.most_common(5)) for k, v in by_layer.items()},
    }


def validate(checklist: list[dict], graph: dict, models: dict, patterns: dict) -> list[dict]:
    warnings = []
    known = set(models) | set(graph)
    # sources virtuais
    for name, m in models.items():
        for schema, table in m.get("sources", []):
            known.add(f"source.{schema}.{table}")

    cycles = find_cycles(graph)
    for cyc in cycles:
        path = " → ".join(cyc)
        warnings.append({
            "severity": "warning",
            "label": "Atenção",
            "model": cyc[0] if cyc else "",
            "message": f"Existe um loop no fluxo: {path}. Isso impede a compilação.",
            "action": "Remova uma das referências circulares.",
        })

    for item in checklist:
        name = item["name"]
        if item["status"] == "IGUAL":
            continue
        # refs inexistentes
        for ref in item.get("refs", []):
            if ref not in known and not ref.startswith("source."):
                warnings.append({
                    "severity": "critical",
                    "label": "Bloqueio",
                    "model": name,
                    "message": (
                        f"O arquivo {name} referencia {ref}, mas ele não existe no projeto. "
                        f"Crie {ref} primeiro."
                    ),
                    "action": f"Crie o arquivo {ref} ou corrija a referência.",
                })
        for schema, table in item.get("sources", []):
            src = f"source.{schema}.{table}"
            # source declarado em yaml conta como conhecido se estiver no graph
            if src not in known:
                # aviso informativo — yaml pode estar incompleto
                warnings.append({
                    "severity": "warning",
                    "label": "Atenção",
                    "model": name,
                    "message": (
                        f"O arquivo {name} usa a origem {schema}.{table}. "
                        f"Confirme se está declarada no sources.yml."
                    ),
                    "action": "Verifique o arquivo de sources (.yml).",
                })

        # nomenclatura
        prefs = patterns.get("by_layer", {}).get(item.get("layer", ""), {})
        if prefs and "_" in name:
            prefix = name.split("_", 1)[0] + "_"
            top = next(iter(prefs), None)
            if top and prefix not in prefs and item["status"] in {"NOVO", "ALTERADO"}:
                warnings.append({
                    "severity": "warning",
                    "label": "Atenção",
                    "model": name,
                    "message": (
                        f"O nome {name} não segue o padrão mais comum desta camada ({top}...). "
                        f"Revise a nomenclatura."
                    ),
                    "action": f"Considere renomear para algo como {top}{name.split('_', 1)[-1]}.",
                })

        # SAFE_CAST
        casts = models.get(name, {}).get("casts", []) if name in models else []
        if any(c.upper() in {"SAFE_CAST", "TRY_CAST"} for c in casts):
            warnings.append({
                "severity": "safe",
                "label": "Seguro",
                "model": name,
                "message": f"{name} usa SAFE_CAST/TRY_CAST — boa prática detectada.",
                "action": "",
            })

        # removido com downstream
        if item["status"] == "REMOVIDO":
            deps = downstream(graph, name)
            if deps:
                warnings.append({
                    "severity": "critical",
                    "label": "Bloqueio",
                    "model": name,
                    "message": (
                        f"O arquivo {name} seria removido, mas ainda é usado por: "
                        f"{', '.join(deps[:8])}."
                    ),
                    "action": "Não remova sem atualizar os arquivos que dependem dele.",
                })

        # dead model (novo sem dependents e sem ser source/mart)
        if item["status"] == "NOVO" and item.get("layer") not in {"source", "mart", "aggregate", "seed"}:
            deps = downstream(graph, name)
            if not deps and item.get("type") == "model":
                warnings.append({
                    "severity": "info",
                    "label": "Info",
                    "model": name,
                    "message": f"Ninguém usa {name} ainda. Confirme se é um modelo final ou se faltou referenciar.",
                    "action": "Documente como entrega final ou conecte a um modelo downstream.",
                })

        # sample sem stg
        if "_sample" in name.lower() or item.get("layer") == "sample":
            stg_guess = name.lower().replace("_sample", "").replace("sample_", "stg_")
            if not stg_guess.startswith("stg_"):
                stg_guess = "stg_" + stg_guess
            if stg_guess not in models and stg_guess not in {c["name"] for c in checklist}:
                warnings.append({
                    "severity": "info",
                    "label": "Info",
                    "model": name,
                    "message": f"Amostra {name} encontrada. Lembre de criar o staging correspondente.",
                    "action": "Após validar com 1% dos dados, promova para staging.",
                })

    # similaridade simples (mesmo prefixo + overlap de refs)
    novos = [c for c in checklist if c["status"] == "NOVO"]
    base_names = [c["name"] for c in checklist if c["status"] in {"IGUAL", "ALTERADO", "REMOVIDO"}]
    for n in novos:
        for bname in base_names:
            if n["name"] == bname:
                continue
            if n["name"].split("_")[0] == bname.split("_")[0] and len(n["name"]) > 3:
                nrefs = set(n.get("refs", []))
                brefs = set(models.get(bname, {}).get("refs", []))
                if nrefs and brefs and len(nrefs & brefs) >= 1:
                    warnings.append({
                        "severity": "info",
                        "label": "Info",
                        "model": n["name"],
                        "message": (
                            f"Já existe {bname} com referências parecidas. "
                            f"Evite retrabalho — confira antes de criar."
                        ),
                        "action": f"Compare com {bname} no projeto base.",
                    })
                    break

    # ordenar por severidade
    rank = {"critical": 0, "warning": 1, "info": 2, "safe": 3}
    warnings.sort(key=lambda w: (rank.get(w["severity"], 9), w.get("model", "")))
    return warnings


def enrich_checklist(checklist: list[dict], graph: dict) -> list[dict]:
    for item in checklist:
        deps = downstream(graph, item["name"])
        item["impact"] = deps
        item["impact_text"] = (
            f"Afeta depois: {', '.join(deps[:10])}" if deps else "Ninguém depende deste arquivo"
        )
    return checklist


def load_timeline(snapshots_path: str) -> list[dict]:
    timeline = []
    if not snapshots_path or not os.path.isdir(snapshots_path):
        return timeline
    for name in sorted(os.listdir(snapshots_path)):
        manifest = os.path.join(snapshots_path, name, "manifest.json")
        if os.path.isfile(manifest):
            try:
                with open(manifest, "r", encoding="utf-8") as f:
                    timeline.append(json.load(f))
            except (OSError, json.JSONDecodeError):
                continue
    return timeline


def build_flow_chains(checklist: list[dict], graph: dict) -> list[str]:
    """Cadeias curtas para visualização source→…→mart."""
    by_layer = defaultdict(list)
    for c in checklist:
        if c["status"] == "REMOVIDO":
            continue
        by_layer[c["layer"]].append(c)
    # pick roots (sample/source/staging novos/alterados) e seguir dependents
    chains = []
    seeds = [
        c["name"]
        for c in checklist
        if c["status"] in {"NOVO", "ALTERADO"} and c["layer"] in {"source", "sample", "staging", "seed"}
    ]
    if not seeds:
        seeds = [c["name"] for c in checklist if c["status"] in {"NOVO", "ALTERADO"}][:5]
    for start in seeds[:12]:
        chain = [start]
        cur = start
        for _ in range(6):
            deps = [d for d in graph.get(cur, {}).get("dependents", []) if d in {c["name"] for c in checklist}]
            if not deps:
                break
            nxt = deps[0]
            chain.append(nxt)
            cur = nxt
        if len(chain) >= 1:
            # anotar status
            status_map = {c["name"]: c["status"] for c in checklist}
            parts = []
            for n in chain:
                st = status_map.get(n, "IGUAL")
                mark = {"NOVO": "criar", "ALTERADO": "atualizar", "IGUAL": "ok", "REMOVIDO": "remover"}.get(st, st)
                parts.append(f"{n} ({mark})")
            chains.append(" → ".join(parts))
    return chains[:20]


def run(config: dict) -> dict:
    base_path = config["base_project_path"]
    ws_path = config["workspace_path"]
    snapshots_path = config.get("snapshots_path", "")
    card_id = config.get("card_id", "CARD-XXX")

    base = load_project(base_path)
    ws = load_project(ws_path)

    # grafo unificado: base + workspace (workspace sobrescreve)
    merged = dict(base)
    merged.update(ws)

    detect_removed = bool(config.get("detect_removed", False))
    checklist = compare(base, ws, detect_removed=detect_removed)
    graph = build_graph(merged)
    checklist = enrich_checklist(checklist, graph)
    patterns = learn_patterns(base)
    warnings = validate(checklist, graph, merged, patterns)
    order = topo_order(checklist, graph)

    # aplicar ordem sugerida no checklist
    order_idx = {n: i for i, n in enumerate(order)}
    for item in checklist:
        item["suggested_order"] = order_idx.get(item["name"], 999)

    checklist.sort(key=lambda c: (0 if c["status"] != "IGUAL" else 1, c["layer_order"], c.get("suggested_order", 999), c["name"]))

    summary = {
        "novo": sum(1 for c in checklist if c["status"] == "NOVO"),
        "alterado": sum(1 for c in checklist if c["status"] == "ALTERADO"),
        "removido": sum(1 for c in checklist if c["status"] == "REMOVIDO"),
        "igual": sum(1 for c in checklist if c["status"] == "IGUAL"),
        "pending": sum(1 for c in checklist if c["status"] in {"NOVO", "ALTERADO", "REMOVIDO"}),
        "critical": sum(1 for w in warnings if w["severity"] == "critical"),
        "warning": sum(1 for w in warnings if w["severity"] == "warning"),
        "base_models": len(base),
        "workspace_models": len(ws),
    }

    empty_ws = len(ws) == 0
    message = ""
    if empty_ws:
        message = (
            "Nenhum arquivo encontrado no workspace. "
            "Extraia o ZIP do Jira na pasta workspace/ e execute novamente."
        )
    elif summary["pending"] == 0 and summary["critical"] == 0:
        message = (
            "Parabéns! Nada pendente neste pacote. "
            "Marque SaaS OK e BQ OK na aba Assistente para finalizar."
        )
    elif summary["critical"] > 0:
        message = (
            f"Você tem {summary['critical']} bloqueio(s). "
            "Resolva-os antes de continuar — veja a aba Alertas."
        )

    session = {
        "card_id": card_id,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "message": message,
        "checklist": checklist,
        "warnings": warnings,
        "order": order,
        "flow_chains": build_flow_chains(checklist, graph),
        "timeline": load_timeline(snapshots_path),
        "patterns": patterns,
        "empty_workspace": empty_ws,
    }
    return session
