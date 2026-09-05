# Especificação do Sistema v1 — Plataforma XML-JATS (nome de trabalho: xmljats)

**Base:** `plano_implementacao_xml_jats_v3.md` + análise do validador DOCX → SciELO PS da Wise Thorough (editor português, vídeo `Demonstração XML.mp4` e prints).
**Data:** 04/09/2026.
**Companheiro deste documento:** `prototipo_ui.html` (protótipo navegável das telas, dados de exemplo).

> Nota sobre o resumo automático do vídeo: ele fala em "padrões CEL (Central Editorial Layer)". Pelas telas e pelo XML gerado, o alvo da ferramenta é a **SciELO** (SciELO Publishing Schema, "SciELO PS"). "CEL" é erro de transcrição de "SciELO". O "package maker" citado é, muito provavelmente, o **XML Package Maker (XPM)** da própria SciELO, ou um módulo dele com o mesmo nome; no nosso plano isso corresponde à ferramenta 6 (montador de pacote).

---

## 0. Resumo para os sócios (leia só isto se tiver 5 minutos)

**O que a ferramenta do português prova**

1. Com um **DOCX no modelo da revista**, a conversão para XML SciELO fica quase toda determinística (regras + código). IA só entra quando o DOCX não segue o modelo. Isso derruba o custo e o risco de erro "inventado" que o plano v3 assumia ao partir de PDF.
2. **Validação gratuita como porta de entrada** funciona como funil: qualquer pessoa envia o DOCX, vê a lista de erros, cria conta para gerar o XML. Ele limita a 5 conversões grátis por mês.
3. O produto é basicamente **um formulário espelhando a estrutura do JATS** (revista, artigo, títulos por idioma, autores/afiliações, histórico, licença, seções, notas, referências) com mensagens em três severidades: bloqueante, aviso e "preenchido automaticamente, confirme".
4. Um **cadastro de revistas por conta** (acrônimo, título abreviado, ISSN, editora) elimina os erros mais repetitivos.

**O que muda no nosso plano v3**

| Antes (v3) | Depois (v3.1) | Motivo |
|---|---|---|
| Entrada principal: PDF + IA | Entrada principal: **DOCX no modelo**; DOCX livre com heurísticas + IA; PDF vira linha de "retroconversão" | Revistas têm o DOCX final de todo artigo novo. PDF só é necessário para números antigos. |
| Ferramenta 1 = validador DTD | Ferramenta 1 = **modelo de artigo + gerador de XML + validação packtools** | O validador oficial da SciELO (packtools) já existe e é gratuito. Não construir; integrar. |
| Serviço (nós fazemos a marcação) | **Mesma ferramenta, dois modos**: operador (nós) e autoatendimento (revista) | O piloto roda no modo operador; o validador grátis vira ferramenta de venda do Murillo. |
| Dataset de teste: 3 a 5 PDFs | **3 a 5 DOCX + PDF** dos mesmos artigos, mais o modelo de DOCX que cada revista já usa | Precisamos dos dois formatos para os dois caminhos. |

**Quatro decisões que só vocês dois podem tomar** (detalhe na seção 8)

1. Serviço, SaaS ou os dois. Recomendação: os dois, piloto em modo operador.
2. Validação gratuita pública desde o piloto ou só depois da certificação.
3. Relação com o desenvolvedor português: concorrente, parceiro ou indiferente. Ele está em Portugal, mira SciELO, e a ferramenta é beta.
4. Stack e hospedagem (recomendação na seção 3.1; é decisão do Giliard, mas afeta custo).

---

## 1. Inventário da ferramenta Wise Thorough (o que ela faz, tela a tela)

Endereço: `solutions.wisethorough.com`. Interface em PT-PT ("ficheiro", "registar"). Aparência: PHP server-side simples, sem framework de frontend, Cloudflare Turnstile no cadastro.

### 1.1 Fluxo completo observado

```
Validador (público) → Resultado da validação → "Rever e editar conteúdo" (formulário)
      → Criar conta / Entrar → Confirmar e-mail → Painel (documentos validados + minhas revistas)
      → Preparar XML (Confirmar e gerar) → XML pronto (download, expira em 24 h)
```

### 1.2 Telas e elementos

| Tela | Elementos | Comportamento observado | Adotar? |
|---|---|---|---|
| **Validador DOCX** (home) | Campo "Revista / periódico (opcional)" com autocomplete por título, acrônimo ou ISSN (fonte: OpenAlex + lista SciELO + revistas da conta); "Formato do output" (SciELO PS); seletor de arquivo DOCX; botão Validar; bloco "Como funciona"; link para "template de referência (garante a conversão sem erros)" | Validação sem login, gratuita e "confidencial". Regras "visuais, semânticas e de IA quando não existem separadores explícitos" | Sim, com três origens de arquivo (DOCX modelo / DOCX livre / PDF) e modo de publicação explícito |
| **Resultado da validação** | Status "Ficheiro não pronto" (vermelho); lista "Correções obrigatórias"; lista "Avisos"; botão preto "Rever e editar conteúdo" (expansível); aviso de cota (5 conversões/mês); cards "Acesso à conta" e "Como funciona" | Não mostra contagem nem prioridade; mensagens repetidas ("Foi detetada tradução, mas falta o título" duas vezes sem dizer qual idioma) | Sim, com contagens, idioma/campo em cada mensagem e link "ir para o campo" |
| **Rever e editar conteúdo** | Formulário longo, na ordem do JATS: Metadados do documento → Títulos, resumos e palavras-chave (principal + 1ª e 2ª tradução) → Pontos-chave → Editores → Autores e afiliações → Autor correspondente → Histórico (4 datas em DD/MM/YYYY) → Licença → Seções do corpo (título, tipo `sec-type`, conteúdo) → Figuras e tabelas → Equações → Notas de rodapé (id, legenda, `fn-type`, texto) → Referências (uma por linha) → Sobre os autores | Mensagens inline por campo em três cores: roxo (obrigatório), bege (aviso), verde (preenchido automaticamente). Edições ficam na plataforma; não voltam ao DOCX | Sim, é o coração do produto. Acrescentar o original lado a lado (já previsto no plano: "painel de revisão humana") |
| **Painel** | Tabela "Documentos validados" (revista, arquivo, apagar, data, status da validação, botão Gerar XML / Confirmar e-mail); "As minhas revistas" (título, título curto, editora, acrônimo, ISSN, eISSN, usos, última utilização); validador repetido embaixo; contador "Conversões: 5" no topo | Revista entra no cadastro só depois do primeiro XML gerado | Sim, com etapa do pipeline por documento e cadastro de revista antes do primeiro envio |
| **Preparar XML** | Estado + "Ver relatório"; botões "Confirmar e gerar XML" / "Voltar ao painel" | Deixa gerar mesmo com "não pronto" | Não: bloquear (ou marcar como rascunho) enquanto houver bloqueante |
| **XML pronto** | Mensagem de sucesso; "Descarregar XML"; aviso "caminho base das imagens: src/"; "ficheiros armazenados temporariamente, descarregue em 24 h" | Entrega só o XML; sem pacote, sem PDF, sem validação DTD/SPS visível | Substituir por tela de **Pacote** (XML + PDF + imagens + relatório packtools) |
| **Cadastro / login** | E-mail, senha (mín. 10 caracteres), confirmação, Turnstile; e-mail de confirmação com link válido por 24 h | Padrão | Sim |

### 1.3 Regras de validação observadas (mensagens reais dele)

| Mensagem (tradução livre) | Severidade nele | Elemento JATS |
|---|---|---|
| Acrônimo da revista obrigatório; deve corresponder ao publisher-id registrado | Obrigatória | `journal-id[@journal-id-type="publisher-id"]` |
| Título abreviado da revista obrigatório, no padrão da revista | Obrigatória | `abbrev-journal-title` |
| Contagem de páginas do DOCX obrigatória e deve ser confirmada | Obrigatória | `counts/page-count` |
| Tradução detectada, mas falta o título | Obrigatória | `trans-title-group/trans-title` |
| O documento deve conter pelo menos um autor | Obrigatória | `contrib[@contrib-type="author"]` |
| ORCID obrigatório (validação orientada a SciELO); usar URL HTTPS completa | Obrigatória | `contrib-id[@contrib-id-type="orcid"]` |
| Pelo menos um e-mail de autor de correspondência | Obrigatória | `author-notes/corresp/email` |
| Modo de publicação inserido automaticamente; confirme | Aviso | `pub-date`, `elocation-id`, `volume`/`issue` |
| Nome da editora altamente recomendado | Aviso | `publisher-name` (na SPS é obrigatório) |
| Afiliação declarada sem autor ligado a ela | Aviso | `aff` sem `xref[@ref-type="aff"]` |
| Data de recebimento/aceitação/publicação preenchida automaticamente (6 meses / 1 mês antes / hoje) | Aviso | `history/date` — **não copiar, ver 2.6** |
| Nota existe, mas não foi detectada chamada no texto | Aviso | `fn` sem `xref[@ref-type="fn"]` |
| Tipo de artigo inserido automaticamente; confirme | Aviso | `article/@article-type` |
| Identificador Order inserido por omissão; confirme | Aviso | `article-id[@pub-id-type="other"]` (5 dígitos) |
| Revista não encontrada na lista SciELO por acrônimo, ISSN, eISSN ou título | Aviso | cruzamento com a lista pública da SciELO |
| fn-type inserido por omissão; confirme | Info (verde) | `fn/@fn-type` |
| ID interno preenchido automaticamente; confirme antes da geração final | Info (verde) | `article-id[@pub-id-type="publisher-id"]` |
| URL e texto da licença CC BY 4.0 inseridos por omissão | Info (verde) | `permissions/license` |
| Tipo de nota preenchido com base no conteúdo ("Afiliação atual") | Info (verde) | `fn[@fn-type="current-aff"]` |

### 1.4 O modelo DOCX dele (template_exemplo_01)

Uma página, com pistas puramente visuais:

- Cabeçalho alinhado à direita: `ISSN:1413-9936/ eISSN:1981-5344 / V:5/ e12345 / Order 00101` e `DOI:10.1590/1981-5344/57626`
- Tipo de artigo em itálico à direita (`ARTIGO`)
- Título original em negrito; títulos traduzidos em negrito e itálico
- Autores alinhados à direita com sobrescrito de afiliação e ORCID ao lado: `José da Silva*,1 0000-0002-1825-0097`
- Afiliações numeradas; linha `* Autor para correspondência: nome, email`
- `Resumo:` / `Palavras-chave:` e depois `Abstract:` / `Keywords:`

Fragilidade: tudo depende de negrito, itálico e alinhamento. No artigo real do vídeo (que não usava o modelo), o nome da autora virou título do artigo e o texto da afiliação foi quebrado por regex em campos errados (cidade = "296X / e", estado = "mail: . O presente traba"). Nosso modelo deve usar **estilos nomeados do Word** e uma **tabela de metadados** (seção 6).

### 1.5 O XML que ele gera

Raiz: `<article dtd-version="1.1" specific-use="sps-1.9" xml:lang="pt" article-type="research-article">`. Ou seja, JATS 1.1 + SPS 1.9, uma versão atrás da atual (SPS 1.10 = JATS 1.3). Com o arquivo "não pronto", ele preenche `journal-id`, `abbrev-journal-title` e `publisher-name` com o texto literal **"not defined"**, o que reprova no QA da SciELO. A estrutura em si está correta (journal-meta, article-meta, article-categories com heading, title-group, contrib-group com contrib-id ORCID, xref para aff e corresp, aff com institution orgname, addr-line, country com código ISO).

### 1.6 Fraquezas dele = nossas oportunidades

1. Inventa datas de histórico e o identificador "order".
2. Gera XML com placeholders "not defined".
3. Não valida contra DTD/Schematron nem monta o pacote (XML + PDF + imagens + nomenclatura).
4. Não aceita PDF.
5. Parser de front matter frágil fora do modelo.
6. Referências ficam como texto (uma por linha); não há classificação por tipo nem `element-citation`.
7. Arquivos expiram em 24 h; sem histórico de versões nem rastreio de etapa na SciELO.
8. Só XML; sem integração com OJS (todas as revistas do Murillo usam OJS).

---

## 2. O que muda no plano v3

### 2.1 DOCX antes do PDF

Dois caminhos de entrada, com custo e confiabilidade muito diferentes:

| Caminho | Quando | Técnica | IA? |
|---|---|---|---|
| **A. DOCX no modelo da revista** | Artigos novos (99% do volume recorrente) | Estilos nomeados + tabela de metadados → parser determinístico | Só para referências e afiliações |
| **B. DOCX livre** | Revista que ainda não adotou o modelo | Heurísticas visuais (negrito, itálico, alinhamento, "Resumo:", "Palavras-chave:") + IA para segmentar o front matter quando as heurísticas falham | Sim, uma chamada por artigo |
| **C. PDF publicado** | Retroconversão de números antigos; artigo sem DOCX | PyMuPDF/pdfplumber + OCR + IA para segmentar tudo | Sim, chamadas maiores |

O caminho A é o produto. B é a ponte. C é uma linha de serviço separada ("retroconversão"), precificada à parte.

### 2.2 Validação gratuita como funil

Copiar o mecanismo, não a cota: validação pública gratuita e ilimitada (custa quase nada, é código puro); geração de XML e pacote exige conta; cota gratuita pequena para autoatendimento; operadores (nós) sem cota. O resultado da validação é a peça de venda do Murillo: "seu DOCX tem 6 problemas que reprovariam no QA da SciELO; a gente resolve".

### 2.3 Cadastro de revistas

Tabela `journals` por conta (tenant), preenchida **antes** do primeiro envio, com: título, título abreviado, acrônimo (publisher-id SciELO), ISSN impresso, e-ISSN, editora, licença padrão, modo de publicação padrão, padrão de DOI (ex.: `10.21119/anamps.{vol}.{num}.{eloc}`), seções (headings) por idioma, idiomas, modelo DOCX da revista. Semente global: lista pública de periódicos SciELO (título, ISSN, acrônimo) para autocomplete e para o aviso "revista não encontrada na lista SciELO". Complemento: OpenAlex para revistas fora da SciELO.

### 2.4 Serviço vs. SaaS: mesma ferramenta, dois modos

| | Modo operador (nós) | Modo autoatendimento (revista) |
|---|---|---|
| Quem revisa | Nossa equipe, no painel de revisão | O editor da revista |
| Quem entrega à SciELO | Nós (após certificação) ou a revista via FTP dela | A revista |
| Cobrança | Por artigo / por número | Plano mensal ou por conversão |
| Multi-tenant | Sim: um tenant por revista cliente, operadores veem todos | Sim: tenant vê só o próprio |

O plano v3 já previa multi-tenant. A diferença é só de papéis (operador / cliente) e de cota.

### 2.5 Reordenação de prioridades

O plano v3 colocava "Validador DTD JATS 1.3" como ferramenta 1 a construir. Não construir: **packtools** (biblioteca oficial da SciELO, BSD, Python ≥ 3.9, versão 4.16) valida DTD JATS e Schematron SPS e é o mesmo motor do Style Checker que a SciELO usa. Ferramenta 1 passa a ser o **modelo de artigo + gerador de XML**, com packtools no loop de teste desde o primeiro dia.

Ordem revisada de construção:

| Ordem | Ferramenta | Tipo | Fase |
|---|---|---|---|
| 1 | Modelo de artigo (`ArticleModel`, espelho do JATS) + gerador de XML | Código | 1 |
| 2 | Integração packtools (DTD + SPS) e relatório legível | Código | 1 |
| 3 | Parser DOCX no modelo (estilos + tabela de metadados) | Código | 1 |
| 4 | Motor de regras (catálogo da seção 4) | Código | 1 |
| 5 | Parser de referências (mixed-citation → element-citation) | IA + Crossref | 1-2 |
| 6 | Nome de arquivo + montador de pacote .zip | Código | 2 |
| 7 | Telas: validador, resultado, revisar e editar (com original ao lado) | Interface | 2 |
| 8 | Contas, cadastro de revistas, painel, fila, métricas | Interface + código | 2 |
| 9 | Parser DOCX livre (heurísticas + IA) | Código + IA | 2-3 |
| 10 | Extrator PDF + IA (retroconversão) | IA | 3-5 |
| 11 | Integração OJS (API REST) | Integração | 5 |
| 12 | Automação parcial do depósito FTP | Código | 5 |

### 2.6 O que NÃO copiar dele

1. **Datas inventadas.** Ele preenche recebido = hoje − 6 meses, aceito = hoje − 1 mês, publicado = hoje. Isso é metadado falso num registro permanente. Regra nossa: data ausente é bloqueante para `research-article`; nunca inferir.
2. **Placeholders no XML.** Nada de "not defined". Sem bloqueante resolvido, não há XML final (no máximo um rascunho marcado como tal, para o operador).
3. **"Order" derivado de forma opaca** (11222, 21119). Order é o número de ordem no fascículo, 5 dígitos, vindo do sumário da revista ou do elocation-id, sempre confirmado.
4. **Afiliação quebrada por regex.** Afiliação passa por normalização (IA + lista de instituições), com o texto original preservado em `aff` e os campos estruturados só quando houver confiança.
5. **Arquivos expirando em 24 h.** Guardar por contrato (serviço) e por plano (SaaS).
6. Textos em PT-PT e a identidade visual dele. Inspiração é no fluxo, nos campos e nas severidades; textos, marca e CSS são nossos.

---

## 3. Arquitetura proposta

### 3.1 Stack (recomendação)

| Camada | Escolha | Por quê |
|---|---|---|
| Linguagem | Python 3.12 | packtools, python-docx, PyMuPDF e lxml são Python; é a linguagem do Giliard no plano |
| Web | FastAPI + Jinja2 + HTMX | Uma pessoa desenvolvendo; telas são formulários e tabelas; o protótipo HTML vira template direto. React só se o formulário de revisão exigir mais interatividade |
| Parsing DOCX | python-docx (+ acesso direto ao `document.xml` via lxml para notas de rodapé, equações OMML e imagens) | python-docx não expõe notas de rodapé nem OMML; precisamos do XML cru |
| Parsing PDF | PyMuPDF (layout, fontes, blocos) + OCR (Tesseract) quando escaneado | Já previsto no plano |
| XML | lxml (builder) + templates por seção | Escapa corretamente; gera árvore validável |
| Validação | packtools 4.x (`XMLValidator`: DTD JATS + Schematron SPS) | Motor oficial da SciELO |
| IA | Claude API, modelo padrão `claude-opus-5`, saída estruturada (`output_config.format`) com esquema JSON do `ArticleModel`; Batch API (50% de desconto) para lotes de retroconversão | Detalhe em 3.4 |
| Banco | PostgreSQL (SQLite na PoC) | Multi-tenant, JSONB para o `ArticleModel` |
| Fila | Tarefas em background do FastAPI na PoC; RQ/Redis no MVP | Conversões demoram segundos; PDF + IA demora minutos |
| Arquivos | Disco local na PoC; S3-compatível (Backblaze B2 / Cloudflare R2) no MVP | Barato |
| Hospedagem | 1 VPS (Hetzner / Contabo) com Docker Compose | Custo fixo baixo |
| Autenticação | E-mail + senha com confirmação por link; Turnstile no cadastro | Igual ao dele, suficiente |

### 3.2 Pipeline

```
upload (DOCX/PDF)
  → detecção de caminho (A/B/C)
  → parser → ArticleModel v0 (JSON, com "proveniência" por campo: lido / inferido / padrão da revista / editado)
  → enriquecimento: journal-meta do cadastro, Crossref (DOI das referências), ORCID (formato + dígito verificador)
  → motor de regras → relatório (bloqueantes, avisos, auto-preenchidos) com ponteiro para o campo
  → tela Revisar e editar → edições viram overrides versionados sobre o ArticleModel
  → revalidação (regras) → sem bloqueantes
  → gerador XML → packtools (DTD + SPS) → se falhar, volta ao relatório com a mensagem do packtools traduzida
  → montador de pacote: nome do arquivo, PDF(s), imagens renomeadas, XML, relatório → .zip
  → painel: etapa "Pacote pronto" → (operador) entrega FTP → Pré-QA → QA → QA finalizado
```

Cada etapa grava um evento em `jobs` (início, fim, duração, custo de IA) para as métricas previstas no plano.

### 3.3 Modelo de dados (mínimo)

| Tabela | Campos principais |
|---|---|
| `tenants` | id, nome, tipo (operador/cliente), plano, cota mensal |
| `users` | id, tenant_id, e-mail, senha (hash), papel (admin/operador/editor), confirmado_em |
| `journals` | id, tenant_id, título, título_abreviado, acrônimo, issn, eissn, editora, licença_padrão, modo_publicação_padrão, padrão_doi, idiomas, seções (JSON), modelo_docx (arquivo), na_lista_scielo (bool) |
| `documents` | id, tenant_id, journal_id, arquivo_original, tipo (docx_modelo/docx_livre/pdf), etapa, status_validação, criado_por, criado_em |
| `extractions` | id, document_id, versão, article_model (JSONB), proveniência (JSONB), parser, duração, custo_ia |
| `edits` | id, extraction_id, caminho_do_campo, valor_anterior, valor_novo, user_id, em |
| `validation_reports` | id, extraction_id, bloqueantes (JSON), avisos (JSON), autos (JSON), packtools (JSON) |
| `packages` | id, document_id, nome_base, xml, zip, relatório, gerado_em, entregue_em, status_scielo |
| `jobs` | id, document_id, etapa, início, fim, erro, custo_ia |
| `ai_calls` | id, job_id, modelo, tokens_in, tokens_out, custo, finalidade |

### 3.4 Onde entra IA (e onde não entra)

**Sem IA (código puro, determinístico):** parser do DOCX no modelo; todas as regras da seção 4; gerador de XML; validação DTD/SPS; nomenclatura; pacote; checksum de ORCID (ISO 7064 mod 11-2) e ISSN; formato de DOI; cruzamento xref ↔ fn/ref/aff; detecção de idioma (biblioteca); contagem de páginas do PDF.

**Com IA (Claude API, saída estruturada validada contra esquema):**

| Uso | Entrada | Saída | Modelo | Custo estimado por artigo |
|---|---|---|---|---|
| Referências: texto → `element-citation` (tipo, autores, título, fonte, ano, volume, páginas, DOI) | Lista de referências (~40 × 60 tokens) | JSON por referência | `claude-opus-5`; lote via Batch API | ~US$ 0,05 |
| Front matter de DOCX livre: delimitar título, autores, afiliações, resumos, palavras-chave | Primeiras ~2 páginas como texto com marcas de formatação | Offsets + campos | `claude-opus-5` | ~US$ 0,05 |
| Normalização de afiliação (instituição, divisão, cidade, UF, país ISO) | Texto da afiliação | Campos | `claude-opus-5` (ou `claude-haiku-4-5` se a qualidade medida for igual) | ~US$ 0,01 |
| PDF (retroconversão): segmentar seções, figuras, tabelas, notas | Texto com layout (~30k tokens) | Estrutura (não o texto: o texto vem do extrator) | `claude-opus-5` | ~US$ 0,30 a 0,50 |

Preços de referência (API Anthropic, jun/2026): Opus 5 US$ 5 / US$ 25 por milhão de tokens (entrada / saída); Sonnet 5 US$ 2 / US$ 10; Haiku 4.5 US$ 1 / US$ 5; Batch API com 50% de desconto. Conclusão para a precificação: **IA custa centavos de dólar por artigo; o custo real do artigo é a revisão humana.** Regra de projeto: a IA nunca devolve o corpo do texto, só estrutura (offsets, classificação, campos), para manter os tokens de saída baixos e impedir que o modelo "reescreva" o artigo. Toda saída de IA entra no `ArticleModel` com proveniência "inferido" e aparece como "preenchido automaticamente, confirme".

### 3.5 Integrações

| Serviço | Uso | Custo |
|---|---|---|
| packtools (biblioteca) | Validação DTD + SPS; geração de HTML de pré-visualização (`htmlgenerator`) | Gratuito |
| Lista de periódicos SciELO (CSV público) | Semente do autocomplete e do aviso "não encontrada na lista" | Gratuito |
| OpenAlex API | Autocomplete de revistas fora da SciELO; enriquecimento | Gratuito |
| Crossref API | Encontrar DOI das referências; validar DOI do artigo | Gratuito |
| ORCID (público) | Confirmar que o ORCID existe e o nome bate | Gratuito |
| OJS REST API (fase 5) | Puxar título, resumo, palavras-chave, autores com ORCID e afiliação, seção, DOI, datas e galleys direto da submissão | Gratuito; exige chave de API da revista |
| FTP SciELO (fase 5) | Depósito do pacote após certificação | — |

---

## 4. Catálogo de regras de validação v1

Severidades: **B** = bloqueante (impede XML), **A** = aviso (XML sai, mas o operador precisa olhar), **I** = informação (preenchido automaticamente; confirmar). Cada regra tem id estável para aparecer no relatório e no formulário.

### 4.1 Revista (`journal-meta`)

| ID | Regra | Sev. | Elemento |
|---|---|---|---|
| J01 | Acrônimo (publisher-id) presente e igual ao cadastro | B | `journal-id[@journal-id-type="publisher-id"]` |
| J02 | Título da revista presente | B | `journal-title` |
| J03 | Título abreviado presente | B | `abbrev-journal-title[@abbrev-type="publisher"]` |
| J04 | Pelo menos um ISSN (impresso ou eletrônico), formato `NNNN-NNNX` com dígito verificador válido | B | `issn[@pub-type]` |
| J05 | Nome da editora presente | B | `publisher-name` |
| J06 | Revista encontrada na lista SciELO (por ISSN ou acrônimo) | A | cruzamento |

### 4.2 Artigo (`article-meta`)

| ID | Regra | Sev. | Elemento |
|---|---|---|---|
| A01 | DOI presente e no formato `10.xxxx/...`; se a revista tem padrão de DOI, conferir | B | `article-id[@pub-id-type="doi"]` |
| A02 | Order de 5 dígitos presente (do sumário ou do elocation-id), confirmado | B | `article-id[@pub-id-type="other"]` |
| A03 | Tipo de artigo entre os permitidos pela SPS; se inferido, confirmar | B / I | `article/@article-type` |
| A04 | Seção (heading) no idioma do artigo, entre as seções cadastradas da revista | B | `subj-group[@subj-group-type="heading"]/subject` |
| A05 | Título no idioma do artigo | B | `article-title` |
| A06 | Para cada idioma com resumo/palavras-chave, título traduzido presente | B | `trans-title-group[@xml:lang]` |
| A07 | Idioma do documento detectado e confirmado | I | `article/@xml:lang` |
| A08 | Modo de publicação: fascículo exige volume e número (e páginas ou elocation); contínua exige elocation-id e ano de coleção; AOP exige data eletrônica | B | `volume`, `issue`, `elocation-id`, `fpage`/`lpage`, `pub-date` |
| A09 | Datas de publicação coerentes (pub ≤ hoje; collection = ano) | B | `pub-date[@date-type="pub"]`, `pub-date[@date-type="collection"]` |
| A10 | Contagem de páginas (lida do PDF), figuras, tabelas, equações e referências | B (page-count) / I (demais) | `counts` |
| A11 | Artigos de correção, retratação, adendo, comentário, resposta e parecer exigem artigo relacionado | B | `related-article` |
| A12 | Resumo no idioma do artigo (obrigatório para `research-article` e `review-article`), sem citações e sem parágrafos múltiplos, 100 a 250 palavras (limite da revista) | B / A | `abstract` |
| A13 | Palavras-chave para cada idioma que tem resumo (≥ 1; separadas por ponto e vírgula) | B | `kwd-group[@xml:lang]/kwd` |

### 4.3 Autores e afiliações (`contrib-group`, `aff`, `author-notes`)

| ID | Regra | Sev. | Elemento |
|---|---|---|---|
| C01 | Pelo menos um autor com sobrenome e nomes próprios | B | `contrib[@contrib-type="author"]/name` |
| C02 | ORCID de todo autor, como URL `https://orcid.org/0000-0000-0000-000X`, dígito verificador válido | B | `contrib-id[@contrib-id-type="orcid"]` |
| C03 | Todo autor vinculado a ≥ 1 afiliação | B | `xref[@ref-type="aff"]` |
| C04 | Toda afiliação vinculada a ≥ 1 autor | A | `aff/@id` |
| C05 | Afiliação com instituição (orgname), cidade, estado e país com código ISO | B (país, orgname) / A (cidade, estado) | `institution[@content-type="orgname"]`, `addr-line`, `country[@country]` |
| C06 | Texto original da afiliação preservado | I | `aff` (conteúdo misto) |
| C07 | Autor correspondente com e-mail | B | `author-notes/corresp/email` |
| C08 | ORCID existe e o nome confere (consulta pública) | A | — |

### 4.4 Histórico e licença

| ID | Regra | Sev. | Elemento |
|---|---|---|---|
| H01 | Datas de recebido e aceito presentes para `research-article` (nunca inferidas) | B | `history/date[@date-type]` |
| H02 | Recebido ≤ revisado ≤ aceito ≤ publicado | B | idem |
| L01 | Licença presente, com URL e texto no idioma do artigo; padrão da revista aplicado | B / I | `permissions/license[@xlink:href]/license-p` |

### 4.5 Corpo, figuras, tabelas, equações, notas

| ID | Regra | Sev. | Elemento |
|---|---|---|---|
| S01 | Seções com título e `sec-type` (quando reconhecível: intro, methods, results, discussion, conclusions...) | A / I | `sec[@sec-type]/title` |
| S02 | Hierarquia de seções sem saltos (H1 → H3 sem H2) | A | `sec/sec` |
| F01 | Figura com rótulo, legenda e arquivo de imagem (TIFF/JPG/PNG/SVG); referenciada no texto | B (arquivo) / A (chamada) | `fig/label`, `caption`, `graphic[@xlink:href]`, `xref[@ref-type="fig"]` |
| T01 | Tabela com rótulo, legenda e conteúdo (`table` ou imagem); referenciada no texto | B / A | `table-wrap`, `xref[@ref-type="table"]` |
| E01 | Equação convertida de OMML para MathML; se não converter, imagem + aviso | A | `disp-formula/mml:math` |
| N01 | Toda nota de rodapé tem chamada no texto | A | `fn` ↔ `xref[@ref-type="fn"]` |
| N02 | `fn-type` classificado (afiliação atual, financiamento, conflito de interesse, outro); se inferido, confirmar | I | `fn/@fn-type` |
| N03 | Nota que é biografia de autor vira `bio` ou `fn[@fn-type="current-aff"]`, não fica no título do artigo | B | — |

### 4.6 Referências e citações

| ID | Regra | Sev. | Elemento |
|---|---|---|---|
| R01 | Lista de referências não vazia | B | `ref-list/ref` |
| R02 | Cada referência com `mixed-citation` (texto original) e `element-citation` com `publication-type` | B | `ref/mixed-citation`, `element-citation[@publication-type]` |
| R03 | Cada referência com ano e fonte (ou título) | A | `year`, `source` |
| R04 | Citação no texto (AUTOR, ano) ligada a uma referência | A | `xref[@ref-type="bibr"]` |
| R05 | Referência sem citação no texto | A | — |
| R06 | DOI da referência encontrado no Crossref (quando existir) | I | `pub-id[@pub-id-type="doi"]` |

### 4.7 Pacote

| ID | Regra | Sev. | Fonte |
|---|---|---|---|
| P01 | Nome base no padrão SPS: `ISSN-acrônimo-volume-número-paginação` (ex.: `0124-4567-scie-10-03-365`); com elocation `…-e234`; AOP `ISSN-acrônimo-DOI sem prefixo`; suplemento `…-s01-365`. Só hífen, nunca underline; números com dois dígitos | B | Manual SPS, "Regras de nomeação de arquivos" |
| P02 | Imagens nomeadas `<nome-base>-gf01.tif` em sequência; toda `graphic` aponta para arquivo presente | B | idem |
| P03 | PDF com o mesmo nome base; traduções com sufixo de idioma (`-en.pdf`) | B | idem |
| P04 | XML válido no packtools (DTD JATS 1.3 + Schematron SPS 1.10), zero erros | B | packtools |
| P05 | Raiz `dtd-version="1.3" specific-use="sps-1.10"` | B | SPS |

---

## 5. Telas do nosso sistema (baseadas no layout dele, adaptadas)

Todas em PT-BR. Protótipo navegável em `prototipo_ui.html`.

| # | Tela | Função | O que tem a mais que a dele |
|---|---|---|---|
| 1 | **Validador** (público) | Escolher revista, origem do arquivo (DOCX modelo / DOCX livre / PDF), modo de publicação, enviar | Origem explícita; modo de publicação explícito; link para o modelo DOCX da revista |
| 2 | **Resultado da validação** | Status com contagens; bloqueantes, avisos e auto-preenchidos, cada um com campo e link "ir para o campo"; resumo do que foi extraído | Contagens, ponteiro para campo, resumo de extração, recomendação "corrija no DOCX e reenvie" |
| 3 | **Revisar e editar** | Formulário na ordem do JATS com mensagens inline; **original ao lado** (DOCX renderizado ou PDF) com realce do trecho ligado ao campo em foco; barra fixa com salvar/revalidar | Original lado a lado (previsto no plano v3), proveniência por campo, abas por idioma |
| 4 | **Painel** | Documentos com etapa do pipeline (Enviado → Extraído → Validado → Revisado → XML → Pacote → Entregue → Pré-QA → QA → QA finalizado), fila, métricas | Etapa da SciELO com os nomes que ela usa nos e-mails (plano v3, fase 4) |
| 5 | **Revistas** | Cadastro completo por revista (seção 2.3), modelo DOCX para download | Cadastro antes do primeiro envio; padrão de DOI; seções e idiomas |
| 6 | **Pacote** | Pré-verificação (DTD, SPS, nomenclatura, imagens, PDF), árvore do pacote, prévia do XML, downloads, relatório packtools | Ele entrega só o XML |
| 7 | **Admin interno** (fase 2) | Fila, tempo médio, taxa de erro, custo de IA por artigo, por revista | Métricas do plano v3 |

---

## 6. Modelo DOCX de referência (nosso)

Princípio: o parser lê **estilos**, não aparência. Distribuir um `.dotx` por revista (com a identidade dela) que carrega estes estilos e uma tabela de metadados na primeira página.

**Tabela de metadados (2 colunas, primeira página, removida do corpo na conversão):**

| Campo | Exemplo |
|---|---|
| Revista (acrônimo) | anamps |
| Tipo de artigo | research-article |
| Seção | Artigos |
| Idioma | pt |
| Modo de publicação | contínua |
| Volume / Número / Ano | 11 / 1 / 2026 |
| elocation-id ou páginas | e1222 |
| DOI | 10.21119/anamps.11.1.e1222 |
| Recebido / Revisado / Aceito / Publicado | 18/01/2026 / — / 18/06/2026 / 18/07/2026 |
| Licença | CC BY 4.0 |

**Estilos nomeados:** `SPS Título`, `SPS Título Traduzido (en)`, `SPS Título Traduzido (es)`, `SPS Autor` (um parágrafo por autor: `Sobrenome, Nomes | ORCID | aff1;aff2 | correspondente`), `SPS Afiliação` (um por afiliação: `aff1 | Instituição | Divisão | Cidade | UF | País`), `SPS Correspondência`, `SPS Resumo`, `SPS Palavras-chave`, `SPS Abstract`, `SPS Keywords`, `Título 1/2/3` (seções), `SPS Figura` (rótulo + legenda, imagem no parágrafo anterior), `SPS Tabela`, `SPS Referência` (uma por parágrafo), `SPS Biografia`. Notas de rodapé nativas do Word. Equações no editor de equações do Word (OMML).

**Modo tolerante:** se o DOCX não usa os estilos, o parser cai nas heurísticas do caminho B e o relatório avisa "arquivo fora do modelo; extração por heurísticas e IA; revise com atenção".

---

## 7. Roadmap revisado (v3.1)

| Fase | Duração | Entregas | Critério de sucesso |
|---|---|---|---|
| **0. Societário e coleta** | 3-4 sem (paralela à 1) | Tudo do v3 + decidir serviço/SaaS + obter de 3 a 5 artigos da ANAMORPHOSIS em **DOCX e PDF** + o modelo de DOCX que a revista usa + ler o modelo dele | Decisões da seção 8 tomadas |
| **1. PoC técnica** | 4-5 sem | Sem. 1-2: `ArticleModel` + gerador XML + packtools no loop, a partir de um artigo marcado à mão. Sem. 2-4: parser DOCX no modelo + motor de regras + nomenclatura. Sem. 4-5: parser de referências (IA + Crossref) e montador de pacote | 3 artigos reais passam no packtools com zero erros, com ≤ 10 min de revisão humana cada |
| **2. MVP web** | 5-7 sem | Telas 1 a 6, contas, cadastro de revistas, multi-tenant, fila, métricas, modelo DOCX distribuível | Murillo consegue rodar um artigo sozinho, do envio ao pacote |
| **3. Piloto** | 4-6 sem | Revistas do Murillo em modo operador; programa piloto igual ao dele: DOCX que falharem alimentam o parser; acompanhar 1 artigo no QA da SciELO | Custo real por artigo medido (IA + revisão) |
| **4. Comercial** | paralela à 3 | Precificação; validador gratuito público em xmljats.com; painel de status com nomes da SciELO | Primeiro contrato pago |
| **5. Escala** | contínua | DOCX livre (heurísticas + IA), retroconversão de PDF, integração OJS, certificação SciELO, FTP | Redução da revisão humana medida por métrica |

---

## 8. Decisões pendentes e riscos novos

### Decisões para os sócios

1. **Modo de operação no piloto.** Recomendação: operador (nós revisamos tudo), com o validador público aberto desde a fase 4.
2. **Cota gratuita.** Recomendação: validação ilimitada e gratuita; XML/pacote só com conta; 3 conversões gratuitas por mês para autoatendimento.
3. **Desenvolvedor português.** Opções: (a) ignorar; (b) propor parceria (ele atende Portugal e revistas lusófonas fora do Brasil, nós o Brasil, com troca de modelos e casos); (c) tratar como concorrente. Notar que ele ainda não gera pacote nem valida no packtools. Recomendação: (b), sem depender dele para nada do roadmap.
4. **Stack.** Seção 3.1. Se o Giliard preferir React no formulário de revisão, o protótipo continua servindo de referência visual.
5. **Guarda de arquivos.** Prazo de retenção por contrato (sugestão: 12 meses no serviço; 90 dias no autoatendimento gratuito).

### Riscos novos (além dos do v3)

| Risco | Mitigação |
|---|---|
| Revistas não adotam o modelo DOCX | Caminho B (heurísticas + IA) desde a fase 2; o modelo é vantagem, não pré-requisito |
| packtools muda de versão e quebra a validação | Fixar versão no `requirements`; testes de regressão com os 3 artigos do piloto |
| SciELO passa a exigir SPS 1.11 / JATS 1.4 | Gerador por templates versionados; raiz e regras parametrizadas por versão |
| Parecer visual próximo demais da ferramenta dele | Identidade própria (já no protótipo), textos próprios, sem reuso de CSS ou marca |
| Equações OMML → MathML mal convertidas | Fallback para imagem com aviso; revisão humana obrigatória em artigos com equações |

---

## Anexo A — Nomenclatura SPS (fonte oficial, para a ferramenta 6)

| Caso | Padrão | Exemplo oficial |
|---|---|---|
| Fascículo com paginação | `ISSN-acrônimo-volume-número-paginação` | `0124-4567-scie-10-03-365` |
| Publicação contínua (elocation) | `ISSN-acrônimo-volume-número-elocation` | `0124-4567-scie-41-01-e234` |
| Ahead of print | `ISSN-acrônimo-DOI sem prefixo` | `0124-4567-scie-S0123-45672018050` |
| Suplemento | `ISSN-acrônimo-volume-número-suppl-paginação` | `0124-4567-scie-10-03-s01-365` |
| Imagens | `<nome-base>-gf01.tif`, sequencial, extensões tif/jpg/png/svg | — |
| Traduções | `<nome-base>-en.pdf`, `-es`, `-pt` | — |

Regras: sempre hífen, nunca underline nem espaço; números com dois dígitos. Exemplo para o piloto: artigo `e1222` do v. 11, n. 1 da ANAMORPHOSIS (e-ISSN 2446-8088, acrônimo `anamps`) → `2446-8088-anamps-11-01-e1222.xml`.

## Anexo B — Fontes consultadas

- Ferramenta analisada: `solutions.wisethorough.com` (prints e vídeo `Demonstração XML.mp4`).
- packtools (SciELO): https://github.com/scieloorg/packtools e https://packtools.readthedocs.io/en/latest/api.html
- Style Checker da SciELO (mesmo motor): https://manager.scielo.org/tools/validators/stylechecker/
- SciELO Publishing Schema (guia de elementos): https://scielo.readthedocs.io/projects/scielo-publishing-schema/pt-br/latest/
- Regras de nomeação de arquivos: https://scielo.readthedocs.io/projects/scielo-publishing-schema/pt-br/latest/narr/regra-nomeacao.html
- Como validar o pacote XML SPS (XPM): https://scielo.readthedocs.io/projects/scielo-pc-programs/en/latest/pt_how_to_validate_xml_package.html
- Revista piloto: ANAMORPHOSIS – Revista Internacional de Direito e Literatura, e-ISSN 2446-8088, Rede Brasileira de Direito e Literatura, OJS, publicação contínua, DOI `10.21119/anamps.<vol>.<num>.<elocation>`.

## Anexo C — Dataset de teste

Cinco PDFs de quatro revistas em `modelos/` (ANAMORPHOSIS ×2, Direito e Práxis, Pensar, RBDPP) mais o PDF segmentado da Opinião Jurídica. A caracterização de cada um, a lista consolidada de capacidades do caminho C e o resultado do extrator estão em `modelos/analise_modelos.md`.

Estado em 04/09/2026: o extrator de PDF da PoC (`poc/extrair.py`, ver `poc/README.md`) produz o `ArticleModel` da seção 3.2 a partir dos seis PDFs e passa nos seis elementos obrigatórios em todos eles, medido contra gabaritos escritos à mão (`modelos/gabarito/`). O XML oficial SciELO do artigo da Direito e Práxis está em `modelos/gabarito/` e é o gabarito do gerador de XML (ferramenta 1). Nota: esse XML oficial ainda usa SPS 1.9 / JATS 1.1; a SciELO aceita a versão anterior.

O gerador de XML (`poc/gerar_xml.py` + `poc/extrator/xml_jats.py`) já existe: produz o XML com nome-base SPS, válido no DTD JATS 1.1 nos seis artigos, e no Schematron SPS 1.9 falha só onde o PDF não tem o dado (data de publicação com dia e mês; seção da revista), que são bloqueantes nossos (A09, A04) e virão do OJS ou do cadastro. Contra o XML oficial da Direito e Práxis, 22 de 24 campos são iguais. Resultado detalhado na seção 6 de `modelos/analise_modelos.md`.

Estado em 05/09/2026: site em homologação (Dokploy, `https://xmljats-homol-…sslip.io`) com validador, resultado, **revisar e editar** (tela 3 da seção 5, sem o original renderizado ao lado ainda: mostra o resumo da extração) e pacote .zip (ferramenta 6, sem imagens). Primeiro artigo a atingir "Pronto" no packtools pela plataforma: Direito e Práxis e92016, após informar a data de publicação.

Estado em 05/09/2026, fim do dia (app 0.7.0): figuras, tabelas e equações no pacote e no XML; notas de rodapé com `xref`; `element-citation` completo (ABNT, APA e numérico); interface em modo claro e escuro com contraste medido; contas com registro público e três papéis (administrador, operador, cliente, este último vendo apenas os próprios documentos); telas 1 a 7 da seção 5 no ar, incluindo o **Admin interno** com métricas por etapa, revista e bloqueante. Auditoria automática em `ops/auditoria.py`, que reprocessa os PDFs, valida no packtools, exercita o site e escreve `auditoria.md`. Para testar tabelas e equações foram usados quatro artigos reais da SciELO com PDF e XML oficial (Física e Saúde Pública). O caminho DOCX continua aguardando os arquivos da ANAMORPHOSIS.
