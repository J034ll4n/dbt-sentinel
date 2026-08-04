# -*- coding: utf-8 -*-
"""DBT Guardian — ponto de entrada CLI (stdlib only)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import webbrowser
from datetime import datetime

import engine
import ui

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "config.json")


def load_config() -> dict:
    if not os.path.isfile(CONFIG_PATH):
        print(f"ERRO: config.json não encontrado em {CONFIG_PATH}")
        sys.exit(1)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERRO: config.json inválido: {e}")
        sys.exit(1)

    if not isinstance(cfg, dict):
        print("ERRO: config.json deve ser um objeto JSON")
        sys.exit(1)

    # paths relativos → absolutos a partir da pasta do Guardian
    for key in ("workspace_path", "output_path", "snapshots_path", "base_project_path"):
        p = cfg.get(key, "")
        if p and isinstance(p, str) and not os.path.isabs(p):
            cfg[key] = os.path.abspath(os.path.join(ROOT, p))
        elif p and isinstance(p, str):
            cfg[key] = os.path.abspath(p)

    cfg["card_id"] = engine.sanitize_card_id(cfg.get("card_id", "CARD-XXX"))
    if "aliases" not in cfg or cfg["aliases"] is None:
        cfg["aliases"] = {}
    if "match_threshold" not in cfg:
        cfg["match_threshold"] = 0.62
    if "detect_removed" not in cfg:
        cfg["detect_removed"] = False
    if "allow_empty_base" not in cfg:
        cfg["allow_empty_base"] = False
    if "require_git_integrity" not in cfg:
        cfg["require_git_integrity"] = False
    if "base_include" not in cfg or cfg["base_include"] is None:
        cfg["base_include"] = []

    errors = engine.validate_config(cfg)
    if errors:
        print("ERRO de configuração:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    # só cria pastas do Guardian — nunca dentro do base
    for key in ("workspace_path", "output_path", "snapshots_path"):
        os.makedirs(cfg[key], exist_ok=True)
    return cfg


def git_porcelain(repo: str) -> str | None:
    """Retorna porcelain string, '' se limpo, None se git indisponível."""
    if not repo or not os.path.isdir(repo):
        return None
    git_dir = os.path.join(repo, ".git")
    if not os.path.isdir(git_dir):
        return None
    try:
        out = subprocess.run(
            ["git", "-c", "safe.directory=*", "status", "--porcelain"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
        )
        if out.returncode != 0:
            return None
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def assert_write_target(path: str, allowed_roots: list[str]) -> None:
    """Garante que só gravamos em output/ ou snapshots/."""
    abs_path = os.path.abspath(path)
    for root in allowed_roots:
        root_abs = os.path.abspath(root)
        try:
            if os.path.commonpath([root_abs, abs_path]) == root_abs:
                return
        except ValueError:
            continue
    raise RuntimeError(f"Bloqueado: tentativa de gravar fora de output/snapshots: {abs_path}")


def save_snapshot(cfg: dict, session: dict, verification: dict | None = None) -> str:
    card = engine.sanitize_card_id(session.get("card_id", "CARD-XXX"))
    dest = os.path.join(cfg["snapshots_path"], card)
    assert_write_target(dest, [cfg["snapshots_path"]])
    os.makedirs(dest, exist_ok=True)
    plan = []
    for c in session.get("checklist", []):
        if c.get("policy_action") not in {"create", "append"}:
            continue
        plan.append({
            "model": c["name"],
            "action": c.get("policy_action"),
            "status": c["status"],
            "path": c.get("path", ""),
            "domain": c.get("domain") or "",
            "add_count": c.get("add_count", 0),
            "add_items": c.get("add_items") or [],
            "match_name": c.get("match_name"),
            "label": c.get("label"),
        })
    manifest = {
        "card_id": card,
        "timestamp": session.get("timestamp") or datetime.now().isoformat(timespec="seconds"),
        "plan": plan,
        "changes": [
            {
                "model": c["name"],
                "status": c["status"],
                "policy_action": c.get("policy_action"),
                "path": c.get("path", ""),
                "match_name": c.get("match_name"),
                "add_count": c.get("add_count", 0),
            }
            for c in session.get("checklist", [])
            if c["status"] != "IGUAL"
        ],
        "summary": session.get("summary") or {},
        "critical_count": session["summary"].get("critical", 0),
        "warning_count": session["summary"].get("warning", 0),
        "pending_count": session["summary"].get("pending", 0),
        "renomeado_count": session["summary"].get("renomeado", 0),
        "verification": verification or {},
        "structural_hashes": {
            c["name"]: c.get("hash", "")
            for c in session.get("checklist", [])
            if c["status"] != "IGUAL"
        },
    }
    path = os.path.join(dest, "manifest.json")
    assert_write_target(path, [cfg["snapshots_path"]])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    if verification:
        vpath = os.path.join(dest, "verification.json")
        assert_write_target(vpath, [cfg["snapshots_path"]])
        with open(vpath, "w", encoding="utf-8") as f:
            json.dump(verification, f, ensure_ascii=False, indent=2)
        pmd = verification.get("pending_markdown") or engine.build_pending_markdown(verification)
        ppath = os.path.join(dest, "pending.md")
        assert_write_target(ppath, [cfg["snapshots_path"]])
        with open(ppath, "w", encoding="utf-8") as f:
            f.write(pmd)
    return path


def print_summary(session: dict) -> None:
    s = session["summary"]
    print()
    print("=" * 56)
    print(f"  DBT Guardian — {session.get('card_id')}")
    print("=" * 56)
    print(f"  Base:      {s['base_models']} arquivo(s)")
    print(f"  Workspace: {s['workspace_models']} arquivo(s)")
    print(f"  Criar:        {s.get('novo', 0)}")
    print(f"  Acrescentar:  {s.get('acrescentar', 0)}")
    print(f"  Não alterar:  {s.get('nao_alterar', 0)}")
    print(f"  Revisar:      {s.get('revisar', 0)}")
    print(f"  Já na base:   {s.get('igual', 0)}")
    print(f"  Bloqueios:    {s.get('critical', 0)}")
    print(f"  Pendentes:    {s.get('pending', 0)}")
    if session.get("message"):
        print()
        print(f"  → {session['message']}")
    print("=" * 56)


def print_config_wizard(cfg: dict) -> None:
    """Guia de paths no start."""
    base = cfg.get("base_project_path") or ""
    ws = cfg.get("workspace_path") or ""
    print()
    print("--- Configuração ---")
    print(f"  Card:      {cfg.get('card_id')}")
    print(f"  Base:      {base}")
    print(f"  Workspace: {ws}")
    print(f"  Output:    {cfg.get('output_path')}")
    print(f"  Snapshots: {cfg.get('snapshots_path')}")

    if base and os.path.isdir(base):
        tops = engine.list_top_folders(base)
        inc = cfg.get("base_include") or []
        print(f"  Pastas na base ({len(tops)}): {', '.join(tops) if tops else '(nenhuma)'}")
        if inc:
            print(f"  Analisando SOMENTE ({len(inc)}): {', '.join(inc)}")
            missing = [n for n in inc if n not in tops]
            if missing:
                print(f"  AVISO: base_include não encontrado: {', '.join(missing)}")
        elif tops and len(tops) > 3:
            print("  AVISO: muitas pastas e base_include vazio — pode ficar lento.")
            print('  Dica: "base_include": ["ebody", "AIS"]')
    else:
        print("  AVISO: base_project_path inválido ou inexistente.")

    if ws and os.path.isdir(ws):
        ws_tops = engine.list_top_folders(ws)
        sql_count = 0
        for root, _dirs, files in os.walk(ws):
            sql_count += sum(1 for f in files if f.lower().endswith((".sql", ".yml", ".yaml")))
            if sql_count > 500:
                break
        print(f"  Workspace OK — pastas: {', '.join(ws_tops) if ws_tops else '(plana)'}")
        print(f"  Arquivos .sql/.yml encontrados (amostra): ~{sql_count}")
        if sql_count == 0:
            print("  AVISO: workspace sem .sql/.yml — extraia o ZIP do card dentro desta pasta.")
    else:
        print("  AVISO: workspace_path inválido ou inexistente.")
    print("--------------------")


def print_verification(report: dict) -> None:
    print()
    print("=" * 56)
    print("  VERIFICAÇÃO FINAL — SÓ O QUE FALTA")
    print("=" * 56)
    pending = report.get("pending_only") or []
    if pending:
        for i, p in enumerate(pending, 1):
            miss = p.get("missing") or []
            extra = f" | falta: {', '.join(miss)}" if miss else ""
            print(f"  {i}. [{p.get('action')}] {p.get('name')}{extra}")
            if p.get("message"):
                print(f"      {p['message']}")
    else:
        print("  (nada pendente)")
    print()
    print(report.get("summary_text") or "")
    if report.get("complete"):
        print()
        print("  ✓ Tudo que o card pediu parece estar na base.")
    else:
        print()
        print("  ✗ Ainda há pendências — use a lista acima (não o card inteiro).")
    if report.get("diverged"):
        print("  (Houve diferenças manuais/SQL ignoradas — valide SaaS/BQ.)")
    print("=" * 56)


def main() -> None:
    print("DBT Guardian — iniciando análise (somente leitura)...")
    cfg = load_config()
    base = cfg.get("base_project_path", "")

    if not base or not os.path.isdir(base):
        print()
        print("ERRO: base_project_path inválido no config.json")
        print(f"  Atual: {base!r}")
        print("  Edite config.json com o caminho absoluto do repositório DBT.")
        if not cfg.get("allow_empty_base"):
            print("  (Para forçar sem base: \"allow_empty_base\": true — NÃO recomendado)")
            sys.exit(1)
        print("  Continuando com allow_empty_base=true — resultados NÃO confiáveis.")

    # base e workspace iguais = perigoso / sem sentido
    if base and cfg.get("workspace_path"):
        try:
            if os.path.abspath(base) == os.path.abspath(cfg["workspace_path"]):
                print("ERRO: base_project_path e workspace_path não podem ser a mesma pasta.")
                sys.exit(1)
        except OSError:
            pass

    before = git_porcelain(base)
    if before is None and cfg.get("require_git_integrity") and base and os.path.isdir(base):
        print("ERRO: require_git_integrity=true mas a base não é um repo git válido.")
        sys.exit(1)
    if before is None and base and os.path.isdir(base):
        print("AVISO: integridade git indisponível na base (sem .git ou git).")
        print("  A ferramenta não grava na base, mas não há checagem automática.")

    # Mostra pastas de negócio encontradas vs filtradas
    print_config_wizard(cfg)

    try:
        session = engine.run(cfg)
    except Exception as e:
        print(f"ERRO na análise: {type(e).__name__}: {e}")
        sys.exit(1)

    out_dir = cfg["output_path"]
    session_path = os.path.join(out_dir, "session.json")
    html_path = os.path.join(out_dir, "index.html")
    roteiro_path = os.path.join(out_dir, "roteiro.md")

    try:
        assert_write_target(session_path, [out_dir])
        assert_write_target(html_path, [out_dir])
        assert_write_target(roteiro_path, [out_dir])
        with open(session_path, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(ui.render(session))
        with open(roteiro_path, "w", encoding="utf-8") as f:
            f.write(session.get("order_markdown") or "")
    except (OSError, RuntimeError) as e:
        print(f"ERRO ao gravar relatório: {e}")
        sys.exit(1)

    after = git_porcelain(base)
    if before is not None and after is not None and before != after:
        print()
        print("ERRO DE INTEGRIDADE: git status do projeto base mudou após a execução.")
        print("O DBT Guardian não deveria alterar o repositório. Abortando finalização.")
        print(f"Antes:\n{before}\nDepois:\n{after}")
        print(f"Relatório gerado mesmo assim em: {html_path}")
        sys.exit(2)

    print_summary(session)
    print(f"\n  Relatório: {html_path}")
    print(f"  Sessão:    {session_path}")
    print(f"  Roteiro:   {roteiro_path}")

    try:
        webbrowser.open(html_path)
    except Exception:
        pass

    s = session["summary"]
    print()
    try:
        ans = input(f"Finalizar card {session.get('card_id')} e salvar snapshot? (S/N): ").strip().upper()
    except EOFError:
        print("Entrada indisponível — snapshot não salvo.")
        return

    if ans != "S":
        print("Snapshot não salvo. Limpe workspace/ quando terminar o card.")
        return

    if s["critical"] > 0:
        print(f"Não é possível finalizar: ainda há {s['critical']} bloqueio(s) CRITICAL.")
        print("Resolva os bloqueios, rode novamente e tente de novo.")
        return

    print()
    print("Conferindo a base (o que foi criado/acrescentado de fato)...")
    try:
        verification = engine.verify_card(cfg, session)
    except Exception as e:
        print(f"AVISO: falha na verificação final: {e}")
        verification = {"complete": False, "summary_text": str(e), "details": []}
    print_verification(verification)

    # grava pending.md no output para colar no Jira
    try:
        pending_path = os.path.join(out_dir, "pending.md")
        assert_write_target(pending_path, [out_dir])
        pmd = verification.get("pending_markdown") or engine.build_pending_markdown(verification)
        with open(pending_path, "w", encoding="utf-8") as f:
            f.write(pmd)
        print(f"  Pendências: {pending_path}")
    except (OSError, RuntimeError) as e:
        print(f"AVISO: não gravou pending.md: {e}")

    if not verification.get("complete"):
        try:
            conf = input("Ainda há pendências. Finalizar snapshot mesmo assim? (S/N): ").strip().upper()
        except EOFError:
            conf = "N"
        if conf != "S":
            print("Snapshot cancelado. Ajuste a base e rode de novo para re-verificar.")
            return
    elif s["pending"] > 0:
        print(f"Aviso: checklist ainda tinha {s['pending']} pendente(s) na análise inicial.")

    try:
        path = save_snapshot(cfg, session, verification)
    except (OSError, RuntimeError) as e:
        print(f"ERRO ao salvar snapshot: {e}")
        sys.exit(1)
    print(f"Snapshot salvo em: {path}")
    print("  (manifest.json = plano + verificação; verification.json = detalhe)")
    print("Limpe a pasta workspace/ e atualize card_id no config.json para o próximo card.")


if __name__ == "__main__":
    main()
