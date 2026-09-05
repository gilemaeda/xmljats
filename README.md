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

## Acesso

No primeiro acesso com `APP_SENHA` definida, entre com login `admin` e essa senha; depois crie as contas em Usuários. A partir do momento em que existem contas, `APP_SENHA` deixa de valer no navegador (continua valendo para scripts, que não pedem HTML): quem abrir o site vai para a tela de login. Sem `APP_SENHA` e sem usuários cadastrados (desenvolvimento local), o app abre sem login como `local`.

Papéis: **administrador** (administra usuários e revistas, vê o sistema inteiro), **operador** (vê todos os documentos) e **cliente** (vê apenas os próprios documentos; é o papel de quem se cadastra sozinho).

## Fuso horário

Todo o sistema grava e mostra horários no **horário de Brasília (UTC-3)**, mesmo com o servidor em UTC (`app/tempo.py`). Datas gravadas antes dessa mudança são convertidas na exibição.

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
- Notas de rodapé: as chamadas no corpo do texto viram `<xref ref-type="fn">` ligadas ao `fn-group`; o resultado lista cada nota com tipo, chamada e vínculo (autor, título).
- Referências: `element-citation` completo por heurística ABNT/APA (autores com iniciais, organizadores, autor institucional em `collab`, título e fonte, capítulo, edição, local e editora, volume, número, páginas, ano, DOI, link e data de acesso), com grau de confiança por referência mostrado no resultado. Contra o XML oficial da SciELO da Direito e Práxis, 69 de 76 campos iguais (`modelos/gabarito/rdp-referencias.json`).
- Interface em modo claro e escuro (seletor no topo, ou o tema do sistema), com contraste medido par a par: `python ops/audita_contraste.py` regenera `app/static/contraste.md` e falha se algum par ficar abaixo do mínimo WCAG.
- Contas: login por sessão (cookie assinado) e registro público, papéis admin, operador e cliente (o cliente só vê e abre os próprios documentos), tela Usuários (criar, trocar senha, papel, remover), tela Minha conta e área de administração separada com métricas. Com `APP_SENHA` definida e nenhum usuário, o primeiro acesso cria o admin `admin` com essa senha; `APP_SENHA` continua valendo como HTTP Basic para scripts. Usuários em `XMLJATS_DATA/usuarios.json` (senhas só como hash PBKDF2).
- Cadastro de revistas editável na tela (admin): acrônimo, ISSN com dígito verificador conferido, título, abreviado, editora, prefixo DOI, licença, modo de publicação, seção padrão, site e observações. Vive em `XMLJATS_DATA/revistas.json`, semeado de `modelos/revistas.json`.
- Painel administrativo: filtro por conta e por data, validações por dia, quem está online agora, último acesso com IP e navegador, quantas validações cada conta fez, e edição de nome, e-mail, papel e senha de qualquer usuário.
- Cadastro de revistas tem área do conhecimento e estilo de referências esperado. A área não muda o XML (JATS é o mesmo para toda área), mas registra o que esperar do artigo; se o texto for lido num estilo diferente do cadastrado, o resultado avisa.
- Painel: documentos com filtros por revista, etapa e situação; a etapa do artigo no fluxo SciELO (Recebido → Em revisão → Pronto para entrega → Entregue à SciELO → Pré-QA → QA → QA finalizado → Publicado) é anotada à mão, com histórico de quem mudou e quando.
- Tabelas: quando a grade tem linhas, vira `<table>` de verdade no XML; quando as colunas não são reconstruíveis com segurança (tabelas só com filetes horizontais), a tabela vai como imagem, com aviso, para não entregar dado trocado.
- Equações: PDF não guarda MathML, então cada equação destacada é recortada em alta resolução e emitida em `<disp-formula>` com `<graphic>`, `label` e `xref` no texto.
- Referências em três estilos: ABNT, APA e numérico (Vancouver `1.` e IEEE `[1]`). Nas quatro amostras da SciELO o número de referências bate exatamente com o XML oficial.
- Auditoria: `python ops/auditoria.py` reprocessa tudo, exercita o site inteiro e escreve `auditoria.md` com os números medidos.
- Falta: caminho DOCX, fila com IA, integração com OJS.
