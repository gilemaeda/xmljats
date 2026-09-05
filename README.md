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

Papéis: **administrador** (administra usuários, revistas, correio e configurações; não usa o validador, a home dele é o painel administrativo), **operador** (vê todos os documentos e valida) e **cliente** (vê apenas os próprios documentos; é o papel de quem se cadastra sozinho).

## E-mail (Resend)

Em **Configurações**, dentro da administração: chave da API do Resend, e-mail remetente de um domínio verificado, endereço público do site e o interruptor de confirmação de conta. A chave fica em `XMLJATS_DATA/config.json`, no volume do servidor, e nunca aparece inteira na tela.

Com isso ligado, quem se cadastra recebe o link de confirmação e só pode enviar arquivos depois de confirmar. O **Correio** guarda tudo em cinco caixas (entrada, saída, enviados, rascunhos, lixeira): sem configuração, a mensagem espera na caixa de saída com o motivo, em vez de sumir. Para registrar entrega e abertura, e para receber mensagens, cadastre no Resend o webhook `<site>/webhook/resend?k=<segredo>`; o segredo está no mesmo arquivo de configuração.

## Entrega à SciELO

Segue o **Guia de Entrega de Pacote XML para Publicação em SciELO** (dez/2024). A SciELO não publica API de depósito: o que existe é um FTP e um e-mail obrigatório — e o sistema faz os dois, na tela **Entrega à SciELO** de cada documento.

1. Chegar a "Pronto para entrega" (zero bloqueantes, validador oficial sem erro).
2. A tela confere o pacote contra o guia: é `.zip` (`.rar` não é aceito), os nomes não têm ponto extra, underline nem acento, o XML é válido no DTD e no Schematron, todos os arquivos citados pelo XML estão dentro e o relatório de validação vai junto.
3. Depósito no FTP: o `.zip` vai para a pasta `Entrega`; correções vão para `Correcao`. As credenciais são pedidas a `publicacao@scielo.org` e ficam em **Configurações**, gravadas só em `XMLJATS_DATA/config.json` (a senha nunca aparece inteira em tela).
4. Aviso por e-mail: depositar sozinho **não garante publicação**. Ao depositar daqui, o aviso para `publicacao@scielo.org` já fica como rascunho no correio, com periódico, ISSN, DOI e nome do pacote.

O que entra no pacote: XML em SciELO PS (e `sub-article` por tradução), PDF por idioma, imagens em `.tiff`/`.jpg`/`.png`, **tabelas, fórmulas e equações codificadas em MathML ou LaTeX** (imagem não é aceita), relatório do validador em `.html`, material suplementar e vídeos em `.mp4`. Em publicação contínua, o `article-id` do tipo `other` tem exatamente 5 dígitos e o título da seção precisa ser idêntico no PDF, na planilha de "Other" e no XML.

**Atestado de capacidade técnica** (o "selo"): reconhecimento para quem marca XML das coleções SciELO Brasil, SciELO Saúde Pública, RevEnf e Pepsic. Só pessoa jurídica, com CNPJ. O pedido é um e-mail a `publicacao@scielo.org` solicitando a amostra: 15 dias corridos para devolvê-la marcada com o relatório do validador, 15 para a SciELO avaliar, com possível segunda rodada de 15 + 15 (30 a 60 dias no total). Reprovada, nova amostra só depois de 6 meses. Em **Configurações**, o pedido é montado como rascunho no correio.

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
- Cadastro de revista pelo ISSN, em cascata por cinco bases (`app/issn.py`): **Portal do ISSN** (issn.org), **SciELO** (ArticleMeta), **DOAJ**, **Crossref** e **OpenAlex**. Cada campo registra de qual base veio. O acrônimo vem da SciELO (é ele que entra no nome dos arquivos), o título abreviado vem do Portal do ISSN (é a autoridade do registro e a única fonte pública do *abbreviated key title* que a SPS exige) e a licença vem do DOAJ. O dígito verificador é conferido antes de ir à rede, e quando a SciELO não acha pelo número informado o sistema tenta o ISSN irmão. A API oficial do ISSN (`api.issn.org`) é paga e responde 403 sem token, por isso lemos a ficha pública do portal; o CBISSN/IBICT não publica base consultável nem API de periódicos — o site dele serve para pedir um ISSN novo.
- No validador e no revisar, escolher "Detectar pelo ISSN" abre o campo do número: ele consulta as bases, mostra o que cada uma respondeu e cadastra a revista antes de validar.
- **Revisar e editar** mostra o arquivo original numa janela ao lado: a página vai renderizada em imagem com uma camada de texto por cima, do jeito que um leitor de PDF funciona. Selecionar um trecho e escolher o campo joga o texto no campo, sem digitar de novo. Abas: Original, Texto lido e Anexos.
- Tabelas, figuras, equações, quadros e diálogos aparecem na revisão e podem ser criados à mão: tabela com prévia da grade (colar do Word ou do Excel funciona), imagem por upload, quadro como `<boxed-text>` e diálogo como `<speech>`/`<speaker>`.
- Campos que a SciELO exige e o PDF não traz (`app/obrigatorios.py`) travam o salvar: cada aviso cita o pattern do Schematron oficial ou o item do guia que exige o campo. "Guardar rascunho" guarda o que foi digitado sem gerar XML, para não se perder trabalho no meio do preenchimento.
- Página **Como funciona**: o caminho do artigo, o que o motor extrai, quais etapas acontecem aqui e quais acontecem na SciELO, como entregar o pacote e o que ainda não é feito.
- Interface: menu na lateral ou no topo (a escolha fica no navegador), tema claro ou escuro e foto de perfil.
- Painel administrativo: filtro por conta e por data, validações por dia, quem está online agora, último acesso com IP e navegador, quantas validações cada conta fez, e edição de nome, e-mail, papel e senha de qualquer usuário.
- Cadastro de revistas tem área do conhecimento e estilo de referências esperado. A área não muda o XML (JATS é o mesmo para toda área), mas registra o que esperar do artigo; se o texto for lido num estilo diferente do cadastrado, o resultado avisa.
- Painel: documentos com filtros por revista, etapa e situação; a etapa do artigo no fluxo SciELO (Recebido → Em revisão → Pronto para entrega → Entregue à SciELO → Pré-QA → QA → QA finalizado → Publicado) é anotada à mão, com histórico de quem mudou e quando.
- Tabelas: quando a grade tem linhas, vira `<table>` de verdade no XML; quando as colunas não são reconstruíveis com segurança (tabelas só com filetes horizontais), a tabela vai como imagem, com aviso, para não entregar dado trocado.
- Equações: o guia de entrega da SciELO exige fórmula **codificada em MathML ou LaTeX**, não como imagem. O extrator recorta cada equação destacada e a mostra na revisão; ao lado do recorte há o campo de LaTeX, de onde sai o MathML (`latex2mathml`) que vai dentro de `<disp-formula>`. Equação que sairia só como imagem é bloqueante, com o motivo e a fonte da regra.
- Referências em três estilos: ABNT, APA e numérico (Vancouver `1.` e IEEE `[1]`). Nas quatro amostras da SciELO o número de referências bate exatamente com o XML oficial.
- Auditoria: `python ops/auditoria.py` reprocessa tudo, exercita o site inteiro e escreve `auditoria.md` com os números medidos.
- Entrega: conferência do pacote contra o guia, depósito no FTP da SciELO (`app/entrega.py`), aviso obrigatório montado no correio e pedido do atestado de capacidade técnica. `ops/test_entrega.py` sobe um servidor FTP local e deposita de verdade.
- **Entrada por DOCX** (`poc/extrator/docx.py`): o Word diz o que o PDF obriga a adivinhar. O título vem do estilo `Title` (ou do cabeçalho que precede o resumo), as seções vêm dos estilos `Heading1/2/3`, a tabela vem com as células separadas e nunca vira imagem, e a fórmula vem em **OMML**, que é convertido em **MathML** sem ninguém digitar LaTeX. O resto do front matter (autores, ORCID, afiliações, resumos, datas, licença, referências) usa as mesmas heurísticas do caminho PDF. Nos quatro DOCX de exemplo: 5, 7, 5 e 15 seções lidas pelos estilos, contra a heurística de posição do PDF.
- **Busca dentro do documento** no visualizador, sem acento e sem caixa, com navegação entre as ocorrências.
- **Completar pelo DOI** (`app/enriquece.py`): consulta o Crossref e traz volume, número, licença, resumo e o ORCID de cada autor, campo a campo, mostrando a origem. Nada é gravado sem confirmação. A data de publicação só é aproveitada quando vem com dia e mês.
- **Conferir o ORCID** no registro público do orcid.org: diz de quem é o número e avisa quando o nome não bate com o do autor.
- **CRediT**: a contribuição de cada autor sai em `<role content-type>` com os 13 termos que o Schematron da SciELO aceita.
- **Financiamento**: `funding-group` com `award-group` (fonte e número do processo) e `funding-statement`. A SciELO cruza os dados: todo número de processo precisa aparecer também numa nota `fn-type="financial-disclosure"`, e o sistema emite as duas coisas juntas ou nenhuma.
- **Pedir o que falta**: um botão monta no correio, para a revista ou para o autor, a lista das pendências com o motivo de cada uma. É o que mais custa tempo no dia a dia: ORCID, datas do OJS e seção do sumário nunca estão no arquivo.
- **Referências cruzadas com o Crossref: medido e descartado.** O casamento por texto devolve nota semelhante para uma referência real e para texto sem sentido, e o editor da revista piloto depositou as 13 referências do artigo sem nenhum DOI. Injetar um DOI errado no XML é pior do que não ter DOI, então isso não foi implementado.
- **Pré-visualização**: a aba "Como fica" mostra o artigo renderizado como a SciELO publica, gerado do nosso XML pelo `htmlgenerator` do packtools, com as imagens do documento no lugar dos nomes do pacote. É onde se vê de uma vez se figura, tabela e fórmula caíram na posição certa.
- **Texto de cada seção editável** no revisar: um parágrafo por bloco, separados por linha em branco. O que sai daí é o `<body>` do XML.
- **Anexos ancorados no texto**: tabela, imagem, equação, quadro e diálogo são inseridos pelos botões dentro da seção, e cada um tem os campos "vai na seção" e "antes do parágrafo". É assim que o item cai no lugar certo do XML, em vez de ficar solto no fim do corpo.
- **Vincular a revista já preenche o que é dela**: licença, seção do sumário e idioma vêm do cadastro (que a busca por ISSN preenche a partir do DOAJ), marcados na tela como "preenchido pelo cadastro" para serem confirmados. São dados da revista, não do artigo.
- **Declarações editoriais** no revisar, no lugar exato em que a SciELO as publica (conferido no XML oficial da revista piloto): agradecimentos em `<ack>`, contribuição dos autores e conflito de interesses em `author-notes` (`fn-type` `con` e `conflict`), editor responsável em `edited-by`, disponibilidade de dados como seção do back com `sec-type="data-availability"` e `specific-use`, uso de inteligência artificial em `fn-group` como `other`. Financiamento com número de processo sai em `financial-disclosure` cruzado com o `funding-group`; sem número de processo sai em `supported-by`, porque o validador da SciELO recusa `financial-disclosure` sem `award-id`.
- **Como citar este documento**: a citação do próprio artigo, montada dos metadados. Não é campo do XML (a SciELO gera no site), mas serve de prova: se a citação sai errada, algum metadado está errado.
- **Preenchimento automático em azul**: o que o sistema preencheu sozinho fica destacado, dizendo de onde veio (do texto do próprio arquivo, ou do cadastro da revista). Nada é gravado sem alguém salvar.
- **Cadastro de revista** ganhou editor-chefe, ORCID e currículo Lattes, e passou a ser aberto a qualquer conta. Editar e remover uma revista já cadastrada continuam sendo do administrador.
- **Conferência externa do XML (05/09/2026).** O Murillo mandou um XML nosso para uma análise independente. Dos oito pontos levantados, três eram defeito nosso e foram corrigidos: `(eds.)`/`(org.)` na abertura da referência viravam autor em vez de editor; a data de acesso saía sozinha quando o artigo trazia "Disponível em:" sem endereço; e o rodapé da revista ("Recebido: … Aceito: …") grudava na última referência. Um quarto ponto virou aviso: referência sem chamada no texto (R03). Dois pontos não procediam: `page-count` não é exigido (nenhum dos cinco XML publicados pela SciELO que usamos de gabarito o traz, e a regra do Schematron dispensa quando há `elocation-id`), e o "Uma outa linha" é erro do próprio PDF do artigo, não da extração.
- **`page-count` e os contadores**: a documentação da SPS (whatsnew-1.1) torna obrigatórios os cinco contadores, e o tagset manda **retirar** de `<counts>` o que o documento não tem. O sistema conta as páginas do arquivo enviado e emite `page-count`; com `fpage`/`lpage` usa a faixa, que é o que o Schematron confere. O total é editável na revisão. No DOCX a paginação é estimada pelo nosso layout, então ela não vira `page-count` sozinha: sai um aviso pedindo o número da paginação final. Contador zerado não sai. Registro honesto: nenhum dos cinco XML que a SciELO publicou e que usamos de gabarito traz `page-count`; seguimos a documentação, que é o que ela cobra.
- **Declarações em vários idiomas**: os blocos do fim do artigo são reconhecidos em português, inglês e espanhol ("Acknowledgement", "IA Statement", "Conflict of interest declaration", "Financiación", "Data availability", "How to cite"), com exclusões para o que só parece ("Editorial process dates" não é o editor, "Declaration of originality" não é contribuição).
- **Datas na caixa editorial**: "Recebido: 23/12/24" com ano de dois dígitos passou a ser lido, que era o motivo de as datas do fim do artigo não serem capturadas.
- **"Como citar" é editável** e, preenchido, sai como nota no fim do artigo, do jeito que muitas revistas imprimem.
- Falta: fila e processamento em lote, integração com o OJS (puxar metadados direto da submissão), validador público sem login, modelo DOCX distribuível para as revistas, custo por artigo medido.
