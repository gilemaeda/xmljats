# Auditoria do xmljats — 2026-09-05

Gerada por `python ops/auditoria.py` (app 0.13.0). Cada número vem de uma medição desta rodada: os PDFs foram reprocessados, os XML gerados e validados no packtools, e o site exercitado ponta a ponta.

## 1. Resumo

- **Site:** 83 de 83 verificações passaram.
- **Contraste (WCAG):** 0 par(es) abaixo do mínimo nos dois temas.
- **XML:** 10 de 10 arquivos válidos no DTD JATS.
- **Schematron SPS:** 0 de 10 sem erros. O que sobra está na seção 5: são dados que o PDF não traz (dia e mês da publicação, seção da revista, resumo em revistas cujo layout ainda não é lido), todos já sinalizados como bloqueante na tela de revisão.

## 2. Placar dos seis elementos obrigatórios (PDFs com gabarito conferido à mão)

| Arquivo | Seção | Título | Autor + ORCID | Afiliação | Citações | Referências | Extras |
|---|---|---|---|---|---|---|---|
| article.segmented | n/a | **sim** | **sim** | **sim** | **sim** | **sim** | DOI ok; recebido ok; aceito ok; resumos ok; idioma ok |
| 1222+-+VF (5) | n/a | **sim** | **sim** | **sim** | **sim** | **sim** | DOI ok; resumos ok; idioma ok |
| 1227_VF+-+Simioni (3) | n/a | **sim** | **sim** | **sim** | **sim** | **sim** | DOI ok; resumos ok; idioma ok |
| Direito e Praxis | **sim** | **sim** | **sim** | **sim** | **sim** | **sim** | DOI ok; recebido ok; aceito ok; resumos ok; idioma ok |
| document | **sim** | **sim** | **sim** | **sim** | **sim** | **sim** | DOI ok; recebido ok; aceito ok; resumos ok; idioma ok |
| RBDPP_2026_v12n2_1498 | **sim** | **sim** | **sim** | **sim** | **sim** | **sim** | DOI ok; recebido ok; aceito ok; resumos ok; idioma ok |

## 3. O que o motor extraiu de cada PDF

| Arquivo | Págs | Autores | ORCID | Afil. | Resumos | Seções | Notas | Figs | Tabelas (com grade) | Equações | Refs (estilo) | DTD | Erros packtools | Campos iguais ao XML oficial |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1222+-+VF (5) | 16 | 1 | 1 | 1 | 3 | 5 | 2 | 0 | 0 (0) | 0 | 20 (ABNT) | ok | 2 | — |
| 1227_VF+-+Simioni (3) | 23 | 1 | 1 | 1 | 3 | 5 | 4 | 8 | 0 (0) | 0 | 34 (ABNT) | ok | 2 | — |
| Direito e Praxis | 28 | 1 | 1 | 1 | 2 | 7 | 4 | 0 | 0 (0) | 0 | 13 (ABNT) | ok | 2 | 22/24 |
| RBDPP_2026_v12n2_1498 | 30 | 1 | 1 | 1 | 3 | 6 | 6 | 0 | 0 (0) | 0 | 17 (APA) | ok | 2 | — |
| article.segmented | 28 | 3 | 3 | 3 | 3 | 6 | 9 | 0 | 0 (0) | 0 | 27 (ABNT) | ok | 3 | — |
| document | 14 | 2 | 2 | 2 | 3 | 15 | 11 | 0 | 0 (0) | 0 | 48 (ABNT) | ok | 2 | — |
| rbef-equacoes | 13 | 1 | 0 | 1 | 0 | 6 | 1 | 4 | 0 (0) | 38 | 30 (numérico (Vancouver)) | ok | 4 | 12/24 |
| rbef-tabelas-equacoes | 14 | 0 | 0 | 0 | 0 | 11 | 1 | 18 | 5 (4) | 31 | 28 (numérico (Vancouver)) | ok | 5 | 11/24 |
| rsp-tabelas | 12 | 3 | 0 | 1 | 1 | 4 | 4 | 0 | 5 (5) | 0 | 40 (numérico (Vancouver)) | ok | 2 | 12/24 |
| rsp-tabelas2 | 10 | 2 | 0 | 1 | 1 | 9 | 4 | 0 | 4 (4) | 0 | 30 (numérico (Vancouver)) | ok | 2 | 10/24 |

## 4. Verificações do site

- ok — página protegida redireciona para /entrar sem sessão
- ok — /saude aberto
- ok — tela de login com botão de mostrar senha
- ok — tela de registro público
- ok — login do administrador
- ok — senha guardada só como hash
- ok — cadastro de revistas semeado
- ok — revista com ISSN inválido é recusada
- ok — revista válida é criada
- ok — upload de PDF processa e redireciona
- ok — resultado traz bloqueantes, referências e etapa
- ok — XML disponível para download
- ok — pacote .zip disponível
- ok — etapa muda e fica gravada
- ok — etapa inválida recusada
- ok — registro público cria conta e entra
- ok — conta nova é cliente
- ok — cliente não vê documento de outra conta
- ok — cliente não acessa administração
- ok — cliente não edita cadastro de revistas
- ok — painel do cliente vem vazio
- ok — tela da conta com troca de senha
- ok — tela de ajuda
- ok — admin vê visão geral com métricas
- ok — admin vê todos os documentos
- ok — sessão com cookie adulterado é recusada
- ok — horários no fuso de Brasília (-03)
- ok — atividade do usuário é registrada (último acesso e IP)
- ok — painel administrativo mostra contas, uso e filtro por conta
- ok — admin edita nome e e-mail de um usuário
- ok — cadastro de revista tem área e estilo de referências
- ok — administração é ambiente próprio: admin não usa o validador
- ok — menu alterna entre lateral e topo
- ok — correio tem as cinco caixas
- ok — configuração do Resend com chave mascarada
- ok — confirmação de conta pode ser ligada e desligada por um controle próprio
- ok — mensagem sem envio configurado fica na caixa de saída
- ok — webhook do correio exige segredo
- ok — foto de perfil e confirmação de e-mail na conta
- ok — ajuda explica as etapas e separa o que é feito aqui do que é feito na SciELO
- ok — ajuda diz o que ainda não é feito
- ok — cadastro de revista busca nas bases de ISSN
- ok — página Revistas explica de onde vêm os dados e como pedir ISSN novo
- ok — dígito verificador do ISSN é conferido antes de ir à rede
- ok — consulta de ISSN responde com as fontes ou com a revista já cadastrada
- ok — revisar mostra o arquivo original com abas
- ok — revisar liga a seleção do PDF a um campo
- ok — revisar oferece inserir tabela, imagem, equação, quadro e diálogo
- ok — revisar lista o que a SciELO exige e ainda falta
- ok — revisar tem salvar-e-validar e guardar-rascunho
- ok — páginas do original são renderizadas com camada de texto
- ok — imagem da página é servida
- ok — nome de página fora do padrão é recusado
- ok — campo obrigatório vazio impede salvar e validar
- ok — tela de entrega confere o pacote contra o guia
- ok — entrega lembra o aviso obrigatório e o formato do pacote
- ok — entrega explica o atestado de capacidade técnica
- ok — pacote com arquivos na raiz e relatório de validação dentro
- ok — regras de nome do guia (sem acento, underline ou ponto extra)
- ok — depósito sem FTP configurado é recusado com explicação
- ok — configurações têm FTP da SciELO e pedido do atestado
- ok — pedido de atestado exige empresa e CNPJ
- ok — visualizador tem busca no documento
- ok — revisar completa pelo DOI e confere o ORCID
- ok — item removido pode voltar (campo escondido antes da caixa)
- ok — pré-visualização do artigo (htmlgenerator do packtools)
- ok — DOI inválido é recusado sem ir à rede
- ok — ORCID fora do formato é recusado sem ir à rede
- ok — site aceita DOCX
- ok — XML vindo de DOCX é válido no DTD JATS
- ok — DOCX original fica guardado
- ok — formato fora da lista é recusado com o motivo
- ok — fórmula do Word (OMML) vira MathML
- ok — CRediT por autor na tela (13 termos da taxonomia)
- ok — bloco de financiamento (funding-group) na tela
- ok — pedido das pendências por e-mail na tela
- ok — pedido sem destinatário é recusado
- ok — os 13 termos CRediT são os que o Schematron da SciELO aceita
- ok — licença CC BY-NC-ND não vira CC BY-NC
- ok — licença CC BY-SA não vira CC BY-NC-SA
- ok — LaTeX vira MathML
- ok — LaTeX quebrado explica o erro em vez de gerar XML inválido
- ok — sair encerra a sessão

## 5. O que o validador oficial ainda aponta

Agrupado por mensagem, somando os arquivos desta rodada. Todos são dados que o PDF não traz (a SciELO os recebe do OJS) e que o sistema já mostra como bloqueante na tela de revisão.

| Mensagem do packtools | Arquivos |
|---|---|
| SPS [@sps-1.9]: Element 'pub-date': Missing element day. | 10 |
| SPS [@sps-1.9]: Element 'pub-date': Missing element month. | 10 |
| SPS [@sps-1.9]: Element 'article-meta': Missing element article-categories. | 3 |
| SPS [@sps-1.9]: Element 'article-meta': Missing element abstract. | 2 |
| SPS [@sps-1.9]: Element 'article-meta': Missing elements fpage or elocation-id. | 1 |

## 6. Etapas do documento

Fluxo implementado: recebido → em_revisao → pronto → entregue → pre_qa → qa → qa_finalizado → publicado.

## 7. Cobertura do plano

Telas da especificação (seção 5) e ferramentas do plano v3, com o estado de hoje.

| Item do plano | Estado | Evidência |
|---|---|---|
| Tela 1 · Validador público | pronto | verificação "upload de PDF processa e redireciona" |
| Tela 2 · Resultado da validação | pronto | verificação "resultado traz bloqueantes, referências e etapa" |
| Tela 3 · Revisar e editar | pronto (sem o original renderizado ao lado; mostra o resumo da extração) | tela /doc/{id}/editar |
| Tela 4 · Painel com etapas da SciELO | pronto | verificações de etapa; seção 6 |
| Tela 5 · Cadastro de revistas | pronto | verificações de cadastro de revista |
| Tela 6 · Pacote | pronto | verificação "pacote .zip disponível" |
| Tela 7 · Admin interno | pronto (métricas por etapa, revista e bloqueante) | verificação "admin vê visão geral com métricas" |
| Contas e papéis | pronto (admin, operador, cliente) | verificações de isolamento entre contas |
| Confirmação de conta por e-mail | pronto (Resend, ligável em Configurações) | verificações de correio e confirmação |
| Correio do sistema (entrada, saída, enviados, rascunhos, lixeira) | pronto | verificação "correio tem as cinco caixas" |
| Foto de perfil e menu lateral/topo | pronto | verificações de conta e de menu |
| Cadastro de revista pelo ISSN (ISSN.org, SciELO, DOAJ, Crossref, OpenAlex) | pronto | verificações de consulta por ISSN |
| Visualização do arquivo original no revisar, com seleção ligada aos campos | pronto | verificações do visualizador |
| Inserir tabela, imagem, equação, quadro e diálogo na revisão | pronto | verificação "revisar oferece inserir..." |
| Campos que a SciELO exige travando salvar e validar | pronto | verificação "campo obrigatório vazio impede salvar" |
| Fórmulas em MathML (exigência do guia de entrega) | pronto | verificações de LaTeX/MathML |
| Entrada por DOCX (seções, tabelas e fórmulas vindas do arquivo) | pronto | ops/test_docx.py, 40 verificações |
| Fórmula do Word (OMML) convertida em MathML sem digitar | pronto | verificação "fórmula do Word (OMML) vira MathML" |
| Busca dentro do documento no visualizador | pronto | verificação "visualizador tem busca no documento" |
| Completar pelo DOI no Crossref (volume, licença, ORCID, resumo) | pronto | ops/test_ferramentas.py |
| Conferir o ORCID no registro público orcid.org | pronto | ops/test_ferramentas.py |
| CRediT: contribuição de cada autor em <role content-type> | pronto | ops/test_credit.py |
| Financiamento em funding-group, com a nota cruzada que a SciELO exige | pronto | ops/test_credit.py |
| Pedir à revista, por e-mail, tudo que falta de uma vez | pronto | ops/test_credit.py |
| Pré-visualização do artigo como a SciELO publica (htmlgenerator) | pronto | verificação "pré-visualização do artigo" |
| Referências cruzadas com o Crossref | não é confiável | medido: texto sem sentido recebe nota parecida com a de uma referência real, e o editor deposita as referências sem DOI; injetar DOI errado é pior que não ter |
| API oficial do ISSN (api.issn.org) | fora de alcance | é paga e responde 403 sem token; lemos a ficha pública do portal |
| Base consultável do CBISSN/IBICT | não existe | o site é institucional (pedido de ISSN), sem API de periódicos |
| Depósito do pacote no FTP da SciELO, com o aviso obrigatório por e-mail | pronto | ops/test_entrega.py deposita num FTP de verdade |
| Conferência do pacote contra o guia de entrega (formato, nomes, arquivos citados) | pronto | verificações de entrega |
| Pedido do atestado de capacidade técnica (o "selo") montado no correio | pronto | verificação "pedido de atestado exige empresa e CNPJ" |
| API de depósito da SciELO | não existe | a SciELO entrega por FTP e e-mail; é o que o sistema faz |
| Ferramenta 1 · Gerador XML + packtools | pronto | seção 3 (coluna DTD) |
| Ferramenta 6 · Nomenclatura SPS e pacote | pronto | nome-base nos arquivos gerados |
| Figuras, tabelas, equações, notas, referências | pronto | seção 3 (colunas correspondentes) |
| Caminho DOCX | não começou | depende dos arquivos DOCX da ANAMORPHOSIS |
| Parser de referências com IA + Crossref | não começou | hoje é heurística; a confiança de cada referência aparece no resultado |
| Multi-tenant por revista, fila e métricas de custo | não começou | fase 2 do plano |
| Integração com OJS e depósito por FTP | não começou | fase 5 do plano |

