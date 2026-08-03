# DBT Sentinel (Guardian)

Ferramenta de **orientação visual** para migrar pacotes SaaS/Jira para o repositório DBT corporativo.

Compara o que veio no ZIP com o que já existe no projeto, mostra o que **criar**, o que **atualizar**, o que é o **mesmo objeto com outro nome**, o **fluxo de dados** e os **bloqueios** — em uma página HTML simples.

| | |
|---|---|
| **Ambiente** | VDI restrita (sem pip, npm, Docker, plugins) |
| **Stack** | Python stdlib + HTML/CSS/JS puro |
| **Sobre o DBT** | **Somente leitura** — não altera o repositório corporativo |
| **Como rodar** | `py -3 main.py` |

Repositório: https://github.com/J034ll4n/dbt-sentinel

---

## Índice

1. [Para que serve](#1-para-que-serve)
2. [Guia passo a passo (para leigos)](#2-guia-passo-a-passo-para-leigos)
3. [O que aparece na tela](#3-o-que-aparece-na-tela)
4. [Configuração (`config.json`)](#4-configuração-configjson)
5. [Arquitetura](#5-arquitetura)
6. [Segurança e blindagem](#6-segurança-e-blindagem)
7. [Testes](#7-testes)
8. [Troubleshooting](#8-troubleshooting)
9. [O que a ferramenta NÃO faz](#9-o-que-a-ferramenta-não-faz)
10. [Estrutura de arquivos](#10-estrutura-de-arquivos)

---

## 1. Para que serve
Auxilia a migração de SaaS para DBT em ambientes restritos 

1. Você recebe um **card no Jira** com um ZIP do fluxo SaaS DBT.
2. Precisa levar isso para o **repositório corporativo** (source → sample → stg → int → aggregate).
3. A IDE fica confusa; nomes mudam; dá medo de quebrar o que já existe.

O **DBT Sentinel** roda **fora** do VSCode do DBT, lê os dois lados e gera um **assistente no navegador** dizendo exatamente o que fazer.

```
ZIP do Jira (workspace/)  +  Projeto DBT (base)  →  output/index.html
```

---

## 2. Guia passo a passo (para leigos)

Siga nesta ordem. Não precisa saber programar.

### Primeira vez 

1. Instale / confirme **Python 3** na VDI (não precisa de `pip`).
2. Baixe ou clone este projeto (ex.: `C:\Users\zirn1\novo` ou a pasta do Sentinel).
3. Abra o arquivo `config.json` no Bloco de Notas.
4. Troque `base_project_path` pelo caminho **real** da pasta do seu DBT corporativo, por exemplo:
   ```text
   C:\projetos\dbt-corporativo
   ```
5. Salve o arquivo.

### Todo card (rotina diária)

| # | O que fazer | Onde |
|---|-------------|------|
| 1 | Atualize o projeto DBT (`git pull`) | VSCode do DBT |
| 2 | Baixe o ZIP do card no Jira | Portal Jira |
| 3 | **Apague** o conteúdo antigo de `workspace\` (se houver) | Pasta do Sentinel |
| 4 | Extraia o ZIP **dentro** de `workspace\` | Explorer |
| 5 | No `config.json`, mude `card_id` (ex.: `CARD-205`) | Bloco de Notas |
| 6 | Abra o terminal **na pasta do Sentinel** (não no DBT) | PowerShell |
| 7 | Rode: `py -3 main.py` | Terminal |
| 8 | O navegador abre `output\index.html` | Chrome / Edge |
| 9 | Na aba **Assistente**, faça o Passo 1 → 2 → 3 → 4 | Navegador |
| 10 | Copie/atualize os arquivos no projeto DBT conforme os cards | VSCode do DBT |
| 11 | Valide no **SaaS** e no **BigQuery** | Ambientes externos |
| 12 | Volte ao terminal e digite `S` para gravar o histórico do card | Terminal |
| 13 | Limpe `workspace\` de novo | Explorer |

> Se o comando `python` não funcionar, use sempre: **`py -3 main.py`**

### Como saber se está certo?

- **Vermelho (Bloqueio)** → resolva antes de continuar (ex.: referência a modelo que não existe).
- **Roxo (Nome diferente)** → **não crie arquivo novo**; atualize o que já existe no projeto.
- **Azul (Criar)** → copie do `workspace` para o caminho indicado.
- **Amarelo (Atualizar)** → o arquivo já existe; aplique as mudanças listadas.
- **Verde (Pronto)** → nada a fazer.

### Ordem de implementação (importante)

```text
source (.yml)  →  sample (1% dos dados)  →  staging  →  intermediate  →  aggregate/mart
```

O Assistente sugere essa ordem automaticamente. Siga para não quebrar `ref()` / `source()`.

### Regra de ouro

1. Não finalize o card com **bloqueios vermelhos**.
2. Marque cada item como feito na aba **Arquivos**.
3. Só responda **S** no terminal depois de **SaaS OK** e **BQ OK**.

---

## 3. O que aparece na tela

Uma única página (`output/index.html`) com **4 abas**:

| Aba | Para quê |
|-----|----------|
| **Assistente** | Wizard em 4 passos: bloqueios → criar → atualizar/renomear → validar SaaS/BQ |
| **Arquivos** | Checklist: um card por arquivo, com caminho e “o que mudou” |
| **Fluxo** | Cadeia visual source → sample → stg → int → final |
| **Alertas** | Bloqueios, atenções e histórico de cards (snapshots) |

### Status dos arquivos

| Status | Na tela | Ação |
|--------|---------|------|
| `NOVO` | Criar arquivo | Copiar do workspace para o path indicado |
| `ALTERADO` | Atualizar arquivo | Merge manual guiado pelo diff |
| `RENOMEADO` | Nome diferente | Mesmo objeto, outro nome — **não duplicar** |
| `REMOVIDO` | Verificar remoção | Só aparece se `detect_removed: true` |
| `IGUAL` | Pronto | Já sincronizado (estrutura **e** lógica iguais) |

### Quando a IA muda o nome do arquivo

Três camadas:

1. **Aliases** no `config.json` (você fixa o mapa).
2. **Nome parecido** (`stg_client` ≈ `stg_cliente`).
3. **Estrutura parecida** (mesmos refs/sources/colunas), só na **mesma camada**.

Se casar → status **RENOMEADO**, com % de confiança e o caminho do arquivo **já existente**.

---

## 4. Configuração (`config.json`)

```json
{
  "base_project_path": "C:\\caminho\\para\\dbt\\corporativo",
  "workspace_path": "C:\\Users\\zirn1\\novo\\workspace",
  "output_path": "C:\\Users\\zirn1\\novo\\output",
  "snapshots_path": "C:\\Users\\zirn1\\novo\\snapshots",
  "card_id": "CARD-100",
  "detect_removed": false,
  "match_threshold": 0.62,
  "aliases": {
    "stg_client": "stg_cliente"
  },
  "allow_empty_base": false,
  "require_git_integrity": false
}
```

| Campo | Significado |
|-------|-------------|
| `base_project_path` | Pasta do DBT corporativo (**somente leitura**) |
| `workspace_path` | Onde você extrai o ZIP do Jira |
| `output_path` | Onde saem `index.html` e `session.json` |
| `snapshots_path` | Histórico por card |
| `card_id` | Identificador do card (ex.: `CARD-205`) |
| `detect_removed` | `false` = ZIP parcial (padrão). `true` = avisa o que sumiu |
| `match_threshold` | Sensibilidade do detector de renomeação (0.0–1.0) |
| `aliases` | Mapa `nome_no_ZIP` → `nome_no_projeto` |
| `allow_empty_base` | Só em emergência — resultados **não confiáveis** |
| `require_git_integrity` | Se `true`, exige que a base seja um repo git |

**Importante:** `output_path`, `snapshots_path` e `workspace_path` **não podem** ficar dentro do projeto DBT. O Sentinel recusa e encerra.

---

## 5. Arquitetura

Código mínimo, 3 arquivos Python:

```text
main.py     → CLI (config, git check, snapshot, abre HTML)
engine.py   → scan → parse → compare → grafo → validação
ui.py       → gera output/index.html (4 abas, CSS/JS inline)
```

Fluxo interno:

```text
Discovery (scan) → Parser (SQL/YAML) → Compare (hash estrutural + corpo)
                 → Lineage (grafo) → Validate (alertas) → HTML
```

- Modelos em memória = `dict` (sem classes pesadas).
- Diff por **hash estrutural** (refs, sources, joins, casts, columns) **+ hash do corpo SQL** (evita “IGUAL” falso quando só o `WHERE` mudou).
- Lineage em grafo puro Python (dependências, ciclos, impacto downstream).

---

## 6. Segurança e blindagem

| Proteção | Detalhe |
|----------|---------|
| Somente leitura na base | Nunca grava no DBT; checa `git status` antes/depois |
| Escrita restrita | Só `output/` e `snapshots/` |
| Path traversal | `card_id` sanitizado; paths validados dentro da pasta |
| Symlinks | Ignorados no scan |
| XSS | JSON no HTML com escape `\u003c` |
| Arquivos grandes | Ignora > 2 MB; teto de 20k arquivos |
| YAML correto | `sources:` separado de `models:` (coluna ≠ source) |
| Rename exclusivo | Um modelo base não é reivindicado duas vezes |
| Base obrigatória | Sem base válida → erro (salvo `allow_empty_base`) |

---

## 7. Testes

Sem dependências externas:

```powershell
cd C:\Users\zirn1\novo
py -3 tests.py
```

Cobre: parse SQL/YAML, hash, ciclos, lineage, rename/alias, XSS, path safety, diff de corpo SQL, atribuição exclusiva de nomes.

---

## 8. Troubleshooting

| Problema | Solução |
|----------|---------|
| `base_project_path inválido` | Coloque o caminho absoluto real no `config.json` |
| Workspace vazio | Extraia o ZIP **dentro** de `workspace\`, não na raiz do Sentinel |
| Nenhum modelo detectado | Confira se o ZIP tem `.sql` / `.yml` |
| HTML em branco | Abra `output\index.html` (dados já vêm embutidos) |
| `git status mudou` | Não deveria acontecer — reporte; a ferramenta não grava na base |
| Muitos “Nome diferente” errados | Suba `match_threshold` (ex.: `0.75`) ou use `aliases` |
| Poucos renames detectados | Baixe um pouco o threshold ou cadastre `aliases` |
| `python` não encontrado | Use `py -3 main.py` |

---

## 9. O que a ferramenta NÃO faz

- Não executa `dbt run` / `dbt compile`
- Não consulta BigQuery
- Não altera arquivos no repositório DBT
- Não substitui a validação final no SaaS e no BQ
- Não instala pacotes (`pip` / `npm` proibidos)

Ela é um **orientador**. Você ainda valida SaaS + BQ no final.

---

## 10. Estrutura de arquivos

```text
dbt-sentinel/
├── main.py           # Execute este
├── engine.py         # Motor de análise
├── ui.py             # Gerador do HTML
├── config.json       # Seus caminhos e card_id
├── tests.py          # Suite de testes
├── README.md         # Este documento
├── GUIA_DE_USO.md    # Resumo rápido (apontando para cá)
├── .gitignore
├── workspace/        # Cole o ZIP do Jira aqui
├── output/           # index.html + session.json
└── snapshots/        # Histórico CARD-xxx/manifest.json
```

### Comandos úteis

```powershell
# Análise do card
py -3 main.py

# Testes
py -3 tests.py
```

---

## Licença / uso interno

Uso interno de consultoria / engenharia de dados. Adequado a VDI corporativa restritiva.
