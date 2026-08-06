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
    include = config.get("base_include", [])
    if include is None:
        include = []
    if not isinstance(include, list):
        errors.append("base_include deve ser uma lista de nomes de pasta, ex.: [\"ebody\", \"AIS\"]")
    else:
        for name in include:
            if not isinstance(name, str) or not name.strip():
                errors.append("cada item de base_include deve ser texto (nome da pasta)")
                break
            if "/" in name or "\\" in name or ".." in name:
                errors.append(f"base_include inválido (só o nome da pasta, sem caminho): {name!r}")
                break
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
        for name in include if isinstance(include, list) else []:
            if isinstance(name, str) and name.strip():
                sub = os.path.join(base_abs, name.strip())
                if not os.path.isdir(sub):
                    errors.append(
                        f"base_include: pasta '{name}' não existe em {base_abs}"
                    )
    return errors


def list_top_folders(root: str) -> list[str]:
    """Pastas de 1º nível na base (ex.: AIS, ebody, Rodos)."""
    if not root or not os.path.isdir(root):
        return []
    out = []
    try:
        for name in sorted(os.listdir(root)):
            if name.startswith(".") or name in IGNORE_DIRS:
                continue
            full = os.path.join(root, name)
            if os.path.isdir(full) and not os.path.islink(full):
                out.append(name)
    except OSError:
        return []
    return out


def detect_domain(rel_path: str) -> str:
    """Primeiro segmento do path relativo = pasta de negócio (ex.: ebody/models/... → ebody)."""
    parts = (rel_path or "").replace("\\", "/").split("/")
    if not parts or not parts[0]:
        return ""
    # se começa com models/, não é domínio
    if parts[0].lower() in {"models", "macros", "seeds", "analyses", "tests", "snapshots"}:
        return ""
    return parts[0]


def resolve_scan_roots(root: str, include: list[str] | None) -> list[str]:
    """Raízes efetivas de varredura (base inteira ou só pastas de base_include)."""
    if not root or not os.path.isdir(root):
        return []
    root_abs = os.path.abspath(root)
    include = [n.strip() for n in (include or []) if isinstance(n, str) and n.strip()]
    if not include:
        return [root_abs]
    roots = []
    for name in include:
        sub = os.path.join(root_abs, name)
        if os.path.isdir(sub):
            roots.append(os.path.abspath(sub))
    return roots


def scan_dir(root: str, include: list[str] | None = None) -> list[str]:
    found = []
    roots = resolve_scan_roots(root, include)
    if not roots:
        return found
    root_abs = os.path.abspath(root)
    for start in roots:
        for dirpath, dirnames, filenames in os.walk(start, followlinks=False):
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


RE_REF = re.compile(r"""\{\{\s*ref\s*\(\s*['"]([^'"]+)['"]\s*\)\s*\}\}""", re.I)
RE_SOURCE = re.compile(
    r"""\{\{\s*source\s*\(\s*['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]\s*\)\s*\}\}""",
    re.I,
)
RE_JOIN = re.compile(r"\b((?:LEFT|RIGHT|INNER|FULL|CROSS)\s+JOIN|JOIN)\b", re.I)
RE_CAST = re.compile(r"\b((?:SAFE_|TRY_)?CAST)\s*\(", re.I)
RE_COMMENT_LINE = re.compile(r"--[^\n]*")
RE_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.S)
# Preferir alias: ... AS nome  |  fallback: table.col ou col no fim do item
RE_SELECT_ALIAS = re.compile(r"\bas\s+([A-Za-z_][\w]*)\s*(?=,|$)", re.I)
RE_SELECT_BARE = re.compile(
    r"(?:^|,)\s*(?:[\w.]+\.)?([A-Za-z_][\w]*)\s*(?:,|$)",
    re.M,
)

LAYER_MAP = (
    ("staging", "staging"),
    ("stg", "staging"),
    ("sample", "sample"),
    ("intermediate", "intermediate"),
    ("int", "intermediate"),
    ("marts", "mart"),
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

# Política: criar o novo; se já existe, ACRESCEENTAR só itens novos do card;
# nunca reescrever o código principal.
POLICY_LABEL = {
    "create": "Criar",
    "append": "Acrescentar",
    "skip": "Não alterar",
    "review": "Revisar",
    "exists": "Já na base",
    "observe": "Não alterar",
}

POLICY_HINT = {
    "create": (
        "Arquivo NOVO do card. Crie na base com os itens listados."
    ),
    "append": (
        "Arquivo JÁ EXISTE. Acrescente SOMENTE os itens novos do card "
        "(não copie o arquivo inteiro; não reescreva o código antigo, mesmo com erros)."
    ),
    "skip": (
        "Arquivo já existe e o card não trouxe itens novos seguros para acrescer. "
        "NÃO altere o código principal."
    ),
    "review": (
        "Revisar com cuidado: possível nome diferente ou remoção. "
        "NÃO crie duplicado e NÃO reescreva o principal."
    ),
    "exists": "Já está igual na base — nada a fazer.",
    "observe": "NÃO altere o arquivo principal.",
}

# Compat: labels antigos por status (quando add_only aplica policy_action)
ADD_ONLY_LABEL = {
    "NOVO": "Criar",
    "ALTERADO": "Não alterar",
    "REMOVIDO": "Não remover",
    "RENOMEADO": "Revisar",
    "IGUAL": "Já na base",
}

ADD_ONLY_HINT = {
    "NOVO": POLICY_HINT["create"],
    "ALTERADO": POLICY_HINT["skip"],
    "REMOVIDO": "NÃO remova da base.",
    "RENOMEADO": POLICY_HINT["review"],
    "IGUAL": POLICY_HINT["exists"],
}

# Taxonomia de colunas (prefixo → tipo DBT esperado)
COLUMN_TAXONOMY = {
    "aa": "integer",
    "ar": "array",
    "bn": "bignumeric",
    "by": "bytes",
    "cd": "string",
    "dd": "integer",
    "dm": "datetime",
    "ds": "string",
    "dt": "date",
    "fl": "boolean",
    "ge": "geography",
    "hh": "numeric",
    "hr": "time",
    "id": "integer",
    "im": "string",
    "in": "interval",
    "js": "json",
    "li": "record",
    "mm": "integer",
    "nm": "string",
    "nu": "integer",
    "pc": "numeric",
    "qt": "integer",
    "sg": "string",
    "sk": "integer",
    "sq": "integer",
    "st": "string",
    "te": "string",
    "to": "string",
    "ts": "timestamp",
    "tx": "numeric",
    "vr": "numeric",
}

# Natureza "código" / destino → representação numérica no DBT (integer)
CODE_LIKE_PREFIXES = {"cd", "id", "nu", "sk", "sq"}

TABLE_KIND_LABEL = {
    "F": "fato",
    "DIB": "dimensão",
    "AGGR": "agregada",
}

NAME_MAX_LEN = 35
RE_NAME_OK = re.compile(r"^[a-z][a-z0-9_]*$")
RE_COL_PREFIX = re.compile(r"^([a-z]{2})(?:_|$)")


def detect_table_kind(name: str, layer: str = "") -> str | None:
    """Detecta F / DIB / AGGR pelo nome ou camada."""
    n = (name or "").lower()
    lay = (layer or "").lower()
    if n.startswith("aggr_") or "_aggr_" in n:
        return "AGGR"
    if n.startswith("agg_") or lay == "aggregate":
        return "AGGR"
    if n.startswith("dib_") or "_dib_" in n:
        return "DIB"
    if n.startswith("f_") or re.search(r"(^|_)f_", n):
        return "F"
    if lay == "mart" and ("dim" in n or n.startswith("d_")):
        return "DIB"
    return None


def column_prefix(col: str) -> str | None:
    """Extrai prefixo de 2 letras da taxonomia (ex.: cd_cliente → cd)."""
    c = (col or "").strip().lower()
    if not c:
        return None
    m = RE_COL_PREFIX.match(c)
    if not m:
        return None
    pref = m.group(1)
    return pref if pref in COLUMN_TAXONOMY else None


def check_model_name_taxonomy(name: str) -> list[str]:
    """Regras de nome: minúsculas, underscore, máx. 35 caracteres."""
    issues = []
    if not name:
        return ["nome vazio"]
    if len(name) > NAME_MAX_LEN:
        issues.append(f"nome tem {len(name)} caracteres (máximo {NAME_MAX_LEN})")
    if name != name.lower():
        issues.append("nome deve ser todo em minúsculas")
    if "-" in name or " " in name:
        issues.append("use underscore (_) — sem hífen nem espaço")
    if not RE_NAME_OK.match(name.lower()):
        issues.append("use só a-z, 0-9 e underscore; comece com letra")
    return issues


def apply_add_only_labels(checklist: list[dict]) -> None:
    for item in checklist:
        action = item.get("policy_action")
        if action in POLICY_LABEL:
            item["label"] = POLICY_LABEL[action]
            item["hint"] = POLICY_HINT.get(action, "")
        else:
            st = item.get("status")
            if st in ADD_ONLY_LABEL:
                item["label"] = ADD_ONLY_LABEL[st]
                item["hint"] = ADD_ONLY_HINT[st]
        item["add_only"] = True


def validate_taxonomy(item: dict, models: dict) -> list[dict]:
    """Alertas de taxonomia (nome, tipo F/DIB/AGGR, prefixos de coluna)."""
    warnings = []
    name = item["name"]
    if item.get("type") not in {"model", "seed", None}:
        # yaml/source: só checa nome se for NOVO
        pass

    for issue in check_model_name_taxonomy(name):
        warnings.append({
            "severity": "warning",
            "label": "Taxonomia",
            "model": name,
            "message": f"Nome fora da taxonomia: {issue}.",
            "action": (
                f"Renomeie para minúsculas, separado por _, com no máximo {NAME_MAX_LEN} caracteres."
            ),
        })

    kind = detect_table_kind(name, item.get("layer", ""))
    if kind == "DIB":
        warnings.append({
            "severity": "info",
            "label": "Dimensão (DIB)",
            "model": name,
            "message": (
                "Tabela dimensão deve trazer informação complementar ao fato/evento, "
                "com regras de negócio e colunas adicionais documentadas."
            ),
            "action": "Confirme regras de negócio e colunas complementares antes de criar.",
        })
    elif kind == "AGGR":
        refs = item.get("refs") or []
        ok_origin = False
        for ref in refs:
            rk = detect_table_kind(ref, (models.get(ref) or {}).get("layer", ""))
            if rk in {"F", "DIB"}:
                ok_origin = True
                break
        if refs and not ok_origin:
            warnings.append({
                "severity": "warning",
                "label": "Agregada (AGGR)",
                "model": name,
                "message": (
                    "Tabela agregada deve ter origem em fato (F) ou dimensão (DIB), "
                    "pois só elas têm a visão analítica para gerar a agregação."
                ),
                "action": "Ajuste os ref() para apontar a uma fato ou dimensão.",
            })
        warnings.append({
            "severity": "info",
            "label": "Agregada (AGGR)",
            "model": name,
            "message": (
                "Explique de forma clara o conteúdo da agregada e a frequência de atualização."
            ),
            "action": "Documente conteúdo + frequência (diária, horária, etc.) no modelo/YAML.",
        })
    elif kind == "F":
        warnings.append({
            "severity": "info",
            "label": "Fato (F)",
            "model": name,
            "message": "Tabela fato (F): registre o evento/medida com chaves e métricas alinhadas à taxonomia.",
            "action": "Confira prefixos de coluna (id_, qt_, vr_, …) e tipos no DBT.",
        })

    # Colunas (aliases do SELECT) × taxonomia
    cols = item.get("columns") or (models.get(name) or {}).get("columns") or []
    for col in cols:
        pref = column_prefix(col)
        if not pref:
            # só alerta se parecer prefixo de 2 letras + underscore
            if re.match(r"^[a-z]{2}_", (col or "").lower()):
                raw = (col or "").lower()[:2]
                warnings.append({
                    "severity": "warning",
                    "label": "Taxonomia",
                    "model": name,
                    "message": (
                        f"Coluna '{col}' usa prefixo '{raw}_', que não está na taxonomia oficial."
                    ),
                    "action": (
                        "Use um prefixo válido (aa, cd, id, nm, qt, ts, …) conforme a natureza do campo."
                    ),
                })
            continue
        expected = COLUMN_TAXONOMY[pref]
        # Código / destino → reforço numérico
        if pref in CODE_LIKE_PREFIXES and expected == "string" and pref == "cd":
            warnings.append({
                "severity": "warning",
                "label": "Taxonomia",
                "model": name,
                "message": (
                    f"Coluna '{col}' (cd = código): se origem/destino for natureza código, "
                    f"o tipo no DBT deve ser numérico (integer). "
                    f"Se o negócio esperar texto, use string; se número, use integer."
                ),
                "action": (
                    "Parametrize no DBT: número → integer; varchar/texto → string. "
                    "Alinhe com a natureza do campo."
                ),
            })
        # prefixo válido: sem spam de info por coluna
    return warnings


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
    # source → sample → stg → int → dim/fato (mart) → aggr
    order = {
        "source": 1,
        "seed": 2,
        "sample": 3,
        "staging": 4,
        "intermediate": 5,
        "mart": 6,
        "aggregate": 7,
        "macro": 8,
        "other": 9,
    }
    return order.get(layer, 9)


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
        "domain": detect_domain(rel),
        "refs": parsed.get("refs", []),
        "sources": parsed.get("sources", []),
        "joins": parsed.get("joins", []),
        "casts": parsed.get("casts", []),
        "columns": parsed.get("columns", []),
        "content_hash": parsed.get("content_hash", ""),
    }
    model["hash"] = structural_hash(model)
    return model


def load_project(root: str, include: list[str] | None = None) -> dict[str, dict]:
    models: dict[str, dict] = {}
    collisions: list[str] = []
    if not root or not os.path.isdir(root):
        return models
    for path in scan_dir(root, include=include):
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


def _split_select_items(chunk: str) -> list[str]:
    """Divide o SELECT em itens respeitando parênteses (CAST, funções)."""
    items = []
    buf: list[str] = []
    depth = 0
    for ch in chunk:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == "," and depth == 0:
            part = "".join(buf).strip()
            if part:
                items.append(part)
            buf = []
        else:
            buf.append(ch)
    part = "".join(buf).strip()
    if part:
        items.append(part)
    return items


def extract_select_columns(chunk: str) -> list[str]:
    """Nomes de coluna do SELECT: prioriza AS alias; senão último identificador."""
    skip = {"as", "on", "and", "or", "case", "when", "then", "else", "end", "distinct", "select"}
    cols: list[str] = []
    for item in _split_select_items(chunk):
        # remove newlines excessivos
        flat = re.sub(r"\s+", " ", item).strip()
        if not flat:
            continue
        am = RE_SELECT_ALIAS.search(flat)
        if am:
            name = am.group(1).lower()
            if name not in skip:
                cols.append(name)
            continue
        # sem AS: pega identificador simples (table.col → col)
        bm = re.search(r"(?:[\w]+\.)?([A-Za-z_][\w]*)\s*$", flat)
        if bm:
            name = bm.group(1).lower()
            if name not in skip:
                cols.append(name)
    # dedupe preservando ordem
    seen = set()
    out = []
    for c in cols:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out[:40]


def parse_sql(text: str) -> dict:
    clean = _strip_comments(text)
    refs = sorted(set(RE_REF.findall(clean)))
    sources = sorted(set((a, b) for a, b in RE_SOURCE.findall(clean)))
    joins = sorted(set(j.upper().replace("  ", " ") for j in RE_JOIN.findall(clean)))
    casts = sorted(set(c.upper() for c in RE_CAST.findall(clean)))
    cols = []
    m = re.search(r"\bselect\b(.*?)\bfrom\b", clean, re.I | re.S)
    if m:
        cols = extract_select_columns(m.group(1))
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
            "columns": model.get("columns", []),
            "hash": model.get("hash", ""),
            "content_hash": model.get("content_hash", ""),
            "done": status == "IGUAL",
            "match": match_info,
            "table_kind": detect_table_kind(name, model.get("layer", "")),
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
            "columns": w.get("columns", []),
            "hash": w.get("hash", ""),
            "content_hash": w.get("content_hash", ""),
            "done": False,
            "match": match_info,
            "table_kind": detect_table_kind(name, w.get("layer", "")),
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
                "columns": b.get("columns", []),
                "hash": b.get("hash", ""),
                "content_hash": b.get("content_hash", ""),
                "done": False,
                "match": None,
                "table_kind": detect_table_kind(name, b.get("layer", "")),
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


def analyze_dag_cycles(graph: dict) -> list[dict]:
    """Ciclos com caminho e arestas candidatas a cortar (não altera find_cycles)."""
    out = []
    for cyc in find_cycles(graph):
        if not cyc or len(cyc) < 2:
            continue
        path = " → ".join(cyc)
        nodes = cyc[:-1]
        cut_edges = []
        for i in range(len(cyc) - 1):
            a, b = cyc[i], cyc[i + 1]
            cut_edges.append({"from": a, "to": b})
        out.append({
            "path": path,
            "nodes": nodes,
            "cycle": list(cyc),
            "cut_edges": cut_edges,
            "hint": (
                f"Remova uma ref() neste loop (candidatas: "
                + ", ".join(f"{e['from']}→{e['to']}" for e in cut_edges[:4])
                + ")."
            ),
        })
    return out


def topo_order_meta(checklist: list[dict], graph: dict, order: list[str] | None = None) -> dict:
    """Metadados da ordem: prefixo seguro vs nós travados por ciclo (ordem atual intacta)."""
    order = list(order) if order is not None else topo_order(checklist, graph)
    cycles = analyze_dag_cycles(graph)
    blocked_set: set[str] = set()
    for c in cycles:
        for n in c.get("nodes") or []:
            blocked_set.add(n)

    by_name = {c["name"]: c for c in checklist}
    pending = [
        c["name"]
        for c in checklist
        if c.get("policy_action") in {"create", "append"}
        or c["status"] in {"NOVO", "ALTERADO", "RENOMEADO"}
    ]
    seen: set[str] = set()
    pending_u = []
    for n in pending:
        if n not in seen:
            seen.add(n)
            pending_u.append(n)
    pending_set = set(pending_u)

    def sort_key(name: str) -> tuple:
        c = by_name.get(name) or {}
        layer = c.get("layer") or "other"
        kind = c.get("table_kind") or detect_table_kind(name, layer)
        kind_boost = {"AGGR": 2, "F": 1, "DIB": 1}.get(kind or "", 0)
        return (layer_order(layer), kind_boost, name)

    indeg = {n: 0 for n in pending_u}
    for n in pending_u:
        for r in graph.get(n, {}).get("refs", []):
            if r in pending_set:
                indeg[n] = indeg.get(n, 0) + 1

    ready = sorted([n for n, d in indeg.items() if d == 0], key=sort_key)
    safe_prefix: list[str] = []
    while ready:
        n = ready.pop(0)
        safe_prefix.append(n)
        for dep in graph.get(n, {}).get("dependents", []):
            if dep in indeg:
                indeg[dep] -= 1
                if indeg[dep] == 0:
                    ready.append(dep)
                    ready.sort(key=sort_key)

    blocked_by_cycle = [n for n in pending_u if n not in safe_prefix]
    # reforça com nós explicitamente no ciclo
    for n in sorted(blocked_set):
        if n in pending_set and n not in blocked_by_cycle:
            blocked_by_cycle.append(n)

    return {
        "order": order,
        "safe_prefix": safe_prefix,
        "blocked_by_cycle": blocked_by_cycle,
        "has_cycle": bool(cycles),
        "cycle_count": len(cycles),
        "cycles": cycles,
    }


def layer_edge_violations(
    checklist: list[dict],
    graph: dict,
    models: dict | None = None,
) -> list[dict]:
    """Refs que invertem/pulam camada (stg→mart, mart→stg, etc.)."""
    models = models or {}
    by_name = {c["name"]: c for c in checklist}
    violations = []

    def layer_of(name: str) -> str:
        if name.startswith("source."):
            return "source"
        c = by_name.get(name) or {}
        if c.get("layer"):
            return c["layer"]
        m = models.get(name) or {}
        if m.get("layer"):
            return m["layer"]
        return detect_layer(m.get("path") or name)

    for item in checklist:
        name = item["name"]
        src_layer = item.get("layer") or layer_of(name)
        src_ord = layer_order(src_layer)
        actionable = item.get("policy_action") in {"create", "append"} or item.get("status") == "NOVO"
        for ref in item.get("refs") or graph.get(name, {}).get("refs", []):
            if not ref or ref.startswith("source."):
                # source como ref de modelo é ok (camada 1)
                continue
            dst_layer = layer_of(ref)
            dst_ord = layer_order(dst_layer)
            # invertido: depende de camada mais "baixa" (downstream)
            if dst_ord > src_ord and src_layer != "other" and dst_layer != "other":
                violations.append({
                    "model": name,
                    "ref": ref,
                    "from_layer": src_layer,
                    "to_layer": dst_layer,
                    "kind": "inverted",
                    "actionable": actionable,
                    "message": (
                        f"'{name}' ({src_layer}) referencia '{ref}' ({dst_layer}) — "
                        f"camada invertida (dbt não deve apontar para downstream)."
                    ),
                })
            # pulo agressivo: source/sample direto para mart/aggregate sem staging
            elif (
                src_layer in {"mart", "aggregate"}
                and dst_layer in {"source", "sample"}
                and actionable
            ):
                violations.append({
                    "model": name,
                    "ref": ref,
                    "from_layer": src_layer,
                    "to_layer": dst_layer,
                    "kind": "skip",
                    "actionable": actionable,
                    "message": (
                        f"'{name}' ({src_layer}) referencia direto '{ref}' ({dst_layer}). "
                        f"Prefira passar por staging/intermediate."
                    ),
                })
    return violations


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
    """Ordem de execução: respeita refs e prioriza source→sample→stg→int→dim/fato→aggr."""
    by_name = {c["name"]: c for c in checklist}
    pending = [
        c["name"]
        for c in checklist
        if c.get("policy_action") in {"create", "append"}
        or c["status"] in {"NOVO", "ALTERADO", "RENOMEADO"}
    ]
    # dedupe preservando
    seen = set()
    pending_u = []
    for n in pending:
        if n not in seen:
            seen.add(n)
            pending_u.append(n)
    pending = pending_u
    pending_set = set(pending)

    def sort_key(name: str) -> tuple:
        c = by_name.get(name) or {}
        layer = c.get("layer") or "other"
        kind = c.get("table_kind") or detect_table_kind(name, layer)
        # AGGR depois de F/DIB na mesma faixa
        kind_boost = {"AGGR": 2, "F": 1, "DIB": 1}.get(kind or "", 0)
        return (layer_order(layer), kind_boost, name)

    indeg = {n: 0 for n in pending}
    for n in pending:
        for r in graph.get(n, {}).get("refs", []):
            if r in pending_set:
                indeg[n] = indeg.get(n, 0) + 1
            # source.* não está em pending — ok (indeg não sobe)

    ready = sorted([n for n, d in indeg.items() if d == 0], key=sort_key)
    order = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        for dep in graph.get(n, {}).get("dependents", []):
            if dep in indeg:
                indeg[dep] -= 1
                if indeg[dep] == 0:
                    ready.append(dep)
                    ready.sort(key=sort_key)
    for n in sorted(pending, key=sort_key):
        if n not in order:
            order.append(n)
    return order


def verify_card(config: dict, session: dict) -> dict:
    """Re-lê a base e confere o que o card pediu vs o que está lá agora."""
    base_path = config.get("base_project_path") or ""
    include = config.get("base_include") or []
    if not isinstance(include, list):
        include = []
    base_now = (
        load_project(base_path, include=include)
        if base_path and os.path.isdir(base_path)
        else {}
    )

    created_ok = []
    created_missing = []
    append_ok = []
    append_partial = []
    append_missing = []
    diverged = []
    details = []

    for item in session.get("checklist") or []:
        action = item.get("policy_action")
        name = item["name"]
        target = item.get("match_name") or name

        if action == "create":
            if name in base_now:
                created_ok.append(name)
                details.append({
                    "name": name,
                    "action": "create",
                    "result": "ok",
                    "message": f"Arquivo '{name}' encontrado na base.",
                })
            else:
                created_missing.append(name)
                details.append({
                    "name": name,
                    "action": "create",
                    "result": "missing",
                    "message": f"Ainda não está na base — falta criar '{name}'.",
                })

        elif action == "append":
            expected = [
                a["name"]
                for a in (item.get("add_items") or [])
                if a.get("kind") == "coluna"
            ]
            # também refs novas como informativo
            expected_refs = [
                a["name"]
                for a in (item.get("add_items") or [])
                if a.get("kind") == "referência"
            ]
            b = base_now.get(target)
            if not b:
                append_missing.append(target)
                details.append({
                    "name": target,
                    "action": "append",
                    "result": "missing_file",
                    "message": f"Arquivo '{target}' não encontrado na base para conferir acrescento.",
                    "expected": expected,
                })
                continue
            cols_now = set(c.lower() for c in (b.get("columns") or []))
            found = [c for c in expected if c.lower() in cols_now]
            missing = [c for c in expected if c.lower() not in cols_now]
            # corpo divergiu do workspace original?
            ws_hash = item.get("content_hash") or ""
            # não temos ws reload aqui — usar ignored_changes como sinal
            if missing and found:
                append_partial.append(target)
                details.append({
                    "name": target,
                    "action": "append",
                    "result": "partial",
                    "message": (
                        f"Acrescentado parcial em '{target}': ok={found}, falta={missing}."
                    ),
                    "found": found,
                    "missing": missing,
                })
            elif missing and not found:
                append_missing.append(target)
                details.append({
                    "name": target,
                    "action": "append",
                    "result": "missing",
                    "message": f"Nenhum item novo detectado em '{target}'. Falta: {missing}.",
                    "missing": missing,
                })
            else:
                append_ok.append(target)
                details.append({
                    "name": target,
                    "action": "append",
                    "result": "ok",
                    "message": (
                        f"Itens novos presentes em '{target}': {found or 'ok'}."
                        + (f" Refs pedidas: {expected_refs}" if expected_refs else "")
                    ),
                    "found": found,
                })
            # se o card tinha ignored body change e o arquivo mudou de hash vs snapshot esperado
            if item.get("ignored_changes"):
                # informação: mudanças manuais podem existir
                diverged.append({
                    "name": target,
                    "message": (
                        "Havia diferença de SQL no ZIP (ignorada). "
                        "Confira se ajustes manuais não quebraram o modelo."
                    ),
                })

    planned = sum(
        1
        for c in session.get("checklist") or []
        if c.get("policy_action") in {"create", "append"}
    )
    done = len(created_ok) + len(append_ok)

    pending_only = []
    for name in created_missing:
        pending_only.append({
            "name": name,
            "action": "create",
            "missing": [],
            "message": f"Falta criar '{name}' na base.",
        })
    for name in append_missing:
        detail = next(
            (d for d in details if d.get("name") == name and d.get("action") == "append"),
            {},
        )
        pending_only.append({
            "name": name,
            "action": "append",
            "missing": list(detail.get("missing") or detail.get("expected") or []),
            "message": detail.get("message") or f"Falta acrescer itens em '{name}'.",
        })
    for name in append_partial:
        detail = next(
            (d for d in details if d.get("name") == name and d.get("result") == "partial"),
            {},
        )
        pending_only.append({
            "name": name,
            "action": "append",
            "missing": list(detail.get("missing") or []),
            "message": detail.get("message") or f"Acrescento parcial em '{name}'.",
        })

    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "card_id": session.get("card_id"),
        "planned": planned,
        "done_ok": done,
        "created_ok": created_ok,
        "created_missing": created_missing,
        "append_ok": append_ok,
        "append_partial": append_partial,
        "append_missing": append_missing,
        "diverged": diverged,
        "details": details,
        "pending_only": pending_only,
        "complete": (
            not created_missing
            and not append_missing
            and not append_partial
        ),
        "summary_text": "",
        "pending_markdown": "",
    }

    lines = []
    if pending_only:
        lines.append("=== SÓ O QUE FALTA ===")
        for i, p in enumerate(pending_only, 1):
            miss = p.get("missing") or []
            extra = f" | falta: {', '.join(miss)}" if miss else ""
            lines.append(f"  {i}. [{p['action']}] {p['name']}{extra}")
            if p.get("message"):
                lines.append(f"      {p['message']}")
        lines.append("")
    else:
        lines.append("=== SÓ O QUE FALTA ===")
        lines.append("  (nada pendente)")
        lines.append("")

    lines.extend([
        f"Planejado: {planned} ação(ões) · OK: {done}",
        f"Criados OK: {', '.join(created_ok) or '—'}",
        f"Acrescentados OK: {', '.join(append_ok) or '—'}",
    ])
    if diverged:
        lines.append(
            "Atenção manual: "
            + "; ".join(d["name"] + " — " + d["message"] for d in diverged[:5])
        )
    report["summary_text"] = "\n".join(lines)
    report["pending_markdown"] = build_pending_markdown(report)
    return report


def collect_declared_sources(models: dict) -> set[str]:
    """Origens declaradas em YAML (source.schema.table)."""
    declared = set()
    for m in models.values():
        for schema, table in m.get("sources") or []:
            # só conta como declarado se veio de arquivo yaml/source
            if m.get("type") in {"source", "yaml"} or (m.get("path") or "").lower().endswith(
                (".yml", ".yaml")
            ):
                declared.add(f"source.{schema}.{table}")
    return declared


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


def validate(
    checklist: list[dict],
    graph: dict,
    models: dict,
    patterns: dict,
    *,
    add_only: bool = True,
    enforce_taxonomy: bool = True,
    declared_sources: set | None = None,
) -> list[dict]:
    warnings = []
    known = set(models) | set(graph)
    declared_sources = declared_sources or set()
    # sources virtuais
    for name, m in models.items():
        for schema, table in m.get("sources", []):
            known.add(f"source.{schema}.{table}")

    dag_cycles = analyze_dag_cycles(graph)
    for info in dag_cycles:
        cyc = info.get("cycle") or []
        path = info.get("path") or " → ".join(cyc)
        warnings.append({
            "severity": "critical",
            "label": "Ciclo na DAG",
            "code": "DAG_CYCLE",
            "model": cyc[0] if cyc else "",
            "cycle_path": path,
            "cut_edges": info.get("cut_edges") or [],
            "message": (
                f"Loop no fluxo (dbt não compila): {path}. "
                f"Ex.: A→B→C→D→A é inválido."
            ),
            "action": info.get("hint") or "Remova uma das referências circulares (ref).",
        })

    for viol in layer_edge_violations(checklist, graph, models):
        # aviso (não bloqueio rígido): ZIP/IA pode trazer ref errada e você refatora na base
        code = "LAYER_INVERTED" if viol.get("kind") == "inverted" else "LAYER_SKIP"
        warnings.append({
            "severity": "warning",
            "label": "Camada",
            "code": code,
            "model": viol.get("model") or "",
            "ref": viol.get("ref") or "",
            "message": viol.get("message") or "",
            "action": (
                f"Ajuste ref('{viol.get('ref')}') para respeitar "
                f"source → sample → stg → int → mart → aggregate."
            ),
        })

    for item in checklist:
        name = item["name"]
        status = item["status"]

        # Política add_only: append = acrescer só o novo; skip/review = não reescrever
        action = item.get("policy_action") or ""
        if add_only and status == "ALTERADO" and action == "append":
            n_add = int(item.get("add_count") or 0)
            sample = ", ".join(a["name"] for a in (item.get("add_items") or [])[:6])
            warnings.append({
                "severity": "warning",
                "label": "Acrescentar",
                "model": name,
                "policy": True,
                "message": (
                    f"'{name}' já existe na base. O card trouxe {n_add} item(ns) NOVO(S) "
                    f"({sample}). Acrescente SOMENTE isso no arquivo — "
                    f"não substitua o código antigo (mesmo com erros no ZIP)."
                ),
                "action": (
                    f"Abra '{name}' na base e adicione apenas os itens listados no checklist. "
                    f"Ignore mudanças de SQL que não sejam acrescento."
                ),
            })
        elif add_only and status == "ALTERADO" and action == "skip":
            warnings.append({
                "severity": "critical",
                "label": "Não alterar",
                "model": name,
                "policy": True,
                "message": (
                    f"'{name}' já existe e o card não trouxe itens novos para acrescer "
                    f"(só mudou corpo/SQL). NÃO altere o arquivo principal."
                ),
                "action": "Ignore as diferenças do ZIP neste arquivo.",
            })
        if add_only and status == "RENOMEADO" and action == "append":
            match = item.get("match_name") or "?"
            n_add = int(item.get("add_count") or 0)
            warnings.append({
                "severity": "warning",
                "label": "Acrescentar",
                "model": name,
                "policy": True,
                "message": (
                    f"ZIP='{name}' corresponde a '{match}' na base. "
                    f"Acrescente só os {n_add} item(ns) novos em '{match}'. "
                    f"Não crie '{name}'."
                ),
                "action": f"Edite '{match}' apenas para acrescentar os itens novos.",
            })
        elif add_only and status == "RENOMEADO":
            match = item.get("match_name") or "?"
            warnings.append({
                "severity": "critical",
                "label": "Revisar",
                "model": name,
                "policy": True,
                "message": (
                    f"O ZIP chama '{name}', mas na base já existe '{match}'. "
                    f"NÃO crie duplicado e NÃO reescreva o arquivo antigo."
                ),
                "action": f"Revise; use '{match}' se for o mesmo objeto.",
            })
        if add_only and status == "REMOVIDO":
            warnings.append({
                "severity": "critical",
                "label": "Revisar",
                "model": name,
                "policy": True,
                "message": f"NÃO remova '{name}' da base sem pedido explícito.",
                "action": "Mantenha o arquivo na base.",
            })

        if status == "IGUAL":
            continue

        # refs inexistentes — só bloqueia de verdade para o que vamos CRIAR
        for ref in item.get("refs", []):
            if ref not in known and not ref.startswith("source."):
                sev = "critical" if status == "NOVO" else "warning"
                warnings.append({
                    "severity": sev,
                    "label": "Bloqueio" if sev == "critical" else "Atenção",
                    "code": "BROKEN_REF" if sev == "critical" else "BROKEN_REF_INFO",
                    "model": name,
                    "message": (
                        f"O arquivo {name} referencia {ref}, mas ele não existe no projeto. "
                        f"Crie {ref} primeiro."
                        if status == "NOVO"
                        else (
                            f"Diferença no ZIP: {name} referencia {ref}. "
                            f"Como não alteramos o antigo, isto é só informativo."
                        )
                    ),
                    "action": (
                        f"Crie o arquivo {ref} ou corrija a referência."
                        if status == "NOVO"
                        else "Não altere o arquivo antigo."
                    ),
                })
        for schema, table in item.get("sources", []):
            src = f"source.{schema}.{table}"
            if item.get("policy_action") in {"create", "append"} or item["status"] == "NOVO":
                if declared_sources and src not in declared_sources:
                    warnings.append({
                        "severity": "warning",
                        "label": "Sources",
                        "code": "UNDECLARED_SOURCE",
                        "model": name,
                        "message": (
                            f"O arquivo {name} usa source('{schema}', '{table}'), "
                            f"mas isso não aparece declarado em sources.yml na base/workspace."
                        ),
                        "action": (
                            f"Declare {schema}.{table} no sources.yml ou confirme o nome da origem."
                        ),
                    })
                elif src not in known:
                    warnings.append({
                        "severity": "warning",
                        "label": "Sources",
                        "code": "UNDECLARED_SOURCE",
                        "model": name,
                        "message": (
                            f"O arquivo {name} usa a origem {schema}.{table}. "
                            f"Confirme se está declarada no sources.yml."
                        ),
                        "action": "Verifique o arquivo de sources (.yml).",
                    })

        # nomenclatura empírica da base (só para NOVO)
        prefs = patterns.get("by_layer", {}).get(item.get("layer", ""), {})
        if prefs and "_" in name and status == "NOVO":
            prefix = name.split("_", 1)[0] + "_"
            top = next(iter(prefs), None)
            if top and prefix not in prefs:
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

        # Taxonomia corporativa — sinaliza se a IA/ZIP fugiu da regra (foco no NOVO)
        if enforce_taxonomy and status == "NOVO":
            warnings.extend(validate_taxonomy(item, models))

        # SAFE_CAST
        casts = models.get(name, {}).get("casts", []) if name in models else []
        if status == "NOVO" and any(c.upper() in {"SAFE_CAST", "TRY_CAST"} for c in casts):
            warnings.append({
                "severity": "safe",
                "label": "Seguro",
                "model": name,
                "message": f"{name} usa SAFE_CAST/TRY_CAST — boa prática detectada.",
                "action": "",
            })

        # removido com downstream (quando não é add_only, ou reforço)
        if status == "REMOVIDO" and not add_only:
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
        if status == "NOVO" and item.get("layer") not in {"source", "mart", "aggregate", "seed"}:
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
        if status == "NOVO" and ("_sample" in name.lower() or item.get("layer") == "sample"):
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

    # similaridade simples — só para NOVO
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

    # Renomeações — se não for add_only, aviso clássico
    if not add_only:
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

    # Colisão de nomes
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

    rank = {"critical": 0, "warning": 1, "info": 2, "safe": 3}
    warnings.sort(key=lambda w: (rank.get(w["severity"], 9), w.get("model", "")))
    return warnings


def upstream(graph: dict, name: str) -> list[str]:
    """Ancestors (refs transitivos), ordem da origem → atual."""
    if name not in graph:
        return []
    out = []
    seen = set()
    q = deque(graph[name].get("refs", []))
    while q:
        n = q.popleft()
        if n in seen:
            continue
        seen.add(n)
        out.append(n)
        q.extend(graph.get(n, {}).get("refs", []))
    out.reverse()
    return out


def compute_add_items(ws_model: dict | None, base_model: dict | None = None) -> list[dict]:
    """Itens que o card traz para ACRESULAR (nunca remoções/alterações)."""
    ws_model = ws_model or {}
    items: list[dict] = []

    def push(kind: str, name: str, extra: dict | None = None):
        row = {"kind": kind, "name": str(name)}
        if extra:
            row.update(extra)
        items.append(row)

    if base_model is None:
        cols = list(ws_model.get("columns") or [])
        refs = list(ws_model.get("refs") or [])
        sources = list(ws_model.get("sources") or [])
        joins = list(ws_model.get("joins") or [])
        casts = list(ws_model.get("casts") or [])
    else:
        cols, _ = _set_diff(base_model.get("columns") or [], ws_model.get("columns") or [])
        refs, _ = _set_diff(base_model.get("refs") or [], ws_model.get("refs") or [])
        sources, _ = _set_diff(base_model.get("sources") or [], ws_model.get("sources") or [])
        joins, _ = _set_diff(base_model.get("joins") or [], ws_model.get("joins") or [])
        casts, _ = _set_diff(base_model.get("casts") or [], ws_model.get("casts") or [])

    for c in cols:
        pref = column_prefix(c)
        push(
            "coluna",
            c,
            {
                "prefix": pref or "",
                "dbt_type": COLUMN_TAXONOMY.get(pref, "") if pref else "",
            },
        )
    for r in refs:
        push("referência", r)
    for src in sources:
        if isinstance(src, (list, tuple)) and len(src) >= 2:
            push("origem", f"{src[0]}.{src[1]}")
        else:
            push("origem", str(src))
    for j in joins:
        push("join", j)
    for c in casts:
        push("cast", c)
    return items


def ignored_changes(ws_model: dict | None, base_model: dict | None) -> list[str]:
    """Mudanças do card que NÃO devem ser aplicadas no arquivo principal."""
    if not base_model or not ws_model:
        return []
    notes = []
    _, rem_cols = _set_diff(base_model.get("columns") or [], ws_model.get("columns") or [])
    _, rem_refs = _set_diff(base_model.get("refs") or [], ws_model.get("refs") or [])
    for c in rem_cols:
        notes.append(f"coluna removida no ZIP (ignore): {c}")
    for r in rem_refs:
        notes.append(f"referência removida no ZIP (ignore): {r}")
    if (
        base_model.get("content_hash")
        and ws_model.get("content_hash")
        and base_model["content_hash"] != ws_model["content_hash"]
    ):
        notes.append("SQL/corpo diferente no ZIP — NÃO reescreva o arquivo principal")
    return notes


def build_snippet(item: dict) -> dict:
    """Texto para copiar: só adições (append) ou guia de criar (create)."""
    action = item.get("policy_action") or ""
    name = item.get("match_name") or item.get("name") or ""
    path = item.get("path") or ""
    adds = item.get("add_items") or []
    base_cols = item.get("base_columns") or []
    ignored = item.get("ignored_changes") or []

    cols = [a["name"] for a in adds if a.get("kind") == "coluna"]
    refs = [a["name"] for a in adds if a.get("kind") == "referência"]
    sources = [a["name"] for a in adds if a.get("kind") == "origem"]
    other = [
        a for a in adds
        if a.get("kind") not in {"coluna", "referência", "origem"}
    ]

    place = [a["name"] for a in adds]
    exists = list(base_cols)
    attention = list(ignored)

    if action == "create" or item.get("status") == "NOVO":
        lines = [
            f"-- DBT Sentinel — CRIAR arquivo `{name}`",
            "-- NÃO altere arquivos que já existem na base.",
            f"-- Destino: {path or '(path no card)'}",
            "-- Ação: copie o arquivo do workspace/ para o path acima.",
            "--",
            "-- Checklist do que este arquivo traz:",
        ]
        if cols:
            lines.append("-- Colunas:")
            for c in cols:
                lines.append(f"--   - {c}")
        if refs:
            lines.append("-- Refs:")
            for r in refs:
                lines.append(f"--   - {{{{ ref('{r}') }}}}")
        if sources:
            lines.append("-- Sources:")
            for s in sources:
                lines.append(f"--   - {s}")
        if not (cols or refs or sources):
            lines.append("--   (ver arquivo no workspace)")
        text = "\n".join(lines) + "\n"
        label = "Guia para CRIAR (copie do workspace)"
    elif action == "append":
        lines = [
            f"-- DBT Sentinel — ACRESCENTAR em `{name}`",
            "-- Só adições. NÃO reescreva o arquivo principal.",
            f"-- Path: {path or '(path no card)'}",
            "--",
        ]
        if cols:
            lines.append("-- Colunas novas (acrescente no SELECT):")
            for i, c in enumerate(cols):
                # vírgula à esquerda: padrão para colar após coluna existente
                lines.append(f", {c}")
            lines.append("--")
        if refs:
            lines.append("-- Refs novas (use no FROM/JOIN — não remova as antigas):")
            for r in refs:
                lines.append(f"-- {{{{ ref('{r}') }}}}")
            lines.append("--")
        if sources:
            lines.append("-- Sources novas:")
            for s in sources:
                parts = str(s).split(".", 1)
                if len(parts) == 2:
                    lines.append(f"-- {{{{ source('{parts[0]}', '{parts[1]}') }}}}")
                else:
                    lines.append(f"-- {s}")
            lines.append("--")
        if other:
            lines.append("-- Outros itens novos:")
            for a in other:
                lines.append(f"--   [{a.get('kind')}] {a.get('name')}")
            lines.append("--")
        if exists:
            lines.append("-- Já na base (não mexer):")
            lines.append("--   " + ", ".join(exists[:20]))
            if len(exists) > 20:
                lines.append(f"--   … +{len(exists) - 20}")
            lines.append("--")
        if attention:
            lines.append("-- Atenções (NÃO aplicar do ZIP):")
            for note in attention[:8]:
                lines.append(f"--   ! {note}")
        if not cols and not refs and not sources and not other:
            lines.append("-- (sem itens novos detectados)")
        text = "\n".join(lines) + "\n"
        label = "Só adições — não reescreva"
    else:
        text = (
            f"-- `{name}`: sem snippet de criação/acréscimo "
            f"(ação={action or '—'}).\n"
        )
        label = "Sem snippet"
        place, exists, attention = [], exists, attention

    return {
        "label": label,
        "text": text,
        "place": place,
        "exists": exists,
        "attention": attention,
        "action": action or "",
    }


def build_order_markdown(checklist: list[dict], order: list[str], card_id: str = "") -> str:
    """Roteiro Markdown colável (Jira / VS Code)."""
    by_name = {c["name"]: c for c in checklist}
    actionable = []
    for n in order or []:
        c = by_name.get(n)
        if c and c.get("policy_action") in {"create", "append"}:
            actionable.append(c)
    seen = {c["name"] for c in actionable}
    for c in checklist:
        if c.get("policy_action") in {"create", "append"} and c["name"] not in seen:
            actionable.append(c)
            seen.add(c["name"])

    lines = [f"# Card {card_id or 'CARD'} — roteiro", ""]
    if not actionable:
        lines.append("_Nada para executar neste card._")
        lines.append("")
        return "\n".join(lines)

    for i, c in enumerate(actionable, 1):
        action = c.get("policy_action")
        target = c.get("match_name") or c["name"]
        path = c.get("path") or ""
        adds = c.get("add_items") or []
        names = ", ".join(f"`{a['name']}`" for a in adds[:12])
        more = f" (+{len(adds) - 12})" if len(adds) > 12 else ""
        if action == "create":
            lines.append(
                f"{i}. [ ] **CRIAR** `{target}` — `{path}`"
                + (f" — traz: {names}{more}" if names else "")
            )
        else:
            lines.append(
                f"{i}. [ ] **ACRESCENTAR** `{target}`"
                + (f": {names}{more}" if names else " (itens novos do card)")
                + (f" — `{path}`" if path else "")
            )
            lines.append("   - Só o novo. **Não reescreva** o arquivo principal.")

    # atenções
    att_lines = []
    for c in checklist:
        for note in c.get("ignored_changes") or []:
            att_lines.append(f"- `{c['name']}`: {note}")
        if c.get("policy_action") in {"skip", "review"}:
            att_lines.append(
                f"- `{c['name']}`: {c.get('add_summary') or c.get('hint') or 'revisar / não alterar'}"
            )
    if att_lines:
        lines.append("")
        lines.append("## Atenções")
        lines.extend(att_lines[:30])
    lines.append("")
    lines.append("_Gerado pelo DBT Sentinel — somente adições; base corporativa read-only._")
    lines.append("")
    return "\n".join(lines)


def build_pending_markdown(report: dict) -> str:
    """Markdown curto: só o que falta após verificação."""
    card = report.get("card_id") or "CARD"
    pending = report.get("pending_only") or []
    lines = [f"# Card {card} — só o que falta", ""]
    if not pending:
        lines.append("Nada pendente — tudo que o card pediu parece estar na base.")
        lines.append("")
        return "\n".join(lines)
    for i, p in enumerate(pending, 1):
        miss = p.get("missing") or []
        miss_s = (", ".join(f"`{m}`" for m in miss[:12]) if miss else "")
        lines.append(
            f"{i}. [ ] **{p.get('action', '').upper()}** `{p.get('name')}`"
            + (f" — falta: {miss_s}" if miss_s else "")
        )
        if p.get("message"):
            lines.append(f"   - {p['message']}")
    lines.append("")
    return "\n".join(lines)


def enrich_additive(
    checklist: list[dict],
    base: dict,
    ws: dict,
) -> list[dict]:
    """Anexa add_items / add_count e metadados de política por arquivo."""
    for item in checklist:
        name = item["name"]
        status = item["status"]
        w = ws.get(name)
        if status == "RENOMEADO":
            bname = item.get("match_name")
            b = base.get(bname) if bname else None
            w = w or ws.get(name)
        elif status == "REMOVIDO":
            b = base.get(name)
            w = None
        else:
            b = base.get(name)

        if status == "NOVO":
            adds = compute_add_items(w, None)
            item["exists_in_base"] = False
            item["policy_action"] = "create"
            item["bucket"] = "criar"
            item["add_summary"] = (
                f"Você vai criar este arquivo e adicionar {len(adds)} item(ns)."
                if adds
                else "Você vai criar este arquivo novo na base."
            )
        elif status == "IGUAL":
            adds = []
            item["exists_in_base"] = True
            item["policy_action"] = "exists"
            item["bucket"] = "pronto"
            item["add_summary"] = "Já existe na base e está igual — nada a adicionar."
        elif status == "ALTERADO":
            adds = compute_add_items(w, b)
            item["exists_in_base"] = True
            if adds:
                # Já existe MAS o card trouxe itens novos → ACRESCEENTAR só o novo
                item["policy_action"] = "append"
                item["bucket"] = "acrescentar"
                names = ", ".join(a["name"] for a in adds[:8])
                more = f" (+{len(adds)-8})" if len(adds) > 8 else ""
                item["add_summary"] = (
                    f"Arquivo já existe. ACRESCENTE somente estes {len(adds)} item(ns) novos "
                    f"do card ({names}{more}). Não reescreva o restante do arquivo."
                )
            else:
                item["policy_action"] = "skip"
                item["bucket"] = "nao_alterar"
                item["add_summary"] = (
                    "Arquivo já existe. O card mudou SQL/estrutura sem itens novos "
                    "para acrescer — NÃO altere o principal."
                )
        elif status == "RENOMEADO":
            adds = compute_add_items(w, b)
            item["exists_in_base"] = True
            match = item.get("match_name") or "?"
            if adds:
                item["policy_action"] = "append"
                item["bucket"] = "acrescentar"
                item["add_summary"] = (
                    f"O ZIP chama '{name}', mas na base é '{match}'. "
                    f"Acrescente só os {len(adds)} item(ns) novos em '{match}' — "
                    f"não crie '{name}' e não reescreva o arquivo."
                )
            else:
                item["policy_action"] = "review"
                item["bucket"] = "revisar"
                item["add_summary"] = (
                    f"Nome diferente: ZIP='{name}' / base='{match}'. "
                    f"Revise — não crie duplicado e não reescreva o principal."
                )
        else:  # REMOVIDO
            adds = []
            item["exists_in_base"] = True
            item["policy_action"] = "review"
            item["bucket"] = "revisar"
            item["add_summary"] = "NÃO remova da base. Só revise se a remoção foi pedida à parte."

        item["add_items"] = adds
        item["add_count"] = len(adds)
        item["ignored_changes"] = ignored_changes(w, b) if b and w else []
        if w and not item.get("columns"):
            item["columns"] = list(w.get("columns") or [])
        if b and status != "NOVO":
            item["base_columns"] = list(b.get("columns") or [])
        item["table_kind"] = item.get("table_kind") or detect_table_kind(
            name, item.get("layer", "")
        )
        if item.get("policy_action") in {"create", "append"}:
            item["snippet"] = build_snippet(item)
        else:
            item["snippet"] = None
    return checklist


def build_lineage(checklist: list[dict], graph: dict, models: dict) -> dict:
    """Estrutura para UI: nós por camada + arestas + metadados clicáveis."""
    status_map = {c["name"]: c for c in checklist}
    # incluir refs/sources do grafo que aparecem no checklist ou como vizinhos
    names = set(status_map)
    for c in checklist:
        if c["status"] == "REMOVIDO":
            continue
        names.add(c["name"])
        for r in c.get("refs") or []:
            names.add(r)
        for schema, table in c.get("sources") or []:
            names.add(f"source.{schema}.{table}")
        match = c.get("match_name")
        if match:
            names.add(match)

    layer_of = {}
    for n in names:
        if n in status_map:
            layer_of[n] = status_map[n].get("layer") or "other"
        elif n.startswith("source."):
            layer_of[n] = "source"
        elif n in models:
            layer_of[n] = models[n].get("layer") or detect_layer(models[n].get("path", ""))
        else:
            layer_of[n] = "other"

    nodes = []
    for n in sorted(names, key=lambda x: (layer_order(layer_of.get(x, "other")), x)):
        item = status_map.get(n)
        if item:
            status = item["status"]
            action = item.get("policy_action") or ""
            if action == "create" or status == "NOVO":
                visual = "new"
            elif action == "append":
                visual = "append"
            elif action in {"skip", "observe"} or status == "REMOVIDO":
                visual = "locked"
            elif action == "review":
                visual = "review"
            else:
                visual = "exist"
            node = {
                "id": n,
                "label": n,
                "status": status,
                "visual": visual,
                "layer": item.get("layer") or layer_of[n],
                "table_kind": item.get("table_kind"),
                "path": item.get("path", ""),
                "domain": item.get("domain") or "",
                "add_count": item.get("add_count", 0),
                "add_items": item.get("add_items") or [],
                "add_summary": item.get("add_summary") or "",
                "ignored_changes": item.get("ignored_changes") or [],
                "columns": item.get("columns") or [],
                "base_columns": item.get("base_columns") or [],
                "refs": item.get("refs") or [],
                "sources": [
                    f"{a}.{b}" for a, b in (item.get("sources") or [])
                ],
                "upstream": upstream(graph, n),
                "downstream": list(downstream(graph, n)),
                "depends_on": list(graph.get(n, {}).get("refs", [])),
                "used_by": list(graph.get(n, {}).get("dependents", [])),
                "policy_action": action or "observe",
                "bucket": item.get("bucket") or "",
                "hint": item.get("hint") or "",
                "type": item.get("type") or "model",
            }
        else:
            # nó de contexto (já na base / source virtual)
            m = models.get(n) or {}
            node = {
                "id": n,
                "label": n,
                "status": "IGUAL" if not n.startswith("source.") else "SOURCE",
                "visual": "exist",
                "layer": layer_of[n],
                "table_kind": detect_table_kind(n, layer_of[n]),
                "path": m.get("path", ""),
                "domain": m.get("domain") or "",
                "add_count": 0,
                "add_items": [],
                "add_summary": "Já existe no projeto (contexto do fluxo).",
                "ignored_changes": [],
                "columns": list(m.get("columns") or []),
                "base_columns": list(m.get("columns") or []),
                "refs": list(m.get("refs") or []),
                "sources": [f"{a}.{b}" for a, b in (m.get("sources") or [])],
                "upstream": upstream(graph, n),
                "downstream": list(downstream(graph, n)),
                "depends_on": list(graph.get(n, {}).get("refs", [])),
                "used_by": list(graph.get(n, {}).get("dependents", [])),
                "policy_action": "exists",
                "bucket": "pronto",
                "hint": "Nó de contexto — já na base / origem.",
                "type": m.get("type") or ("source" if n.startswith("source.") else "model"),
            }
        nodes.append(node)

    edges = []
    node_ids = {n["id"] for n in nodes}
    for n in nodes:
        for ref in graph.get(n["id"], {}).get("refs", []):
            if ref in node_ids:
                edges.append({"from": ref, "to": n["id"]})
        # sources no item
        for src in n.get("sources") or []:
            sid = src if src.startswith("source.") else f"source.{src}" if "." in src else src
            # sources já estão como source.schema.table nos refs do graph
            pass

    layers_order = [
        "source", "seed", "sample", "staging", "intermediate", "mart", "aggregate", "other"
    ]
    return {
        "nodes": nodes,
        "edges": edges,
        "layers": [L for L in layers_order if any(n["layer"] == L for n in nodes)],
    }


def build_macro_view(
    focus: str,
    checklist: list[dict],
    graph: dict,
    models: dict,
    base: dict | None = None,
) -> dict:
    """Visão MACRO: um arquivo no centro + vizinhos do grafo corporativo.

    - Arquivo NOVO: nó verde encaixado via refs/sources no que já existe.
    - Arquivo APPEND: nó cinza com destaque verde nos itens que o card acrescenta.
    Vizinhos só-base ficam cinza (contexto).
    """
    base = base or {}
    by_check = {c["name"]: c for c in checklist}
    item = by_check.get(focus) or {}

    names: set[str] = {focus}
    # vizinhos transitivos no grafo unificado
    if focus in graph:
        names.update(upstream(graph, focus))
        names.update(downstream(graph, focus))
        names.update(graph[focus].get("refs") or [])
        names.update(graph[focus].get("dependents") or [])
    # refs/sources do checklist (garante encaixe mesmo se grafo incompleto)
    for r in item.get("refs") or []:
        names.add(r)
    for schema, table in item.get("sources") or []:
        names.add(f"source.{schema}.{table}")
    match = item.get("match_name")
    if match:
        names.add(match)

    # se ainda vazio além do focus, puxa 1 salto dos refs no models
    mfocus = models.get(focus) or {}
    for r in mfocus.get("refs") or []:
        names.add(r)
    for schema, table in mfocus.get("sources") or []:
        names.add(f"source.{schema}.{table}")

    def layer_of(n: str) -> str:
        if n in by_check:
            return by_check[n].get("layer") or "other"
        if n.startswith("source."):
            return "source"
        if n in models:
            return models[n].get("layer") or detect_layer(models[n].get("path", ""))
        if n in base:
            return base[n].get("layer") or detect_layer(base[n].get("path", ""))
        return detect_layer(n) if "_" in n else "other"

    def visual_of(n: str) -> str:
        c = by_check.get(n)
        if not c:
            return "exist"
        action = c.get("policy_action") or ""
        if action == "create" or c.get("status") == "NOVO":
            return "new"
        if action == "append":
            return "add"  # corporativo + verde no que acresce
        if action in {"skip", "observe"} or c.get("status") == "REMOVIDO":
            return "locked"
        if action == "review":
            return "review"
        return "exist"

    def origin_of(n: str) -> str:
        in_base = n in base or n.startswith("source.")
        in_ws = n in models and n not in base
        if n.startswith("source."):
            return "base"
        if in_base and (by_check.get(n) or {}).get("status") in {"NOVO", "ALTERADO", "RENOMEADO"}:
            return "both"
        if (by_check.get(n) or {}).get("status") == "NOVO" or (
            n not in base and n in models
        ):
            return "workspace"
        if in_base:
            return "base"
        return "workspace" if in_ws else "context"

    nodes = []
    for n in sorted(names, key=lambda x: (layer_order(layer_of(x)), x)):
        c = by_check.get(n)
        m = models.get(n) or base.get(n) or {}
        vis = visual_of(n)
        add_items = list((c or {}).get("add_items") or [])
        add_count = int((c or {}).get("add_count") or 0)
        # para APPEND: itens novos são o destaque verde do macro
        highlight_items = add_items if vis in {"new", "add"} else []
        g = graph.get(n) or {"refs": [], "dependents": []}
        # restringe depends/used_by ao recorte do macro
        depends = [r for r in (g.get("refs") or []) if r in names]
        used = [d for d in (g.get("dependents") or []) if d in names]
        nodes.append({
            "id": n,
            "label": n,
            "focus": n == focus,
            "layer": layer_of(n),
            "table_kind": (c or {}).get("table_kind") or detect_table_kind(n, layer_of(n)),
            "visual": vis,
            "origin": origin_of(n),
            "status": (c or {}).get("status") or ("SOURCE" if n.startswith("source.") else "IGUAL"),
            "policy_action": (c or {}).get("policy_action") or ("exists" if n in base or n.startswith("source.") else "create"),
            "path": (c or {}).get("path") or m.get("path") or "",
            "domain": (c or {}).get("domain") or m.get("domain") or "",
            "in_checklist": c is not None,
            "add_count": add_count,
            "add_items": highlight_items,
            "add_summary": (c or {}).get("add_summary") or "",
            "columns": list((c or {}).get("columns") or m.get("columns") or []),
            "base_columns": list((c or {}).get("base_columns") or (base.get(n) or {}).get("columns") or []),
            "depends_on": depends,
            "used_by": used,
            "upstream": [u for u in upstream(graph, n) if u in names] if n in graph else [],
            "downstream": [d for d in downstream(graph, n) if d in names] if n in graph else [],
            "hint": (
                "Arquivo novo — encaixa aqui no grafo corporativo."
                if vis == "new" and n == focus
                else (
                    "Já existe na base — verde = só o que o card acrescenta."
                    if vis == "add" and n == focus
                    else "Contexto corporativo (já na base)."
                )
            ),
        })

    edges = []
    node_ids = {n["id"] for n in nodes}
    for n in nodes:
        for ref in graph.get(n["id"], {}).get("refs", []):
            if ref in node_ids:
                # aresta "nova" se o destino é create ou a ref é item novo do append
                dest = by_check.get(n["id"]) or {}
                is_new_edge = (
                    dest.get("policy_action") == "create"
                    or dest.get("status") == "NOVO"
                    or any(
                        a.get("kind") == "referência" and a.get("name") == ref
                        for a in (dest.get("add_items") or [])
                    )
                )
                edges.append({
                    "from": ref,
                    "to": n["id"],
                    "kind": "new" if is_new_edge else "exist",
                })

    layers_order = [
        "source", "seed", "sample", "staging", "intermediate", "mart", "aggregate", "other"
    ]
    focus_item = by_check.get(focus) or {}
    mode = (
        "create"
        if focus_item.get("policy_action") == "create" or focus_item.get("status") == "NOVO"
        else (
            "append"
            if focus_item.get("policy_action") == "append"
            else "context"
        )
    )
    recompile = [
        d for d in (downstream(graph, focus) if focus in graph else [])
        if not str(d).startswith("source.")
    ][:12]
    snip = focus_item.get("snippet")
    if not snip and focus_item.get("policy_action") in {"create", "append"}:
        snip = build_snippet(focus_item)
    return {
        "focus": focus,
        "mode": mode,
        "title": focus,
        "subtitle": (
            "Arquivo novo no grafo corporativo (verde = criar)."
            if mode == "create"
            else (
                "Arquivo já na base — destaque verde = o que acrescer."
                if mode == "append"
                else "Contexto do arquivo no grafo."
            )
        ),
        "recompile": recompile,
        "snippet": snip,
        "nodes": nodes,
        "edges": edges,
        "layers": [L for L in layers_order if any(n["layer"] == L for n in nodes)],
        "add_items": list(focus_item.get("add_items") or []),
        "add_count": int(focus_item.get("add_count") or 0),
    }


def build_macros(
    checklist: list[dict],
    graph: dict,
    models: dict,
    base: dict | None = None,
) -> dict:
    """Uma visão macro por arquivo criar/acrescentar (focos do card)."""
    focuses = []
    for c in checklist:
        if c.get("policy_action") in {"create", "append"} or c.get("status") == "NOVO":
            focuses.append({
                "id": c["name"],
                "label": c["name"],
                "mode": "create" if (c.get("policy_action") == "create" or c["status"] == "NOVO") else "append",
                "layer": c.get("layer") or "",
                "domain": c.get("domain") or "",
                "add_count": int(c.get("add_count") or 0),
                "order": int(c.get("suggested_order") or 999),
            })
    # dedupe + sort
    seen = set()
    uniq = []
    for f in sorted(focuses, key=lambda x: (x["order"], x["id"])):
        if f["id"] not in seen:
            seen.add(f["id"])
            uniq.append(f)
    by_focus = {
        f["id"]: build_macro_view(f["id"], checklist, graph, models, base)
        for f in uniq
    }
    return {
        "focuses": uniq,
        "by_focus": by_focus,
        "default": uniq[0]["id"] if uniq else "",
    }


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
        item["upstream"] = upstream(graph, item["name"])
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

    include = config.get("base_include") or []
    if not isinstance(include, list):
        include = []

    top_folders = list_top_folders(base_path) if base_path and os.path.isdir(base_path) else []
    base = (
        load_project(base_path, include=include)
        if base_path and os.path.isdir(base_path)
        else {}
    )
    # workspace: se tiver as mesmas pastas de negócio, filtra; senão lê tudo
    ws_include = None
    if include and ws_path and os.path.isdir(ws_path):
        ws_tops = set(list_top_folders(ws_path))
        if any(n in ws_tops for n in include):
            ws_include = [n for n in include if n in ws_tops]
    ws = load_project(ws_path, include=ws_include) if ws_path and os.path.isdir(ws_path) else {}

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
    # anexa domínio (pasta de negócio) quando existir
    for item in checklist:
        src = ws.get(item["name"]) or base.get(item["name"]) or {}
        item["domain"] = src.get("domain") or detect_domain(item.get("path", ""))
    graph = build_graph(merged)
    checklist = enrich_checklist(checklist, graph)
    checklist = enrich_additive(checklist, base, ws)
    patterns = learn_patterns(base)
    declared_sources = collect_declared_sources(merged)
    add_only = bool(config.get("add_only", True))
    enforce_taxonomy = bool(config.get("enforce_taxonomy", True))
    if add_only:
        apply_add_only_labels(checklist)
    warnings = validate(
        checklist,
        graph,
        merged,
        patterns,
        add_only=add_only,
        enforce_taxonomy=enforce_taxonomy,
        declared_sources=declared_sources,
    )
    order = topo_order(checklist, graph)
    order_meta = topo_order_meta(checklist, graph, order=order)
    dag_cycles = order_meta.get("cycles") or analyze_dag_cycles(graph)

    # aplicar ordem sugerida no checklist
    order_idx = {n: i for i, n in enumerate(order)}
    for item in checklist:
        item["suggested_order"] = order_idx.get(item["name"], 999)

    checklist.sort(key=lambda c: (0 if c["status"] != "IGUAL" else 1, c["layer_order"], c.get("suggested_order", 999), c["name"]))

    lineage = build_lineage(checklist, graph, merged)
    macros = build_macros(checklist, graph, merged, base)
    order_markdown = build_order_markdown(checklist, order, card_id)

    summary = {
        "novo": sum(1 for c in checklist if c.get("policy_action") == "create" or c["status"] == "NOVO"),
        "acrescentar": sum(1 for c in checklist if c.get("policy_action") == "append"),
        "alterado": sum(1 for c in checklist if c["status"] == "ALTERADO"),
        "removido": sum(1 for c in checklist if c["status"] == "REMOVIDO"),
        "renomeado": sum(1 for c in checklist if c["status"] == "RENOMEADO"),
        "igual": sum(1 for c in checklist if c["status"] == "IGUAL"),
        "nao_alterar": sum(1 for c in checklist if c.get("policy_action") == "skip"),
        "revisar": sum(1 for c in checklist if c.get("policy_action") == "review"),
        "pending": (
            sum(1 for c in checklist if c.get("policy_action") in {"create", "append"})
            if add_only
            else sum(
                1
                for c in checklist
                if c["status"] in {"NOVO", "ALTERADO", "REMOVIDO", "RENOMEADO"}
            )
        ),
        "critical": sum(
            1
            for w in warnings
            if w["severity"] == "critical" and not w.get("policy")
        ),
        "policy_blocks": sum(1 for w in warnings if w.get("policy") and w["severity"] == "critical"),
        "policy_append": sum(
            1 for w in warnings if w.get("policy") and w.get("label") == "Acrescentar"
        ),
        "warning": sum(1 for w in warnings if w["severity"] == "warning"),
        "base_models": len(base),
        "workspace_models": len(ws),
        "cycle_count": len(dag_cycles),
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
            f"Você tem {summary['critical']} bloqueio(s) nos arquivos NOVOS. "
            "Resolva-os antes de criar — veja a aba Alertas."
        )
    elif add_only and summary.get("acrescentar", 0) > 0:
        message = (
            f"Crie {summary['novo']} arquivo(s) novos e ACRESCENTE itens em "
            f"{summary['acrescentar']} arquivo(s) que já existem "
            f"(só o que veio de novo no card — não reescreva o principal)."
        )
    elif add_only and summary.get("policy_blocks", 0) > 0 and summary["novo"] > 0:
        message = (
            f"Crie os {summary['novo']} arquivo(s) VERDE(S). "
            f"Há {summary['policy_blocks']} item(ns) para não alterar/revisar."
        )
    elif add_only and summary.get("policy_blocks", 0) > 0 and summary["novo"] == 0:
        message = (
            "Nada novo para criar. Revise avisos de política — "
            "não reescreva a base sem necessidade."
        )

    session = {
        "card_id": card_id,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "message": message,
        "checklist": checklist,
        "warnings": warnings,
        "order": order,
        "order_meta": order_meta,
        "order_markdown": order_markdown,
        "dag_cycles": dag_cycles,
        "flow_chains": build_flow_chains(checklist, graph),
        "lineage": lineage,
        "macro": macros,
        "timeline": load_timeline(snapshots_path),
        "patterns": patterns,
        "empty_workspace": empty_ws,
        "missing_base": missing_base,
        "base_path": base_path,
        "base_include": include,
        "base_top_folders": top_folders,
        "domains_scanned": include if include else top_folders,
        "add_only": add_only,
        "enforce_taxonomy": enforce_taxonomy,
        "declared_sources": sorted(declared_sources),
    }
    return session
