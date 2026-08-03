# DBT Sentinel (Guardian)

Ferramenta de **orientação visual** para migrar pacotes SaaS/Jira para o repositório DBT corporativo.

Compara o ZIP do card com o projeto base, mostra o que **criar**, **atualizar**, o que é o **mesmo objeto com outro nome**, o **fluxo** e os **bloqueios** — em HTML simples.

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
2. [Qual caminho colar no config (LEIA ISTO)](#2-qual-caminho-colar-no-config-leia-isto)
3. [Guia passo a passo (para leigos)](#3-guia-passo-a-passo-para-leigos)
4. [O que aparece na tela](#4-o-que-aparece-na-tela)
5. [Configuração completa](#5-configuração-completa)
6. [Arquitetura](#6-arquitetura)
7. [Segurança](#7-segurança)
8. [Testes](#8-testes)
9. [Troubleshooting](#9-troubleshooting)
10. [O que NÃO faz](#10-o-que-não-faz)
11. [Arquivos do projeto](#11-arquivos-do-projeto)

---

## 1. Para que serve

1. Você recebe um **card no Jira** com um ZIP do fluxo SaaS DBT.
2. Precisa levar isso para o **repositório corporativo** (source → sample → stg → int → aggregate).
3. O Sentinel compara os dois lados e gera um assistente no navegador.

```text
ZIP do Jira (workspace/)  +  Projeto DBT (base)  →  output/index.html
```

---

## 2. Qual caminho colar no config (LEIA ISTO)

Na empresa o DBT costuma ter **uma pasta raiz** e **várias pastas de negócio** dentro (ex.: `AIS`, `ebody`, `Rodos`, `impress_code`, `schemas`…).

Você **não precisa** analisar tudo. O Sentinel deixa você **tunelar** só os negócios do card.

### Exemplo real da estrutura

```text
C:\projetos\dbt-corporativo\          ← ESTA é a pasta BASE (cole no config)
├── AIS\
│   └── models\staging\...
├── ebody\
│   └── models\staging\...
│   └── models\intermediate\...
├── Rodos\
│   └── models\...
├── impress_code\
├── schemas\
└── (outras pastas que você IGNORA)
```

### O que colar no `config.json`

| Campo | O que colocar | Exemplo |
|-------|----------------|---------|
| `base_project_path` | Caminho da **pasta raiz** do DBT (a que contém AIS, ebody, Rodos…) | `C:\\projetos\\dbt-corporativo` |
| `base_include` | **Só** os nomes das pastas de negócio deste card (lista) | `["ebody", "AIS", "Rodos"]` |

Exemplo pronto para copiar:

```json
{
  "base_project_path": "C:\\projetos\\dbt-corporativo",
  "base_include": ["ebody", "AIS", "Rodos"],
  "workspace_path": "C:\\Users\\zirn1\\novo\\workspace",
  "output_path": "C:\\Users\\zirn1\\novo\\output",
  "snapshots_path": "C:\\Users\\zirn1\\novo\\snapshots",
  "card_id": "CARD-100"
}
```

### Como descobrir o caminho certo no Windows

1. Abra o Explorer na pasta do DBT.
2. Clique na barra de endereço → copie o caminho completo.
3. No `config.json`, use barras duplas: `C:\\projetos\\dbt-corporativo`
4. Em `base_include`, coloque **apenas o nome** da pasta (sem `C:\` e sem `\models`):
   - Certo: `"ebody"`
   - Errado: `"C:\\projetos\\dbt-corporativo\\ebody"`
   - Errado: `"ebody\\models"`

### Duas formas de usar

**A) Recomendado — raiz + filtro (vários negócios no mesmo card)**

```json
"base_project_path": "C:\\projetos\\dbt-corporativo",
"base_include": ["ebody", "AIS", "Rodos"]
```

O Sentinel analisa **somente** essas pastas. O resto da árvore é ignorado.

**B) Um negócio só — apontar direto para a pasta**

```json
"base_project_path": "C:\\projetos\\dbt-corporativo\\ebody",
"base_include": []
```

Use quando o card for 100% de um único domínio.

### O que o terminal mostra

Ao rodar `py -3 main.py`, você verá algo assim:

```text
  Pasta base: C:\projetos\dbt-corporativo
  Pastas encontradas na base: AIS, ebody, Rodos, impress_code, schemas
  Analisando SOMENTE: ebody, AIS, Rodos
```

Se `base_include` estiver vazio e houver muitas pastas, o Sentinel avisa para você filtrar.

### Workspace (ZIP do Jira)

- Extraia o ZIP em `workspace\`
- Se o ZIP tiver as mesmas pastas (`ebody`, `AIS`…), o filtro `base_include` também se aplica ao workspace
- Se o ZIP vier “achatado” (só `models\...`), o Sentinel lê o workspace inteiro

---

## 3. Guia passo a passo (para leigos)

### Primeira vez

1. Confirme Python 3 na VDI (`py -3 --version`).
2. Abra `config.json`.
3. Cole `base_project_path` = pasta **raiz** do DBT.
4. Preencha `base_include` com as 2–3 pastas de negócio do seu time (ex.: `ebody`, `AIS`, `Rodos`).
5. Salve.

### Todo card

| # | O que fazer | Onde |
|---|-------------|------|
| 1 | `git pull` no DBT | VSCode do DBT |
| 2 | Baixar ZIP do Jira | Portal |
| 3 | Limpar `workspace\` | Explorer |
| 4 | Extrair ZIP **dentro** de `workspace\` | Explorer |
| 5 | Ajustar `card_id` (e `base_include` se o card for outro negócio) | `config.json` |
| 6 | Terminal na pasta do Sentinel | PowerShell |
| 7 | `py -3 main.py` | Terminal |
| 8 | Conferir no terminal quais pastas serão analisadas | Terminal |
| 9 | Abrir `output\index.html` | Navegador |
| 10 | Seguir Assistente (Passos 1→4) | HTML |
| 11 | Copiar/atualizar no DBT nos paths indicados (ex.: `ebody\models\...`) | VSCode |
| 12 | Validar SaaS + BigQuery | Ambientes |
| 13 | Responder `S` no terminal | Snapshot |
| 14 | Limpar `workspace\` | Explorer |

> Se `python` falhar, use sempre: **`py -3 main.py`**

### Regra de ouro

1. Sem bloqueios vermelhos.
2. Marque itens feitos na aba Arquivos.
3. Só finalize (`S`) depois de SaaS OK e BQ OK.

### Ordem do fluxo

```text
source (.yml) → sample (1%) → staging → intermediate → aggregate/mart
```

---

## 4. O que aparece na tela

| Aba | Função |
|-----|--------|
| **Assistente** | 4 passos: bloqueios → criar → atualizar/renomear → SaaS/BQ |
| **Arquivos** | Checklist com path completo (inclui pasta de negócio) |
| **Fluxo** | Cadeia source → … → final |
| **Alertas** | Bloqueios + histórico |

| Status | Significado |
|--------|-------------|
| Criar | Arquivo novo |
| Atualizar | Já existe e mudou (estrutura ou lógica SQL) |
| Nome diferente | Mesmo objeto, outro nome — **não duplicar** |
| Pronto | Igual (estrutura **e** corpo SQL) |

Cada card mostra **Negócio:** (ex.: `ebody`) quando a pasta existir no path.

---

## 5. Configuração completa

```json
{
  "base_project_path": "C:\\projetos\\dbt-corporativo",
  "base_include": ["ebody", "AIS", "Rodos"],
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
| `base_project_path` | Raiz do DBT corporativo |
| `base_include` | Lista de pastas de negócio a analisar (vazio = tudo) |
| `workspace_path` | Onde está o ZIP extraído |
| `output_path` / `snapshots_path` | Saídas do Sentinel (**fora** do DBT) |
| `card_id` | ID do card Jira |
| `detect_removed` | `false` para ZIP parcial |
| `match_threshold` | Sensibilidade de renomeação |
| `aliases` | Mapa nome-ZIP → nome-projeto |
| `allow_empty_base` | Emergência apenas |
| `require_git_integrity` | Exige git na base |

---

## 6. Arquitetura

```text
main.py     → CLI
engine.py   → scan (com filtro de pastas) → parse → compare → lineage → validate
ui.py       → HTML com 4 abas
```

---

## 7. Segurança

Somente leitura na base · escrita só em output/snapshots · path traversal bloqueado · XSS escapado · YAML `sources` ≠ `models` · rename exclusivo · base inválida falha fechado · `base_include` valida se a pasta existe.

---

## 8. Testes

```powershell
py -3 tests.py
```

---

## 9. Troubleshooting

| Problema | Solução |
|----------|---------|
| Analisou pastas demais | Preencha `base_include` |
| `base_include: pasta X não existe` | Nome errado — confira no Explorer (maiúsculas importam no Windows às vezes) |
| Paths sem `ebody\...` | Você apontou `base_project_path` direto para dentro de `ebody` — OK, ou use a raiz + include |
| Workspace vazio | Extraia o ZIP **dentro** de `workspace\` |
| `python` não encontrado | Use `py -3 main.py` |

---

## 10. O que NÃO faz

Não roda `dbt run` · não consulta BQ · não altera o repo DBT · não substitui validação SaaS/BQ.

---

## 11. Arquivos do projeto

```text
main.py, engine.py, ui.py, tests.py, config.json
README.md, GUIA_DE_USO.md
workspace/   output/   snapshots/
```

```powershell
py -3 main.py    # análise
py -3 tests.py   # testes
```
