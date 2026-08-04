# DBT Sentinel

**Diff do card contra a base: o que já existe × o que você precisa colocar — sem reescrever o principal.**

Para consultoria em VDI (só Python stdlib + HTML). Base dbt = somente leitura.

---

## Seu fluxo

1. Card no Jira → ZIP no `workspace/`
2. Configure `config.json` (`base_project_path` = raiz do dbt corporativo)
3. `py -3 main.py`
4. Abra `output/index.html` → aba **Diff** (existe × colocar)
5. **Ordem** → copie o snippet e acrescente só as diferenças
6. Rode o **dbt** / SaaS / BQ → no terminal `S` para fechar

---

## Abas

| Aba | Uso |
|---|---|
| **Diff** | Existe × colocar (núcleo do trabalho) |
| **Ordem** | Sequência + snippets copiáveis |
| **Fluxo** | Dependências do card |
| **Zoom** | Um arquivo no grafo da base |
| **Resumo** / **Avisos** | Visão geral e alertas |

---

## Stack

Python 3 stdlib · HTML/CSS/JS · zero `pip`.

```json
{
  "base_project_path": "C:\\\\caminho\\\\para\\\\dbt\\\\corporativo",
  "base_include": ["dominio"],
  "workspace_path": "workspace",
  "output_path": "output",
  "card_id": "CARD-123",
  "add_only": true
}
```

Guia: [`GUIA_DE_USO.md`](GUIA_DE_USO.md).

[github.com/J034ll4n/dbt-sentinel](https://github.com/J034ll4n/dbt-sentinel)
