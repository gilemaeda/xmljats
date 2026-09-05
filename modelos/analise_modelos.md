# Análise dos modelos de teste (5 PDFs) e do PDF segmentado

**Data:** 04/09/2026.
**Método:** script `poc/analisa_pdf.py` (Python 3.12 + PyMuPDF 1.28), que lê cada PDF e tenta reconhecer o que o nosso pipeline precisa reconhecer: identificadores, título, autores, resumos, seções, notas, referências, figuras, cabeçalhos repetidos. Saídas em `poc/saida/` (`.json` com a estrutura detectada, `.txt` com o texto de cada página anotado com tamanho de fonte, negrito e posição).

Para rodar de novo (num terminal novo o `python` já deve estar no PATH; senão use o caminho completo):

```
"C:\Users\gilej\AppData\Local\Programs\Python\Python312\python.exe" poc\analisa_pdf.py "modelos\*.pdf" article.segmented.pdf
```

---

## 0. Resumo

- Os cinco PDFs vêm de **quatro revistas** (ANAMORPHOSIS ×2, Direito e Práxis, Pensar, RBDPP). Todos têm texto extraível (nenhum precisa de OCR), todos em uma coluna; três foram gerados pelo Word e dois pelo InDesign.
- **O script já pega sozinho:** DOI, ISSN, e-mails, ORCID quando está inteiro numa linha, cabeçalho e rodapé repetidos (e deles volume, número, elocation), títulos de seção numerados, início da lista de referências e entradas ABNT, citações autor-data, legendas de figura.
- **O que ele erra hoje, e cada erro é uma regra a implementar:** título com fonte do mesmo tamanho do corpo (ANAMORPHOSIS); ORCID quebrado em duas linhas (Simioni, Opinião Jurídica); datas ausentes (ANAMORPHOSIS) ou em lugares não convencionais (margem rotacionada, quadro lateral, última página); títulos de seção sem negrito, em versalete (RBDPP); referências em estilo APA em vez de ABNT (RBDPP); ordem de leitura com coluna lateral (Pensar); ORCID da editora confundido com o do autor (Opinião Jurídica).
- **Achado mais valioso:** Direito e Práxis é revista SciELO (DOI com prefixo 10.1590) e a RBDPP muito provavelmente também. O XML oficial desses dois artigos está publicado no site da SciELO. É o gabarito perfeito para testar o nosso gerador: mesmo artigo, PDF de entrada, XML aprovado no QA como saída esperada.
- **PDF do seu amigo:** é uma segmentação por caixas com rótulo JATS (azul = front, verde = body, laranja = back). Acerta autores, biografias, resumo e referências; erra o título (rotulado como parágrafo), o sumário (rotulado como seção) e o cabeçalho corrente (rotulado como título). Não rotula notas, palavras-chave nem títulos traduzidos. Vale como ideia e como possível dataset rotulado; não vale como dependência. O JSON que ele mencionou não veio no anexo.

---

## 1. Quadro geral

| Arquivo | Revista | Tipo | Gerado por | Págs. | Corpo | Idiomas | Figuras | Notas | Refs. | Datas no PDF |
|---|---|---|---|---|---|---|---|---|---|---|
| `1222+-+VF (5).pdf` | ANAMORPHOSIS v.11 n.1 e1222 | research-article | Word 365 | 16 | 11 pt | pt + es + en (resumos) | 0 | 2 | 20 | **nenhuma** |
| `1227_VF+-+Simioni (3).pdf` | ANAMORPHOSIS v.11 n.1 e1227 | research-article | Word 365 | 23 | 11 pt | pt + es + en | 8 legendas, 10 imagens | 4 | 35 | **nenhuma** |
| `Direito e Praxis.pdf` | Rev. Direito e Práxis (UERJ) v.17 n.3 e92016, p. 01-28 | research-article, seção "Artigos inéditos" | Word 365 | 28 | 11 pt | pt + en | 0 | 4 | 11 | recebido 25/05/2025, aceito 17/04/2026 (p.1) |
| `document.pdf` | Pensar (Unifor) v.31 e16796 | research-article, "Eixo Temático: Artigo Internacional" | InDesign 20 | 14 | 10 pt | **en** (texto) + pt + es | 0 | 0 (bios com * e **) | 34 | recebido 19/04/2026, aceito 22/04/2026 (quadro lateral) |
| `RBDPP_2026_v12n2_1498.pdf` | Rev. Bras. de Direito Processual Penal v.12 n.2 e1498 | **editorial** de dossiê | InDesign 21 | 30 | 9,5 pt | **es** (texto) + en + pt | 0 | 2 | 13 (APA) | submissão e decisão na **última página** |
| `article.segmented.pdf` | Rev. Opinião Jurídica (Unichristus) ano 24 n.45 e5842 | research-article, 3 autores | Word 2019 + caixas | 28 | 13 pt | pt + en + es | 0 | 20 | 24 | submetido 30 jun. 2025, aprovado 11 nov. 2025 (**margem esquerda**) |

---

## 2. Cada arquivo: particularidades, o que o script viu, o que precisa mudar

### 2.1 `1222+-+VF (5).pdf` — ANAMORPHOSIS, artigo sobre "O meu guri"

**Layout.** Linha de 6 pt no topo: `© 2025 by RDL | ISSN 2446-8088 | Doi: 10.21119/anamps.11.1.e1222`. Nome da revista em 12 pt negrito. **Título em 11 pt negrito caixa alta, mesmo tamanho do corpo.** Títulos traduzidos (es, en) em 10 pt negrito. Autor em 9 pt negrito caixa alta com sobrescrito ¹. Resumos com rótulo inline (`RESUMO:`, `PALAVRAS-CHAVE:`, `RESUMEN:`, `PALABRAS CLAVE:`, `ABSTRACT:`, `KEYWORDS:`) em 9 pt, atravessando a quebra de página. Biografia do autor na nota de rodapé 1, com afiliação em prosa ("Doutorando em Direito pela FDRP-USP... Ribeirão Preto-SP, Brasil"), ORCID como URL, Lattes e e-mail. Cabeçalho corrente a partir da p. 2 (`ANAMORPHOSIS – ..., v. 11, n. 1, e1222`) e da p. 3 (`COLUCCI | Eu não entendo essa gente...`). Seções `1 INTRODUÇÃO` em 11 pt negrito. Referências em **12 pt** (maiores que o corpo), ABNT.

**O script viu:** DOI, ISSN, ORCID, e-mail, cabeçalhos repetidos, 5 seções numeradas, 20 referências ABNT, 14 citações autor-data.
**O script errou:** nenhum candidato a título (regra de "fonte 1,3× maior" não funciona aqui); nenhuma data (não existe no PDF); afiliação só em prosa.

**Regras necessárias:** título por posição + negrito + caixa alta + logo abaixo do nome da revista, não por tamanho; ligação autor ↔ sobrescrito ↔ nota biográfica; extração de afiliação da prosa por IA (cidade, UF, país, instituição); datas ausentes viram bloqueante H01 e devem vir do OJS. O e-mail vem partido em pedaços ("CV" / "Lattes:" / "E-mail:" em linhas separadas por causa da justificação): juntar linhas antes de aplicar regex.

### 2.2 `1227_VF+-+Simioni (3).pdf` — ANAMORPHOSIS, artigo com figuras

Mesmo layout do anterior, com três diferenças que importam:

1. **ORCID quebrado em duas linhas** na nota biográfica: `https://orcid.org/0000-0002-` / `8484-4491.` O script achou 0 ORCID. Regra: juntar linhas do mesmo bloco (removendo hífen de quebra só quando não faz parte do identificador) antes das regex de ORCID, DOI e URL.
2. **Nota de rodapé no título** (sobrescrito ¹ no título = "Texto resultante de investigações realizadas junto ao Grupo de Pesquisa..."), que em JATS vira `fn` com `fn-type="supported-by"` ou `other` ligada ao título, não ao autor. A nota 2 é a biografia.
3. **8 figuras** com legenda `Figura N – ...` e linha `Fonte: ...`; 10 imagens no PDF (algumas são partes de uma mesma figura). Regra: extrair imagens, agrupar por legenda, nomear `<base>-gf01.tif`, gerar `fig/label`, `caption`, `attrib` (fonte) e `graphic`.

Restante: 35 referências ABNT, 16 citações, sem datas.

### 2.3 `Direito e Praxis.pdf` — Revista Direito e Práxis (UERJ), revista SciELO

**É o PDF mais bem estruturado dos cinco** e é o mais importante: a revista já está na SciELO (DOI `10.1590/2179-8966/2026/92016`), portanto o XML SPS oficial deste artigo (e92016) existe e pode ser baixado do site da SciELO como gabarito.

**Layout.** Três linhas repetidas em todas as páginas (`Rev. Direito e Práx., Rio de Janeiro, Vol. 17, N. 03, 2026, p. 01-28.` / `Copyright © 2026 Sara...` / `https://doi.org/... | ISSN: 2179-8966 | e92016`). Rótulo de seção `[Artigos inéditos]` em 14 pt (isso é o `subject` do heading). Título 16 pt negrito; título traduzido 12 pt itálico. Autora 11 pt negrito com ¹ (caractere Unicode, não sobrescrito de fonte). **Afiliação estruturada numa linha:** `¹ Universidade Federal da Bahia (UFBA), Salvador, Bahia, Brasil. E-mail: ... ORCID: https://orcid.org/...`. **Datas numa frase:** `Artigo recebido em 25/05/2025 e aceito em 17/04/2026.` Texto da licença CC BY 4.0. `Resumo` e `Abstract` como títulos em negrito em linha própria; `Palavras-chave:` / `Keywords:` inline. Seções `1. Introdução` (numeradas com ponto). Notas de rodapé em 9 pt numeradas `1 `, chamadas por sobrescrito de fonte. Tem **página inicial e final (01-28) e elocation (e92016)** ao mesmo tempo. Referências `Referências bibliográficas`, ABNT.

**O script viu:** título (aqui a regra de tamanho funciona), DOI, ISSN, ORCID, e-mail, datas, resumo/abstract, 7 seções numeradas, 4 notas, 11 referências, 56 citações.
**O script errou:** nada relevante; só precisa mapear `[Artigos inéditos]` para `subj-group` e ler `Vol. 17, N. 03` do cabeçalho.

**Uso:** primeiro artigo a fazer passar ponta a ponta (PDF → ArticleModel → XML → packtools) e comparar com o XML oficial.

### 2.4 `document.pdf` — Pensar (Unifor), artigo em inglês com quadro lateral

**Layout.** Página 1 tem uma **coluna lateral esquerda** (7 pt, x≈54) com metadados editoriais: `Histórico do Artigo` (Recebido 19/04/2026, Aceito 22/04/2026), `Eixo Temático: Artigo Internacional` (o heading), `Editores-chefes` e `Editor Responsável` com afiliação e e-mail, `Autor` com e-mail e **contribuição CRediT** ("Conceptualization, Methodology, Writing – Original Draft..."), `Como citar`, `Declaração de disponibilidade de dados`. Coluna principal: título 12,5 pt negrito em inglês; títulos traduzidos (pt, es) em negrito itálico **entre aspas**; autores 8 pt negrito com marcadores `*` e `**`; **ORCID e Lattes na mesma linha separados por `;`**; afiliação curta sob cada autor; biografias longas em notas de 6 pt marcadas `*`/`**` (não numeradas); `Abstract` / `Resumo` / `Resumen:` com palavras-chave em três idiomas; `1 Introduction` 12 pt negrito; `References` ABNT em 10 pt, muitas com URL e "Acesso em".

**O script viu:** DOIs (inclusive 3 DOIs de referências, que a regex pegou no texto todo), 2 ORCID, 4 e-mails (2 são de editores), datas, 15 seções numeradas, 34 referências, 23 citações.
**O script errou:** ordem de leitura (o PyMuPDF entregou biografias → licença → quadro lateral → título); "0 notas" porque as bios usam `*` e não número; não distingue e-mail de autor e de editor.

**Regras necessárias:** ordenar blocos por coluna antes de ler (quadro lateral é um bloco à parte); marcadores de nota não numéricos (`*`, `**`, `†`); editores viram `contrib-type="editor"`, não autor; CRediT vira `role` com vocabulário CRediT (SPS 1.10 aceita); idioma do artigo é `en` mesmo com a revista brasileira; "Eixo Temático" é o heading.

### 2.5 `RBDPP_2026_v12n2_1498.pdf` — Revista Brasileira de Direito Processual Penal, editorial em espanhol

**Layout.** Cabeçalho `Dossier – Reformas judiciales...` em 7,5 pt. Título 13 pt negrito; traduções (en, pt) 11 pt itálico. Autor 10 pt negrito com ¹; sob ele três linhas estruturadas: instituição + cidade + país (Argentina), e-mail, ORCID URL. `Resumen:` inline; `Abstract:` e `Resumo:` em itálico. **Notas de rodapé com o número numa linha separada em 4,9 pt** e o texto em 8,5 pt na linha seguinte (o script contou 0). **Títulos de seção em versalete sem negrito e menores que o corpo** (`Introducción`, `1. La época del actor judicial incomprendido` em 7,7 pt): a regra "negrito ou maior" não pega; só a numeração ou o nome da fonte. **Referências em estilo APA** (`Bourdieu, P. (1997). Razones prácticas. Barcelona. Anagrama`): a regra ABNT `SOBRENOME, Nome` pegou 1 de 13. Back matter longo: `Authorship information`, `Additional information and author's declarations` (agradecimento, conflito de interesse, autoria, originalidade, dados, declaração de IA), `Editorial process dates` na última página (Submission 20/05/2026; review 23/05/2025 [sic]; decision 28/05/2026), `Editorial team`, licença, `How to cite (ABNT Brazil)`.

**O script viu:** título, DOI, ORCID, e-mail, 14 candidatos a seção (a maioria por tamanho, com ruído), 9 citações.
**O script errou:** 0 notas, 1 referência, 0 datas (estão na p. 30, fora do padrão "recebido/aceito").

**Regras necessárias:** heading por nome de fonte (versalete) e numeração; nota com rótulo em linha própria; parser de referência APA além de ABNT; datas em bloco final com vocabulário em inglês (Submission, Final editorial decision); declarações viram `fn` com `fn-type` (`conflict`, `financial-disclosure`/`supported-by`, `other`) e `author-notes`; `article-type="editorial"` inferido do título e da seção "Dossier". Detalhe útil: a data de revisão (2025) é anterior à submissão (2026) no próprio PDF; a regra H02 pegaria isso.

Como a RBDPP também deve estar na SciELO, vale baixar o XML oficial dela pelo mesmo motivo do 2.3 (confirmar na lista de periódicos).

### 2.6 `article.segmented.pdf` — Revista Opinião Jurídica (Unichristus), o artigo por baixo das caixas

**Layout do artigo.** Cabeçalho da p. 1 com `Editora responsável: Profa. Dra. ...` e o **ORCID da editora** (`0000-0001-6444-2631`), logo acima do DOI: uma regex ingênua atribui esse ORCID a um autor. Licença **CC BY-NC-SA 4.0** (não é CC BY: a regra L01 precisa ler a licença do PDF, não assumir o padrão). Datas `Submetido: 30 jun. 2025` / `Aprovado: 11 nov. 2025` **na margem esquerda, em texto vertical** (x≈32). Título 14 pt negrito caixa alta em pt, en, es. Três autores em 13 pt alinhados à direita com `*`, `**`, `***`. Linha de **sumário** (`1 Introdução. 2 Desenvolvimento. 3 Conclusão. Referências.`). **Resumo estruturado** (Contextualização / Objetivo / Método / Conclusões) e, no abstract em inglês, `Keywords:` colado no meio do parágrafo (erro de autoria que o validador deve avisar). Biografias em notas com `*`; ORCID quebrado em duas linhas (`https://orcid.org/0009-` / `0004-3553-806X`). 20 notas em 16 páginas. Referências ABNT com muitos **documentos legais** (`BRASIL. Lei nº 8.078...`, `BRASIL. Supremo Tribunal Federal...`) e **notícias** (G1, Valor, Conjur): tipos `legal-doc` e `newspaper` no `element-citation`.

**O script viu:** DOI, 3 ORCID (2 dos autores + 1 da editora, e perdeu 1 quebrado), 3 e-mails, data de aprovação, 5 seções numeradas, 20 notas, 24 referências.

---

## 3. O que o extrator de PDF precisa ter (lista consolidada)

Cada item abaixo veio de pelo menos um dos seis arquivos. Entra no backlog do caminho C (retroconversão) da especificação, seção 2.1.

| # | Capacidade | Vista em |
|---|---|---|
| 1 | Juntar linhas do mesmo bloco antes de qualquer regex (ORCID, DOI, URL, e-mail quebrados) | Simioni, Opinião Jurídica, ANAMORPHOSIS 1222 |
| 2 | Título por posição, negrito e caixa alta, não só por tamanho de fonte | ANAMORPHOSIS (título = 11 pt = corpo) |
| 3 | Delimitar o front matter: tudo até o primeiro título de seção ou o primeiro resumo | todos |
| 4 | Resumos por rótulo inline (`RESUMO:`) ou por título em linha própria (`Resumo`); idioma por detecção, não pelo rótulo | todos |
| 5 | Ligar autor ↔ marcador (número, ¹ Unicode, `*`, `**`) ↔ nota biográfica; extrair afiliação, ORCID e e-mail da nota (IA) | ANAMORPHOSIS, Pensar, Opinião Jurídica |
| 6 | Excluir ORCID e e-mail de editores (cabeçalho, quadro lateral, "Editorial team") | Opinião Jurídica, Pensar, RBDPP |
| 7 | Remover cabeçalho e rodapé repetidos e extrair deles volume, número, elocation, páginas, ano | todos |
| 8 | Notas: rótulo numérico na mesma linha ou em linha própria; marcadores não numéricos; chamada por sobrescrito de fonte ou caractere Unicode | RBDPP, Pensar, Direito e Práxis |
| 9 | Títulos de seção por negrito, tamanho, numeração **ou nome da fonte** (versalete); inferir `sec-type` | RBDPP |
| 10 | Referências: agrupar linhas em entradas; reconhecer ABNT e APA; classificar tipo (book, journal, webpage, legal-doc, newspaper, thesis) | RBDPP (APA), Opinião Jurídica (legal-doc) |
| 11 | Datas em cinco formatos e lugares diferentes; ausência vira bloqueante, nunca inferência | todos |
| 12 | Ordem de leitura por coluna (quadro lateral; texto vertical na margem) | Pensar, Opinião Jurídica |
| 13 | Back matter: declarações (conflito, autoria, originalidade, dados, IA), CRediT, "como citar", editores | RBDPP, Pensar |
| 14 | Figuras: legenda `Figura N –` + `Fonte:`; extrair e nomear imagens `gf01` | Simioni |
| 15 | Heading (seção da revista) em formas variadas: `[Artigos inéditos]`, `Eixo Temático: ...`, `Dossier – ...` | Direito e Práxis, Pensar, RBDPP |
| 16 | Licença lida do PDF (CC BY, BY-NC, BY-NC-SA), com o texto no idioma do artigo | Opinião Jurídica, Direito e Práxis, Pensar |
| 17 | Idioma do artigo independente do país da revista (en, es) | Pensar, RBDPP |

Do lado do **caminho A (DOCX no modelo)**, nada disso é necessário: todos esses dados entram na tabela de metadados e nos estilos. É a prova prática do argumento da especificação: PDF é retroconversão; o fluxo principal deve ser DOCX.

---

## 4. O PDF segmentado do seu amigo

**O que é.** O artigo da Opinião Jurídica com caixas desenhadas por cima (94 retângulos vetoriais, sem anotações PDF, sem anexo). Legenda impressa na p. 1: `AZUL=front VERDE=body LARANJA=back`. Cada caixa tem um rótulo em 7 pt com o nome da tag JATS: `contrib`, `aff`, `abstract`, `article-title`, `sec`, `p[n]`, `ref`. Contagem: 10 caixas azuis, 77 verdes, 7 laranja.

**O que ele acertou e errou (p. 1, 2, 25, 26):**

| Rótulo dele | Onde caiu | Avaliação |
|---|---|---|
| `contrib` ×3 | Nomes dos três autores | Certo |
| `aff` ×3 | Notas biográficas com `*` | Aceitável: em JATS é `aff` + `bio`/`fn`, e ORCID e e-mail precisam sair de dentro |
| `abstract` | Bloco `RESUMO` | Certo |
| `sec` | Linha de sumário `1 Introdução. 2 Desenvolvimento...` | **Errado**: isso não é seção |
| `p[6]`, `p[1]` | **Título do artigo** na p. 1 | **Errado**: o título virou parágrafo do corpo |
| `article-title` | **Cabeçalho corrente** da p. 2 | **Errado**: é o running head, não o título |
| `p[n]` ×77 | Parágrafos do corpo | Provavelmente certo na maioria; a numeração salta (41, 47, 53, 3, 7), o que sugere ordem de leitura instável |
| `ref` ×7 | Blocos da lista de referências | Certo, mas por bloco, não por entrada |
| não rotulou | Títulos traduzidos, palavras-chave, datas, DOI, 20 notas de rodapé, títulos de seção reais, licença | Faltam justamente os campos que a SciELO mais cobra |

**Veredito.** A ideia (segmentar em blocos com bounding box → rotular com tag JATS → JSON → XML) é exatamente o caminho C da nossa especificação, e a parte de segmentação o PyMuPDF já entrega de graça (`get_text("dict")` devolve blocos, linhas, fontes e bboxes, que é o que o `analisa_pdf.py` usa). O valor está na **classificação**, e é nela que ele erra o que mais importa. Não é dependência para nada do roadmap.

**Faz sentido aproveitar?** Sim, de duas formas, se ele topar:

1. Pedir o **JSON** e o código: comparar o esquema do JSON dele com o nosso `ArticleModel` custa pouco e pode render ideias.
2. Propor que ele **rotule à mão** (corretamente) uns 10 a 20 PDFs. Um dataset de caixas com a tag JATS certa é o que precisamos para medir a taxa de acerto do nosso extrator, e é trabalho que ele já sabe fazer.

**O post da Editora Cubo no LinkedIn** só mostra a "equipe técnica de XML" deles: confirma que o líder do mercado faz marcação com gente, não com ferramenta. Não há nada ali para reutilizar; é argumento comercial para o Murillo.

---

## 5. Resultado do extrator (PoC do caminho C), 04/09/2026

O diagnóstico da seção 2 virou um extrator de verdade: `poc/extrair.py` + pacote `poc/extrator/` (leitura, front, corpo, referencias, placar). Ele produz, por PDF, um `ArticleModel` em JSON (espelho do JATS, com proveniência por campo), um resumo legível e o placar dos seis elementos obrigatórios contra gabaritos escritos à mão em `modelos/gabarito/`. Como rodar e como adicionar um PDF: `poc/README.md`.

### 5.1 Placar final (seis elementos obrigatórios do plano)

| Arquivo | Seção | Título | Autor + ORCID | Afiliação | Citações | Referências | Extras |
|---|---|---|---|---|---|---|---|
| 1222+-+VF (5) | n/a | sim | sim | sim | sim | sim (20) | DOI ok; resumos pt/es/en; idioma ok |
| 1227_VF+-+Simioni (3) | n/a | sim | sim | sim | sim | sim (34) | DOI ok; resumos ok; idioma ok |
| Direito e Praxis | sim | sim | sim | sim | sim | sim (13) | DOI, recebido, aceito, resumos, idioma ok |
| document (Pensar) | sim | sim | sim | sim | sim | sim (48) | DOI, recebido, aceito, resumos, idioma ok |
| RBDPP_2026_v12n2_1498 | sim | sim | sim | sim | sim | sim (17) | DOI, recebido, aceito, resumos, idioma ok |
| article.segmented (Opinião Jurídica) | n/a | sim | sim | sim | sim | sim (27) | DOI, recebido, aceito, resumos, idioma ok |

"n/a" = a revista não imprime a seção no PDF; ela virá do cadastro da revista. O placar é gerado em `poc/saida/placar.md` a cada rodada.

**Critério de "sim":** título igual ao gabarito (semelhança ≥ 0,95 e traduções no idioma certo); todos os autores com o ORCID exato; instituição e país de cada autor; citações únicas ≥ mínimo; referências dentro de 5% do total contado à mão. As regras estão em `poc/extrator/placar.py`.

### 5.2 O que o extrator faz hoje (itens da tabela da seção 3)

| # | Capacidade | Estado |
|---|---|---|
| 1 | Junção de linhas com de-hifenização que preserva ORCID, DOI e URL | feito |
| 2 | Título por destaque e posição (não por tamanho); agrupamento por estilo com tolerância; quebra por idioma que respeita aspas abertas | feito |
| 3 | Front matter delimitado pelo primeiro título de seção | feito |
| 4 | Resumos por rótulo inline ou em linha própria; idioma por detecção; palavras-chave até o fim da linha com ponto | feito |
| 5 | Autor ↔ marcador (número, ¹, *, sobrescrito) ↔ nota biográfica; ORCID, e-mail, Lattes e afiliação por heurística; direção das linhas de apoio (ORCID acima ou abaixo do nome) decidida por documento | feito (afiliação em prosa fica com confiança baixa; é onde a IA entra) |
| 6 | ORCID de editores nunca atribuído a autor (fica em "não atribuídos") | feito |
| 7 | Cabeçalhos e rodapés repetidos removidos e minerados: volume, número, elocation, páginas, ano, título da revista | feito |
| 8 | Notas: rótulo na linha ou em linha própria; marcadores não numéricos; chamadas por sobrescrito de fonte ou Unicode; zona de notas só quando o resto da página é pequeno | feito |
| 9 | Títulos de seção por negrito, tamanho, numeração ou fonte diferente; sec-type; títulos em duas linhas | feito |
| 10 | Referências: agrupamento por padrões ABNT/APA/legal ou por recuo francês; tipo (book, journal, webpage, legal-doc, newspaper, thesis, confproc, report); ligação citação ↔ referência | feito (element-citation com campos separados ainda não) |
| 11 | Datas em cinco formatos e lugares (frase, rótulo, margem rotacionada, quadro lateral, última página); nunca inferidas; H02 detecta aceite anterior ao recebimento | feito |
| 12 | Coluna lateral e texto rotacionado como zonas próprias; e-mails e editores lidos do quadro lateral | feito |
| 13 | Back matter (declarações, "como citar", nota de coautoria) capturado | feito (CRediT ainda não vira `role`) |
| 14 | Figuras: legenda, fonte e chamada no texto | feito (imagens ainda não são extraídas nem nomeadas `gf01`) |
| 15 | Heading em três formas (`[Artigos inéditos]`, `Eixo Temático:`, `Dossier –`) | feito |
| 16 | Licença lida do PDF (CC BY, BY-NC, BY-NC-SA) | feito |
| 17 | Idioma do artigo independente da revista | feito |

Pendências conhecidas: extração de imagens; equações; CRediT; separação de campos dentro de cada referência; normalização de afiliação por IA; o cabeçalho "© 2025" da ANAMORPHOSIS é lido como ano do artigo (a revista não imprime o ano do fascículo).

### 5.3 O que os gabaritos ensinaram

- Minhas contagens iniciais de referências (feitas com regex ingênua) estavam erradas em quatro dos seis arquivos: RBDPP 14 → 17, Pensar 34 → 48, Opinião Jurídica 24 → 27, Simioni 35 → 34. O extrator estava certo; o gabarito foi corrigido contando linha a linha no texto bruto. Lição para o piloto: **todo PDF novo entra com gabarito conferido à mão**, senão o placar mede o erro do gabarito.
- O XML oficial da Direito e Práxis (`modelos/gabarito/rdp-R5b6JFS9XcMzLF9CTsncxQm.xml`, baixado com `poc/baixa_gabarito_scielo.py`) ainda usa `dtd-version="1.1" specific-use="sps-1.9"` em 2026: a SciELO segue aceitando SPS 1.9. Tem 13 referências, 44 citações apontando para 7 delas, afiliação dentro de `contrib-group`, e notas tipadas `coi-statement`, `edited-by`, `financial-disclosure`, `data-availability`. É o gabarito da ferramenta 1 (gerador de XML).
- A RBDPP não foi encontrada na SciELO pelo DOI (resolve para o site da revista) e a busca do site bloqueia scripts; confirmar à mão se ela está na coleção.

### 5.4 Próximos passos

1. **DOCX da ANAMORPHOSIS** dos artigos 1222 e 1227, para medir o caminho A contra o caminho C nos mesmos textos.
2. **Mais PDFs de outras revistas** no placar, cada um com gabarito conferido à mão.
3. **JSON e código do seu amigo**, e a proposta de ele rotular PDFs.

---

## 6. Gerador de XML e validação no packtools (Fase 1, ferramenta 1), 04/09/2026

`poc/gerar_xml.py` lê o `model.json`, casa a revista pelo ISSN ou pelo prefixo de DOI no cadastro `modelos/revistas.json`, gera o XML SciELO PS (1.9 por padrão, `--sps 1.10` para JATS 1.3), valida no packtools 4.16 (DTD JATS + Schematron SPS) e, quando existe XML oficial da SciELO para o artigo, compara campo a campo. Saídas em `poc/saida/xml/`: o XML já com o **nome-base da SPS** (ex.: `2179-8966-rdp-17-03-e92016.xml`), um relatório por artigo e `relatorio_xml.md`.

### 6.1 Resultado

| Arquivo | Nome-base gerado | DTD JATS 1.1 | Schematron SPS 1.9 | Bloqueantes nossos |
|---|---|---|---|---|
| 1222 (ANAMORPHOSIS) | `2446-8088-anamps-11-01-e1222` | válido | data de publicação sem dia/mês | datas de histórico ausentes; data de publicação incompleta |
| 1227 (ANAMORPHOSIS) | `2446-8088-anamps-11-01-e1227` | válido | idem | idem |
| Direito e Práxis | `2179-8966-rdp-17-03-e92016` | válido | idem | data de publicação incompleta |
| Pensar | `2317-2150-pensar-31-e16796` | válido | idem | idem |
| RBDPP | `2525-510X-rbdpp-12-02-e1498` | válido | idem | idem |
| Opinião Jurídica | `2447-6641-opiniaojuridica-24-45-e5842` | válido | idem + `article-categories` ausente | seção ausente; data incompleta |

- **DTD:** os seis XML são válidos contra o DTD JATS 1.1 empacotado no packtools.
- **Schematron SPS:** o único erro comum é `pub-date` sem dia e mês. Nenhum dos PDFs traz a data completa de publicação (o XML oficial da Direito e Práxis tem 03/08/2026, que só existe no OJS). Na Opinião Jurídica falta também a seção da revista, que não está no PDF nem no cadastro. Os dois casos já eram bloqueantes nossos (A09, A04): o XML sai gerado, mas marcado como não entregável, exatamente o comportamento que a especificação pede (nada de "not defined").
- **Comparação com o XML oficial da Direito e Práxis:** 22 de 24 campos iguais (tipo, idioma, acrônimo, título abreviado, DOI, seção, título, tradução, autora, ORCID, afiliação, país, volume/número/elocation, histórico, licença, resumos, palavras-chave, seções e subseções, 13 referências com os mesmos anos e tipos). Diferem apenas: número de `xref` para referências (62 nossos contra 44; ligamos mais citações) e notas de declaração (o oficial tem conflito de interesses, editoras e financiamento, que não estão no PDF).
- **Lição sobre o oficial:** o XML da SciELO usa `fn-type="coi-statement"`, que não passa no DTD JATS 1.1 nem no Schematron 1.9 do packtools. A SciELO valida com outra combinação (provavelmente o Schematron `scielo-br`). Nosso gerador mapeia para `conflict` no 1.9.

### 6.2 O que o XML gerado ainda não tem

tabelas e equações (figuras já saem com `fig`/`graphic`, imagens em TIFF no pacote e `xref` no texto, desde 05/09), chamadas `xref` para notas de rodapé dentro do texto, CRediT em `role`, e os campos completos de `element-citation` (hoje: autores, ano, fonte, volume/número/páginas por heurística, DOI e URL). Tudo isso é trabalho de código, não de IA, menos a normalização de afiliações em prosa.

### 6.3 Ambiente

- packtools do PyPI é antigo (2.6.4, preso ao Pillow 6 e sem instalação no Python 3.12). Instalar a versão 4.16.0 do GitHub: `pip install https://github.com/scieloorg/packtools/archive/refs/tags/4.16.0.zip`.
- O `validate()` do packtools não acha o DTD no Windows (variável `XML_CATALOG_FILES` não é exportada); `gerar_xml.py` cai para o DTD local empacotado no próprio packtools. O Schematron funciona direto.
