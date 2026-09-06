# Plano de Implementação v3 — Plataforma de Marcação XML-JATS
### Versão consolidada, para apresentação aos sócios

Este documento reúne tudo que foi levantado até aqui: a leitura completa do manual oficial SPS 1.10 da SciELO, o mapeamento da concorrência real do setor, a lista de ferramentas prioritárias a construir, e a proposta de estrutura de equipe entre os sócios.

---

## Estrutura de papéis entre os sócios

```
                    Sócios
                Projeto XML-JATS
                       |
        ---------------------------------
        |                               |
     Giliard                         Murillo
  Tecnologia & produto          Comercial & relacionamento
        |                               |
   -----------                     -----------
   |         |                     |         |
Dev.      Infra              Comercial   Suporte
técnico   & QA              Vendas       Pós-venda
IA + XML  Validação XML      revistas
```

- **Giliard — Tecnologia & produto:** responsável pelo desenvolvimento do pipeline de IA (extração), geração e validação do XML, infraestrutura do sistema e controle de qualidade técnico.
- **Murillo — Comercial & relacionamento:** responsável por trazer e manter clientes (rede de ~200 revistas), negociação comercial, e suporte pós-venda ao cliente.

Essa divisão é a base pra formalizar a sociedade na Fase 0 (percentuais, responsabilidades e o que acontece se um dos dois sair).

---

## Concorrência — visão corrigida

A ideia original partiu da premissa de que só a Editora Cubo domina o mercado. Depois de pesquisar, isso não é exato: a própria SciELO mantém uma **lista pública de empresas certificadas** para fazer marcação XML, e nela aparecem vários nomes além da Cubo — GN1 (a mais antiga, credenciada desde 2007), Grillo Tecnologia, Grifo Diagramações, HG Design Digital, EPUBTRANS, Editora Letra1, e até empresas estrangeiras (Espanha, Índia).

**O que isso muda na estratégia:** a diferenciação não pode ser "somos a alternativa à Cubo". Ela precisa ser real: **preço menor + velocidade + foco de nicho** (direito, educação, história, filosofia — áreas onde o Murillo já tem rede). A boa notícia encontrada numa lista de discussão da própria SciELO: nenhuma dessas empresas parece ter uma ferramenta de IA nativa e barata — a maioria resolve isso com mão de obra humana especializada. É aí que mora a oportunidade real.

**A certificação em si não é uma barreira governamental.** É um processo interno da SciELO (que é um programa mantido pela FAPESP, não um órgão público): qualquer empresa pode solicitar, mandando CNPJ pra `publicacao@scielo.org` e completando um teste de amostra. Isso é uma tarefa, não um impeditivo.

---

## Fase 0 — Investigação e alinhamento societário (3-4 semanas)

- [ ] Formalizar a divisão de papéis acima e o % de sociedade, por escrito
- [ ] Decidir estrutura jurídica (MEI, LTDA, ou vincular à Maeda Systems)
- [ ] Mapear os concorrentes certificados em mais detalhe (site, preço quando disponível, área de atuação) — usar a lista pública da SciELO como ponto de partida
- [ ] Iniciar processo de solicitação do atestado de capacidade técnica junto à SciELO (`publicacao@scielo.org`), mesmo que a certificação só seja usada mais adiante
- [ ] Murillo confirmar com 5-10 revistas da rede dele se topam testar
- [ ] Conseguir de 3 a 5 PDFs de artigos reais publicados para servir de dataset de teste

---

## Fase 1 — Prova de conceito técnica (4-5 semanas)

Núcleo do produto — as duas ferramentas que realmente diferenciam o negócio, porque usam IA:

1. **Extrator de PDF → texto estruturado** (`pdfplumber`/`PyMuPDF`, com OCR para PDFs escaneados)
2. **Motor de extração semântica via IA** — identifica título, seção, autores (nome, ORCID, afiliação), citações e classifica cada referência bibliográfica por tipo

Critério de sucesso: processar os PDFs de teste do Murillo e conseguir extrair corretamente os **6 elementos obrigatórios** do manual SciELO (seção no idioma certo, título, autoria com ORCID, afiliação, citação no texto, lista de referências), medindo taxa de erro e tempo por artigo.

---

## Fase 2 — MVP funcional (5-7 semanas)

Ferramentas que devem ser código puro, sem IA — mais baratas, mais confiáveis, zero risco de erro "inventado":

3. **Gerador de XML por template** — preenche a estrutura fixa do JATS/SPS a partir dos dados extraídos
4. **Validador contra o DTD JATS 1.3** — confere estrutura antes de qualquer revisão humana
5. **Gerador automático de nome de arquivo/pasta** — segue as regras rígidas do manual (ISSN-Acrônimo-Volume-Número), evitando o erro bobo que provavelmente derruba pacotes de concorrentes que fazem isso manualmente
6. **Montador do pacote .zip** — organiza XML + PDF + imagens + relatório na estrutura exigida

Mais a camada de operação:

- [ ] Interface de upload
- [ ] **Painel de revisão humana** — campos extraídos lado a lado com o PDF original antes de liberar
- [ ] Fila de processamento
- [ ] Armazenamento multi-tenant por cliente
- [ ] Métricas internas: tempo médio, taxa de erro, custo de IA por artigo

---

## Fase 3 — Piloto com clientes reais (4-6 semanas)

- [ ] Rodar com as revistas validadas pelo Murillo, gratuito ou com desconto de lançamento
- [ ] Se o modelo for "revista deposita ela mesma" no FTP, documentar esse processo pra ela
- [ ] Acompanhar um artigo real pelo processo de QA da SciELO, pra entender na prática que correções costumam ser pedidas
- [ ] Calcular custo real por artigo (IA + processamento + revisão humana)

---

## Fase 4 — Modelo comercial e lançamento (paralelo à Fase 3)

- [ ] Definir precificação com base no custo real apurado
- [ ] Ajustar a promessa de venda: "geramos seu XML certo e rápido, por um preço menor" — não "publicamos mais rápido na SciELO" (isso está fora do nosso controle)
- [ ] Murillo estrutura abordagem comercial pra rede de revistas
- [ ] **Painel de status do pacote**, usando os mesmos nomes que a SciELO usa nos e-mails (Entrega → Pré-QA → QA → QA Finalizado) — dá transparência ao cliente

---

## Fase 5 — Escala e diferenciação (contínuo)

- [ ] Reduzir dependência de revisão humana conforme a IA prova consistência
- [ ] Concluir o processo de atestado de capacidade técnica, se ainda pendente, pra virar prestador oficial com FTP próprio
- [ ] Expandir pra mais áreas de conhecimento
- [ ] Concluir a certificação de prestador (atestado), pra ter FTP próprio e não depender mais da credencial de cada revista

---

## Como funciona o envio para a SciELO (e por que dá pra automatizar)

Isso **não é só o validador** — o manual descreve um processo de entrega com duas ações obrigatórias, e as duas são automatizáveis por código, sem precisar de IA:

**1. Depósito do pacote .zip num FTP.**
Existem 2 tipos de conta de FTP: a da própria SciELO (usada por revistas sem prestador certificado — login pedido por e-mail a `publicacao@scielo.org`) ou a conta própria de um prestador com o atestado de capacidade técnica. O pacote é depositado dentro de uma pasta "Entrega" (ou "Correcao", se for correção de um pacote já enviado). Isso é upload de arquivo via protocolo FTP — totalmente scriptável, sem precisar do FileZilla manualmente.

**2. E-mail obrigatório avisando do depósito.**
Só subir o arquivo no FTP não garante nada — é preciso mandar um e-mail para `publicacao@scielo.org` (com cópia pra equipe editorial da revista) avisando. O detalhe importante: **o título do e-mail segue um formato fixo e replicável por código**, por exemplo:
`Entrega | scie v40n2 2025 - BR`
(termo "Entrega" + acrônimo da revista + volume/número + ano + sigla da coleção). O corpo do e-mail também é um template simples ("Informo que o .zip com a marcação XML do periódico [nome], foi disponibilizado no FTP. Total de XMLs = xx").

**Conclusão prática:** como o nome do arquivo, a estrutura de pastas e o título/corpo do e-mail seguem regras fixas e conhecidas, dá pra automatizar o processo inteiro de entrega — não só gerar e validar o XML, mas também depositar e avisar a SciELO automaticamente. A única coisa que não é automatizável de cara é **conseguir a credencial do FTP** (isso exige um pedido pontual por e-mail — da própria revista, sem precisar de atestado, ou do prestador, com atestado).

---

## Mapa de ferramentas por prioridade de construção

| Ordem | Ferramenta | Tipo | Fase |
|---|---|---|---|
| 1 | Validador DTD JATS 1.3 | Código | 1 |
| 2 | Extrator de PDF | Código | 1 |
| 3 | Motor de extração semântica | IA | 1 |
| 4 | Gerador de XML por template | Código | 1-2 |
| 5 | Gerador de nome de arquivo/pasta | Código | 2 |
| 6 | Montador de pacote .zip | Código | 2 |
| 7 | **Módulo de entrega — upload FTP + e-mail formatado automático** | Código | 2-3 |
| 8 | Painel de revisão humana | Interface | 2 |
| 9 | Painel de status do pacote | Interface | 4 |
| 10 | Fila de processamento | Código | 2 |

O item 7 só funciona na prática depois que alguma credencial de FTP existir (a da própria revista, pedida sem burocracia na Fase 0/3, ou a do prestador certificado, mais pra frente) — mas o código do módulo em si pode ser construído em paralelo, sem esperar isso.

---

## Riscos

| Risco | Mitigação |
|---|---|
| Concorrência mais numerosa do que se pensava | Diferenciar por preço + velocidade + foco de nicho, não por ser "o segundo" |
| Não conseguir o atestado de capacidade técnica cedo | Vender só a geração do XML no início; revista deposita sozinha |
| PDFs variados quebram o parser | Testar com amostra diversa desde a Fase 1 |
| Autores/referências extraídos errados pela IA | Revisão humana obrigatória até validar a taxa de erro |
| Cliente esperar publicação rápida na SciELO | Deixar claro na venda: SLA é sobre a geração do XML, não sobre o processo da SciELO |
| Pacote rejeitado por erro de nomenclatura | Automatizar 100% essa parte com código, sem intervenção manual |

---

## Próximo passo imediato

Rodar a Fase 0 e a Fase 1 em paralelo: enquanto você testa a extração com os PDFs de exemplo, o Murillo confirma a rede de revistas e inicia o contato com a SciELO sobre o atestado.
