# Guia rápido — DBT Sentinel

> Documentação completa (passo a passo para leigos, config, segurança, testes):  
> **[README.md](README.md)**

## Em 30 segundos

1. Edite `base_project_path` e `card_id` no `config.json`
2. Extraia o ZIP do Jira em `workspace/`
3. Rode: `py -3 main.py`
4. Abra `output/index.html` e siga o **Assistente**
5. Valide SaaS + BQ → responda `S` no terminal → limpe `workspace/`

## Status na tela

| Cor / status | Ação |
|--------------|------|
| Bloqueio (vermelho) | Resolver primeiro |
| Criar (azul) | Copiar arquivo novo |
| Atualizar (amarelo) | Editar o que já existe |
| Nome diferente (roxo) | **Não duplicar** — atualize o arquivo do projeto |
| Pronto (verde) | Nada a fazer |

## Ordem do fluxo

```text
source → sample (1%) → stg → int → aggregate/mart
```
