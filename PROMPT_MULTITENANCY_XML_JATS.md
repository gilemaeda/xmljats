# PROMPT — Evolução do Sistema para Multi-Tenant Completo (Instituições, Revistas, Editores e Parceiros)

> Este documento foi escrito para ser colado diretamente numa sessão do Claude Code, no repositório do projeto de marcação XML-JATS. Ele assume que o pipeline técnico (extração, geração e validação de XML) já existe e foca exclusivamente em como o sistema deve modelar e atender **todos os tipos de cliente e usuário do ecossistema editorial**, não só "uma revista, um login".

---

## Contexto de negócio (leia antes de programar)

O sistema atende uma cadeia de atores real, mapeada a partir do manual oficial da SciELO e de pesquisa de mercado:

```
Instituição mantenedora (universidade, sociedade científica, associação)
        └─ pode manter uma ou várias Revistas
                └─ cada Revista tem um Editor-chefe / corpo editorial
                        └─ e uma Equipe técnica / secretaria editorial (quem opera o dia a dia)
                                └─ que contrata Prestadores de serviço (nós)
```

Duas particularidades importantes que o sistema **precisa** suportar, porque são a realidade do setor, não exceção:

1. **Um editor pode atuar em várias revistas ao mesmo tempo**, inclusive de instituições diferentes. É a norma na academia, não a exceção.
2. **Uma instituição pode manter várias revistas** e querer visão consolidada (financeira, de uso) de todas elas, mesmo que cada revista opere seu próprio fluxo de artigos separadamente.

Além disso, o sistema deve deixar aberta a porta para um terceiro tipo de cliente, que pode não existir hoje mas é uma direção de crescimento real: **outras pequenas empresas de marcação XML (prestadores concorrentes menores, sem tecnologia própria) usando nossa plataforma como back-end** para atender os próprios clientes delas.

---

## Atores do sistema (personas)

| # | Ator | O que precisa fazer no sistema |
|---|---|---|
| 1 | **Organização** (instituição mantenedora, ou empresa parceira revendedora) | Cadastrar-se uma vez, gerenciar uma ou mais revistas sob ela, ver faturamento consolidado |
| 2 | **Revista** | Unidade operacional principal — tem ISSN, acrônimo oficial, idioma(s), coleção(ões) que participa (ex: BR/SP/RE/PS), fila própria de artigos |
| 3 | **Editor-chefe / corpo editorial** | Aprovar/rejeitar o XML antes da entrega; pode estar vinculado a mais de uma revista, inclusive de organizações diferentes |
| 4 | **Equipe técnica / secretaria editorial** | Fazer upload de PDFs, acompanhar status, corrigir dados extraídos — é o usuário operacional do dia a dia |
| 5 | **Financeiro/admin da organização** | Ver faturamento consolidado de todas as revistas da organização, gerenciar quem tem acesso a quê |
| 6 | **Staff interno (nossa equipe)** | Fazer a revisão de qualidade antes de liberar o XML — precisa ver artigos de múltiplos clientes diferentes, mas com escopo de acesso controlado (não é um "cliente", é um papel administrativo nosso) |
| 7 | **Parceiro revendedor** (visão de crescimento, não é MVP) | Cadastra seus próprios clientes (revistas) na plataforma; vê só a carteira dele, isolada de outros parceiros e de clientes diretos |

---

## Modelo de dados proposto

Adaptar nomes/convenções ao que já existe no projeto, mas a estrutura relacional deve ser esta:

- **`organizations`** — id, nome, tipo (`instituicao` | `parceiro_revenda`), plano/forma de cobrança
- **`journals`** — id, `organization_id` (FK), nome, issn, acronimo_oficial, idiomas (array), colecoes (array: BR/SP/RE/PS...)
- **`users`** — id, nome, email, senha/hash, tipo_global (`cliente` | `staff_interno`)
- **`user_journal_roles`** — tabela de junção **N:N**: `user_id`, `journal_id`, `role` (`editor_chefe` | `corpo_editorial` | `secretaria_editorial`). É esta tabela que permite um mesmo usuário ter papéis diferentes em revistas diferentes, inclusive de organizações diferentes.
- **`organization_admins`** — `user_id`, `organization_id` — quem administra a organização inteira (todas as revistas dela, inclusive faturamento)
- **`submissions`** (ou `articles`) — `journal_id` (FK), PDF original, dados extraídos, XML gerado, status do pipeline, status de entrega (FTP/e-mail)
- **`partners`** — extensão de `organizations` com tipo `parceiro_revenda`, quando esse modelo for ativado

**Ponto crítico de design:** a permissão do usuário **nunca deve ser um campo único no usuário** (tipo `users.role`). Ela precisa morar na tabela de junção `user_journal_roles`, porque o mesmo humano pode ser `editor_chefe` na Revista A e `secretaria_editorial` na Revista B.

---

## Matriz de permissões (papel × ação)

| Ação | Secretaria editorial | Editor-chefe | Financeiro/admin org. | Staff interno |
|---|---|---|---|---|
| Upload de PDF | ✅ | ✅ (opcional) | ❌ | ❌ |
| Corrigir dados extraídos | ✅ | ❌ | ❌ | ✅ (fila de QA) |
| Aprovar XML para entrega | ❌ | ✅ | ❌ | ❌ |
| Ver status do pacote | ✅ | ✅ | ✅ | ✅ |
| Ver faturamento da organização | ❌ | ❌ | ✅ | ❌ |
| Gerenciar usuários/papéis | ❌ | ❌ | ✅ (da própria org.) | ✅ (global) |

---

## Fluxos-chave que o sistema precisa suportar

1. Um editor com login único alterna entre revistas diferentes (inclusive de organizações diferentes) e vê apenas os dados relevantes a cada uma — como um "seletor de workspace".
2. Uma universidade com 5 revistas cadastra a organização uma vez; cada revista opera separadamente, mas o financeiro da universidade vê tudo consolidado.
3. Nosso staff interno processa artigos de várias organizações/revistas diferentes numa fila de trabalho única, sem misturar os dados entre clientes.
4. Uma revista nova é criada dentro de uma organização já existente, sem recriar login nem faturamento do zero.
5. (Fase futura) Um parceiro revendedor cadastra clientes próprios e enxerga só a carteira dele.

---

## Requisitos técnicos

- Isolamento multi-tenant por `organization_id`/`journal_id` em toda tabela relevante, reforçado na camada de aplicação (idealmente também no banco, se o motor suportar políticas de acesso por linha)
- Autorização centralizada em middleware único — não espalhar `if (role === ...)` em cada rota
- O token de sessão/JWT deve carregar: `user_id`, lista de `(journal_id, role)`, e `organization_id` nos casos em que o usuário for admin de organização
- Se o projeto já usa um stack definido (ORM, framework, padrão de autenticação), seguir esse padrão — este documento define o modelo de dados e as regras de negócio, não impõe uma stack

---

## Fora de escopo por enquanto

- Split de pagamento automático para parceiros revendedores (tratar manualmente fora do sistema no início)
- White-label completo (logo/domínio customizado do parceiro) — o essencial agora é isolar dados e dar um dashboard próprio ao parceiro, não a marca visual
- Papéis muito granulares além dos listados na matriz acima (ex: separar "revisor de referências" de "revisor de metadados") — começar simples

---

## O que entregar, em etapas (não fazer tudo de uma vez)

1. Proposta de schema/migrations para as tabelas acima, revisável antes de aplicar
2. Middleware de autenticação/autorização com base na matriz de permissões
3. Endpoints mínimos: criar organização → criar revista dentro dela → convidar usuário e atribuir papel por revista → alternar entre revistas no frontend
4. Só depois disso, ajustar as telas existentes para respeitar o novo modelo de permissões

Pare depois de cada etapa para revisão antes de seguir para a próxima.
