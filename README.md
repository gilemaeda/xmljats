# xmljats

Plataforma para transformar artigos científicos (PDF hoje; DOCX na próxima fase) em XML JATS / SciELO PS validado no packtools, o validador oficial da SciELO.

| Pasta | O que é |
|---|---|
| `app/` | Site (FastAPI + Jinja2): validador, resultado, **revisar e editar** (corrige metadados e revalida), pacote .zip, revistas. Chama o motor. |
| `poc/` | Motor: extrator de PDF (`poc/extrator/`), gerador de XML (`xml_jats.py`), CLIs (`extrair.py`, `gerar_xml.py`). Ver `poc/README.md`. |
| `modelos/` | PDFs de teste, gabaritos manuais, XML oficial da SciELO, cadastro de revistas (`revistas.json`), análise dos modelos. |
| `especificacao_sistema_v1.md` | Especificação do sistema (arquitetura, regras, telas, roadmap). |
| `plano_implementacao_xml_jats_v3.md` | Plano original dos sócios. |
| `prototipo_ui.html` | Protótipo navegável das telas (referência visual). |

## Rodar localmente

```
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Abra http://127.0.0.1:8000. Sem `APP_SENHA` definida, o site não pede senha (uso local).

## Variáveis de ambiente

| Variável | Uso | Padrão |
|---|---|---|
| `APP_SENHA` | Senha única (HTTP Basic) para todas as páginas, menos `/saude`. Obrigatória em qualquer servidor exposto. | vazio = sem senha |
| `XMLJATS_DATA` | Pasta dos uploads e XML gerados (montar volume). | `./data` (no Docker: `/app/data`) |
| `MAX_UPLOAD_MB` | Tamanho máximo do PDF. | `50` |

## Deploy no Dokploy

1. Projeto **XML** → *Create Service* → **Application**, fonte **GitHub**, este repositório, branch `main`.
2. *Build type*: **Dockerfile** (arquivo `Dockerfile` na raiz). Porta do container: **8000**.
3. *Environment*: `APP_SENHA=<senha forte>`; opcionalmente `MAX_UPLOAD_MB`.
4. *Volumes* → *Volume Mount*: nome `xmljats-data`, caminho no container `/app/data`.
5. *Domains*: adicionar o domínio (ex.: `homol.xmljats.com` → porta 8000, HTTPS pelo Let's Encrypt do Dokploy).
6. *Deploy*. O healthcheck do container consulta `/saude`.

Os mesmos passos podem ser feitos pela API do Dokploy com `ops/dokploy.py` (lê URLs e tokens de `.env.deploy`, que fica fora do git). Foi assim que a homologação foi criada em 05/09/2026.

Ordem: homologação primeiro, produção depois. Banco de dados ainda não é necessário (o MVP grava em disco); quando entrar (contas, revistas, fila), criar um serviço Postgres **próprio** dentro do projeto XML, separado do Gestão Foco, para ter backup e isolamento independentes.

## Estado (setembro de 2026)

- Extrator de PDF passa nos seis elementos obrigatórios da SciELO nos seis PDFs de teste (placar em `poc/saida/placar.md` após rodar `poc/extrair.py`).
- XML gerado é válido no DTD JATS 1.1; o Schematron SPS reprova só onde o PDF não traz o dado (data de publicação com dia e mês; seção da revista), que o site mostra como bloqueante.
- Tela "Revisar e editar": o operador preenche o que o PDF não traz (datas do OJS, seção, ORCID, e-mail de correspondência, revista) e o XML é regenerado e revalidado. As edições ficam em `edicoes.json` como sobreposições à extração; o PDF e o modelo original não mudam. Com isso, o artigo da Direito e Práxis chega a "Pronto" (zero bloqueantes, Schematron ok) preenchendo só a data de publicação.
- Figuras: as imagens são extraídas do PDF, associadas às legendas, emitidas como `<fig>`/`<graphic>` com chamadas `xref` no texto, convertidas para TIFF no pacote com o nome `<base>-gfNN.tif` e mostradas como miniaturas no resultado.
- Pacote `.zip` com XML, PDF e imagens no nome-base da SPS.
- Falta: caminho DOCX, tabelas e equações, chamadas de notas no texto, campos completos de referência, contas e cadastro editável de revistas, fila com IA.
