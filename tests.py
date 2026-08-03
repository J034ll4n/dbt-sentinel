# -*- coding: utf-8 -*-
"""Testes do DBT Guardian — stdlib only. Rode: py -3 tests.py"""
from __future__ import annotations

import json
import os
import shutil
import tempfile

import engine
import ui

passed = 0
failed = 0


def ok(name: str) -> None:
    global passed
    passed += 1
    print("OK  ", name)


def fail(name: str, msg: str) -> None:
    global failed
    failed += 1
    print("FAIL", name, "-", msg)


def assert_true(cond, name, detail="") -> None:
    if cond:
        ok(name)
    else:
        fail(name, detail or "assertion failed")


def test_parse_sql() -> None:
    sql = """
{{ config(materialized='table') }}
-- comment
select a.id, SAFE_CAST(a.x as int) as x
from {{ ref('stg_a') }} a
left join {{ source('crm','cliente') }} s on a.id = s.id
"""
    p = engine.parse_sql(sql)
    assert_true("stg_a" in p["refs"], "parse_sql.refs")
    srcs = [tuple(x) for x in p["sources"]]
    assert_true(("crm", "cliente") in srcs, "parse_sql.sources", str(p["sources"]))
    assert_true(any("LEFT" in j for j in p["joins"]), "parse_sql.joins", str(p["joins"]))
    assert_true("SAFE_CAST" in p["casts"], "parse_sql.casts", str(p["casts"]))


def test_hash() -> None:
    a = {"refs": ["x"], "sources": [], "joins": ["LEFT JOIN"], "casts": ["SAFE_CAST"], "columns": ["id"]}
    b = {"refs": ["x"], "sources": [], "joins": ["LEFT JOIN"], "casts": ["SAFE_CAST"], "columns": ["id"]}
    assert_true(engine.structural_hash(a) == engine.structural_hash(b), "structural_hash_stable")
    c = {"refs": ["y"], "sources": [], "joins": [], "casts": [], "columns": []}
    assert_true(engine.structural_hash(a) != engine.structural_hash(c), "structural_hash_diff")


def test_cycles_downstream() -> None:
    g = {
        "a": {"refs": ["b"], "dependents": []},
        "b": {"refs": ["c"], "dependents": []},
        "c": {"refs": ["a"], "dependents": []},
    }
    cyc = engine.find_cycles(g)
    assert_true(len(cyc) >= 1, "find_cycles", str(cyc))

    models = {
        "stg": {"refs": [], "sources": [], "name": "stg"},
        "int": {"refs": ["stg"], "sources": [], "name": "int"},
        "fct": {"refs": ["int"], "sources": [], "name": "fct"},
    }
    g2 = engine.build_graph(models)
    deps = engine.downstream(g2, "stg")
    assert_true("int" in deps and "fct" in deps, "downstream", str(deps))


def test_integration() -> None:
    root = tempfile.mkdtemp(prefix="dbt_g_")
    try:
        base = os.path.join(root, "base")
        ws = os.path.join(root, "ws")
        out = os.path.join(root, "out")
        snap = os.path.join(root, "snap")
        for d in [
            os.path.join(base, "models", "staging"),
            os.path.join(base, "models", "intermediate"),
            os.path.join(ws, "models", "staging"),
            os.path.join(ws, "models", "intermediate"),
            os.path.join(ws, "models", "sample"),
            out,
            snap,
        ]:
            os.makedirs(d, exist_ok=True)

        with open(os.path.join(base, "models", "staging", "stg_cliente.sql"), "w", encoding="utf-8") as f:
            f.write("select id from {{ source('crm', 'cliente') }}\n")
        with open(os.path.join(base, "models", "intermediate", "int_cliente.sql"), "w", encoding="utf-8") as f:
            f.write("select id from {{ ref('stg_cliente') }}\n")

        with open(os.path.join(ws, "models", "sample", "sample_cliente.sql"), "w", encoding="utf-8") as f:
            f.write("select id from {{ source('crm', 'cliente') }} where true\n")
        with open(os.path.join(ws, "models", "staging", "stg_cliente.sql"), "w", encoding="utf-8") as f:
            f.write("select id, nome from {{ ref('sample_cliente') }}\n")
        with open(os.path.join(ws, "models", "intermediate", "int_cliente.sql"), "w", encoding="utf-8") as f:
            f.write(
                "select id, SAFE_CAST(x as int) as x from {{ ref('stg_cliente') }} "
                "left join {{ ref('stg_empresa') }} e on 1=1\n"
            )
        with open(os.path.join(ws, "models", "intermediate", "int_novo.sql"), "w", encoding="utf-8") as f:
            f.write("select id from {{ ref('int_cliente') }}\n")

        cfg = {
            "base_project_path": base,
            "workspace_path": ws,
            "output_path": out,
            "snapshots_path": snap,
            "card_id": "CARD-TEST",
            "detect_removed": False,
        }
        s = engine.run(cfg)
        assert_true(s["summary"]["novo"] >= 2, "run.novo", str(s["summary"]))
        assert_true(s["summary"]["alterado"] >= 2, "run.alterado", str(s["summary"]))
        # com add_only, refs quebradas em ALTERADO não são critical técnico
        assert_true(s["summary"]["critical"] == 0 or s["summary"]["pending"] >= 1, "run.critical_or_pending", str(s["summary"]))
        assert_true(s["summary"]["removido"] == 0, "run.no_false_removed", str(s["summary"]))
        assert_true("sample_cliente" in s["order"], "run.order", str(s["order"]))

        names = {c["name"]: c["status"] for c in s["checklist"]}
        assert_true(names.get("sample_cliente") == "NOVO", "status.sample")
        assert_true(names.get("stg_cliente") == "ALTERADO", "status.stg")
        assert_true(names.get("int_cliente") == "ALTERADO", "status.int")
        assert_true(names.get("int_novo") == "NOVO", "status.int_novo")
        # política: ALTERADO com itens novos → acrescentar
        assert_true(
            s["summary"].get("acrescentar", 0) >= 1 or s["summary"].get("policy_blocks", 0) >= 1,
            "policy_or_append",
            str(s["summary"]),
        )
        assert_true(s.get("add_only") is True, "add_only.flag")
        by_label = {c["name"]: c.get("label", "") for c in s["checklist"]}
        assert_true("Não alterar" in by_label.get("stg_cliente", "") or "Acrescentar" in by_label.get("stg_cliente", ""),
                    "label.add_only", by_label.get("stg_cliente"))

        html = ui.render(s)
        assert_true("DBT Guardian" in html, "ui.title")
        assert_true("Assistente" in html and "Arquivos" in html, "ui.tabs")
        assert_true("Ordem" in html, "ui.ordem_tab")
        assert_true("sample_cliente" in html, "ui.has_model")
        assert_true("Regra de ouro" in html, "ui.gold")
        assert_true("stg_empresa" in html, "ui.has_blocker")
        assert_true("Lineage" in html or "lineage" in html, "ui.lineage_tab")
        assert_true(isinstance(s.get("lineage"), dict) and "nodes" in s["lineage"], "lineage.nodes")
        novo_items = next(c for c in s["checklist"] if c["name"] == "int_novo")
        assert_true("add_count" in novo_items, "add_count.field")
        assert_true(novo_items.get("add_summary"), "add_summary")
        # ALTERADO com colunas novas → append
        stg = next(c for c in s["checklist"] if c["name"] == "stg_cliente")
        assert_true(stg.get("policy_action") in {"append", "skip"}, "stg.policy", stg.get("policy_action"))

        with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
            f.write(html)
        with open(os.path.join(out, "session.json"), "w", encoding="utf-8") as f:
            json.dump(s, f)

        # detect_removed
        ws2 = os.path.join(root, "ws2")
        os.makedirs(os.path.join(ws2, "models", "staging"), exist_ok=True)
        with open(os.path.join(ws2, "models", "staging", "stg_cliente.sql"), "w", encoding="utf-8") as f:
            f.write("select id from {{ source('crm', 'cliente') }}\n")
        cfg2 = dict(cfg)
        cfg2["workspace_path"] = ws2
        cfg2["detect_removed"] = True
        s2 = engine.run(cfg2)
        assert_true(s2["summary"]["removido"] >= 1, "detect_removed_true", str(s2["summary"]))

        cfg3 = dict(cfg2)
        cfg3["detect_removed"] = False
        s3 = engine.run(cfg3)
        assert_true(s3["summary"]["removido"] == 0, "detect_removed_false", str(s3["summary"]))

        # empty workspace
        empty = os.path.join(root, "empty")
        os.makedirs(empty, exist_ok=True)
        cfg4 = dict(cfg)
        cfg4["workspace_path"] = empty
        s4 = engine.run(cfg4)
        assert_true(s4["empty_workspace"] is True, "empty_workspace.flag")
        assert_true("workspace" in s4["message"].lower(), "empty_workspace.msg", s4["message"])

    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_name_matching() -> None:
    assert_true(engine.name_similarity("stg_clientes", "stg_cliente") >= 0.85, "normalize_plural")
    assert_true(engine.name_similarity("stg_client", "stg_cliente") >= 0.75, "name_sim_client")
    assert_true(engine.name_similarity("fct_vendas", "stg_cliente") < 0.5, "name_sim_unrelated")
    # não misturar sample com stg só pelo núcleo "cliente"
    assert_true(engine.name_similarity("sample_cliente", "stg_cliente") < 0.85, "no_cross_prefix")

    a = {"name": "stg_client", "layer": "staging", "refs": [], "sources": [["crm", "cliente"]],
         "columns": ["id", "nome"], "hash": "aaa"}
    b = {"name": "stg_cliente", "layer": "staging", "refs": [], "sources": [["crm", "cliente"]],
         "columns": ["id", "nome"], "hash": "aaa"}
    score, reasons = engine.match_score(a, b)
    assert_true(score >= 0.7, "match_score_high", f"{score} {reasons}")


def test_rename_detection() -> None:
    root = tempfile.mkdtemp(prefix="dbt_ren_")
    try:
        base = os.path.join(root, "base")
        ws = os.path.join(root, "ws")
        for d in [
            os.path.join(base, "models", "staging"),
            os.path.join(ws, "models", "staging"),
        ]:
            os.makedirs(d, exist_ok=True)
        with open(os.path.join(base, "models", "staging", "stg_cliente.sql"), "w", encoding="utf-8") as f:
            f.write("select id, nome from {{ source('crm', 'cliente') }}\n")
        # ZIP usa nome em inglês — mesma estrutura
        with open(os.path.join(ws, "models", "staging", "stg_client.sql"), "w", encoding="utf-8") as f:
            f.write("select id, nome, email from {{ source('crm', 'cliente') }}\n")

        cfg = {
            "base_project_path": base,
            "workspace_path": ws,
            "output_path": os.path.join(root, "out"),
            "snapshots_path": os.path.join(root, "snap"),
            "card_id": "CARD-REN",
            "detect_removed": False,
            "aliases": {},
            "match_threshold": 0.55,
        }
        os.makedirs(cfg["output_path"], exist_ok=True)
        os.makedirs(cfg["snapshots_path"], exist_ok=True)
        s = engine.run(cfg)
        names = {c["name"]: c for c in s["checklist"]}
        assert_true("stg_client" in names, "rename.has_ws_name")
        item = names["stg_client"]
        assert_true(item["status"] == "RENOMEADO", "rename.status", item["status"])
        assert_true(item.get("match_name") == "stg_cliente", "rename.match", str(item.get("match_name")))
        assert_true(s["summary"]["renomeado"] >= 1, "rename.summary")

        # alias forçado
        cfg["aliases"] = {"stg_client": "stg_cliente"}
        s2 = engine.run(cfg)
        item2 = {c["name"]: c for c in s2["checklist"]}["stg_client"]
        assert_true(item2["status"] in {"ALTERADO", "IGUAL", "RENOMEADO"}, "alias.status", item2["status"])
        assert_true(item2.get("match_name") == "stg_cliente" or "Alias" in str(item2.get("diff")),
                    "alias.linked", str(item2))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_hardening() -> None:
    assert_true(engine.sanitize_card_id("../../etc") == "CARD-XXX" or ".." not in engine.sanitize_card_id("../../etc"),
                "sanitize_dotdot")
    assert_true("/" not in engine.sanitize_card_id("CARD/100") and "\\" not in engine.sanitize_card_id("CARD\\100"),
                "sanitize_slash")
    assert_true(engine.sanitize_card_id("CARD-100") == "CARD-100", "sanitize_ok")

    root = tempfile.mkdtemp(prefix="dbt_safe_")
    try:
        inside = os.path.join(root, "a.sql")
        open(inside, "w", encoding="utf-8").write("select 1")
        assert_true(engine.safe_relpath(inside, root) is not None, "safe_inside")
        outside = os.path.join(root, "..", "outside.sql")
        assert_true(engine.safe_relpath(outside, root) is None, "safe_outside")

        cfg_bad = {
            "workspace_path": root,
            "output_path": os.path.join(root, "out"),
            "snapshots_path": os.path.join(root, "snap"),
            "base_project_path": root,
            "aliases": "nope",
        }
        errs = engine.validate_config(cfg_bad)
        assert_true(any("aliases" in e for e in errs), "validate_aliases", str(errs))

        base = os.path.join(root, "dbt")
        os.makedirs(base)
        cfg_nest = {
            "workspace_path": os.path.join(root, "ws"),
            "output_path": os.path.join(base, "out"),
            "snapshots_path": os.path.join(root, "snap"),
            "base_project_path": base,
            "aliases": {},
            "match_threshold": 0.62,
        }
        errs2 = engine.validate_config(cfg_nest)
        assert_true(any("output_path" in e for e in errs2), "validate_nest", str(errs2))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    evil = {
        "card_id": "CARD-X",
        "timestamp": "t",
        "summary": {"novo": 0, "alterado": 0, "removido": 0, "renomeado": 0, "igual": 0,
                    "pending": 0, "critical": 0, "policy_blocks": 0, "warning": 0,
                    "base_models": 0, "workspace_models": 0},
        "message": "</script><script>alert(1)</script>",
        "checklist": [],
        "warnings": [],
        "order": [],
        "flow_chains": [],
        "timeline": [],
        "patterns": {},
        "empty_workspace": True,
        "add_only": True,
        "lineage": {"nodes": [], "edges": [], "layers": []},
    }
    html = ui.render(evil)
    assert_true("</script><script>" not in html, "xss_script_break")
    assert_true("\\u003c" in html or "&lt;" in html, "xss_escaped")


def test_content_hash_not_false_igual() -> None:
    """Mesmos refs/colunas mas WHERE diferente → ALTERADO, não IGUAL."""
    a = engine.parse_sql("select id from {{ ref('stg') }} where a = 1")
    b = engine.parse_sql("select id from {{ ref('stg') }} where a = 2")
    assert_true(a["refs"] == b["refs"], "same_refs")
    assert_true(a["content_hash"] != b["content_hash"], "diff_content_hash")
    ma = {"hash": engine.structural_hash({**a, "name": "x"}), "content_hash": a["content_hash"],
          "refs": a["refs"], "sources": a["sources"], "joins": a["joins"], "casts": a["casts"], "columns": a["columns"]}
    mb = {"hash": engine.structural_hash({**b, "name": "x"}), "content_hash": b["content_hash"],
          "refs": b["refs"], "sources": b["sources"], "joins": b["joins"], "casts": b["casts"], "columns": b["columns"]}
    # structural may be equal
    assert_true(not engine.models_equal(ma, mb), "not_equal_body")


def test_yaml_models_not_sources() -> None:
    yml = """
version: 2
models:
  - name: stg_cliente
    columns:
      - name: id
      - name: nome
sources:
  - name: crm
    tables:
      - name: cliente
"""
    p = engine.parse_yaml(yml)
    assert_true(["crm", "cliente"] in [list(x) for x in p["sources"]], "yaml_source_ok", str(p["sources"]))
    assert_true(["stg_cliente", "id"] not in [list(x) for x in p["sources"]], "yaml_no_col_as_source", str(p["sources"]))
    assert_true("stg_cliente" in p.get("yaml_models", []) or "stg_cliente" in p.get("columns", []),
                "yaml_model_listed", str(p))


def test_exclusive_rename_no_double_claim() -> None:
    root = tempfile.mkdtemp(prefix="dbt_ex_")
    try:
        base = os.path.join(root, "base")
        ws = os.path.join(root, "ws")
        os.makedirs(os.path.join(base, "models", "staging"))
        os.makedirs(os.path.join(ws, "models", "staging"))
        open(os.path.join(base, "models", "staging", "stg_cliente.sql"), "w", encoding="utf-8").write(
            "select id, nome from {{ source('crm', 'cliente') }}\n"
        )
        open(os.path.join(ws, "models", "staging", "stg_cliente.sql"), "w", encoding="utf-8").write(
            "select id, nome from {{ source('crm', 'cliente') }}\n"
        )
        open(os.path.join(ws, "models", "staging", "stg_client.sql"), "w", encoding="utf-8").write(
            "select id, nome from {{ source('crm', 'cliente') }}\n"
        )
        cfg = {
            "base_project_path": base,
            "workspace_path": ws,
            "output_path": os.path.join(root, "o"),
            "snapshots_path": os.path.join(root, "s"),
            "card_id": "T",
            "detect_removed": False,
            "match_threshold": 0.55,
            "aliases": {},
        }
        os.makedirs(cfg["output_path"])
        os.makedirs(cfg["snapshots_path"])
        s = engine.run(cfg)
        by = {c["name"]: c for c in s["checklist"]}
        assert_true(by["stg_cliente"]["status"] in {"IGUAL", "ALTERADO"}, "exact_wins", by["stg_cliente"]["status"])
        assert_true(by["stg_client"]["status"] == "NOVO", "no_double_rename", by["stg_client"]["status"])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_base_include_filters_domains() -> None:
    root = tempfile.mkdtemp(prefix="dbt_dom_")
    try:
        base = os.path.join(root, "base")
        for dom, model in (("ebody", "stg_ebody"), ("AIS", "stg_ais"), ("Rodos", "stg_rodos"), ("schemas", "stg_skip")):
            d = os.path.join(base, dom, "models", "staging")
            os.makedirs(d)
            open(os.path.join(d, model + ".sql"), "w", encoding="utf-8").write(
                "select 1 as id\n"
            )
        tops = engine.list_top_folders(base)
        assert_true("ebody" in tops and "schemas" in tops, "list_tops", str(tops))

        models = engine.load_project(base, include=["ebody", "AIS", "Rodos"])
        names = set(models)
        assert_true("stg_ebody" in names and "stg_ais" in names and "stg_rodos" in names, "include_ok", str(names))
        assert_true("stg_skip" not in names, "schemas_skipped", str(names))
        assert_true(models["stg_ebody"].get("domain") == "ebody", "domain_field", str(models["stg_ebody"]))

        cfg_err = {
            "workspace_path": root,
            "output_path": os.path.join(root, "o"),
            "snapshots_path": os.path.join(root, "s"),
            "base_project_path": base,
            "base_include": ["nao_existe"],
            "aliases": {},
            "match_threshold": 0.62,
        }
        errs = engine.validate_config(cfg_err)
        assert_true(any("nao_existe" in e for e in errs), "include_missing", str(errs))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_taxonomy_rules() -> None:
    assert_true(engine.detect_table_kind("f_venda_dia", "mart") == "F", "kind.f")
    assert_true(engine.detect_table_kind("dib_cliente", "mart") == "DIB", "kind.dib")
    assert_true(engine.detect_table_kind("aggr_venda_mes", "aggregate") == "AGGR", "kind.aggr")
    assert_true(engine.column_prefix("id_cliente") == "id", "col.id")
    assert_true(engine.column_prefix("nm_cliente") == "nm", "col.nm")
    assert_true(engine.COLUMN_TAXONOMY["id"] == "integer", "tax.id")
    assert_true(engine.COLUMN_TAXONOMY["nm"] == "string", "tax.nm")
    long = "a" * 36
    issues = engine.check_model_name_taxonomy(long)
    assert_true(any("35" in i for i in issues), "name.len", str(issues))
    issues2 = engine.check_model_name_taxonomy("Bad-Name")
    assert_true(len(issues2) >= 1, "name.case", str(issues2))

    item = {
        "name": "aggr_venda_mes",
        "status": "NOVO",
        "type": "model",
        "layer": "aggregate",
        "refs": ["stg_cliente"],
        "columns": ["xx_invalido", "id_cliente"],
    }
    ws = engine.validate_taxonomy(item, {"stg_cliente": {"layer": "staging"}})
    labels = " ".join(w["message"] for w in ws)
    assert_true("fato" in labels.lower() or "dimensão" in labels.lower() or "dimens" in labels.lower(),
                "aggr.origin", labels)
    assert_true(any("xx" in w["message"] for w in ws), "bad.prefix", str(ws))


def test_additive_items_and_lineage() -> None:
    base_m = {"columns": ["id_cliente", "nm_nome"], "refs": ["stg_a"], "sources": [], "joins": [], "casts": [],
              "content_hash": "aaa", "hash": "h1"}
    ws_m = {"columns": ["id_cliente", "nm_nome", "dt_ref"], "refs": ["stg_a", "stg_b"], "sources": [],
            "joins": [], "casts": [], "content_hash": "bbb", "hash": "h2"}
    adds = engine.compute_add_items(ws_m, base_m)
    names = {a["name"] for a in adds}
    assert_true("dt_ref" in names, "add.col", str(names))
    assert_true("stg_b" in names, "add.ref", str(names))
    assert_true("id_cliente" not in names, "no_existing_col", str(names))
    ign = engine.ignored_changes(ws_m, base_m)
    assert_true(any("SQL" in x or "corpo" in x for x in ign), "ignore.body", str(ign))

    all_new = engine.compute_add_items({"columns": ["aa_x", "nm_y"], "refs": [], "sources": [], "joins": [], "casts": []}, None)
    assert_true(len(all_new) == 2, "novo.all_cols", str(all_new))


def test_topo_order_layers() -> None:
    """Ordem: stg antes de dim/fato; fato antes de aggr (mesmo com deps)."""
    checklist = [
        {"name": "aggr_x", "layer": "aggregate", "table_kind": "AGGR",
         "policy_action": "create", "status": "NOVO"},
        {"name": "f_viagem", "layer": "mart", "table_kind": "F",
         "policy_action": "create", "status": "NOVO"},
        {"name": "stg_a", "layer": "staging", "table_kind": None,
         "policy_action": "create", "status": "NOVO"},
        {"name": "dib_b", "layer": "mart", "table_kind": "DIB",
         "policy_action": "append", "status": "ALTERADO"},
    ]
    graph = {
        "stg_a": {"refs": [], "dependents": ["dib_b", "f_viagem"]},
        "dib_b": {"refs": ["stg_a"], "dependents": []},
        "f_viagem": {"refs": ["stg_a"], "dependents": ["aggr_x"]},
        "aggr_x": {"refs": ["f_viagem"], "dependents": []},
    }
    order = engine.topo_order(checklist, graph)
    assert_true(order.index("stg_a") < order.index("dib_b"), "stg_before_dib", str(order))
    assert_true(order.index("stg_a") < order.index("f_viagem"), "stg_before_f", str(order))
    assert_true(order.index("f_viagem") < order.index("aggr_x"), "f_before_aggr", str(order))


def test_declared_sources_warning() -> None:
    models = {
        "sources_yml": {
            "name": "sources_yml", "type": "source", "path": "models/sources.yml",
            "sources": [["raw", "cars"]], "refs": [], "columns": [],
        },
        "stg_x": {
            "name": "stg_x", "type": "model", "path": "models/stg_x.sql",
            "sources": [["raw", "missing"]], "refs": [], "columns": [],
        },
    }
    declared = engine.collect_declared_sources(models)
    assert_true("source.raw.cars" in declared, "declared.ok", str(declared))
    assert_true("source.raw.missing" not in declared, "usage_not_declared", str(declared))

    checklist = [{
        "name": "stg_x", "status": "NOVO", "policy_action": "create",
        "layer": "staging", "refs": [], "sources": [["raw", "missing"]],
        "type": "model", "columns": [],
    }]
    graph = {"stg_x": {"refs": ["source.raw.missing"], "dependents": []}}
    ws = engine.validate(
        checklist, graph, models, {},
        add_only=True, enforce_taxonomy=False, declared_sources=declared,
    )
    assert_true(
        any(w.get("label") == "Sources" and "missing" in w.get("message", "") for w in ws),
        "warn.undeclared_source",
        str(ws),
    )


def test_verify_card_create_missing() -> None:
    with tempfile.TemporaryDirectory() as td:
        base = os.path.join(td, "base")
        os.makedirs(os.path.join(base, "models"), exist_ok=True)
        with open(os.path.join(base, "models", "stg_ok.sql"), "w", encoding="utf-8") as f:
            f.write("select id_carro, nm_modelo from x\n")
        cfg = {"base_project_path": base, "base_include": []}
        session = {
            "card_id": "T-1",
            "checklist": [
                {"name": "stg_ok", "policy_action": "create", "status": "NOVO", "add_items": []},
                {"name": "stg_falta", "policy_action": "create", "status": "NOVO", "add_items": []},
                {
                    "name": "dib_x", "policy_action": "append", "status": "ALTERADO",
                    "match_name": "stg_ok",
                    "add_items": [
                        {"kind": "coluna", "name": "id_carro"},
                        {"kind": "coluna", "name": "nm_falta"},
                    ],
                },
            ],
        }
        report = engine.verify_card(cfg, session)
        assert_true("stg_ok" in report["created_ok"], "verify.create_ok", str(report))
        assert_true("stg_falta" in report["created_missing"], "verify.create_missing", str(report))
        assert_true("stg_ok" in report["append_partial"], "verify.append_partial", str(report))
        assert_true(report["complete"] is False, "verify.incomplete", str(report))


def test_ui_domain_and_lineage_svg() -> None:
    session = {
        "card_id": "DEMO",
        "timestamp": "2026-01-01T00:00:00",
        "message": "",
        "summary": {
            "base_models": 1, "workspace_models": 2, "novo": 1, "acrescentar": 1,
            "nao_alterar": 0, "revisar": 0, "igual": 0, "critical": 0, "warning": 0,
            "pending": 2, "renomeado": 0, "alterado": 1, "removido": 0,
        },
        "checklist": [
            {
                "name": "stg_a", "status": "NOVO", "policy_action": "create",
                "domain": "ebody", "layer": "staging", "path": "ebody/stg_a.sql",
                "label": "Criar", "bucket": "criar", "hint": "", "add_count": 0,
                "add_items": [], "add_summary": "", "refs": [], "sources": [],
                "columns": [], "suggested_order": 1, "type": "model",
            },
            {
                "name": "stg_b", "status": "NOVO", "policy_action": "create",
                "domain": "ais", "layer": "staging", "path": "ais/stg_b.sql",
                "label": "Criar", "bucket": "criar", "hint": "", "add_count": 0,
                "add_items": [], "add_summary": "", "refs": [], "sources": [],
                "columns": [], "suggested_order": 2, "type": "model",
            },
        ],
        "warnings": [],
        "lineage": {
            "layers": ["staging", "mart"],
            "nodes": [
                {
                    "id": "stg_a", "label": "stg_a", "visual": "new", "layer": "staging",
                    "used_by": ["dib_x", "f_y"], "add_count": 0, "upstream": [],
                    "downstream": ["dib_x", "f_y"], "depends_on": [], "add_items": [],
                    "policy_action": "create", "columns": [],
                },
                {
                    "id": "dib_x", "label": "dib_x", "visual": "exist", "layer": "mart",
                    "used_by": [], "add_count": 0, "upstream": ["stg_a"],
                    "downstream": [], "depends_on": ["stg_a"], "add_items": [],
                    "policy_action": "exists", "columns": [],
                },
                {
                    "id": "f_y", "label": "f_y", "visual": "new", "layer": "mart",
                    "used_by": [], "add_count": 0, "upstream": ["stg_a"],
                    "downstream": [], "depends_on": ["stg_a"], "add_items": [],
                    "policy_action": "create", "columns": [],
                },
            ],
            "edges": [
                {"from": "stg_a", "to": "dib_x"},
                {"from": "stg_a", "to": "f_y"},
            ],
        },
        "execution_order": ["stg_a", "stg_b"],
        "add_only": True,
        "patterns": {},
        "top_folders": [],
        "base_include": [],
    }
    html = ui.render(session)
    assert_true("Negócio: ebody" in html and "Negócio: ais" in html, "ui.domain_groups", "")
    assert_true('id="ln-svg"' in html, "ui.ln_svg", "")
    assert_true('id="ln-breadcrumb"' in html, "ui.ln_crumb", "")
    assert_true("drawEdges" in html or "ln-svg" in html, "ui.edges_js", "")
    assert_true("→ 2" in html or "se divide" in html.lower() or "ln-fan" in html, "ui.fan", "")


def main() -> None:
    print("=== DBT Guardian tests ===")
    test_parse_sql()
    test_hash()
    test_cycles_downstream()
    test_name_matching()
    test_integration()
    test_rename_detection()
    test_hardening()
    test_content_hash_not_false_igual()
    test_yaml_models_not_sources()
    test_exclusive_rename_no_double_claim()
    test_base_include_filters_domains()
    test_taxonomy_rules()
    test_additive_items_and_lineage()
    test_topo_order_layers()
    test_declared_sources_warning()
    test_verify_card_create_missing()
    test_ui_domain_and_lineage_svg()
    print()
    print(f"Passed: {passed}  Failed: {failed}")
    if failed:
        raise SystemExit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
