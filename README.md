# DBT Sentinel

**Analisador de impacto para migrações dbt em ambientes restritos.**

Compara o pacote de entrega (ZIP de um card) com o projeto dbt corporativo e gera um assistente visual em HTML: o que criar, o que acrescentar, ordem de dependências, lineage e alertas de política — **sem gravar nada** no repositório dbt.

Feito para consultoria em VDIs travadas, onde `pip`, `npm`, Docker e plugins de IDE não estão disponíveis.

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Dependências](https://img.shields.io/badge/deps-somente%20stdlib-success)](#stack)
[![Licença](https://img.shields.io/badge/license-ver%20repositório-lightgrey)](#)

---

## Por que existe

Levar modelos dbt gerados em SaaS para um repositório corporativo grande é arriscado:

- O pacote mistura **arquivos novos** com **alterações em modelos que já existem**
- Nomes divergem (`stg_cliente` vs `stg_clientes`) e o time acaba duplicando objeto
- É preciso uma decisão clara: **criar / acrescentar / não mexer** — não um overwrite cego
- Muitos ambientes bloqueiam instalação de pacotes — a ferramenta precisa rodar só com **stdlib do Python**

O DBT Sentinel transforma essa comparação em checklist guiado + visão de lineage.

```text
ZIP do card (workspace)  +  dbt corporativo (base, somente leitura)
              ↓
        análise no engine
              ↓
   output/index.html  ·  session.json  ·  snapshot opcional
```

---

## Funcionalidades

| Capacidade | O que entrega |
|---|---|
| **Política aditiva** | Prioriza *criar arquivos novos* e *acrescentar só colunas/refs novas*; por padrão não reescreve SQL antigo |
| **Checklist de impacto** | Agrupado por ação (criar / acrescentar / revisar) e domínio de negócio |
| **Ordem de execução** | Ordem topológica: source → sample → staging → intermediate → dim/fato → aggregate |
| **Lineage interativo** | Faixas por camada com setas SVG que **se dividem** quando um modelo alimenta vários |
| **Detecção de rename** | Matching fuzzy + aliases para marcar “mesmo objeto, outro nome” |
| **Taxonomia** | Convenções de nome e prefixo de coluna (F / DIB / AGGR, `id_`, `nm_`, …) |
| **Sources** | Avisa se `source('…')` é usado sem declaração em `sources.yml` |
| **Verificação final** | Ao finalizar, relê a base e reporta criado / acrescentado / faltando / parcial |
| **I/O endurecido** | Escreve só em `output/` e `snapshots/`; proteção de path; HTML escapado |

---

## Stack

| Camada | Escolha | Motivo |
|---|---|---|
| Runtime | Python 3 (stdlib) | Sem `pip` / venv em VDI fechada |
| UI | HTML + CSS + JS em um arquivo | Abre no navegador; sem build |
| Parsing | Regex / YAML leve | Scan estrutural rápido de `.sql` / `.yml` |
| Persistência | Sessão JSON + snapshots | Rastro por card |

Zero dependência Python de terceiros. Zero bundler de frontend.

---

## Como rodar

```bash
git clone https://github.com/J034ll4n/dbt-sentinel.git
cd dbt-sentinel
```

1. Edite o `config.json` — aponte `base_project_path` para a raiz do dbt (somente leitura) e coloque o extrato do card em `workspace/`.
2. Execute:

```bash
py -3 main.py
```

3. Abra `output/index.html` e use as abas **Assistente**, **Ordem**, **Arquivos**, **Lineage** e **Alertas**.

### Demo incluída

O repositório traz uma base de exemplo em `demo_base/` e um script auxiliar:

```bash
py -3 run_demo.py
```

Depois abra `output/index.html` para ver criar/acrescentar e o fan-out do lineage sem precisar de um repo corporativo.

### Testes

```bash
py -3 tests.py
```

---

## Configuração (visão geral)

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
  "match_threshold": 0.62
}
```

| Campo | Função |
|---|---|
| `base_project_path` | Raiz do dbt corporativo (**nunca alterada**) |
| `base_include` | Pastas de domínio opcionais para delimitar o scan |
| `workspace_path` | Conteúdo extraído do card / ZIP |
| `add_only` | Política aditiva (criar + só acrescer o novo) |
| `enforce_taxonomy` | Heurísticas de nomenclatura / tipo |
| `card_id` | Rótulo do relatório HTML e do snapshot |

Checklist operacional do dia a dia: [`GUIA_DE_USO.md`](GUIA_DE_USO.md).

---

## Arquitetura

```text
┌─────────────┐     ┌──────────────────────────┐     ┌─────────────────┐
│  config.json│────▶│  main.py (CLI + segurança)│────▶│ output/index.html│
└─────────────┘     └────────────┬─────────────┘     │ session.json     │
                                 │                   │ snapshots/       │
                    ┌────────────▼─────────────┐     └─────────────────┘
                    │  engine.py               │
                    │  · scan e parse SQL/YAML │
                    │  · diff + buckets de política │
                    │  · grafo / topo / lineage│
                    │  · validate + verify     │
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │  ui.py → relatório HTML  │
                    │  autocontido             │
                    └──────────────────────────┘
```

---

## Princípios de design

1. **Somente leitura na árvore corporativa** — a análise nunca patcha modelos de produção.
2. **Política acima de diff barulhento** — mostra *o que acrescentar*, não cada linha de churn de SQL.
3. **Funciona offline sob lockdown de TI** — só stdlib + HTML estático.
4. **UX na velocidade do consultor** — abas para assistente, ordem, arquivos, lineage e alertas.
5. **Fechamento verificável** — confere a base de novo antes de gravar o snapshot do card.

---

## O que não é

- Não substitui `dbt run` / `dbt test`
- Não valida BigQuery nem SaaS
- Não faz merge automático no repositório corporativo

É uma **camada de decisão e impacto** antes de tocar no projeto real.

---

## Estrutura do projeto

```text
main.py          Entrada CLI, checagens de integridade, snapshot + verificação
engine.py        Parse, matching, política, grafo, lineage, validate/verify
ui.py            Gerador do relatório HTML/CSS/JS
tests.py         Suite de testes (stdlib)
config.json      Paths e flags de política
run_demo.py      Gera o relatório contra demo_base/
demo_base/       Árvore dbt de exemplo
GUIA_DE_USO.md   Checklist rápido do operador
```

---

## Autor

Ferramenta prática para migração dbt sob restrições empresariais — e também peça de portfólio: enquadramento do problema, engenharia sob restrição, UX para quem não é expert, e cuidado com codebases de produção.

Repositório: [github.com/J034ll4n/dbt-sentinel](https://github.com/J034ll4n/dbt-sentinel)
