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

Auxilia a migração de SaaS para DBT em ambientes restritos.

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

### O que o terminal mostra

```text
  Pasta base: C:\projetos\dbt-corporativo
  Pastas encontradas na base: AIS, ebody, Rodos, impress_code, schemas
  Analisando SOMENTE: ebody, AIS, Rodos
```

### Workspace (ZIP do Jira)

- Extraia o ZIP em `workspace\`
- Se o ZIP tiver as mesmas pastas (`ebody`, `AIS`…), o filtro `base_include` também se aplica
- Se o ZIP vier “achatado” (só `models\...`), o Sentinel lê o workspace inteiro

---

## 3. Guia passo a passo (para leigos)

### Primeira vez

1. Confirme Python 3 (`py -3 --version`).
2. Abra `config.json`.
3. Cole `base_project_path` = pasta **raiz** do DBT.
4. Preencha `base_include` com as pastas do card (ex.: `ebody`, `AIS`, `Rodos`).
5. Salve.

### Todo card

| # | O que fazer | Onde |
|---|-------------|------|
| 1 | `git pull` no DBT | VSCode do DBT |
| 2 | Baixar ZIP do Jira | Portal |
| 3 | Limpar `workspace\` | Explorer |
| 4 | Extrair ZIP **dentro** de `workspace\` | Explorer |
| 5 | Ajustar `card_id` e `base_include` | `config.json` |
| 6 | `py -3 main.py` | Terminal do Sentinel |
| 7 | Conferir “Analisando SOMENTE: …” | Terminal |
| 8 | Abrir `output\index.html` | Navegador |
| 9 | Seguir Assistente (Passos 1→4) | HTML |
| 10 | Copiar/atualizar no DBT | VSCode |
| 11 | Validar SaaS + BigQuery | Ambientes |
| 12 | Responder `S` no terminal | Snapshot |
| 13 | Limpar `workspace\` | Explorer |

### Regra de ouro

Sem bloqueios vermelhos → marcar feitos → SaaS OK + BQ OK → só então `S`.

### Ordem do fluxo

```text
source → sample (1%) → staging → intermediate → aggregate/mart
```

---

## 4. O que aparece na tela

| Aba | Função |
|-----|--------|
| **Assistente** | Bloqueios → criar → atualizar/renomear → SaaS/BQ |
| **Arquivos** | Checklist com path (inclui pasta de negócio) |
| **Fluxo** | Cadeia source → final |
| **Alertas** | Bloqueios + histórico |

| Status | Significado |
|--------|-------------|
| Criar | Arquivo novo |
| Atualizar | Já existe e mudou |
| Nome diferente | Mesmo objeto, outro nome — **não duplicar** |
| Pronto | Igual (estrutura e SQL) |

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
  "aliases": {},
  "allow_empty_base": false,
  "require_git_integrity": false
}
```

| Campo | Significado |
|-------|-------------|
| `base_project_path` | Raiz do DBT |
| `base_include` | Pastas de negócio a analisar (vazio = tudo) |
| `workspace_path` | ZIP extraído |
| `output_path` / `snapshots_path` | Saídas (**fora** do DBT) |
| `card_id` | ID do card |
| `detect_removed` | `false` para ZIP parcial |
| `match_threshold` | Sensibilidade de renomeação |
| `aliases` | nome-ZIP → nome-projeto |

---

## 6. Arquitetura

```text
main.py / engine.py / ui.py — stdlib only
```

---

## 7. Segurança

Somente leitura na base · escrita só em output/snapshots · paths seguros · XSS escapado · `base_include` validado.

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
| Pasta X não existe | Confira o nome no Explorer |
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
