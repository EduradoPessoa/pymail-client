# 01 — Requisitos

**Projeto:** PyMail Client — cliente de e-mail desktop leve, privado e minimalista
**Versão desta spec:** 1.0 · **Data:** 2026-09-25
**Escopo deste documento:** o *quê* e o *quanto*. O *como* está em `02-arquitetura.md`.

---

## 1. Objetivo e problema

Clientes de e-mail clássicos falham em três frentes concretas: são lentos (bloqueiam a interface durante rede e disco), renderizam HTML moderno de forma quebrada, e expõem o usuário a rastreamento por padrão. Este projeto ataca essas três frentes e adiciona um fluxo de trabalho orientado a **Inbox Zero** por atalhos de teclado.

O sucesso não é medido por quantidade de funcionalidades, mas por três afirmações verificáveis:

1. A interface **nunca** congela por causa de rede ou disco — comprovado por teste automatizado (RNF-PERF-01).
2. Nenhuma requisição de rede é disparada pelo conteúdo de um e-mail sem consentimento explícito — comprovado por teste automatizado (RNF-PRIV-01).
3. Um usuário consegue ler, arquivar, buscar e enviar e-mail inteiramente pelo teclado.

---

## 2. Convenções de identificação

| Prefixo | Significado |
|---|---|
| `RF-<ÁREA>-<NN>` | Requisito funcional |
| `RNF-<ÁREA>-<NN>` | Requisito não funcional |
| `CA-<ID>-<n>` | Critério de aceite do requisito `<ID>` |
| `[F1]` | Entra na fase 1 (núcleo vertical usável) |
| `[F2]` | Entra na fase 2 |
| `[FORA]` | Explicitamente fora de escopo |

**Áreas funcionais:** `ACC` contas/autenticação · `MSG` sincronização/cache · `RD` leitura/renderização · `SND` composição/envio · `SRCH` busca · `ORG` organização · `UI` interface · `SET` configuração.

**Áreas não funcionais:** `PERF` desempenho · `SEC` segurança · `PRIV` privacidade · `COMP` compatibilidade · `REL` confiabilidade · `USA` usabilidade · `A11Y` acessibilidade · `PACK` empacotamento · `MAINT` manutenibilidade.

**Regra de rastreabilidade:** todo `RF`/`RNF` tem ao menos um `CA` verificável por teste automatizado ou por procedimento manual documentado. Requisito sem critério de aceite é requisito mal escrito e deve ser reescrito, não implementado.

---

## 3. Decisões herdadas que condicionam os requisitos

Estas quatro decisões foram tomadas antes da escrita dos requisitos e são normativas. O detalhamento (contexto, alternativas rejeitadas, consequências) está em `02-arquitetura.md`, seção ADR.

| # | Decisão | Consequência direta nos requisitos |
|---|---|---|
| D1 | Rede com bibliotecas síncronas da stdlib (`imaplib`/`poplib`/`smtplib`) executadas em threads dedicadas, uma conexão por conta | Habilita RNF-PERF-01; impõe regras de afinidade de thread (seção 5) |
| D2 | Autenticação plugável: senha/app password na fase 1, OAuth2 na fase 2 | Contas Microsoft 365 são **limitação conhecida** da fase 1 (RF-ACC-06, seção 7) |
| D3 | Renderização com `QWebEngineView`, JavaScript desabilitado e interceptor de rede | Habilita RNF-PRIV-01; impõe custo de pacote e memória declarado em RNF-PACK-01/RNF-PERF-05 |
| D4 | Sanitização com biblioteca de allowlist (`nh3`) sobre parser HTML real, nunca regex | Habilita RF-RD-01/03/04/06; adiciona dependência fora da lista original do prompt |

---

## 4. Requisitos funcionais

### 4.1 `ACC` — Contas e autenticação

| ID | Fase | Requisito |
|---|---|---|
| RF-ACC-01 | [F1] | Cadastrar conta IMAP informando nome de exibição, e-mail, host, porta, modo de segurança (SSL/TLS, STARTTLS), usuário e senha. |
| RF-ACC-02 | [F1] | Suportar múltiplas contas simultâneas. O schema de dados e a interface nascem multi-conta na fase 1, mesmo que a visualização unificada chegue na fase 2. |
| RF-ACC-03 | [F1] | Testar a conexão de entrada e de saída antes de salvar a conta, exibindo o erro específico do servidor em caso de falha. |
| RF-ACC-04 | [F1] | Autenticar através de uma abstração `AuthProvider` plugável, com a implementação por senha disponível na fase 1. |
| RF-ACC-05 | [F1] | Remover uma conta mediante confirmação explícita, apagando mensagens, corpos, índice de busca e credencial no keyring. |
| RF-ACC-06 | [F2] | Autenticar via OAuth2 (XOAUTH2) em Google e Microsoft, com fluxo de navegador, PKCE, refresh de token no keyring e tratamento de revogação. |
| RF-ACC-07 | [F2] | Suportar contas POP3 com política de retenção no servidor configurável. |
| RF-ACC-08 | [F2] | Autodetectar parâmetros de servidor por domínio (presets + `autoconfig`), com queda para preenchimento manual. |

**CA-RF-ACC-01-1** — Com uma conta válida cadastrada e o aplicativo reiniciado, a sessão IMAP é restabelecida sem nova digitação de senha.
**CA-RF-ACC-02-1** — Com três contas configuradas, cada uma sincroniza em paralelo; forçar erro de autenticação em uma conta **não** impede a sincronização nem a leitura das outras duas.
**CA-RF-ACC-03-1** — Informar host inexistente produz mensagem que distingue falha de resolução DNS, recusa de conexão e credencial inválida.
**CA-RF-ACC-04-1** — Registrar um `AuthProvider` falso em teste faz o aplicativo autenticar por ele **sem qualquer alteração** em `ui/` ou em `storage.py`. Este teste é o que garante que a fase 2 não exigirá refatoração.
**CA-RF-ACC-05-1** — Após remover a conta, nenhuma linha permanece nas tabelas `accounts`, `folders`, `messages`, `bodies`, `attachments`; nenhuma linha do índice `messages_fts` referencia mensagens daquela conta; a entrada correspondente no keyring foi removida. Verificável por consulta direta ao banco e ao keyring falso.

### 4.2 `MSG` — Sincronização e cache

| ID | Fase | Requisito |
|---|---|---|
| RF-MSG-01 | [F1] | Sincronizar **cabeçalhos primeiro**: obter `ENVELOPE`, `BODYSTRUCTURE`, `FLAGS` e `INTERNALDATE` sem baixar corpo algum. |
| RF-MSG-02 | [F1] | Baixar o corpo de uma mensagem somente sob demanda, ao abri-la. |
| RF-MSG-03 | [F1] | Pré-buscar oportunisticamente o corpo das próximas N mensagens da lista (padrão 5) em prioridade baixa, cancelável quando o usuário navega. |
| RF-MSG-04 | [F1] | Sincronizar incrementalmente por `UIDNEXT`/`UIDVALIDITY`; se o `UIDVALIDITY` mudar, invalidar o cache daquela pasta e ressincronizar do zero. |
| RF-MSG-05 | [F1] | Detectar novas mensagens por `IDLE` quando o servidor suportar, com queda para consulta periódica (`NOOP` + `UID SEARCH`) em intervalo configurável (padrão 60 s). |
| RF-MSG-06 | [F1] | Manter cache de corpos em disco com limite configurável (padrão 500 MB) e descarte LRU dos corpos mais antigos, preservando sempre os cabeçalhos. |
| RF-MSG-07 | [F1] | Baixar anexos somente sob demanda, gravando-os em pasta configurável. Na fase 1 apenas os metadados (nome, tipo MIME, tamanho) ficam em cache. |
| RF-MSG-08 | [F1] | Tratar falha de rede com tentativas em recuo exponencial e estado visual "offline", retomando sozinho quando a conexão voltar. |
| RF-MSG-09 | [F1] | Aplicar operações de organização de forma otimista: a interface reflete a ação imediatamente e a operação entra em fila para o servidor. |
| RF-MSG-10 | [F2] | Oferecer caixa de entrada unificada agregando múltiplas contas em ordem cronológica. |
| RF-MSG-11 | [F2] | Suportar retenção configurável por idade (ex.: manter 90 dias localmente) e por tamanho, por conta. |
| RF-MSG-12 | [F2] | Buscar no servidor (IMAP `SEARCH`) mensagens não presentes no cache local, mesclando os resultados com os locais. |

**CA-RF-MSG-01-1** — Sincronizar uma pasta com 5.000 mensagens realiza **zero** comandos `FETCH` de corpo. Verificável contando comandos no servidor falso (ver `06-estrategia-de-testes.md`).
**CA-RF-MSG-01-2** — O tamanho do banco após a sincronização inicial de 5.000 cabeçalhos é inferior a 5 MB, para mensagens de corpo médio.
**CA-RF-MSG-02-1** — Abrir uma mensagem emite exatamente um `FETCH` de corpo, para o UID daquela mensagem, e nenhum para as demais.
**CA-RF-MSG-04-1** — Alterar o `UIDVALIDITY` no servidor falso faz a pasta ser reinicializada e os UIDs antigos deixarem de ser usados, sem gerar mensagens duplicadas.
**CA-RF-MSG-06-1** — Inserir corpos até exceder o limite de cache faz os corpos mais antigos serem removidos (coluna de cache marcada como descartada) **sem** remover a linha da mensagem nem seu cabeçalho.
**CA-RF-MSG-08-1** — Derrubar a conexão no meio de uma sincronização não trava a interface, não corrompe o banco e resulta em nova tentativa automática; ao restabelecer, a sincronização conclui.
**CA-RF-MSG-09-1** — Arquivar uma mensagem com a rede desligada move a mensagem na interface, registra a operação pendente e a executa no servidor quando a conexão retorna; a interface nunca reverte visualmente sem avisar.

### 4.3 `RD` — Leitura e renderização

| ID | Fase | Requisito |
|---|---|---|
| RF-RD-01 | [F1] | Renderizar o HTML da mensagem **sanitizado** por allowlist, com JavaScript permanentemente desabilitado no motor de renderização. |
| RF-RD-02 | [F1] | Exibir `text/plain` quando essa for a única representação; quando houver apenas HTML, derivar texto plano para pré-visualização e indexação. |
| RF-RD-03 | [F1] | Bloquear **todas** as imagens e recursos remotos por padrão, oferecendo o botão "Carregar imagens deste remetente" que cria uma permissão persistente por endereço de remetente. |
| RF-RD-04 | [F1] | Remover de forma **irreversível** pixels de rastreamento (imagens 1×1, 0×0, `display:none`, `visibility:hidden` ou ocultas por atributo), mesmo que o usuário autorize imagens do remetente. |
| RF-RD-05 | [F1] | Remover parâmetros de rastreamento de links (`utm_*`, `fbclid`, `gclid`, `mc_eid`, `_hsenc`, `_hsmi`, `vero_id`, `igshid`) e exibir o destino real ao passar o mouse. |
| RF-RD-06 | [F1] | Impedir execução de `<script>`, `<iframe>`, `<object>`, `<embed>`, `<form>`, manipuladores `on*` e URLs `javascript:`; bloquear na camada de rede qualquer requisição não autorizada pelo interceptor. |
| RF-RD-07 | [F1] | Abrir links no navegador padrão do sistema, mediante confirmação que exibe o host de destino. O leitor nunca navega para fora da mensagem. |
| RF-RD-08 | [F1] | Ajustar o zoom do leitor com `Ctrl` `+`/`-`/`0`, persistindo a preferência por mensagem lida e como padrão do aplicativo. |
| RF-RD-09 | [F1] | Marcar como lida ao abrir, após atraso configurável (padrão 1500 ms), sendo possível desativar o comportamento. |
| RF-RD-10 | [F2] | Agrupar mensagens da mesma conversa (`References`/`In-Reply-To`) em um painel de conversa. |

**CA-RF-RD-01-1** — Um corpus de e-mails hostis em `tests/fixtures/eml/malicious/` (script inline, `javascript:`, `onerror`, iframe, object, form, `style` com `expression()`, CSS `@import` remoto, `<base href>`) produz HTML sanitizado sem nenhum dos elementos ou atributos proibidos. O teste falha se qualquer um sobreviver.
**CA-RF-RD-03-1** — Com imagens bloqueadas, renderizar uma mensagem que referencia 20 imagens remotas produz **zero** requisições de rede. Verificável pelo interceptor, que registra toda tentativa de requisição.
**CA-RF-RD-03-2** — Autorizar imagens do remetente `a@exemplo.com` faz as imagens carregarem nessa e nas próximas mensagens **daquele remetente**, e não em mensagens de outros remetentes. A autorização sobrevive ao reinício.
**CA-RF-RD-04-1** — Mensagem com pixel 1×1 e com imagem declarada `width=1 height=1` via CSS não gera requisição nem após o usuário autorizar imagens do remetente.
**CA-RF-RD-06-1** — Com o interceptor ativo, qualquer requisição a host externo que não seja imagem explicitamente autorizada é cancelada e registrada como bloqueada.
**CA-RF-RD-07-1** — Clicar em link com `href="https://exemplo.com/x"` e texto exibido `https://banco-falso.com` mostra o destino real na confirmação e abre `exemplo.com`, nunca o texto exibido.

### 4.4 `SND` — Composição e envio

| ID | Fase | Requisito |
|---|---|---|
| RF-SND-01 | [F1] | Compor mensagem com Para, Cc, Cco, assunto, corpo em texto e/ou HTML e anexos. |
| RF-SND-02 | [F1] | Responder, responder a todos e encaminhar, com citação do original e cabeçalhos de encadeamento (`In-Reply-To`, `References`) corretos. |
| RF-SND-03 | [F1] | **Undo Send**: a mensagem entra em fila e o envio por SMTP só ocorre após uma janela configurável de 5 a 30 s (padrão 10 s), durante a qual o usuário pode cancelar. |
| RF-SND-04 | [F1] | Persistir rascunhos e a fila de envio, sobrevivendo a reinício do aplicativo. |
| RF-SND-05 | [F1] | Falha de envio devolve a mensagem ao usuário com o motivo e ação de reenvio; nenhuma mensagem é descartada silenciosamente. |
| RF-SND-06 | [F1] | Alertar e exigir confirmação antes de enviar anexos que ultrapassem o limite configurável (padrão 20 MB). |
| RF-SND-07 | [F1] | Exigir TLS na conexão de saída por padrão; recusar transmitir credenciais em texto claro sem que o usuário habilite explicitamente essa exceção. |
| RF-SND-08 | [F1] | Detectar ausência de assunto ou de destinatário e alertar, permitindo enviar mesmo assim. |
| RF-SND-09 | [F2] | Gravar rascunhos e cópias de enviadas em pastas remotas via IMAP `APPEND`. |

**CA-RF-SND-03-1** — Cancelar dentro da janela de undo impede **qualquer** conexão SMTP. Verificável pelo servidor SMTP falso, que registra zero conexões.
**CA-RF-SND-03-2** — Não cancelar faz a mensagem ser enviada exatamente uma vez, com `Message-ID` estável entre a gravação na fila e o envio.
**CA-RF-SND-04-1** — Encerrar o aplicativo com uma mensagem na janela de undo e reabri-lo após o prazo: a mensagem é enviada (dentro da carência de 24 h) ou marcada como falha com notificação — nunca desaparece sem rastro.
**CA-RF-SND-05-1** — Com o servidor SMTP recusando conexão, a mensagem permanece visível em estado de erro com o texto do servidor e botão de reenvio.
**CA-RF-SND-07-1** — Configurar servidor de saída sem TLS faz o envio ser recusado com mensagem explícita, a menos que a opção de exceção esteja habilitada.

### 4.5 `SRCH` — Busca

| ID | Fase | Requisito |
|---|---|---|
| RF-SRCH-01 | [F1] | Buscar localmente com FTS5 sobre assunto, remetente, destinatários e corpo, **insensível a acentos e maiúsculas**. |
| RF-SRCH-02 | [F1] | Buscar enquanto se digita, com atraso de 250 ms e correspondência por prefixo. |
| RF-SRCH-03 | [F1] | Filtrar resultados por conta, pasta, período, não lidos, com anexo e remetente. |
| RF-SRCH-04 | [F1] | Atualizar o índice na **mesma transação** que grava o corpo, garantindo que índice e conteúdo nunca divirjam. |
| RF-SRCH-05 | [F1] | Tratar a sintaxe de consulta do FTS5 sem permitir erro de sintaxe pelo usuário: a entrada livre é escapada e termos inválidos são neutralizados. |
| RF-SRCH-06 | [F2] | Buscar no servidor para mensagens não cacheadas e mesclar resultados (depende de RF-MSG-12). |

**CA-RF-SRCH-01-1** — Buscar `acao` encontra mensagem contendo `Ação`; buscar `ACAO` encontra `ação`; buscar `servico` encontra `serviço`. Casos com cedilha, til, agudo e circunflexo cobertos por teste parametrizado.
**CA-RF-SRCH-02-1** — Com 50.000 mensagens indexadas, uma consulta de duas palavras retorna em menos de 100 ms (medido no teste, com margem de 3× em CI).
**CA-RF-SRCH-04-1** — Simular falha na gravação do corpo não deixa entrada órfã no índice; simular falha na indexação não deixa corpo sem índice. Os dois caminhos são testados com rollback.
**CA-RF-SRCH-05-1** — Entradas como `"`, `AND`, `*`, `NEAR(`, `col:valor` e strings iniciadas por `-` não lançam exceção nem produzem consulta SQL inválida; são tratadas como texto literal.

### 4.6 `ORG` — Organização

| ID | Fase | Requisito |
|---|---|---|
| RF-ORG-01 | [F1] | Arquivar mensagem removendo-a da caixa de entrada e movendo-a para a pasta de arquivo (criando-a se não existir). |
| RF-ORG-02 | [F1] | Enviar mensagem para a lixeira. |
| RF-ORG-03 | [F1] | Marcar como lida/não lida e sinalizar/desinalizar. |
| RF-ORG-04 | [F1] | Aplicar todas as ações acima a uma seleção múltipla. |
| RF-ORG-05 | [F1] | Executar os movimentos com `UID MOVE` quando disponível e com `COPY` + `STORE \Deleted` + `EXPUNGE` como alternativa. |
| RF-ORG-06 | [F2] | Desfazer arquivamento e exclusão por alguns segundos após a ação. |
| RF-ORG-07 | [F2] | Snooze: ocultar a mensagem da caixa de entrada até data e hora escolhidas, reapresentando-a no horário. |

**CA-RF-ORG-01-1** — Arquivar contra servidor com `MOVE` habilitado emite `UID MOVE` e **não** emite `COPY`; contra servidor sem `MOVE`, emite a sequência alternativa. Ambos verificados no servidor falso.
**CA-RF-ORG-04-1** — Selecionar 50 mensagens e arquivar produz 50 movimentos, refletidos na interface antes de qualquer resposta do servidor, e um único progresso agregado.
**CA-RF-ORG-05-1** — Se o `EXPUNGE` falha após o `STORE \Deleted`, o estado local e o do servidor são reconciliados na próxima sincronização, sem mensagem duplicada nem desaparecida.

### 4.7 `UI` — Interface e produtividade

| ID | Fase | Requisito |
|---|---|---|
| RF-UI-01 | [F1] | Layout de três colunas: contas e pastas \| lista de mensagens \| leitor. |
| RF-UI-02 | [F1] | Colapsar a coluna de contas/pastas, com o estado persistido entre sessões. |
| RF-UI-03 | [F1] | Atalhos: `C` compor, `E` ou `Backspace` arquivar, `D` ou `Delete` lixeira, `/` focar busca, `J`/`K` navegar para baixo/cima. |
| RF-UI-04 | [F1] | Desativar atalhos de letra enquanto o foco estiver em campo de texto, saindo do campo com `Esc`. |
| RF-UI-05 | [F1] | Renderizar a lista de forma virtualizada, sustentando 50.000 itens sem travar. |
| RF-UI-06 | [F1] | Alternar tema claro/escuro acompanhando o sistema operacional, com sobreposição manual (sistema/claro/escuro) aplicada em tempo real, sem reiniciar. |
| RF-UI-07 | [F1] | Apresentar estados vazios, de carregamento e de erro informativos — nunca uma área em branco sem explicação. |
| RF-UI-08 | [F1] | Comunicar erros de rede de forma não modal, com ação sugerida, sem interromper o trabalho. |
| RF-UI-09 | [F1] | Densidade da lista configurável (confortável/compacta). |
| RF-UI-10 | [F1] | Indicar progresso de sincronização por conta de forma discreta. |
| RF-UI-11 | [F1] | Exibir pré-visualização de remetente, assunto, trecho, data, indicador de não lido, de sinalizado e de presença de anexo. |
| RF-UI-12 | [F2] | Painel de conversa (depende de RF-RD-10). |

**CA-RF-UI-03-1** — Cada atalho é verificado por teste de interface: o efeito esperado ocorre com foco na lista e **não** ocorre com foco no corpo do compositor ou no campo de busca.
**CA-RF-UI-04-1** — Digitar `c` dentro do campo de busca insere a letra `c` e não abre o compositor; `Esc` devolve o foco à lista e reativa os atalhos.
**CA-RF-UI-05-1** — Carregar 50.000 mensagens na lista mantém a rolagem fluida e não instancia um item de interface por mensagem; a contagem de widgets criados é limitada à área visível mais uma margem, verificada por teste.
**CA-RF-UI-06-1** — Trocar o tema do sistema com o aplicativo aberto altera as cores sem reiniciar e sem recarregar a lista; a preferência manual sobrepõe o sistema e é persistida.

### 4.8 `SET` — Configuração e dados locais

| ID | Fase | Requisito |
|---|---|---|
| RF-SET-01 | [F1] | Persistir configurações em arquivo texto no diretório de dados do sistema operacional. |
| RF-SET-02 | [F1] | Tornar configuráveis: janela do Undo Send, intervalo de verificação de novas mensagens, limite de cache de corpos, atraso para marcar como lida, densidade da lista, tema, pasta de anexos, uso de `IDLE`. |
| RF-SET-03 | [F1] | Versionar o schema do banco e aplicar migrações automáticas e idempotentes na inicialização. |
| RF-SET-04 | [F1] | Registrar logs de diagnóstico com redação de dados sensíveis, com rotação, e oferecer exportação de um pacote de diagnóstico. |
| RF-SET-05 | [F1] | Recuperar-se de banco corrompido: detectar, avisar o usuário, preservar rascunhos e fila de envio, e reconstruir o cache a partir do servidor. |
| RF-SET-06 | [F2] | Exportar e importar contas e configurações, sem exportar credenciais. |

**CA-RF-SET-03-1** — Abrir um banco na versão anterior aplica as migrações e preserva todos os dados; abrir um banco em versão **mais nova** que o aplicativo recusa a operação com mensagem clara em vez de corromper dados.
**CA-RF-SET-04-1** — Nenhum log, em nenhum nível, contém valor de senha, token, corpo de mensagem ou caminho de arquivo de anexo do usuário. Verificável por varredura nos logs de uma execução de teste que exercita login, leitura e envio.
**CA-RF-SET-05-1** — Truncar o arquivo do banco faz o aplicativo detectar a corrupção, exportar rascunhos e outbox para arquivo separado e reconstruir o cache, sem encerrar abruptamente.

---

## 5. Requisitos não funcionais

### 5.1 `PERF` — Desempenho

| ID | Fase | Requisito |
|---|---|---|
| RNF-PERF-01 | [F1] | A thread da interface nunca executa operação de rede ou de disco que possa exceder 16 ms. |
| RNF-PERF-02 | [F1] | Primeira janela utilizável em menos de 1,5 s a frio; lista populada do cache em menos de 500 ms para 10.000 mensagens. |
| RNF-PERF-03 | [F1] | Abertura de mensagem em cache em menos de 150 ms; fora do cache, retorno visual imediato e menos de 3 s em rede típica. |
| RNF-PERF-04 | [F1] | Busca em 50.000 mensagens em menos de 100 ms. |
| RNF-PERF-05 | [F1] | Consumo inferior a 400 MB de RSS com uma conta e uma mensagem aberta, **excluindo** os processos do motor de renderização, cujo custo é medido e declarado separadamente à parte. |

**CA-RNF-PERF-01-1** — Durante uma sincronização simulada de 5.000 mensagens, nenhuma operação submetida à thread da interface bloqueia por mais de 100 ms. Um teste instrumenta a thread principal com um temporizador de supervisão que falha ao detectar bloqueio superior a esse limite. Este teste é o guardião da afirmação central do projeto.

### 5.2 `SEC` — Segurança

| ID | Fase | Requisito |
|---|---|---|
| RNF-SEC-01 | [F1] | Credenciais residem exclusivamente no cofre do sistema operacional, nunca em banco, arquivo de configuração, log, histórico ou argumento de linha de comando. |
| RNF-SEC-02 | [F1] | Exigir TLS nas conexões de entrada e saída, validando o certificado do servidor; nunca degradar para texto claro de forma silenciosa. |
| RNF-SEC-03 | [F1] | Nunca executar conteúdo de e-mail: JavaScript permanentemente desabilitado, sem plugins, sem abertura automática de anexos. |
| RNF-SEC-04 | [F1] | Sanitizar nomes de arquivos de anexo, impedindo travessia de diretório, nomes reservados do sistema e sobrescrita fora da pasta de destino. |
| RNF-SEC-05 | [F1] | Restringir a permissão do banco, dos arquivos de configuração e dos anexos ao próprio usuário, onde o sistema operacional permitir. |
| RNF-SEC-06 | [F2] | Suportar assinatura e cifragem OpenPGP. |

**CA-RNF-SEC-01-1** — Após cadastrar uma conta, uma varredura do banco, dos arquivos de configuração e dos logs não encontra a senha em texto claro nem em forma reversível. O teste falha se o valor aparecer em qualquer um desses locais.
**CA-RNF-SEC-02-1** — Servidor com certificado autoassinado faz a conexão falhar com mensagem que explica o motivo do certificado; não há caminho de código que prossiga sem validação a menos que o usuário habilite a exceção de forma explícita e registrada.
**CA-RNF-SEC-04-1** — Anexos nomeados `../../evil.sh`, `CON`, `..\\..\\win.ini`, `arquivo com byte nulo` e nomes com 300 caracteres são gravados dentro da pasta de destino com nome sanitizado e unicidade garantida.

### 5.3 `PRIV` — Privacidade

| ID | Fase | Requisito |
|---|---|---|
| RNF-PRIV-01 | [F1] | Nenhuma requisição de rede é originada pelo conteúdo de uma mensagem sem consentimento explícito do usuário. |
| RNF-PRIV-02 | [F1] | Não coletar nem transmitir telemetria, métricas de uso ou identificadores de qualquer tipo. |
| RNF-PRIV-03 | [F1] | Bloquear pixels de rastreamento de forma irreversível e remover parâmetros de rastreamento de links. |
| RNF-PRIV-04 | [F1] | Manter a autorização de imagens por remetente, granular e revogável, gerenciável em um painel. |

**CA-RNF-PRIV-01-1** — Renderizar um corpus de mensagens com imagens, CSS remoto (`@import`, `url()`), `background` em estilo inline, `<picture>`/`srcset` e beacon de abertura produz exatamente zero requisições de rede, verificado pelo interceptor que registra toda tentativa. É a prova da proposta de valor do produto.

### 5.4 `COMP`, `REL`, `USA`, `A11Y`, `PACK`, `MAINT`

| ID | Fase | Requisito |
|---|---|---|
| RNF-COMP-01 | [F1] | Executar em Windows 10+, Ubuntu 22.04+/Debian 12+ e macOS 12+. |
| RNF-COMP-02 | [F1] | Exigir Python 3.11 ou superior; sem código específico de plataforma fora de pontos isolados e documentados. |
| RNF-REL-01 | [F1] | Falha de rede ou de servidor jamais causa perda de rascunho, de mensagem na fila de envio ou de dado do usuário. |
| RNF-REL-02 | [F1] | O cache local é descartável por definição e deve poder ser reconstruído a partir do servidor sem intervenção manual. |
| RNF-USA-01 | [F1] | Toda operação destrutiva exige confirmação ou oferece desfazer. |
| RNF-USA-02 | [F1] | Feedback de toda ação em menos de 100 ms, mesmo quando o resultado final depende da rede. |
| RNF-A11Y-01 | [F1] | Navegação completa por teclado, foco sempre visível e contraste mínimo AA nas duas folhas de estilo. |
| RNF-PACK-01 | [F1] | Empacotar com PyInstaller em modo diretório para as três plataformas, com o tamanho real de cada artefato medido e documentado, excluindo módulos Qt não utilizados. |
| RNF-PACK-02 | [F1] | Não exigir privilégios administrativos para instalar nem para executar. |
| RNF-MAINT-01 | [F1] | Manter cobertura de testes automatizados igual ou superior a 80% em `core/`, com foco em sanitização, armazenamento, fila de envio e análise de mensagens. |
| RNF-MAINT-02 | [F1] | Aplicar formatação e análise estática (`ruff format`, `ruff check`) sem avisos no código entregue. |

**CA-RNF-PACK-01-1** — O instalador de cada plataforma tem o tamanho medido e registrado neste documento quando a fase 1 for concluída; a diferença entre o pacote com e sem os módulos Qt excluídos é reportada, tornando o custo do motor de renderização explícito em vez de suposto.

---

## 6. Limitações conhecidas e aceitas da fase 1

Registradas aqui de propósito: são consequências conscientes das decisões D2 e D3, não defeitos a descobrir em produção.

1. **Contas Microsoft 365 e Outlook.com não conectam na fase 1.** A autenticação básica em IMAP/SMTP foi descontinuada pela Microsoft; OAuth2 é obrigatório e chega na fase 2 (RF-ACC-06). Contas Google e demais servidores IMAP funcionam com app password/senha.
2. **O instalador é grande.** O motor de renderização responde por aproximadamente 150 a 200 MB do pacote (RNF-PACK-01 mede esse número). É o preço aceito para renderizar HTML moderno sem quebrar e para bloquear rastreamento de forma confiável.
3. **O consumo de memória cresce com o motor de renderização.** Cada conta com mensagem aberta mantém processos adicionais, medidos à parte de RNF-PERF-05. Não é possível ser simultaneamente fiel a HTML moderno e econômico em memória.
4. **Sem assinatura ou cifragem de ponta a ponta.** Não há OpenPGP nem S/MIME na fase 1.
5. **Detecção de novas mensagens depende do servidor.** Sem `IDLE`, a latência é a do intervalo de verificação configurado.

---

## 7. Fora de escopo

Explicitamente **não** será feito, nem na fase 1 nem na fase 2, sem uma nova decisão registrada:

- Calendário e contatos (CalDAV/CardDAV) — este é um cliente de e-mail.
- Sistema de plugins ou extensões de terceiros.
- `Exchange ActiveSync`, `JMAP` e protocolos proprietários além de IMAP, POP3 e SMTP.
- Aplicativo móvel ou versão web.
- Regras e filtros de servidor gerenciados pelo cliente.
- Cifragem do banco local em repouso (as credenciais já estão no keyring; cifrar o cache é um problema diferente, com custo de desempenho relevante).
- Sincronização do estado entre máquinas.

---

## 8. Matriz de rastreabilidade

Cada requisito aponta para seu critério de aceite e para a tarefa do plano de implementação. A coluna "Verificação" indica como o critério é comprovado: `T` teste automatizado, `M` procedimento manual documentado.

| Requisito | Fase | Critérios de aceite | Verificação | Tarefa em `docs/plans/fase1.md` |
|---|---|---|---|---|
| RF-ACC-01 | F1 | CA-RF-ACC-01-1 | T | T-03, T-04 |
| RF-ACC-02 | F1 | CA-RF-ACC-02-1 | T | T-02, T-18 |
| RF-ACC-03 | F1 | CA-RF-ACC-03-1 | T | T-04 |
| RF-ACC-04 | F1 | CA-RF-ACC-04-1 | T | T-03 |
| RF-ACC-05 | F1 | CA-RF-ACC-05-1 | T | T-19 |
| RF-MSG-01 | F1 | CA-RF-MSG-01-1, CA-RF-MSG-01-2 | T | T-10, T-11 |
| RF-MSG-02 | F1 | CA-RF-MSG-02-1 | T | T-12 |
| RF-MSG-03 | F1 | — | T | T-13 |
| RF-MSG-04 | F1 | CA-RF-MSG-04-1 | T | T-11 |
| RF-MSG-05 | F1 | — | T | T-14 |
| RF-MSG-06 | F1 | CA-RF-MSG-06-1 | T | T-09 |
| RF-MSG-07 | F1 | — | T | T-21 |
| RF-MSG-08 | F1 | CA-RF-MSG-08-1 | T | T-15 |
| RF-MSG-09 | F1 | CA-RF-MSG-09-1 | T | T-16 |
| RF-RD-01 | F1 | CA-RF-RD-01-1 | T | T-05 |
| RF-RD-02 | F1 | — | T | T-06 |
| RF-RD-03 | F1 | CA-RF-RD-03-1, CA-RF-RD-03-2 | T | T-07, T-22 |
| RF-RD-04 | F1 | CA-RF-RD-04-1 | T | T-05, T-07 |
| RF-RD-05 | F1 | — | T | T-05 |
| RF-RD-06 | F1 | CA-RF-RD-06-1 | T | T-07, T-20 |
| RF-RD-07 | F1 | CA-RF-RD-07-1 | T | T-20 |
| RF-RD-08 | F1 | — | M | T-23 |
| RF-RD-09 | F1 | — | T | T-12 |
| RF-SND-01 | F1 | — | T | T-24 |
| RF-SND-02 | F1 | — | T | T-25 |
| RF-SND-03 | F1 | CA-RF-SND-03-1, CA-RF-SND-03-2 | T | T-27, T-28 |
| RF-SND-04 | F1 | CA-RF-SND-04-1 | T | T-26, T-29 |
| RF-SND-05 | F1 | CA-RF-SND-05-1 | T | T-30 |
| RF-SND-06 | F1 | — | T | T-24 |
| RF-SND-07 | F1 | CA-RF-SND-07-1 | T | T-27 |
| RF-SND-08 | F1 | — | T | T-24 |
| RF-SRCH-01 | F1 | CA-RF-SRCH-01-1 | T | T-08 |
| RF-SRCH-02 | F1 | CA-RF-SRCH-02-1 | T | T-31 |
| RF-SRCH-03 | F1 | — | T | T-31 |
| RF-SRCH-04 | F1 | CA-RF-SRCH-04-1 | T | T-08 |
| RF-SRCH-05 | F1 | CA-RF-SRCH-05-1 | T | T-08 |
| RF-ORG-01 | F1 | CA-RF-ORG-01-1 | T | T-17 |
| RF-ORG-02 | F1 | — | T | T-17 |
| RF-ORG-03 | F1 | — | T | T-17 |
| RF-ORG-04 | F1 | CA-RF-ORG-04-1 | T | T-17 |
| RF-ORG-05 | F1 | CA-RF-ORG-05-1 | T | T-17 |
| RF-UI-01 | F1 | — | M | T-32 |
| RF-UI-02 | F1 | — | T | T-33 |
| RF-UI-03 | F1 | CA-RF-UI-03-1 | T | T-34 |
| RF-UI-04 | F1 | CA-RF-UI-04-1 | T | T-34 |
| RF-UI-05 | F1 | CA-RF-UI-05-1 | T | T-35 |
| RF-UI-06 | F1 | CA-RF-UI-06-1 | T | T-36 |
| RF-UI-07 | F1 | — | M | T-32 |
| RF-UI-08 | F1 | — | T | T-15 |
| RF-UI-09 | F1 | — | M | T-35 |
| RF-UI-10 | F1 | — | M | T-33 |
| RF-UI-11 | F1 | — | T | T-35 |
| RF-SET-01 | F1 | — | T | T-01 |
| RF-SET-02 | F1 | — | T | T-01 |
| RF-SET-03 | F1 | CA-RF-SET-03-1 | T | T-02 |
| RF-SET-04 | F1 | CA-RF-SET-04-1 | T | T-37 |
| RF-SET-05 | F1 | CA-RF-SET-05-1 | T | T-38 |
| RNF-PERF-01 | F1 | CA-RNF-PERF-01-1 | T | T-39 |
| RNF-PERF-02 | F1 | — | T | T-39 |
| RNF-PERF-03 | F1 | — | T | T-12, T-39 |
| RNF-PERF-04 | F1 | CA-RF-SRCH-02-1 | T | T-31, T-39 |
| RNF-PERF-05 | F1 | — | M | T-39 |
| RNF-SEC-01 | F1 | CA-RNF-SEC-01-1 | T | T-03, T-37 |
| RNF-SEC-02 | F1 | CA-RNF-SEC-02-1 | T | T-04, T-27 |
| RNF-SEC-03 | F1 | CA-RF-RD-01-1 | T | T-05, T-07 |
| RNF-SEC-04 | F1 | CA-RNF-SEC-04-1 | T | T-21 |
| RNF-SEC-05 | F1 | — | T | T-02 |
| RNF-PRIV-01 | F1 | CA-RNF-PRIV-01-1 | T | T-07 |
| RNF-PRIV-02 | F1 | — | T | T-37 |
| RNF-PRIV-03 | F1 | CA-RF-RD-04-1 | T | T-05 |
| RNF-PRIV-04 | F1 | CA-RF-RD-03-2 | T | T-22 |
| RNF-COMP-01 | F1 | — | M | T-40 |
| RNF-COMP-02 | F1 | — | T | T-01 |
| RNF-REL-01 | F1 | CA-RF-SND-04-1 | T | T-26 |
| RNF-REL-02 | F1 | CA-RF-SET-05-1 | T | T-38 |
| RNF-USA-01 | F1 | — | M | T-19, T-33 |
| RNF-USA-02 | F1 | — | T | T-16 |
| RNF-A11Y-01 | F1 | — | M | T-36 |
| RNF-PACK-01 | F1 | CA-RNF-PACK-01-1 | M | T-40 |
| RNF-PACK-02 | F1 | — | M | T-40 |
| RNF-MAINT-01 | F1 | — | T | T-41 |
| RNF-MAINT-02 | F1 | — | T | T-01, T-41 |

**Cobertura verificada:** 81 linhas na matriz, todas de fase 1, sem requisito duplicado e sem ID órfão. Os **14 requisitos de fase 2** (`RF-ACC-06/07/08`, `RF-MSG-10/11/12`, `RF-ORG-06/07`, `RF-RD-10`, `RF-SET-06`, `RF-SND-09`, `RF-SRCH-06`, `RF-UI-12`, `RNF-SEC-06`) estão definidos nas seções 4 e 5 mas **não** constam da matriz, porque ainda não têm tarefa de implementação: eles entram nela quando a fase 2 for planejada. Total do documento: 95 requisitos.

---

## 8.1 Critérios de aceite complementares

Estes requisitos foram deixados sem critério de aceite na primeira redação deste documento — o que **contrariava a regra da seção 2** e foi apontado na revisão cruzada pelos documentos `04-ui-ux.md` (L-11) e `06-estrategia-de-testes.md` (L-02, L-07, L-11, L-16, L-18). Os critérios abaixo os tornam verificáveis, e as células marcadas com `—` na matriz da seção 8 passam a corresponder às linhas desta tabela.

| Requisito | Critério de aceite | Verificação |
|---|---|---|
| RNF-PERF-01 | **CA-RNF-PERF-01-1a — relação entre os dois números, que não são contraditórios.** 16 ms é o **orçamento de projeto por operação** despachada da thread da GUI: nenhuma operação individual deve se aproximar disso. 100 ms é o **limite observável do teste**, que precisa tolerar ruído de escalonamento e os bloqueios curtos e inevitáveis. A asserção é: nenhum intervalo entre disparos consecutivos de um `QTimer` de 10 ms na thread principal excede 100 ms durante uma sincronização de 5.000 mensagens | T |
| RNF-PERF-02 | **CA-RNF-PERF-02-1** — Primeira janela utilizável em menos de 1,5 s a frio (processo novo, cache de disco frio); lista populada do cache em menos de 500 ms para 10.000 mensagens | T |
| RNF-PERF-03 | **CA-RNF-PERF-03-1** — Mensagem em cache exibe conteúdo em menos de 150 ms; mensagem fora do cache exibe cabeçalho e estado de carregamento em menos de 100 ms, com conteúdo em menos de 3 s | T |
| RNF-PERF-05 | **CA-RNF-PERF-05-1** — RSS do processo principal abaixo de 400 MB com uma conta e uma mensagem aberta; o consumo dos processos do motor de renderização é medido e registrado **separadamente**, no mesmo relatório | M |
| RF-MSG-03 | **CA-RF-MSG-03-1** — Após abrir uma mensagem, no máximo 5 `FETCH` de corpo são emitidos, todos para as mensagens imediatamente posteriores na ordem da lista. Navegar para outra mensagem antes de concluir cancela os pendentes, comprovado pelo registro do servidor falso | T |
| RF-MSG-05 | **CA-RF-MSG-05-1** — Com servidor que anuncia `IDLE`, nova mensagem aparece na lista em menos de 5 s. Com servidor que recusa `IDLE`, o cliente não repete `IDLE` na mesma sessão e passa a `NOOP` no intervalo configurado, sem exibir erro ao usuário | T |
| RF-MSG-07 | **CA-RF-MSG-07-1** — Sincronizar pasta com mensagens que têm anexos emite **zero** comandos de busca de parte de anexo. O conteúdo só é requisitado após ação explícita, e o arquivo é gravado dentro da pasta de destino configurada | T |
| RF-RD-02 | **CA-RF-RD-02-1** — Mensagem apenas `text/plain` é exibida sem passar pelo motor de HTML. Mensagem apenas HTML produz `text_plain` não vazio, com entidades decodificadas, usado na pré-visualização e no índice de busca | T |
| RF-RD-05 | **CA-RF-RD-05-1** — Links contendo `utm_*`, `fbclid`, `gclid`, `mc_eid`, `_hsenc`, `_hsmi`, `vero_id` ou `igshid` são reescritos sem esses parâmetros, preservando os demais parâmetros e a ordem relativa dos que ficam | T |
| RF-RD-08 | **CA-RF-RD-08-1** — `Ctrl` `+`/`-` alteram o zoom em passos fixos dentro da faixa 0,5–3,0; `Ctrl` `0` volta a 1,0; o valor é gravado em `config.toml` e reaplicado na sessão seguinte. **Ambiguidade resolvida:** o zoom é um **padrão global do aplicativo**, não um estado por mensagem | T |
| RF-RD-09 | **CA-RF-RD-09-1** — Abrir e fechar uma mensagem antes do atraso configurado não a marca como lida, nem no cache nem no servidor. Permanecer além do atraso emite `STORE +FLAGS \Seen` **uma única vez**. Com o comportamento desativado, nenhum `STORE` é emitido | T |
| RF-SND-01 | **CA-RF-SND-01-1** — O compositor coleta Para, Cc, Cco, assunto, corpo em texto e/ou HTML e anexos; `to_draft()` produz o objeto sem abrir conexão de rede nem conhecer SMTP | T |
| RF-SND-02 | **CA-RF-SND-02-1** — Responder endereça o remetente; responder a todos exclui os endereços próprios do usuário e remove duplicatas; encaminhar não preenche destinatários e inclui o corpo original citado. `In-Reply-To` e `References` são preenchidos de forma que a resposta apareça encadeada no cliente do destinatário | T |
| RF-SND-06 | **CA-RF-SND-06-1** — Anexo acima de 20 MB (valor configurável) faz o envio ser recusado sem confirmação explícita; após confirmar, o envio prossegue | T |
| RF-SND-08 | **CA-RF-SND-08-1** — Ausência de assunto ou de destinatário produz alerta que **permite** prosseguir; não bloqueia o envio | T |
| RF-SRCH-03 | **CA-RF-SRCH-03-1** — Cada filtro (conta, pasta, período, não lidos, com anexo, remetente) restringe o resultado isoladamente e em combinação com a consulta textual, sem retornar itens que violem qualquer filtro ativo | T |
| RF-ORG-01 | **CA-RF-ORG-01-2** — A pasta de arquivo é descoberta por nome remoto, com candidatos em ordem (`Archive`, `Arquivo`, `Arquivos`, `All Mail`); se nenhum existir, é criada. A escolha é registrada por conta e reutilizada nas ações seguintes | T |
| RF-ORG-02 | **CA-RF-ORG-02-1** — A mensagem sai da pasta atual e aparece na pasta de lixeira do servidor, por `UID MOVE` quando disponível | T |
| RF-ORG-03 | **CA-RF-ORG-03-1** — Alternar lido/não lido e sinalizado reflete na interface antes da resposta do servidor e emite o `STORE` correspondente em `\Seen` e `\Flagged`, sem afetar outras flags | T |
| RF-UI-01 | **CA-RF-UI-01-1** — A janela contém três colunas distintas (contas/pastas, lista, leitor) com as larguras de `04-ui-ux.md` §3, redimensionáveis e com larguras mínimas respeitadas | M |
| RF-UI-02 | **CA-RF-UI-02-1** — Colapsar a coluna de contas/pastas reduz a largura para o valor de `04-ui-ux.md` §3 e o estado persiste entre sessões | T |
| RF-UI-07 | **CA-RF-UI-07-1** — Cada estado (vazio, carregando, erro, offline) exibe texto explicativo não vazio e uma ação sugerida quando aplicável; nenhuma área fica em branco sem explicação | M |
| RF-UI-09 | **CA-RF-UI-09-1** — Alternar a densidade altera a altura da linha para exatamente 72 px (confortável) ou 48 px (compacta), conforme `04-ui-ux.md` §2, e persiste entre sessões | T |
| RF-UI-10 | **CA-RF-UI-10-1** — Cada conta em sincronização exibe progresso próprio na barra lateral; ao concluir, o indicador desaparece. Falha exibe estado de erro distinguível do estado ocioso | M |
| RF-UI-11 | **CA-RF-UI-11-1** — Cada item da lista exibe remetente, assunto, trecho de pré-visualização e data/hora, e indica de forma distinguível não lido, sinalizado e presença de anexo | T |
| RNF-SEC-05 | **CA-RNF-SEC-05-1** — Em Linux e macOS, o banco e os arquivos de configuração têm modo 0600 e o diretório de dados 0700. Em Windows, são gravados sob o perfil do usuário sem permissão para `Everyone` | T |
| RNF-PRIV-02 | **CA-RNF-PRIV-02-1** — Uma sessão completa (cadastrar conta, sincronizar, abrir, buscar, enviar) não origina **nenhuma** conexão de saída para host que não seja um servidor de correio configurado pelo usuário nem `localhost`. Verificado por gravador de rede que registra todo destino | T |
| RNF-A11Y-01 | **CA-RNF-A11Y-01-1** — Todo par texto/fundo dos tokens de ambos os temas atinge contraste calculado ≥ 4,5:1 (texto normal) e ≥ 3:1 (texto grande); o indicador de foco tem espessura mínima de 2 px e é visível nos dois temas. Exceções, se houver, são declaradas nominalmente em `04-ui-ux.md` §2 | T |
| RNF-COMP-01 | **CA-RNF-COMP-01-1** — A suíte completa passa em Windows 10+, Ubuntu 22.04+ e macOS 12+ na matriz de CI, e o instalador é gerado nas três plataformas | M |
| RNF-COMP-02 | **CA-RNF-COMP-02-1** — Uma busca por `sys.platform`, `os.name` e `platform.system()` no código encontra ocorrências apenas nos pontos isolados e documentados de `02-arquitetura.md`; nenhuma outra ramificação por plataforma existe | T |
| RNF-REL-01 | **CA-RNF-REL-01-1** — Duas garantias distintas, ambas exigidas: (a) mensagem enfileirada para envio sobrevive a encerramento abrupto; (b) **rascunho em composição** com mais de N caracteres (ou alterado há mais de 5 s) é persistido automaticamente e recuperado na reabertura. Teste (b) encerra o processo com o compositor aberto e verifica a recuperação | T |
| RNF-USA-01 | **CA-RNF-USA-01-1** — Arquivar e excluir oferecem desfazer por 10 s, com um desfazer ativo por vez (o mais recente); remover conta exige digitação de confirmação; nenhuma ação destrutiva ocorre sem confirmação ou desfazer disponível | T |
| RNF-MAINT-01 | **CA-RNF-MAINT-01-1** — Cobertura medida por `--cov=pymail_client.core` ≥ 80%. Exclusões declaradas: `if TYPE_CHECKING`, `raise NotImplementedError`, blocos `pragma: no cover` justificados em comentário. A medição e o método são os de `06-estrategia-de-testes.md` §9 | T |
| RNF-MAINT-02 | **CA-RNF-MAINT-02-1** — Portão de processo, não teste de unidade: `ruff check` e `ruff format --check` retornam zero avisos no CI. Considerar isto um teste era classificação equivocada na redação anterior | M |

---

## 9. Critério de conclusão da fase 1

A fase 1 está concluída quando, e somente quando, todas as afirmações abaixo forem verdadeiras e comprovadas:

1. Suíte de testes verde, com cobertura de `core/` ≥ 80%.
2. `CA-RNF-PERF-01-1` passando — a interface não bloqueia.
3. `CA-RNF-PRIV-01-1` passando — zero requisições de rede originadas por conteúdo de mensagem.
4. Um usuário consegue, sem tocar no mouse: cadastrar uma conta, sincronizar, ler, buscar, arquivar, responder e enviar com undo.
5. Tamanho e consumo de memória reais medidos e escritos em `02-arquitetura.md`, substituindo as estimativas desta spec.
