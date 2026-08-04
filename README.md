# DBT Sentinel

**Analisador de impacto para migrações dbt em ambientes restritos.**

Compara o ZIP de um card (SaaS/Jira) com o projeto dbt corporativo e gera um assistente visual em HTML: o que **criar**, o que **acrescentar**, ordem de execução, lineage micro/macro, snippets copiáveis e verificação final — **sem gravar nada** no repositório dbt.

Feito para consultoria em VDIs travadas (`pip`, `npm`, Docker e plugins de IDE indisponíveis).

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Dependências](https://img.shields.io/badge/deps-somente%20stdlib-success)](#stack)
[![Política](https://img.shields.io/badge/política-só%20adições-1f7a4d)](#estratégia-como-resolvemos)

Repositório: [github.com/J034ll4n/dbt-sentinel](https://github.com/J034ll4n/dbt-sentinel)

---

## O problema principal

No dia a dia da migração SaaS → dbt corporativo, o consultor recebe um **card no Jira** com um ZIP gerado por IA/SaaS e precisa levar isso para um monorepo grande (vários domínios: `ebody`, `AIS`, …).

Isso costuma falhar por quatro motivos:

1. **O ZIP mistura coisas novas com coisas já existentes**  
   Arquivos que ainda não estão na base + “edições” em modelos que já existem. O reflexo de colar tudo por cima **reescreve produção** e quebra o que já funciona.

2. **Não dá para confiar no diff bruto**  
   O pacote muda SQL antigo, remove colunas, renomeia modelos (`stg_cliente` vs `stg_clientes`). O que importa para o card é: *o que é realmente novo para acrescentar?*

3. **Falta mapa de encaixe**  
   Mesmo sabendo “criar `f_evento`”, falta ver *onde* ele se liga no grafo corporativo e *quem* recompilar depois.

4. **Ambiente trava a stack**  
   VDI sem `pip`/`npm`. Qualquer solução que dependa de pacotes ou build de frontend não sobe.

**Dor resumida:** perder tempo e risco reescrevendo a base, em vez de **só adicionar o que o card trouxe de novo**.

---

## Estratégia: como resolvemos

A aposta do Sentinel é uma **camada de decisão e impacto**, não um auto-merge.

### Regra de ouro (não negociável)

| Situação | O que a ferramenta faz |
|---|---|
| Arquivo **não existe** na base | Orienta a **CRIAR** (copiar do `workspace/` para o path) |
| Arquivo **já existe** | Orienta a **ACRESCENTAR só itens novos** (colunas, refs, sources…) |
| ZIP mudou SQL antigo / removeu coisa | Marca como **atenção / não alterar** — **nunca** sugere reescrever o principal |
| Base corporativa | **Somente leitura** — escrita só em `output/` e `snapshots/` |

### Abordagem em camadas

```text
1. Scan estrutural (SQL/YAML) da base + do workspace
2. Diff aditivo → add_items (o que colocar) × base_columns (já existe) × ignored_changes (atenções)
3. Política add_only → buckets: criar | acrescentar | não alterar | revisar
4. Grafo de refs/sources → ordem topológica + lineage
5. Relatório HTML (assistente) + roteiro Markdown + snippets copiáveis
6. No fechamento do card: re-lê a base e lista SÓ O QUE FALTA
```

### Duas visões de lineage

| Visão | Pergunta que responde |
|---|---|
| **Micro** (aba Lineage) | “O que este *card* mexe no fluxo?” — DAG do pacote, setas que se dividem (1→N) |
| **Macro** (aba Macro) | “Onde *este arquivo* se encaixa na base?” — vizinhos corporativos; verde = criar ou itens novos |

### Velocidade do consultor

Além de decidir, a ferramenta acelera a execução:

- **Snippet “Copiar”** — bloco pronto só com adições (ou guia de criar)
- **Roteiro Markdown** — checklist colável no Jira/VS Code (`output/roteiro.md`)
- **Impacto jusante** — “se aplicar aqui, recompilar: …”
- **Salto Micro ↔ Macro** — menos caça no seletor
- **Pending** — após verificar, só a lista do que ainda falta (`output/pending.md`)

```text
ZIP do card (workspace/)  +  dbt corporativo (base, read-only)
              ↓
         engine (stdlib)
              ↓
  index.html · session.json · roteiro.md · pending.md · snapshots/
```

---

## Funcionalidades (detalhe)

### Assistente

- Passos guiados: bloqueios → criar → acrescentar → taxonomia → SaaS/BQ
- Regra de ouro visível (criar / acrescentar / não reescrever)
- Checkboxes locais (progresso no navegador)

### Ordem

- Execução topológica: **source → sample → staging → intermediate → dim/fato → aggregate**
- Cada passo: path, itens novos, dependências
- **Copiar roteiro** Markdown + **Copiar snippet** por passo
- Atalho **Abrir Macro** do arquivo do passo

### Arquivos

- Seções: **1. Criar** · **2. Acrescentar (só o novo)** · **3. Atenção / Revisar / Não alterar**
- Agrupamento por **domínio de negócio** (`base_include` / pasta)
- Em cada card: checklist do novo, já na base, atenções, snippet copiável

### Lineage (micro)

- Faixas por camada
- Setas SVG que **seguem o card** e **se dividem** quando um modelo alimenta vários
- Breadcrumb do caminho ao clicar
- Botão **Abrir Macro** quando o nó é create/append do card

### Macro (arquivo × base)

- Seletor de arquivo foco (criar ou acrescentar)
- Grafo corporativo ao redor (cinza = contexto; verde = novo / itens a acrescer)
- Faixa **Se aplicar neste arquivo, recompilar depois:** …
- Snippet do foco + **Ver no Lineage**

### Alertas

- Refs quebradas (crítico em arquivo novo)
- `source()` sem declaração em `sources.yml`
- Taxonomia (F / DIB / AGGR, prefixos `id_`, `nm_`, tamanho, case…)
- Política: acrescento vs não reescrever

### Verificação final (CLI)

Ao responder `S` no terminal:

1. Re-lê a base
2. Reporta criados OK / faltando / acrescentos parciais
3. Destaca **SÓ O QUE FALTA** (não o card inteiro de novo)
4. Grava `pending.md` + snapshot (`manifest.json`, `verification.json`)

### Detecção e matching

- Rename fuzzy + aliases (`match_threshold`)
- Hash estrutural + content hash (evita “IGUAL” falso quando só o corpo SQL mudou)
- Parse de colunas com `AS` e `SAFE_CAST(... AS tipo) AS nome`
- Filtro `base_include` para não varrer o monorepo inteiro

### Segurança de I/O

- Escrita restrita a `output/` e `snapshots/`
- Paths sanitizados (sem `..` / escape do sandbox da ferramenta)
- HTML escapado (XSS)
- Checagem opcional de integridade git na base (não deve mudar após a análise)

---

## Stack

| Camada | Escolha | Motivo |
|---|---|---|
| Runtime | Python 3 (**stdlib only**) | VDI sem `pip` |
| UI | Um `index.html` (CSS/JS puro) | Sem build, abre local |
| Parse | Regex + YAML mínimo | Scan rápido de `.sql` / `.yml` |
| Persistência | JSON + Markdown | Sessão, roteiro, pending, snapshot |

Zero dependência Python de terceiros. Zero bundler.

---

## Como rodar

```bash
git clone https://github.com/J034ll4n/dbt-sentinel.git
cd dbt-sentinel
```

1. Configure `config.json` (`base_project_path` = raiz do dbt **read-only**; ZIP em `workspace/`).
2. Execute:

```bash
py -3 main.py
```

3. Abra `output/index.html` — abas **Assistente · Ordem · Arquivos · Lineage · Macro · Alertas**.

### Demo incluída

```bash
py -3 run_demo.py
```

Usa `demo_base/` + `workspace/` de exemplo e gera o relatório sem repo corporativo.

Checklist operacional curto: [`GUIA_DE_USO.md`](GUIA_DE_USO.md).

---

## Configuração

```json
{
  "base_project_path": "caminho/para/dbt-raiz",
  "base_include": ["dominio_a", "dominio_b"],
  "workspace_path": "workspace",
  "output_path": "output",
  "snapshots_path": "snapshots",
  "card_id": "CARD-123",
  "add_only": true,
  "enforce_taxonomy": true,
  "detect_removed": false,
  "match_threshold": 0.62,
  "aliases": {},
  "allow_empty_base": false,
  "require_git_integrity": false
}
```

| Campo | Função |
|---|---|
| `base_project_path` | Raiz do dbt corporativo (**nunca modificada**) |
| `base_include` | Domínios a analisar (vazio = tudo sob a raiz) |
| `workspace_path` | Extrato do card / ZIP |
| `add_only` | Política aditiva (padrão `true`) |
| `enforce_taxonomy` | Heurísticas de nomenclatura |
| `card_id` | Rótulo do relatório e do snapshot |
| `detect_removed` | `false` para ZIP parcial (não inventar remoções) |
| `match_threshold` / `aliases` | Sensibilidade e mapa de rename |

---

## Arquitetura

```text
┌─────────────┐     ┌───────────────────────────┐     ┌──────────────────┐
│  config.json│────▶│  main.py                  │────▶│ output/index.html │
└─────────────┘     │  · wizard de paths        │     │ session.json      │
                    │  · grava roteiro/pending  │     │ roteiro.md        │
                    │  · verify + snapshot      │     │ pending.md        │
                    └────────────┬──────────────┘     │ snapshots/        │
                                 │                    └──────────────────┘
                    ┌────────────▼──────────────┐
                    │  engine.py                │
                    │  · parse SQL/YAML         │
                    │  · compare + add_only     │
                    │  · snippet / order md     │
                    │  · graph · topo · lineage │
                    │  · macro · validate       │
                    │  · verify_card            │
                    └────────────┬──────────────┘
                                 │
                    ┌────────────▼──────────────┐
                    │  ui.py → HTML autocontido │
                    │  Assistente/Ordem/…/Macro │
                    └───────────────────────────┘
```

---

## O que não é

- Não substitui `dbt run` / `dbt test`
- Não valida BigQuery nem o SaaS
- Não aplica patch automático na base corporativa

É a camada que responde: **o que criar, o que só acrescer, o que não tocar — e como encaixa no grafo — o mais rápido possível sob lockdown de TI.**

---

## Estrutura do projeto

```text
main.py          CLI, segurança de I/O, verify, snapshot
engine.py        Parse, política, grafo, lineage, macro, snippets, verify
ui.py            Relatório HTML/CSS/JS (6 abas)
config.json      Paths e flags
run_demo.py      Demo contra demo_base/
demo_base/       Base dbt de exemplo
GUIA_DE_USO.md   Checklist rápido do operador
output/          Relatórios gerados (gitignored)
snapshots/       Histórico por card (gitignored)
workspace/       ZIP extraído do card (gitignored)
```

---

## Autor

Ferramenta prática para migração dbt sob restrições empresariais — e peça de portfólio: problema real, engenharia sob restrição, UX para velocidade do consultor, e cuidado absoluto com codebases de produção.

[github.com/J034ll4n/dbt-sentinel](https://github.com/J034ll4n/dbt-sentinel)
