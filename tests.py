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
        assert_true(s["summary"]["critical"] >= 1, "run.critical", str(s["summary"]))
        assert_true(s["summary"]["removido"] == 0, "run.no_false_removed", str(s["summary"]))
        assert_true("sample_cliente" in s["order"], "run.order", str(s["order"]))

        names = {c["name"]: c["status"] for c in s["checklist"]}
        assert_true(names.get("sample_cliente") == "NOVO", "status.sample")
        assert_true(names.get("stg_cliente") == "ALTERADO", "status.stg")
        assert_true(names.get("int_cliente") == "ALTERADO", "status.int")
        assert_true(names.get("int_novo") == "NOVO", "status.int_novo")

        html = ui.render(s)
        assert_true("DBT Guardian" in html, "ui.title")
        assert_true("Assistente" in html and "Arquivos" in html, "ui.tabs")
        assert_true("sample_cliente" in html, "ui.has_model")
        assert_true("stg_empresa" in html, "ui.has_blocker")

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
                    "pending": 0, "critical": 0, "warning": 0, "base_models": 0, "workspace_models": 0},
        "message": "</script><script>alert(1)</script>",
        "checklist": [],
        "warnings": [],
        "order": [],
        "flow_chains": [],
        "timeline": [],
        "patterns": {},
        "empty_workspace": True,
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
        # ZIP traz o nome certo E um nome parecido — não deve renomear o parecido para o mesmo
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
    print()
    print(f"Passed: {passed}  Failed: {failed}")
    if failed:
        raise SystemExit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
