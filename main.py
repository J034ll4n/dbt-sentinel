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
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    # paths relativos → absolutos a partir da pasta do Guardian
    for key in ("workspace_path", "output_path", "snapshots_path"):
        p = cfg.get(key, "")
        if p and not os.path.isabs(p):
            cfg[key] = os.path.join(ROOT, p)
    for key in ("workspace_path", "output_path", "snapshots_path"):
        os.makedirs(cfg[key], exist_ok=True)
    return cfg


def git_porcelain(repo: str) -> str:
    if not repo or not os.path.isdir(repo):
        return ""
    git_dir = os.path.join(repo, ".git")
    if not os.path.isdir(git_dir):
        return ""  # sem git — não bloqueia
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if out.returncode != 0:
            return ""
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def save_snapshot(cfg: dict, session: dict) -> str:
    card = session.get("card_id", "CARD-XXX")
    dest = os.path.join(cfg["snapshots_path"], card)
    os.makedirs(dest, exist_ok=True)
    manifest = {
        "card_id": card,
        "timestamp": session.get("timestamp") or datetime.now().isoformat(timespec="seconds"),
        "changes": [
            {
                "model": c["name"],
                "status": c["status"],
                "path": c.get("path", ""),
            }
            for c in session.get("checklist", [])
            if c["status"] != "IGUAL"
        ],
        "critical_count": session["summary"].get("critical", 0),
        "warning_count": session["summary"].get("warning", 0),
        "pending_count": session["summary"].get("pending", 0),
        "structural_hashes": {
            c["name"]: c.get("hash", "")
            for c in session.get("checklist", [])
            if c["status"] != "IGUAL"
        },
    }
    path = os.path.join(dest, "manifest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return path


def print_summary(session: dict) -> None:
    s = session["summary"]
    print()
    print("=" * 56)
    print(f"  DBT Guardian — {session.get('card_id')}")
    print("=" * 56)
    print(f"  Base:      {s['base_models']} arquivo(s)")
    print(f"  Workspace: {s['workspace_models']} arquivo(s)")
    print(f"  Criar:     {s['novo']}")
    print(f"  Atualizar: {s['alterado']}")
    print(f"  Verificar: {s['removido']}")
    print(f"  Pronto:    {s['igual']}")
    print(f"  Bloqueios: {s['critical']}")
    print(f"  Pendentes: {s['pending']}")
    if session.get("message"):
        print()
        print(f"  → {session['message']}")
    print("=" * 56)


def main() -> None:
    print("DBT Guardian — iniciando análise (somente leitura)...")
    cfg = load_config()
    base = cfg.get("base_project_path", "")

    if not base or not os.path.isdir(base):
        print()
        print("AVISO: base_project_path inválido no config.json")
        print(f"  Atual: {base!r}")
        print("  Edite config.json com o caminho absoluto do repositório DBT.")
        print("  Continuando só com o workspace...")

    before = git_porcelain(base)

    session = engine.run(cfg)

    out_dir = cfg["output_path"]
    session_path = os.path.join(out_dir, "session.json")
    html_path = os.path.join(out_dir, "index.html")

    with open(session_path, "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(ui.render(session))

    after = git_porcelain(base)
    if before != after:
        print()
        print("ERRO DE INTEGRIDADE: git status do projeto base mudou após a execução.")
        print("O DBT Guardian não deveria alterar o repositório. Abortando finalização.")
        print(f"Antes:\n{before}\nDepois:\n{after}")
        print(f"Relatório gerado mesmo assim em: {html_path}")
        sys.exit(2)

    print_summary(session)
    print(f"\n  Relatório: {html_path}")
    print(f"  Sessão:    {session_path}")

    try:
        webbrowser.open(html_path)
    except Exception:
        pass

    s = session["summary"]
    print()
    ans = input(f"Finalizar card {session.get('card_id')} e salvar snapshot? (S/N): ").strip().upper()
    if ans != "S":
        print("Snapshot não salvo. Limpe workspace/ quando terminar o card.")
        return

    if s["critical"] > 0:
        print(f"Não é possível finalizar: ainda há {s['critical']} bloqueio(s) CRITICAL.")
        print("Resolva os bloqueios, rode novamente e tente de novo.")
        return
    if s["pending"] > 0:
        print(f"Aviso: ainda há {s['pending']} item(ns) pendente(s) no checklist.")
        conf = input("Finalizar mesmo assim? (S/N): ").strip().upper()
        if conf != "S":
            print("Snapshot cancelado.")
            return

    path = save_snapshot(cfg, session)
    print(f"Snapshot salvo em: {path}")
    print("Limpe a pasta workspace/ e atualize card_id no config.json para o próximo card.")


if __name__ == "__main__":
    main()
