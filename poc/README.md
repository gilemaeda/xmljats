# PoC — extrator de PDF (caminho C) e placar

Prova de conceito da Fase 1 do plano: transformar o PDF de um artigo num `ArticleModel` (espelho simplificado do JATS, com proveniência por campo) e medir, por arquivo, os seis elementos obrigatórios da SciELO contra um gabarito escrito à mão.

## Estrutura

```
poc/
  extrair.py                 CLI: PDF -> model.json + resumo.md + placar.md
  gerar_xml.py               CLI: model.json -> XML SPS -> packtools (DTD + Schematron) -> comparacao com XML oficial
  analisa_pdf.py             diagnostico bruto (fontes, zonas, marcadores); util para PDFs novos
  baixa_gabarito_scielo.py   baixa o XML oficial de um artigo SciELO a partir do DOI
  extrator/
    leitura.py               PyMuPDF -> linhas com atributos; zonas (cabecalho, rodape, nota, lateral, margem); ordem de leitura; paragrafos
    front.py                 identificadores, revista, heading, titulos, autores, afiliacoes, resumos, palavras-chave, datas, licenca
    corpo.py                 secoes, paragrafos, citacoes autor-data, notas, figuras, back matter
    referencias.py           lista de referencias: agrupamento, estilo (ABNT/APA), tipo, ligacao com citacoes
    placar.py                compara o modelo com modelos/gabarito/<nome>.json
    xml_jats.py              ArticleModel + cadastro da revista -> XML JATS/SPS (nome-base SPS, bloqueantes, avisos)
    modelo.py                dataclasses do ArticleModel
    util.py                  regex de identificadores, validacao ORCID/ISSN, datas, idioma, paises
  saida/                     gerado a cada rodada (nao versionar)
modelos/
  *.pdf                      amostras
  gabarito/<nome>.json       gabarito de cada PDF (escrito a mao, conferido no texto bruto)
  gabarito/<acronimo>-<pid>.xml  XML oficial SciELO, quando existe
```

## Rodar

```
python poc\extrair.py "modelos\*.pdf" article.segmented.pdf      # PDF -> model.json + placar
python poc\gerar_xml.py "poc\saida\*.model.json"                 # model.json -> XML SPS + packtools (+ comparação com oficial)
python poc\gerar_xml.py --sps 1.10 "poc\saida\*.model.json"      # idem, JATS 1.3 / SPS 1.10
python poc\analisa_pdf.py "modelos\*.pdf"                        # diagnóstico bruto
python poc\baixa_gabarito_scielo.py 10.1590/2179-8966/2026/92016 # XML oficial SciELO pelo DOI
```

Requisitos: Python 3.12, `pip install pymupdf lxml` e o packtools **do GitHub** (o do PyPI é antigo e não instala no 3.12):

```
pip install https://github.com/scieloorg/packtools/archive/refs/tags/4.16.0.zip
```

Arquivos de apoio: `modelos/revistas.json` (cadastro das revistas: acrônimo, título abreviado, ISSN, editora, prefixo de DOI, licença) e `modelos/gabarito/*.xml` (XML oficial da SciELO, usado na comparação quando o acrônimo bate).

Saídas do gerador em `poc/saida/xml/`: `<nome-base-SPS>.xml`, `<nome>.validacao.md` (bloqueantes nossos, avisos, erros do packtools, comparação com o oficial) e `relatorio_xml.md`.

## Adicionar um PDF ao placar

1. Coloque o PDF em `modelos/`.
2. Rode `analisa_pdf.py` e leia `poc/saida/<nome>.txt` (texto por página com tamanho de fonte, negrito e posição).
3. Escreva `modelos/gabarito/<nome>.json` **lendo o PDF**, não a saída do extrator:

```json
{
  "heading": "Artigos" ,                  // null se a revista nao imprime a secao no PDF
  "titulo": "...",
  "titulos_traduzidos": {"en": "...", "es": "..."},
  "autores": [{"nome": "...", "orcid": "0000-0000-0000-0000", "instituicao": "...", "pais_iso": "BR"}],
  "citacoes_min": 10,                     // minimo de pares (autor, ano) distintos no texto
  "referencias": 27,                      // contadas uma a uma
  "doi": "10.xxxx/...", "idioma": "pt", "resumos": ["pt", "en"],
  "datas": {"recebido": "2025-06-30", "aceito": "2025-11-11"}
}
```

4. Rode `extrair.py` e leia `poc/saida/placar.md`. Se o placar discordar do gabarito, confira o texto bruto antes de mexer no código: quatro dos seis gabaritos iniciais estavam errados, não o extrator.

## Critérios do placar

| Elemento | sim | parcial |
|---|---|---|
| Seção | heading contém (ou está contido n)o esperado | achou outro |
| Título | semelhança ≥ 0,95 e traduções no idioma certo | ≥ 0,75, ou tradução faltando |
| Autor + ORCID | todos os autores e todos os ORCIDs exatos, sem autor a mais | nomes ok, ORCID faltando/errado |
| Afiliação | instituição e país de todos os autores | parte deles |
| Citações | pares únicos ≥ mínimo | ≥ metade |
| Referências | dentro de 5% do total | dentro de 20% |

## O que ainda não faz

Imagens (extração e nomes `gf01`), equações, CRediT → `role`, campos separados dentro de cada referência (`element-citation`), normalização de afiliação em prosa (previsto para IA), geração de XML.
