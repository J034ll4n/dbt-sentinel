# -*- coding: utf-8 -*-
"""DBT Guardian — motor de análise (stdlib only)."""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter, defaultdict, deque
from datetime import datetime
from difflib import SequenceMatcher

IGNORE_DIRS = {".git", "target", "dbt_packages", "logs", "__pycache__", ".venv", "node_modules"}
EXTS = {".sql", ".yml", ".yaml", ".csv"}
MAX_FILE_BYTES = 2_000_000  # 2 MB — evita travar VDI com monstro
MAX_FILES_PER_PROJECT = 20_000


def safe_relpath(path: str, root: str) -> str | None:
    """Garante que path está dentro de root (bloqueia path traversal / symlink escape)."""
    try:
        root_abs = os.path.abspath(root)
        path_abs = os.path.abspath(path)
        common = os.path.commonpath([root_abs, path_abs])
        if common != root_abs:
            return None
        return os.path.relpath(path_abs, root_abs).replace("\\", "/")
    except (ValueError, OSError):
        return None


def sanitize_card_id(card_id: str) -> str:
    """Impede card_id com ../ ou caracteres de path."""
    raw = (card_id or "CARD-XXX").strip()
    clean = re.sub(r"[^\w.\-]+", "_", raw, flags=re.UNICODE)
    clean = clean.strip("._") or "CARD-XXX"
    if clean in {".", ".."} or ".." in clean:
        return "CARD-XXX"
    return clean[:80]


def validate_config(config: dict) -> list[str]:
    """Retorna lista de erros fatais de configuração."""
    errors = []
    if not isinstance(config, dict):
        return ["config.json deve ser um objeto JSON"]
    for key in ("workspace_path", "output_path", "snapshots_path"):
        if not config.get(key):
            errors.append(f"Falta {key} no config.json")
    aliases = config.get("aliases", {})
    if aliases is None:
        aliases = {}
    if not isinstance(aliases, dict):
        errors.append("aliases deve ser um objeto {nome_zip: nome_projeto}")
    else:
        for k, v in aliases.items():
            if not isinstance(k, str) or not isinstance(v, str) or not k or not v:
                errors.append(f"alias inválido: {k!r} -> {v!r}")
                break
    thr = config.get("match_threshold", 0.62)
    try:
        thr_f = float(thr)
        if not 0.0 <= thr_f <= 1.0:
            errors.append("match_threshold deve estar entre 0 e 1")
    except (TypeError, ValueError):
        errors.append("match_threshold deve ser número")
    base = config.get("base_project_path") or ""
    out = os.path.abspath(config.get("output_path") or "")
    snap = os.path.abspath(config.get("snapshots_path") or "")
    ws = os.path.abspath(config.get("workspace_path") or "")
    if base and os.path.isdir(base):
        base_abs = os.path.abspath(base)
        for label, p in (("output_path", out), ("snapshots_path", snap), ("workspace_path", ws)):
            if p and (p == base_abs or p.startswith(base_abs + os.sep)):
                errors.append(
                    f"{label} não pode ficar dentro do projeto base (risco de gravar no DBT)"
                )
    return errors

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
    "RENOMEADO": "Mesmo objeto, nome diferente",
    "IGUAL": "Pronto",
}

ACTION_HINT = {
    "NOVO": "Este arquivo ainda não existe no projeto. Copie do workspace para o caminho indicado.",
    "ALTERADO": "Este arquivo já existe e mudou. Aplique as alterações no arquivo do projeto.",
    "REMOVIDO": "Este arquivo sumiu do pacote. Confirme se a remoção é intencional.",
    "RENOMEADO": (
        "A IA/ZIP usou outro nome, mas o conteúdo parece o mesmo objeto já existente. "
        "NÃO crie duplicado — atualize o arquivo do projeto ou alinhe o nome."
    ),
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
    root_abs = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root_abs, followlinks=False):
        # nunca seguir para fora do root
        if safe_relpath(dirpath, root_abs) is None:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
        for name in filenames:
            if name.startswith("."):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in EXTS:
                continue
            full = os.path.join(dirpath, name)
            if safe_relpath(full, root_abs) is None:
                continue
            try:
                if os.path.islink(full):
                    continue
                if os.path.getsize(full) > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            found.append(full)
            if len(found) >= MAX_FILES_PER_PROJECT:
                return found
    return found


def parse_file(path: str, root: str) -> dict | None:
    rel = safe_relpath(path, root)
    if rel is None:
        return None
    name = os.path.splitext(os.path.basename(path))[0]
    if not name or name in {".", ".."}:
        return None
    ext = os.path.splitext(path)[1].lower()
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read(MAX_FILE_BYTES + 1)
        if len(text) > MAX_FILE_BYTES:
            return None
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
        parsed = {
            "refs": [],
            "sources": [],
            "joins": [],
            "casts": [],
            "columns": [],
            "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        }
        kind = "seed"
    else:
        return None

    model = {
        "name": name,
        "path": rel,
        "abs_path": os.path.abspath(path),
        "type": kind,
        "layer": detect_layer(rel),
        "refs": parsed.get("refs", []),
        "sources": parsed.get("sources", []),
        "joins": parsed.get("joins", []),
        "casts": parsed.get("casts", []),
        "columns": parsed.get("columns", []),
        "content_hash": parsed.get("content_hash", ""),
    }
    model["hash"] = structural_hash(model)
    return model


def load_project(root: str) -> dict[str, dict]:
    models: dict[str, dict] = {}
    collisions: list[str] = []
    if not root or not os.path.isdir(root):
        return models
    for path in scan_dir(root):
        m = parse_file(path, root)
        if not m:
            continue
        key = m["name"]
        if key in models:
            prev = models[key]
            # preferir .sql / model sobre yaml
            if prev["type"] == "model" and m["type"] != "model":
                collisions.append(key)
                continue
            if m["type"] == "model" and prev["type"] != "model":
                collisions.append(key)
                models[key] = m
                continue
            collisions.append(key)
            # mesmo tipo: mantém o primeiro, anota colisão no path do vencedor
            prev.setdefault("collisions", []).append(m["path"])
            continue
        models[key] = m
    if collisions:
        # marca no primeiro modelo para o validate avisar
        for key in set(collisions):
            if key in models:
                models[key].setdefault("name_collision", True)
    return models


def parse_sql(text: str) -> dict:
    clean = _strip_comments(text)
    refs = sorted(set(RE_REF.findall(clean)))
    sources = sorted(set((a, b) for a, b in RE_SOURCE.findall(clean)))
    joins = sorted(set(j.upper().replace("  ", " ") for j in RE_JOIN.findall(clean)))
    casts = sorted(set(c.upper() for c in RE_CAST.findall(clean)))
    cols = []
    m = re.search(r"\bselect\b(.*?)\bfrom\b", clean, re.I | re.S)
    if m:
        chunk = m.group(1)
        for c in RE_SELECT_COLS.findall(chunk):
            if c.lower() not in {"as", "on", "and", "or", "case", "when", "then", "else", "end"}:
                cols.append(c.lower())
        cols = sorted(set(cols))[:40]
    # fingerprint do corpo (WHERE, CTEs, etc.) — evita IGUAL falso
    body_norm = re.sub(r"\s+", " ", clean).strip().lower()
    content_hash = hashlib.sha256(body_norm.encode("utf-8")).hexdigest()[:16]
    return {
        "refs": refs,
        "sources": [list(s) for s in sources],
        "joins": joins,
        "casts": casts,
        "columns": cols,
        "content_hash": content_hash,
    }


def _yaml_top_sections(text: str) -> dict[str, str]:
    """Divide o YAML em blocos de chave de topo (sources:, models:, ...)."""
    sections: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z_][\w]*)\s*:\s*(?:#.*)?$", line)
        if m:
            current = m.group(1).lower()
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return {k: "\n".join(v) for k, v in sections.items()}


def parse_yaml(text: str) -> dict:
    """Parser YAML mínimo — sources: separado de models: (não confunde colunas)."""
    sources: list[list[str]] = []
    models: list[str] = []
    sections = _yaml_top_sections(text)

    src_block = sections.get("sources", "")
    if src_block:
        lines = src_block.splitlines()
        i = 0
        while i < len(lines):
            m = re.match(r"^(\s*)-\s*name:\s*([^\n#]+)", lines[i])
            if not m:
                i += 1
                continue
            indent = len(m.group(1))
            schema = m.group(2).strip().strip("\"'")
            i += 1
            # consumir até próximo item da mesma indentação
            in_tables = False
            while i < len(lines):
                line = lines[i]
                m2 = re.match(r"^(\s*)-\s*name:\s*([^\n#]+)", line)
                if m2 and len(m2.group(1)) <= indent:
                    break
                if re.match(rf"^\s{{{indent + 1},}}tables:\s*", line):
                    in_tables = True
                    i += 1
                    continue
                # fallback: linha com "tables:" mais indentada
                if re.match(r"^\s+tables:\s*(?:#.*)?$", line) and len(line) - len(line.lstrip(" ")) > indent:
                    in_tables = True
                    i += 1
                    continue
                if in_tables:
                    mt = re.match(r"^(\s*)-\s*name:\s*([^\n#]+)", line)
                    if mt and len(mt.group(1)) > indent:
                        sources.append([schema, mt.group(2).strip().strip("\"'")])
                i += 1

    mod_block = sections.get("models", "")
    if mod_block:
        for line in mod_block.splitlines():
            m = re.match(r"^(\s*)-\s*name:\s*([^\n#]+)", line)
            if m and len(m.group(1)) <= 4:
                models.append(m.group(2).strip().strip("\"'"))

    return {
        "refs": [],
        "sources": sources,
        "joins": [],
        "casts": [],
        "columns": models,
        "yaml_models": models,
        "content_hash": hashlib.sha256(
            re.sub(r"\s+", " ", text).strip().lower().encode("utf-8")
        ).hexdigest()[:16],
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


def models_equal(a: dict, b: dict) -> bool:
    """IGUAL só se estrutura E corpo forem iguais."""
    if a.get("content_hash") and b.get("content_hash"):
        return a["content_hash"] == b["content_hash"] and a.get("hash") == b.get("hash")
    return a.get("hash") == b.get("hash")


def models_changed(a: dict, b: dict) -> list[str]:
    """Diff semântico + nota se só o corpo mudou."""
    diff = semantic_diff(a, b)
    if a.get("content_hash") and b.get("content_hash") and a["content_hash"] != b["content_hash"]:
        if a.get("hash") == b.get("hash"):
            diff.append("~ lógica/SQL alterada (mesmo refs/colunas, corpo diferente)")
        elif not any("lógica" in d for d in diff):
            diff.append("~ conteúdo do arquivo alterado")
    return diff


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


def split_prefix(name: str) -> tuple[str, str]:
    n = (name or "").lower().strip()
    for pref in ("stg_", "int_", "fct_", "dim_", "agg_", "sample_", "src_"):
        if n.startswith(pref):
            return pref, n[len(pref):]
    return "", n


def normalize_core(name: str) -> str:
    """Núcleo do nome (sem prefixo), com singular leve."""
    _, core = split_prefix(name)
    core = core.replace("-", "_").replace(" ", "_")
    if core.endswith("ies"):
        core = core[:-3] + "y"
    elif core.endswith("s") and not core.endswith("ss"):
        core = core[:-1]
    return core


def name_similarity(a: str, b: str) -> float:
    """Similaridade de nome. Só compara núcleos se o prefixo for da mesma família."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    al, bl = a.lower(), b.lower()
    raw = SequenceMatcher(None, al, bl).ratio()
    pa, _ = split_prefix(al)
    pb, _ = split_prefix(bl)
    # sample_cliente ≠ stg_cliente só porque o núcleo é "cliente"
    if pa and pb and pa == pb:
        norm = SequenceMatcher(None, normalize_core(al), normalize_core(bl)).ratio()
        return max(raw, norm)
    return raw


def structure_similarity(a: dict, b: dict) -> float:
    """Jaccard médio sobre refs, sources e columns."""
    scores = []
    for field in ("refs", "sources", "columns"):
        sa = set(map(_norm, a.get(field, []) or []))
        sb = set(map(_norm, b.get(field, []) or []))
        if not sa and not sb:
            continue
        union = sa | sb
        scores.append(len(sa & sb) / len(union) if union else 0.0)
    if not scores:
        return 1.0 if a.get("hash") and a.get("hash") == b.get("hash") else 0.0
    return sum(scores) / len(scores)


def match_score(ws_model: dict, base_model: dict) -> tuple[float, list[str]]:
    """Score 0–1 + motivos legíveis."""
    reasons = []
    ns = name_similarity(ws_model.get("name", ""), base_model.get("name", ""))
    ss = structure_similarity(ws_model, base_model)
    same_layer = ws_model.get("layer") == base_model.get("layer")
    same_hash = bool(
        (ws_model.get("content_hash") and ws_model.get("content_hash") == base_model.get("content_hash"))
        or (ws_model.get("hash") and ws_model.get("hash") == base_model.get("hash"))
    )

    if same_hash:
        reasons.append("estrutura idêntica (hash)")
    if ns >= 0.7:
        reasons.append(f"nome parecido ({int(ns * 100)}%)")
    if ss >= 0.4:
        reasons.append(f"refs/colunas parecidas ({int(ss * 100)}%)")
    if same_layer:
        reasons.append(f"mesma camada ({ws_model.get('layer')})")

    score = 0.45 * ss + 0.35 * ns + (0.15 if same_layer else 0.0) + (0.2 if same_hash else 0.0)
    score = min(1.0, score)
    return score, reasons


def find_best_match(ws_model: dict, base: dict, used: set, min_score: float = 0.62) -> dict | None:
    """Encontra o melhor candidato na base para um modelo do workspace.

    Só casa automaticamente dentro da mesma camada (sample ≠ stg).
    Não casa com nome que já existe no workspace (evita double-claim).
    """
    best = None
    best_score = 0.0
    best_reasons: list[str] = []
    for bname, bmodel in base.items():
        if bname in used:
            continue
        if ws_model.get("layer") != bmodel.get("layer"):
            continue
        score, reasons = match_score(ws_model, bmodel)
        if score > best_score:
            best_score = score
            best = bname
            best_reasons = reasons
    if best is None or best_score < min_score:
        return None
    return {"name": best, "score": round(best_score, 3), "reasons": best_reasons}


def assign_renames(
    orphans: list[dict],
    base: dict,
    reserved: set,
    match_threshold: float,
) -> dict[str, dict]:
    """Atribuição exclusiva: melhor score primeiro (sem dois ZIP → mesmo base)."""
    candidates = []
    for w in orphans:
        for bname, bmodel in base.items():
            if bname in reserved:
                continue
            if w.get("layer") != bmodel.get("layer"):
                continue
            score, reasons = match_score(w, bmodel)
            if score >= match_threshold:
                candidates.append((score, w["name"], bname, reasons))
    candidates.sort(key=lambda x: (-x[0], x[1], x[2]))
    assigned: dict[str, dict] = {}
    used_base = set(reserved)
    used_ws = set()
    for score, wname, bname, reasons in candidates:
        if wname in used_ws or bname in used_base:
            continue
        used_ws.add(wname)
        used_base.add(bname)
        assigned[wname] = {
            "name": bname,
            "score": round(score, 3),
            "reasons": reasons,
            "path": base[bname].get("path", ""),
        }
    return assigned


def resolve_alias(name: str, aliases: dict) -> str | None:
    """aliases: workspace_name -> base_name (ou o inverso)."""
    if not aliases:
        return None
    if name in aliases:
        return aliases[name]
    for ws_name, base_name in aliases.items():
        if base_name == name:
            return ws_name
    return None


def compare(
    base: dict,
    ws: dict,
    detect_removed: bool = False,
    aliases: dict | None = None,
    match_threshold: float = 0.62,
) -> list[dict]:
    """Compara workspace (ZIP) contra a base.

    Por padrão só avalia arquivos do workspace (ZIP parcial do Jira).
    Detecta nomes diferentes para o mesmo objeto via aliases + similaridade exclusiva.
    """
    aliases = aliases or {}
    items = []
    claimed_base = set()
    pending_orphan: list[dict] = []

    # Passo 1: matches exatos e aliases
    for name in sorted(ws.keys(), key=lambda n: (layer_order(ws[n].get("layer", "other")), n)):
        w = ws[name]
        b = base.get(name)
        match_info = None
        alias_target = resolve_alias(name, aliases)

        if b:
            claimed_base.add(name)
            if models_equal(b, w):
                status, diff = "IGUAL", []
            else:
                status, diff = "ALTERADO", models_changed(b, w)
            model = w
            target = b["path"]
        elif alias_target and alias_target in base and alias_target not in claimed_base:
            b = base[alias_target]
            claimed_base.add(alias_target)
            if models_equal(b, w):
                status, diff = "IGUAL", [f"Alias: {name} = {alias_target} (mesmo conteúdo)"]
            else:
                status, diff = "ALTERADO", (
                    [f"Alias: {name} no ZIP = {alias_target} no projeto"] + models_changed(b, w)
                )
            model = w
            match_info = {
                "name": alias_target,
                "score": 1.0,
                "reasons": ["alias manual no config.json"],
                "path": b.get("path", ""),
            }
            target = b["path"]
        else:
            pending_orphan.append(w)
            continue

        item = {
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
            "content_hash": model.get("content_hash", ""),
            "done": status == "IGUAL",
            "match": match_info,
        }
        if match_info:
            item["match_name"] = match_info["name"]
            item["match_score"] = match_info["score"]
        items.append(item)

    # Passo 2: renomeações exclusivas (nunca se o nome do base já está no ZIP)
    reserved = set(claimed_base) | set(ws.keys())
    renames = assign_renames(pending_orphan, base, reserved, match_threshold)
    for w in pending_orphan:
        name = w["name"]
        hit = renames.get(name)
        if hit:
            claimed_base.add(hit["name"])
            bmatch = base[hit["name"]]
            status = "RENOMEADO"
            diff = models_changed(bmatch, w)
            diff.insert(
                0,
                f"ZIP chama '{name}', projeto tem '{hit['name']}' "
                f"(confiança {int(hit['score'] * 100)}%)",
            )
            for r in hit["reasons"]:
                diff.append(f"· {r}")
            target = hit["path"]
            match_info = hit
        else:
            status = "NOVO"
            diff = []
            target = w["path"]
            match_info = None

        item = {
            "name": name,
            "status": status,
            "label": ACTION_LABEL[status],
            "hint": ACTION_HINT[status],
            "path": target,
            "layer": w.get("layer", "other"),
            "layer_order": layer_order(w.get("layer", "other")),
            "type": w.get("type", "model"),
            "diff": diff,
            "refs": w.get("refs", []),
            "sources": w.get("sources", []),
            "hash": w.get("hash", ""),
            "content_hash": w.get("content_hash", ""),
            "done": False,
            "match": match_info,
        }
        if match_info:
            item["match_name"] = match_info["name"]
            item["match_score"] = match_info["score"]
        items.append(item)

    # Passo 3: removidos (opcional)
    if detect_removed:
        for name in sorted(base.keys()):
            if name in ws or name in claimed_base:
                continue
            b = base[name]
            items.append({
                "name": name,
                "status": "REMOVIDO",
                "label": ACTION_LABEL["REMOVIDO"],
                "hint": ACTION_HINT["REMOVIDO"],
                "path": b["path"],
                "layer": b.get("layer", "other"),
                "layer_order": layer_order(b.get("layer", "other")),
                "type": b.get("type", "model"),
                "diff": [],
                "refs": b.get("refs", []),
                "sources": b.get("sources", []),
                "hash": b.get("hash", ""),
                "content_hash": b.get("content_hash", ""),
                "done": False,
                "match": None,
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
    pending = [c["name"] for c in checklist if c["status"] in {"NOVO", "ALTERADO", "RENOMEADO"}]
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

    # similaridade simples (mesmo prefixo + overlap de refs) — só para NOVO sem match
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

    # Renomeações detectadas — alerta forte para não duplicar
    for item in checklist:
        if item["status"] != "RENOMEADO":
            continue
        match = item.get("match_name") or (item.get("match") or {}).get("name", "?")
        score = int((item.get("match_score") or 0) * 100)
        warnings.append({
            "severity": "warning",
            "label": "Atenção",
            "model": item["name"],
            "message": (
                f"O ZIP chama '{item['name']}', mas no projeto parece ser '{match}' "
                f"(confiança {score}%). São provavelmente o mesmo objeto com nomes diferentes."
            ),
            "action": (
                f"NÃO crie '{item['name']}'. Atualize '{match}' no path do projeto "
                f"ou cadastre um alias em config.json: \"{item['name']}\": \"{match}\"."
            ),
        })

    # Colisão de nomes (dois arquivos com mesmo basename)
    for name, m in models.items():
        if m.get("name_collision") or m.get("collisions"):
            extra = ", ".join(m.get("collisions", [])[:5])
            warnings.append({
                "severity": "warning",
                "label": "Atenção",
                "model": name,
                "message": (
                    f"Existem vários arquivos com o nome '{name}'. "
                    f"O Guardian usou um deles; confira se não há ambiguidade."
                    + (f" Outros: {extra}" if extra else "")
                ),
                "action": "Renomeie arquivos duplicados ou unifique em um único modelo.",
            })

    # ordenar por severidade
    rank = {"critical": 0, "warning": 1, "info": 2, "safe": 3}
    warnings.sort(key=lambda w: (rank.get(w["severity"], 9), w.get("model", "")))
    return warnings


def enrich_checklist(checklist: list[dict], graph: dict) -> list[dict]:
    for item in checklist:
        deps = list(downstream(graph, item["name"]))
        # se for renomeação, impacto também no nome do projeto
        match_name = item.get("match_name")
        if match_name:
            for d in downstream(graph, match_name):
                if d not in deps:
                    deps.append(d)
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
                mark = {
                    "NOVO": "criar",
                    "ALTERADO": "atualizar",
                    "IGUAL": "ok",
                    "REMOVIDO": "remover",
                    "RENOMEADO": "renomear?",
                }.get(st, st)
                parts.append(f"{n} ({mark})")
            chains.append(" → ".join(parts))
    return chains[:20]


def run(config: dict) -> dict:
    base_path = config.get("base_project_path") or ""
    ws_path = config.get("workspace_path") or ""
    snapshots_path = config.get("snapshots_path") or ""
    card_id = sanitize_card_id(config.get("card_id", "CARD-XXX"))
    config = dict(config)
    config["card_id"] = card_id

    base = load_project(base_path) if base_path and os.path.isdir(base_path) else {}
    ws = load_project(ws_path) if ws_path and os.path.isdir(ws_path) else {}

    # grafo unificado: base + workspace (workspace sobrescreve)
    merged = dict(base)
    merged.update(ws)

    detect_removed = bool(config.get("detect_removed", False))
    aliases = config.get("aliases") or {}
    match_threshold = float(config.get("match_threshold", 0.62))
    checklist = compare(
        base,
        ws,
        detect_removed=detect_removed,
        aliases=aliases,
        match_threshold=match_threshold,
    )
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
        "renomeado": sum(1 for c in checklist if c["status"] == "RENOMEADO"),
        "igual": sum(1 for c in checklist if c["status"] == "IGUAL"),
        "pending": sum(
            1 for c in checklist if c["status"] in {"NOVO", "ALTERADO", "REMOVIDO", "RENOMEADO"}
        ),
        "critical": sum(1 for w in warnings if w["severity"] == "critical"),
        "warning": sum(1 for w in warnings if w["severity"] == "warning"),
        "base_models": len(base),
        "workspace_models": len(ws),
    }

    empty_ws = len(ws) == 0
    missing_base = not (base_path and os.path.isdir(base_path))
    message = ""
    if missing_base:
        message = (
            "BASE AUSENTE OU INVÁLIDA — resultados NÃO são confiáveis. "
            "Configure base_project_path no config.json."
        )
    elif empty_ws:
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
        "missing_base": missing_base,
    }
    return session
