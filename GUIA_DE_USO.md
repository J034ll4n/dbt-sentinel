# Guia rápido — DBT Sentinel

> Documentação completa: **[README.md](README.md)**

## Qual caminho colar no config?

Sua base DBT parece isto:

```text
C:\projetos\dbt-corporativo\     ← cole isto em base_project_path
├── AIS\
├── ebody\
├── Rodos\
├── impress_code\
└── schemas\
```

No `config.json`:

```json
"base_project_path": "C:\\projetos\\dbt-corporativo",
"base_include": ["ebody", "AIS", "Rodos"]
```

- `base_project_path` = pasta **raiz** (a que tem várias pastas de negócio)
- `base_include` = **só** os nomes das pastas deste card (sem caminho completo)

## Em 30 segundos

1. Configure `base_project_path` + `base_include` + `card_id`
2. Extraia o ZIP em `workspace/`
3. `py -3 main.py`
4. Confira no terminal: “Analisando SOMENTE: …”
5. Abra `output/index.html` e siga o Assistente
6. SaaS + BQ → `S` no terminal → limpe `workspace/`
