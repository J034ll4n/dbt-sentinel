# -*- coding: utf-8 -*-
"""Gera demo_base + workspace com ~80 modelos e abre o Fluxo para teste de escala.

Uso:
  py -3 make_scale_demo.py
"""
from __future__ import annotations

import json
import os
import shutil
import webbrowser

import engine
import ui

ROOT = os.path.dirname(os.path.abspath(__file__))
DEMO_BASE = os.path.join(ROOT, "demo_base")
WORKSPACE = os.path.join(ROOT, "workspace")
OUTPUT = os.path.join(ROOT, "output")
CONFIG_PATH = os.path.join(ROOT, "config.json")
CONFIG_BAK = os.path.join(ROOT, "config.json.scalebak")


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _sql_stg(name: str, source_table: str, cols: list[str], extra: list[str] | None = None) -> str:
    all_cols = cols + (extra or [])
    body = ",\n  ".join(all_cols)
    return (
        f"-- scale demo: {name}\n"
        f"select\n  {body}\n"
        f"from {{{{ source('raw', '{source_table}') }}}}\n"
    )


def _sql_ref(name: str, refs: list[str], cols: list[str], extra: list[str] | None = None) -> str:
    all_cols = cols + (extra or [])
    body = ",\n  ".join(f"t.{c} as {c}" for c in all_cols)
    from_sql = f"{{{{ ref('{refs[0]}') }}}} t"
    joins = ""
    for i, r in enumerate(refs[1:], 1):
        alias = f"j{i}"
        joins += f"\nleft join {{{{ ref('{r}') }}}} {alias} on t.id_key = {alias}.id_key"
    return (
        f"-- scale demo: {name}\n"
        f"select\n  {body}\n"
        f"from {from_sql}{joins}\n"
    )


def build_fixtures() -> dict:
    """Cria ~80 arquivos SQL em camadas com fan-out realista."""
    if os.path.isdir(DEMO_BASE):
        shutil.rmtree(DEMO_BASE)
    if os.path.isdir(WORKSPACE):
        shutil.rmtree(WORKSPACE)

    domains = ["vendas", "frota", "financeiro", "rh"]
    base_cols = ["id_key", "nm_nome", "cd_codigo", "ts_evento"]

    sources_yml = [
        "version: 2",
        "",
        "sources:",
        "  - name: raw",
        "    tables:",
    ]
    stg_names: list[str] = []
    int_names: list[str] = []
    mart_names: list[str] = []
    agg_names: list[str] = []

    # 4 domains × 5 stg = 20 staging (+ sources)
    for d in domains:
        for i in range(1, 6):
            src_table = f"{d}_src_{i}"
            stg = f"stg_{d}_{i}"
            stg_names.append(stg)
            sources_yml.append(f"      - name: {src_table}")
            _write(
                os.path.join(DEMO_BASE, "ebody", "staging", f"{stg}.sql"),
                _sql_stg(stg, src_table, base_cols),
            )
            # workspace: append qt_extra em metade
            extra = ["qt_extra"] if i % 2 == 1 else None
            _write(
                os.path.join(WORKSPACE, "ebody", "staging", f"{stg}.sql"),
                _sql_stg(stg, src_table, base_cols, extra),
            )

    _write(
        os.path.join(DEMO_BASE, "ebody", "schemas", "sources.yml"),
        "\n".join(sources_yml) + "\n",
    )
    _write(
        os.path.join(WORKSPACE, "ebody", "schemas", "sources.yml"),
        "\n".join(sources_yml) + "\n",
    )

    # 24 intermediate: chains + fan-in
    for d in domains:
        domain_stgs = [n for n in stg_names if n.startswith(f"stg_{d}_")]
        for i in range(1, 7):
            name = f"int_{d}_{i}"
            int_names.append(name)
            refs = [domain_stgs[(i - 1) % len(domain_stgs)]]
            if i > 2:
                refs.append(domain_stgs[i % len(domain_stgs)])
            _write(
                os.path.join(DEMO_BASE, "ebody", "intermediate", f"{name}.sql"),
                _sql_ref(name, refs, base_cols),
            )
            extra = ["qt_extra"] if i <= 3 else None
            _write(
                os.path.join(WORKSPACE, "ebody", "intermediate", f"{name}.sql"),
                _sql_ref(name, refs, base_cols, extra),
            )

    # 8 NEW intermediate only in workspace (create)
    for i in range(1, 9):
        name = f"int_novo_card_{i}"
        int_names.append(name)
        ref = stg_names[(i * 3) % len(stg_names)]
        _write(
            os.path.join(WORKSPACE, "ebody", "intermediate", f"{name}.sql"),
            _sql_ref(name, [ref], base_cols + ["qt_extra"]),
        )

    # 16 marts
    for d in domains:
        domain_ints = [n for n in int_names if n.startswith(f"int_{d}_")]
        for i in range(1, 5):
            name = f"fato_{d}_{i}"
            mart_names.append(name)
            refs = [domain_ints[(i - 1) % len(domain_ints)]]
            if i == 4 and domain_ints:
                refs.append(domain_ints[-1])
            _write(
                os.path.join(DEMO_BASE, "ebody", "marts", f"{name}.sql"),
                _sql_ref(name, refs, base_cols),
            )
            _write(
                os.path.join(WORKSPACE, "ebody", "marts", f"{name}.sql"),
                _sql_ref(name, refs, base_cols, ["qt_extra"] if i <= 2 else None),
            )

    # 4 NEW marts in workspace
    for i in range(1, 5):
        name = f"fato_novo_card_{i}"
        mart_names.append(name)
        ref = int_names[(i * 2) % len(int_names)]
        _write(
            os.path.join(WORKSPACE, "ebody", "marts", f"{name}.sql"),
            _sql_ref(name, [ref], base_cols + ["qt_extra"]),
        )

    # 8 aggregates
    for i in range(1, 9):
        name = f"agg_resumo_{i}"
        agg_names.append(name)
        ref = mart_names[(i - 1) % len(mart_names)]
        cols = ["id_key", "qt_extra"] if i <= 4 else ["id_key", "nm_nome"]
        path_b = os.path.join(DEMO_BASE, "ebody", "aggregate", f"{name}.sql")
        path_w = os.path.join(WORKSPACE, "ebody", "aggregate", f"{name}.sql")
        if i <= 6:
            _write(path_b, _sql_ref(name, [ref], ["id_key", "nm_nome"]))
            _write(path_w, _sql_ref(name, [ref], cols if i <= 4 else ["id_key", "nm_nome"]))
        else:
            # only workspace = create
            _write(path_w, _sql_ref(name, [ref], ["id_key", "qt_extra"]))

    total_sql = 0
    for root, _, files in os.walk(DEMO_BASE):
        total_sql += sum(1 for f in files if f.endswith(".sql"))
    for root, _, files in os.walk(WORKSPACE):
        total_sql += sum(1 for f in files if f.endswith(".sql"))

    return {
        "stg": len(stg_names),
        "int": len([n for n in int_names]),
        "mart": len(mart_names),
        "agg": len(agg_names),
        "sql_files_written": total_sql,
    }


def main() -> None:
    print("Gerando fixtures ~80 nós…")
    stats = build_fixtures()
    print(f"  staging={stats['stg']} int~={stats['int']} mart={stats['mart']} agg={stats['agg']}")

    cfg = {
        "base_project_path": DEMO_BASE,
        "base_include": ["ebody"],
        "workspace_path": WORKSPACE,
        "output_path": OUTPUT,
        "snapshots_path": os.path.join(ROOT, "snapshots"),
        "card_id": "DEMO-SCALE-80",
        "detect_removed": False,
        "match_threshold": 0.62,
        "aliases": {},
        "allow_empty_base": False,
        "require_git_integrity": False,
        "add_only": True,
        "enforce_taxonomy": False,
    }

    # backup config + apontar para o demo
    if os.path.isfile(CONFIG_PATH):
        shutil.copy2(CONFIG_PATH, CONFIG_BAK)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("Rodando análise…")
    session = engine.run(cfg)
    lin = session.get("lineage") or {}
    n = len(lin.get("nodes") or [])
    e = len(lin.get("edges") or [])
    print(f"  lineage: {n} nós · {e} arestas")
    print(f"  criar={session['summary'].get('novo')} acrescer={session['summary'].get('acrescentar')}")

    os.makedirs(OUTPUT, exist_ok=True)
    html_path = os.path.join(OUTPUT, "index.html")
    session_path = os.path.join(OUTPUT, "session.json")
    with open(session_path, "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(ui.render(session))

    print(f"  HTML: {html_path}")
    print("Abra a aba Fluxo — setas sob foco; marque 'Todas as setas' se quiser a mesh.")
    print(f"(config.json aponta para demo; backup em {os.path.basename(CONFIG_BAK)})")
    try:
        webbrowser.open(html_path)
    except Exception:
        pass


if __name__ == "__main__":
    main()
