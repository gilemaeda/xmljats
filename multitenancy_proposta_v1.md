# Proposta v1 — Organizações, revistas e papéis (multi-tenant completo)

**Base:** `PROMPT_MULTITENANCY_XML_JATS.md` + o que o sistema já faz na 0.26.1.
**Data:** 06/09/2026. **Etapa 1 do prompt (proposta de modelo, para revisão antes de programar).**

> Em uma frase: hoje a organização é só "um grupo de contas que vê os mesmos documentos". A proposta transforma
> a organização no dono das revistas, dá a cada pessoa um **papel por revista** (não um papel único na conta),
> cria a **página da organização** (revistas, pessoas, uso, atividade) e coloca o **editor-chefe aprovando o XML
> antes da entrega**. Tudo sobre os arquivos JSON que o sistema já usa; nada do pipeline (extração, XML,
> validação, fila, OCR, pacote, entrega) muda.

---

## 1. O que existe hoje e o que muda

| Tema | Hoje (0.26.1) | Proposta |
|---|---|---|
| Conta | `papel` único: cliente, operador, administrador; campo `organizacao` (uma só) | `tipo` global: cliente ou staff (operador/administrador). O que a pessoa pode fazer vem dos **papéis por revista** (`papeis.json`) e de ser ou não **admin de uma organização** |
| Organização | nome + código de convite; membro vê tudo da organização | organização com **tipo** (instituição ou parceiro revendedor), **administradores**, **revistas** e **página própria** (dashboard) |
| Revista | pública, da organização ou particular | toda revista de trabalho **pertence a uma organização**. As revistas semeadas por nós ficam num **catálogo** de referência; a organização "adota" (vira dela) quando começa a usar |
| Documento | `organizacao` + quem enviou | pertence à **revista** (e, por ela, à organização). Vê quem tem papel na revista, o admin da organização, quem enviou e o staff |
| Entrega | staff deposita | **editor-chefe aprova** o XML antes da entrega (quando a revista tem editor-chefe); depois o staff deposita, por artigo ou por lote |
| "Faturamento" | não existe | **uso consolidado** por organização, revista e mês (enviados, prontos, entregues) — a base da cobrança até a precificação existir |
| Uma pessoa em várias revistas | não dá (uma organização por conta) | dá: papéis diferentes em revistas diferentes, inclusive de organizações diferentes; **seletor de revista** no topo ("workspace") |

## 2. Atores → o que viram no sistema

| Ator do prompt | No xmljats |
|---|---|
| Organização (instituição mantenedora ou parceiro revendedor) | `organizacoes.json` com `tipo`; admin de organização em `admins` |
| Revista | `revistas.json` com `organizacao` obrigatória (fora o catálogo) |
| Editor-chefe / corpo editorial | papel `editor_chefe` / `corpo_editorial` na revista |
| Equipe técnica / secretaria editorial | papel `secretaria_editorial` na revista (é quem envia e corrige) |
| Financeiro/admin da organização | `admins` da organização (vê tudo da organização, gerencia pessoas e papéis, vê o uso) |
| Staff interno (nós) | `tipo` operador (fila de QA, correção, entrega) e administrador (tudo + configurações) |
| Parceiro revendedor (futuro) | organização com `tipo = parceiro_revenda` e organizações-cliente com `pai` apontando para ela |

## 3. Modelo de dados (arquivos JSON, como o resto do sistema)

- **`organizacoes.json`** — `{id, nome, tipo: "instituicao" | "parceiro_revenda", plano, convite, admins: [usuario_id], pai: id | null, criado_em, criado_por}`
- **`revistas.json`** — cada revista ganha `organizacao` (id) ou `catalogo: true`; `colecoes: ["BR"]` (hoje a sigla da coleção está na configuração do FTP, e é dado da revista). Continuam: acrônimo, ISSN, título abreviado, editora, licença, idioma, editor-chefe (nome/ORCID/Lattes), e-mail editorial, modo de publicação
- **`usuarios.json`** — `papel` vira `tipo` (cliente | operador | admin). O campo `organizacao` sai (migrado para papéis e admins)
- **`papeis.json`** (novo; é a tabela de junção N:N) — `[{usuario, revista, papel: "editor_chefe" | "corpo_editorial" | "secretaria_editorial", desde, por}]`
- **`docs/<id>/config.json`** — `revista` continua sendo a chave; `organizacao` passa a ser derivada da revista (o campo fica, por compatibilidade); novo `aprovacao: {por, em, nota}` quando o editor-chefe aprova
- **Convite** — continua o código da organização, que coloca quem entra como `secretaria_editorial` em todas as revistas dela; o admin da organização ajusta os papéis na página da organização. (Convite com papel específico por revista fica para a etapa 3, se fizer falta.)

**Regra de ouro (do prompt):** a permissão nunca é um campo único na conta. Ela mora em `papeis.json` + `admins` da organização.

## 4. Matriz de permissões

| Ação | Secretaria editorial | Corpo editorial | Editor-chefe | Admin da organização | Operador (staff) | Administrador (staff) |
|---|---|---|---|---|---|---|
| Enviar PDF/DOCX (revista) | ✅ | ❌ | ✅ | ❌ | ✅ | ❌ (não usa o validador) |
| Corrigir dados extraídos | ✅ | ❌ | ❌ | ❌ | ✅ (fila de QA) | ❌ |
| Aprovar XML para entrega | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| Ver status do pacote | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Depositar na SciELO (artigo ou lote) | ❌ | ❌ | ❌ | ❌ | ✅ (depois da aprovação, quando há editor-chefe) | ✅ |
| Ver uso consolidado da organização | ❌ | ❌ | ❌ | ✅ (a própria) | ❌ | ✅ (todas) |
| Gerenciar pessoas e papéis | ❌ | ❌ | ❌ | ✅ (a própria) | ❌ | ✅ (global) |
| Criar revista | ❌ | ❌ | ❌ | ✅ (na própria organização) | ✅ | ✅ |

Uma pessoa pode ter papéis diferentes em revistas diferentes; a matriz vale revista a revista.

## 5. Regras de acesso num lugar só

`app/acesso.py`: uma função `pode(usuario, acao, alvo)` e uma dependência `exige("acao")` usada por todas as rotas — sem `if papel == ...` espalhado. O que cada rota consulta:

- **Documento visível** se: staff; ou admin da organização da revista do documento; ou tem papel na revista; ou foi quem enviou.
- **Revistas visíveis** (envio, painel, revisão): catálogo + revistas onde tem papel + revistas da organização que administra; staff vê todas.
- **Sessão** continua o cookie assinado com o id; os papéis são lidos a cada requisição do `papeis.json` (são poucos e o arquivo é pequeno). A "revista atual" (workspace) fica num cookie próprio.

## 6. Telas

- **Seletor de revista no topo** — "Revista: todas / A / B"; filtra o painel e pré-seleciona o envio.
- **Página da organização** (`/organizacao/<id>`; admin da organização e staff): revistas (com enviados, prontos, entregues e últimos 30 dias), pessoas e papéis por revista (convidar, mudar papel, remover), atividade (quem enviou, revisou, aprovou, entregou), uso consolidado por mês (base do faturamento) e código de convite.
- **Revistas** — criar dentro da organização (admin da organização), editar; staff também.
- **Painel do cliente** — filtra pela revista atual; mostra revista e "enviado por".
- **Aprovação** — no resultado, botão "Aprovar para entrega" (editor-chefe); nova etapa `aprovado` entre "pronto" e "entregue"; a entrega exige aprovação quando a revista tem editor-chefe.
- **Staff** — Documentos com filtros por organização e revista (o de organização já existe) = a fila de QA.

## 7. Migração do que já existe (sem perder nada, automática ao subir a versão)

- Cada organização atual: quem a criou vira **admin**; os membros viram **secretaria editorial em todas as revistas da organização** (se a organização ainda não tem revista, entram como membros e ganham o papel quando a primeira revista chegar).
- Revista `da organização` continua; revista `particular` de alguém sem organização: cria-se uma organização com o nome da pessoa (ela renomeia depois) e a revista passa a ser dela.
- Documentos mantêm `revista`; `organizacao` é recalculada pela revista.
- Contas de cliente sem organização e sem papel continuam vendo só o que enviaram, como hoje.
- Senhas, sessões, revistas semeadas, fila, OCR, pacotes e lotes: não mudam.

## 8. Etapas (com parada para revisão, como o prompt pede)

1. **Esta proposta** — revisar e decidir os pontos da seção 9.
2. **Modelo + acesso centralizado + migração + testes**, sem mudar telas: `papeis.json`, `admins` e `tipo` na organização, `app/acesso.py`, migração automática, testes de isolamento (pessoa com dois papéis em duas organizações; admin de organização; staff).
3. **Telas mínimas**: página da organização, seletor de revista, criar revista dentro da organização, convite/papéis, aprovação do editor-chefe.
4. **Ajuste das telas existentes** à matriz (painel, envio, revisão, entrega e lotes, Documentos do staff), ajuda por perfil e novidades.
5. **(futuro)** parceiro revendedor: organização com `pai`, carteira isolada, dashboard próprio.

## 9. Decisões para vocês (com a minha recomendação)

1. **Migração dos membros atuais** → secretaria editorial em todas as revistas da organização; quem criou vira admin. *Recomendo sim.*
2. **Aprovação do editor-chefe antes da entrega** → obrigatória quando a revista tem editor-chefe cadastrado; sem editor-chefe, a entrega segue como hoje. *Recomendo sim.*
3. **Catálogo de revistas** (as que nós semeamos) continua como referência que a organização adota. *Recomendo sim.*
4. **"Faturamento"** = uso consolidado por revista e mês até a precificação existir. *Recomendo sim.*

## 10. O que fica fora (como no prompt)

Split de pagamento para parceiros, white-label, papéis mais finos do que os três da matriz.

---

## 11. Estado — etapa 2 entregue (0.27.0, 06/09/2026)

Aprovada pelo Giliard com as quatro recomendações da seção 9. O que foi feito, sem tela nova (as telas são a etapa 3):

- **`papeis.json`** (`{papeis: [{usuario, revista, papel, desde, por}], migrado, migrado_em}`) e **`organizacoes.json`** com `tipo`, `plano`, `admins`, `membros`, `pai`. O `papel` da conta continua sendo o tipo global (cliente / operador / admin); `usuarios.json[organizacao]` virou só o espelho da "organização principal" (a que Minha conta mostra).
- **`app/acesso.py`**: `pode(usuario, acao, alvo)` para `enviar`, `corrigir`, `aprovar`, `ver_status`, `depositar`, `ver_uso`, `gerenciar_pessoas`, `criar_revista`; `pode_ver_doc`, `revistas_de`, `entrar_na_organizacao` / `sair_da_organizacao`, `ao_criar_revista` / `ao_mudar_organizacao` / `ao_remover_revista`, `organizacao_pessoal`, `entrega_liberada`, `registra_aprovacao` / `desfaz_aprovacao`, `migra()`. Em `main.py`, `_pasta(doc_id, usuario, acao)` é a porta única de cada rota de documento.
- **Rota nova**: `POST /doc/{id}/aprovar` (editor-chefe; só XML pronto). Etapa `aprovado` entre "Pronto para entrega" e "Entregue à SciELO" (não pode ser marcada à mão). Depósito por artigo e por lote recusa XML sem aprovação quando a revista tem editor-chefe.
- **Migração automática** ao subir a versão: quem tinha `organizacao` na conta vira membro; quem criou a organização (sendo cliente) vira admin; membros viram secretaria em todas as revistas da organização; revista `particular` (`dono`) vira de uma organização pessoal "Organização de <nome>" (ninguém ganha acesso que não tinha).

Ajustes em relação à proposta, decididos na implementação (para revisar):

1. **Staff administrador continua podendo enviar** pelo `/validar` (a matriz dizia ❌; o ambiente dele não tem o validador na tela, mas a rota segue aberta ao staff, e a auditoria depende disso).
2. **Revista de catálogo** (sem organização): qualquer cliente envia, e o documento fica visível/corrigível para os colegas da organização de quem enviou — a regra de antes, mantida para não tirar nada de ninguém.
3. **Cadastrar revista** é do admin da organização (na dela), do staff e de quem ainda não está em organização nenhuma (ganha a pessoal). Membro comum não cadastra; "Detectar pelo ISSN" também respeita isso.
4. **Entrar numa segunda organização** pelo convite (ou criar outra) passou a ser permitido em Minha conta: com papéis por revista, isso não abre nada da primeira. A principal continua a primeira.
5. **Usuários (painel do staff)**: "vincular" = entrar como membro e virar principal; "desvincular" = sair da principal (perde os papéis nas revistas dela), sem mexer nas outras.
6. **Corpo editorial** vê o documento e a lista, mas não envia, não corrige e não muda etapa. **Admin da organização sem papel** vê tudo dela, não corrige nem envia.

Testes: `ops/test_acesso.py` (matriz, isolamento entre organizações, pessoa com dois papéis em duas organizações, aprovação e entrega, organização pessoal, migração) e `ops/test_organizacoes.py` atualizado; auditoria 127/127. Próxima etapa (3): página da organização (`/organizacao/<id>`), seletor de revista, criar revista dentro da organização, convite com papel, botão de aprovar no resultado.
