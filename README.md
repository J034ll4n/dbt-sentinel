# DBT Sentinel

**Ferramenta de análise de impacto para migração de pacotes SaaS/Jira para o repositório dbt corporativo.**

Compara o ZIP do card com a base dbt e mostra, de forma objetiva, **o que já existe**, **o que precisa ser colocado** e **em que ordem aplicar** — sem reescrever o código principal e sem gravar nada no repositório corporativo.

Projetada para ambientes restritos (VDI): **apenas Python stdlib + HTML/CSS/JS**. Sem `pip`, sem `npm`, sem Docker.

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Dependências](https://img.shields.io/badge/deps-somente%20stdlib-0f766e)](#stack-e-restrições)
[![Política](https://img.shields.io/badge/política-somente%20adições-0f766e)](#o-que-ele-resolve)

Repositório: [github.com/J034ll4n/dbt-sentinel](https://github.com/J034ll4n/dbt-sentinel)

---

## O que ele resolve

No fluxo típico de consultoria, o profissional recebe um **card no Jira** com um ZIP gerado por SaaS/IA e precisa levar esse conteúdo para o **dbt corporativo**.

O problema não é “abrir o ZIP”. O problema é:

1. **O pacote mistura arquivo novo com alteração em arquivo que já existe**  
   Colar o ZIP inteiro por cima da base **reescreve produção** e introduz regressão.

2. **Falta um diff confiável do que é realmente novo**  
   O consultor precisa olhar o arquivo principal e responder: *o que já está lá?* *o que eu preciso acrescentar?*

3. **Há dependências e ordem de aplicação**  
   Criar/acrescentar fora de ordem quebra compilação (`ref`, staging → mart, etc.).

4. **O ambiente de trabalho é limitado**  
   Em VDI corporativa muitas vezes não há como instalar bibliotecas ou montar front-end moderno.

**DBT Sentinel resolve isso** transformando a comparação card × base em um assistente visual de decisão: criar, acrescer só o novo, ou não mexer — com snippets prontos para copiar e verificação no fechamento do card.

```text
Card Jira (ZIP)     Projeto dbt corporativo
   workspace/    +        base (read-only)
              \          /
               \        /
            DBT Sentinel
                   |
                   v
     output/index.html  ·  roteiro.md  ·  pending.md
```

---

## O que ele faz

### Análise (somente leitura na base)

- Lê o projeto dbt (`base_project_path`) e o conteúdo do card (`workspace/`)
- Extrai refs, sources, colunas e estrutura dos modelos (`.sql` / `.yml`)
- Classifica cada arquivo:
  - **Criar** — não existe na base
  - **Acrescentar** — existe na base; o card trouxe itens novos (colunas, refs, …)
  - **Não alterar / Revisar** — mudança no ZIP que **não** deve ser aplicada no principal
- Monta grafo de dependências e ordem topológica (source → sample → staging → intermediate → dim/fato → aggregate)

### Interface (`output/index.html`)

| Aba | Função |
|---|---|
| **Diff** | Núcleo do trabalho: no arquivo principal, **o que já existe** × **o que colocar** |
| **Ordem** | Sequência de execução + **snippets copiáveis** (só adições) + roteiro Markdown |
| **Fluxo** | Lineage do card (quem alimenta quem; setas que se dividem) |
| **Zoom** | Um arquivo no contexto da base: encaixe, itens novos, impacto a jusante |
| **Resumo** | Visão geral do card e próximos passos |
| **Avisos** | Bloqueios, taxonomia, sources não declarados, política |

### Fechamento do card (CLI)

Ao confirmar no terminal (`S`):

- Re-lê a base e lista **só o que ainda falta** (criar / acrescer)
- Gera `pending.md` para colar no Jira
- Grava snapshot do card em `snapshots/` (auditoria)

### O que ele **não** faz

- Não altera o repositório dbt corporativo
- Não executa `dbt run` / `dbt test`
- Não valida BigQuery nem o SaaS no seu lugar

Ele acelera a **decisão e a aplicação manual segura**; a validação final continua sendo sua (dbt / SaaS / BQ).

---

## Fluxo de uso

1. Receber o card no Jira e extrair o ZIP em `workspace/`
2. Configurar `config.json` (caminho da base dbt + `card_id`)
3. Rodar:

```bash
py -3 main.py
```

4. Abrir `output/index.html` → aba **Diff**
5. Em **Ordem**, copiar o snippet e acrescentar **apenas as diferenças** no arquivo principal
6. Rodar dbt / validar SaaS + BQ
7. No terminal, responder `S` para verificação final e snapshot

Checklist operacional curto: [`GUIA_DE_USO.md`](GUIA_DE_USO.md).

---

## Política aditiva (regra de ouro)

| Situação | Comportamento do Sentinel |
|---|---|
| Arquivo novo | Orienta a **criar** a partir do workspace |
| Arquivo já na base | Orienta a **acrescentar só itens novos** |
| ZIP mudou SQL antigo / removeu algo | Marca **atenção** — **não** sugere reescrever o principal |
| Base corporativa | **Somente leitura** |

Controlado por `add_only: true` (padrão).

---

## Configuração

```json
{
  "base_project_path": "C:\\caminho\\para\\dbt\\corporativo",
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

| Campo | Descrição |
|---|---|
| `base_project_path` | Raiz do dbt corporativo (**nunca modificada**) |
| `base_include` | Pastas de negócio a analisar (opcional; reduz escopo) |
| `workspace_path` | Pasta do ZIP / card |
| `add_only` | Política de só adicionar o novo |
| `enforce_taxonomy` | Alertas de nomenclatura / tipos |
| `card_id` | Identificador do relatório e do snapshot |

---

## Stack e restrições

| Camada | Tecnologia | Motivo |
|---|---|---|
| Runtime | Python 3 (stdlib) | VDI sem instalação de pacotes |
| UI | HTML + CSS + JS em um arquivo | Sem build, abre no navegador |
| Persistência | JSON + Markdown | Sessão, roteiro, pending, snapshots |

Escrita permitida apenas em `output/` e `snapshots/`. Paths protegidos; HTML escapado.

---

## Estrutura do projeto

```text
main.py          CLI, verificação final, snapshot
engine.py        Parse, diff aditivo, grafo, lineage, snippets
ui.py            Relatório HTML (Diff / Ordem / Fluxo / Zoom)
config.json      Paths e política
GUIA_DE_USO.md   Checklist rápido do operador
workspace/       ZIP do card (não versionado)
output/          Relatórios gerados (não versionado)
snapshots/       Histórico por card (não versionado)
```

---

## Autor

Construído para o dia a dia de migração dbt sob restrição empresarial: menos tempo reescrevendo a base, mais tempo aplicando só o que o card realmente exige.

[github.com/J034ll4n/dbt-sentinel](https://github.com/J034ll4n/dbt-sentinel)
