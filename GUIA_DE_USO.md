# Guia de Uso — DBT Guardian

Ferramenta de orientação para migração de pacotes SaaS/Jira para o repositório DBT corporativo.  
**Somente leitura** no projeto DBT. **Sem pip, npm, Docker ou extensões.**

---

## 1. Pré-requisitos

- Python 3.8+ na VDI (já instalado — não precisa de pip)
- Caminho absoluto do repositório DBT corporativo
- ZIP do card Jira baixado

---

## 2. Configuração (primeira vez)

Edite `config.json` com o caminho absoluto do repositório DBT corporativo:

```json
{
  "base_project_path": "C:\\caminho\\real\\do\\seu\\dbt",
  "workspace_path": "C:\\Users\\zirn1\\novo\\workspace",
  "output_path": "C:\\Users\\zirn1\\novo\\output",
  "snapshots_path": "C:\\Users\\zirn1\\novo\\snapshots",
  "card_id": "CARD-100",
  "detect_removed": false,
  "match_threshold": 0.62,
  "aliases": {
    "stg_client": "stg_cliente"
  }
}
```

- `base_project_path` = projeto DBT corporativo (nunca será alterado)
- `workspace_path` = onde você extrai o ZIP do Jira
- `card_id` = número do card atual
- `detect_removed` = `false` por padrão (ZIP do Jira é parcial — não marca o resto do repo como “removido”)
- `aliases` = mapa nome-do-ZIP → nome-no-projeto (quando a IA muda o nome)
- `match_threshold` = sensibilidade do detector automático de renomeação (0.0–1.0)

Comando:

```powershell
cd C:\Users\zirn1\novo
py -3 main.py
```

Abra `output\index.html` e siga as 4 abas.

---

## 3. Fluxo diário

| Passo | Ação | Onde |
|-------|------|------|
| 1 | `git pull` no repo DBT | VSCode do projeto DBT |
| 2 | Baixar ZIP do card Jira | Portal Jira |
| 3 | Extrair o ZIP em `workspace/` | Pasta do Guardian |
| 4 | Atualizar `card_id` no `config.json` | `config.json` |
| 5 | Rodar `python main.py` | Terminal **do Guardian** (não no VSCode do DBT) |
| 6 | Abrir `output/index.html` | Navegador |
| 7 | Seguir o Assistente (4 passos) | Aba Assistente |
| 8 | Copiar/atualizar arquivos no repo | VSCode do DBT |
| 9 | Validar no SaaS e no BigQuery | Ambientes externos |
| 10 | Responder `S` no terminal | Snapshot do card |
| 11 | Limpar `workspace/` | Explorer |

---

## 4. As 4 abas (interface)

| Aba | Para quê |
|-----|----------|
| **Assistente** | Wizard em 4 passos: bloqueios → criar → atualizar → validar SaaS/BQ |
| **Arquivos** | Checklist completo: cada card = uma ação (Criar / Atualizar / Verificar) |
| **Fluxo** | Cadeia source → sample → stg → int → aggregate |
| **Alertas** | Bloqueios, atenções e histórico de cards |

### O que cada status significa

| Status | Na tela | O que fazer |
|--------|---------|-------------|
| NOVO | **Criar arquivo** | Copiar do `workspace/` para o caminho indicado no projeto |
| ALTERADO | **Atualizar arquivo** | O arquivo já existe — aplique as mudanças (veja “O que mudou”) |
| RENOMEADO | **Nome diferente** | A IA usou outro nome, mas é o mesmo objeto — **não crie duplicado** |
| REMOVIDO | **Verificar remoção** | Sumiu do pacote — confirme se é intencional e veja quem depende |
| IGUAL | **Pronto** | Nada a fazer |

### Quando a IA usa nomes diferentes

Três camadas de proteção:

1. **Aliases manuais** em `config.json` — quando você já sabe o mapeamento:
   ```json
   "aliases": {
     "stg_client": "stg_cliente",
     "int_customer": "int_cliente"
   }
   ```
2. **Similaridade de nome** — `stg_client` ≈ `stg_cliente` (stdlib `difflib`)
3. **Fingerprint estrutural** — mesmos `ref`/`source`/colunas ⇒ mesmo objeto mesmo com nome bem diferente

Se casar, o status fica **RENOMEADO** com confiança % e o path do arquivo **já existente** no projeto.  
Ajuste `match_threshold` (padrão `0.62`) se estiver com falsos positivos/negativos.

A detecção automática só compara modelos da **mesma camada** (staging com staging).  
Para mapear entre camadas ou casos difíceis, use `aliases` no `config.json`.

### Regra de ouro

> Não finalize o card com bloqueios vermelhos.  
> Marque cada item como feito na aba Arquivos.  
> Só responda **S** no terminal depois de SaaS OK e BQ OK.

---

## 5. Ordem sugerida de implementação

```
source (.yml) → sample (1% dos dados) → stg → int → aggregate / mart
```

O Assistente lista a **ordem sugerida** automaticamente (topo lógico do fluxo).  
Siga essa ordem para não quebrar `ref()` / `source()`.

---

## 6. Severidades

| Na tela | Significado | Ação |
|---------|-------------|------|
| **Bloqueio** (vermelho) | Vai quebrar compilação ou downstream | Resolver antes de continuar |
| **Atenção** (amarelo) | Risco / padrão / ciclo | Revisar |
| **Info** (cinza) | Dica (ex.: modelo similar já existe) | Conferir |
| **Seguro** (verde) | Boa prática (ex.: SAFE_CAST) | Ok |

---

## 7. Finalizar o card (snapshot)

Quando responder **S** no terminal:

- É criado `snapshots/CARD-XXX/manifest.json`
- O histórico aparece na aba **Alertas**
- Em seguida: limpe `workspace/` e mude o `card_id`

O terminal **bloqueia** finalização se ainda houver bloqueios CRITICAL.  
Se houver itens pendentes, pede confirmação extra.

---

## 8. Troubleshooting

| Problema | Solução |
|----------|---------|
| “base_project_path inválido” | Edite o caminho absoluto no `config.json` |
| Workspace vazio | Extraia o ZIP **dentro** de `workspace/`, não na raiz |
| Nenhum modelo detectado | Confira se há `.sql` / `.yml` no ZIP |
| HTML em branco | Abra `output/index.html` (dados já vêm embutidos) |
| “git status mudou” | O Guardian não deveria alterar o repo — reporte o caso |
| Ref inexistente falso | Confira se o nome do modelo é o mesmo do arquivo |

---

## 9. O que o Guardian NÃO faz

- Não roda `dbt run` / `dbt compile`
- Não consulta BigQuery
- Não altera arquivos no repositório DBT
- Não substitui a validação final no SaaS e no BQ
- Não instala bibliotecas (stdlib only)

## 10. Blindagem (segurança e integridade)

| Proteção | Detalhe |
|----------|---------|
| Somente leitura na base | `git status` antes/depois; aborta se mudar |
| Escrita restrita | Só grava em `output/` e `snapshots/` |
| Paths seguros | Bloqueia path traversal e symlinks fora da pasta |
| card_id limpo | Impede `../` em nomes de snapshot |
| XSS no HTML | JSON embutido com escape `\u003c` |
| Arquivos grandes | Ignora > 2 MB; limite de 20k arquivos |
| Config validada | Recusa output/snapshots dentro do projeto DBT |
| Aliases tipados | Objeto string→string obrigatório |
| Hash do corpo SQL | `IGUAL` exige mesma lógica (não só refs/colunas) |
| YAML scopes | `sources:` e `models:` separados (colunas ≠ sources) |
| Rename exclusivo | Um ZIP não “rouba” o mesmo modelo base duas vezes |
| Base obrigatória | Falha se `base_project_path` inválido (use `allow_empty_base` só em emergência) |

---

## 11. Arquivos do projeto

```
main.py      → execute este
engine.py    → análise (scan, compare, lineage, validação)
ui.py        → gera o HTML
config.json  → caminhos e card_id
workspace/   → ZIP do Jira
output/      → index.html + session.json
snapshots/   → histórico por card
```

Comando único:

```powershell
cd C:\Users\zirn1\novo
py -3 main.py
```

> Se `python` não funcionar na VDI, use `py -3 main.py`.
