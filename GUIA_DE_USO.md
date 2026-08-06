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

1. Configure `base_project_path` + `card_id` (e `base_include` se quiser filtrar)
2. Extraia o ZIP em `workspace/`
3. `py -3 main.py`
4. Abra `output/index.html` → aba **Resumo** (etapas)
5. **Diff** → **Ordem** (só adição)
6. Refatore na base se a IA errou → `dbt compile` / SaaS / BQ → `S` no terminal

### Regra de ouro

`add_only: true` (padrão): **não altere** arquivos que já existem na base — só adicione o que veio de novo no card.

Exemplo em `carros.int` (já existe): cole **só** isto, nunca o SQL inteiro:

```sql
-- CARD-XXX — acrescentar em carros.int
, coluna_nova_1
, coluna_nova_2
```

## Método de 1 dia

O ZIP/IA **não** vem 100% certo. O Sentinel mostra o que criar/acrescer; **você** fecha o SQL fino e valida com dbt.

1. Config + ZIP em `workspace/` → `py -3 main.py`
2. **Resumo** — seguir as etapas na ordem
3. **Diff** — Criar / Acrescentar / Ignorar
4. **Ordem** — snippet **só com a adição**; arquivo novo = copiar do workspace
5. Aplicar na base; se a IA errou, refatorar aí
6. **Fluxo / Avisos** — ciclo `A→…→A`, refs, sources (informativo)
7. `dbt compile` / SaaS / BQ
8. Terminal **`S`** → `pending.md`

Artefatos em `output/`:

| Arquivo | Uso |
|---------|-----|
| `index.html` | Resumo, Diff, Ordem, Fluxo, Zoom, Avisos |
| `roteiro.md` | Sequência + snippets |
| `pending.md` | O que faltou após o `S` |
