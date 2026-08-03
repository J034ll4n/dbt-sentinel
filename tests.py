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


def main() -> None:
    print("=== DBT Guardian tests ===")
    test_parse_sql()
    test_hash()
    test_cycles_downstream()
    test_integration()
    print()
    print(f"Passed: {passed}  Failed: {failed}")
    if failed:
        raise SystemExit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
