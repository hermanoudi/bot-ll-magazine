# Deploy e operação

O bot usa **long polling** do Telegram (não precisa de domínio, porta pública nem HTTPS). A stack tem 4 serviços: `bot`, `evolution-api` (WhatsApp), `postgres` e `redis`.

> **Antes de qualquer deploy:** pare o bot que roda na sua máquina. Só uma instância pode fazer polling com o mesmo token; senão aparece `Conflict: terminated by other getUpdates request`.

## Qual escolher

| | VPS (recomendado) | Railway |
|---|---|---|
| Esforço | `docker compose up`, igual ao local | 4 serviços + volumes montados à mão |
| Custo | ~R$ 25–40/mês (1 vCPU / 2 GB) | ~US$ 5–15/mês, varia com o uso |
| Sessão do WhatsApp | Volume Docker, simples | Precisa de volume no serviço Evolution |
| Painel/QR code | Fica em 127.0.0.1, acesso por túnel SSH | Precisa de domínio público (proteja com a API key) |

A Evolution API guarda a sessão do WhatsApp; se perder o volume/banco, é preciso ler o QR code de novo. Por isso a VPS é mais simples.

---

## Opção A: VPS (Ubuntu 22.04/24.04)

### 1. Preparar o servidor

```bash
ssh root@IP_DA_VPS
adduser deploy && usermod -aG sudo deploy
ssh-copy-id deploy@IP_DA_VPS     # rode no seu computador para copiar sua chave SSH
curl -fsSL https://get.docker.com | sh
usermod -aG docker deploy
ufw allow OpenSSH && ufw enable        # não abra a porta 8080
```

Reconecte como `deploy`.

### 2. Baixar o projeto

```bash
git clone https://github.com/SEU_USUARIO/bot-llmagazine.git
cd bot-llmagazine
```

### 3. Configurar `.env` e `sites.yaml`

```bash
cp .env.example .env
cp sites.example.yaml sites.yaml
```

Preencha o `.env`:

- `TELEGRAM_BOT_TOKEN`
- `LLMAGAZINE_URL`, `LLMAGAZINE_USER`, `LLMAGAZINE_PASS`
- `LLMAGAZINE_WHATSAPP` (número da loja, só dígitos com DDI) e, depois, `LLMAGAZINE_WHATSAPP_GROUP`
- `GOOGLE_API_KEY`
- `EVOLUTION_API_KEY` → `openssl rand -hex 24`
- `POSTGRES_PASSWORD` → `openssl rand -hex 16`

No `sites.yaml`, ajuste `allowed_user_ids` com os Telegram IDs autorizados.

### 4. Subir

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f bot
```

### 5. Criar a instância do WhatsApp (uma vez)

```bash
set -a; source .env; set +a
curl -X POST http://127.0.0.1:8080/instance/create \
  -H "apikey: $EVOLUTION_API_KEY" -H 'Content-Type: application/json' \
  -d '{"instanceName":"llmagazine","qrcode":true,"integration":"WHATSAPP-BAILEYS"}'
```

### 6. Ler o QR code (túnel SSH, a porta 8080 não é pública)

No **seu computador**:

```bash
ssh -L 8080:127.0.0.1:8080 deploy@IP_DA_VPS
```

Abra `http://127.0.0.1:8080/manager`, entre com a `EVOLUTION_API_KEY`, abra a instância `llmagazine` e leia o QR no WhatsApp da loja (Aparelhos conectados → Conectar um aparelho).

### 7. Pegar o ID do grupo

No Telegram, envie `/grupos` ao bot (aceita filtro: `/grupos nome`). Copie o ID (`...@g.us`) para `LLMAGAZINE_WHATSAPP_GROUP` no `.env` e reinicie:

```bash
docker compose up -d bot
```

### 8. Testar

`/novo` no Telegram, cadastre um produto de teste e use "📤 Enviar ao grupo".

### Manutenção

```bash
git pull && docker compose up -d --build     # atualizar
docker compose logs -f bot                    # logs
docker compose restart bot                    # reiniciar
```

Todos os serviços têm `restart: unless-stopped`, então voltam sozinhos após reboot. Faça backup do volume `postgres_data` se não quiser reler o QR code em caso de perda (`docker compose exec postgres pg_dump -U evolution evolution > backup.sql`).

---

## Opção B: Railway

O Railway não executa o `docker-compose.yml` como está; crie cada serviço no mesmo projeto.

### 1. Preparar o repositório

`sites.yaml` só tem referências `${VAR}` (sem segredos), então pode ir para o Git: remova-o do `.gitignore` e faça commit. O compose monta esse arquivo como volume, e no Railway ele precisa estar dentro da imagem. Adicione ao `Dockerfile`, antes do `CMD`:

```dockerfile
COPY sites.yaml ./sites.yaml
```

Confira que `.env` continua fora do Git.

### 2. Criar o projeto

1. railway.com → **New Project** → **Deploy from GitHub repo** → escolha o repositório. Este é o serviço **bot** (usa o `Dockerfile`).
2. **+ New → Database → PostgreSQL**.
3. **+ New → Database → Redis**.
4. **+ New → Docker Image** → `evoapicloud/evolution-api:v2.3.7`. Este é o serviço **evolution-api**.

### 3. Variáveis do serviço `evolution-api`

```
SERVER_URL=https://${{RAILWAY_PUBLIC_DOMAIN}}
AUTHENTICATION_API_KEY=<openssl rand -hex 24>
DATABASE_PROVIDER=postgresql
DATABASE_CONNECTION_URI=${{Postgres.DATABASE_URL}}
DATABASE_SAVE_DATA_INSTANCE=true
DATABASE_SAVE_DATA_NEW_MESSAGE=false
DATABASE_SAVE_MESSAGE_UPDATE=false
DATABASE_SAVE_DATA_CONTACTS=false
DATABASE_SAVE_DATA_CHATS=false
DATABASE_SAVE_DATA_LABELS=false
DATABASE_SAVE_DATA_HISTORIC=false
CACHE_REDIS_ENABLED=true
CACHE_REDIS_URI=${{Redis.REDIS_URL}}/6
CACHE_REDIS_PREFIX_KEY=evolution
CACHE_REDIS_SAVE_INSTANCES=false
CACHE_LOCAL_ENABLED=false
PORT=8080
```

(`Postgres` e `Redis` são os nomes dos serviços; ajuste se renomeou. Se a Evolution reclamar do `?schema=public`, acrescente-o ao fim da URL.)

Em **Settings**: adicione um **Volume** montado em `/evolution/instances` e gere um **domínio público** (porta 8080), necessário para ler o QR code.

### 4. Variáveis do serviço `bot`

Cole as variáveis do `.env` (token, site, `GOOGLE_API_KEY`) e acrescente:

```
SITES_CONFIG=sites.yaml
EVOLUTION_URL=http://evolution-api.railway.internal:8080
EVOLUTION_INSTANCE=llmagazine
EVOLUTION_API_KEY=<a mesma do evolution-api>
LLMAGAZINE_WHATSAPP_GROUP=<preencher no passo 6>
```

O bot não precisa de domínio público nem de porta.

### 5. Criar instância e ler o QR

```bash
curl -X POST https://DOMINIO_DA_EVOLUTION/instance/create \
  -H "apikey: SUA_EVOLUTION_API_KEY" -H 'Content-Type: application/json' \
  -d '{"instanceName":"llmagazine","qrcode":true,"integration":"WHATSAPP-BAILEYS"}'
```

Abra `https://DOMINIO_DA_EVOLUTION/manager`, entre com a API key e leia o QR.

### 6. ID do grupo

`/grupos` no bot → copie o ID para `LLMAGAZINE_WHATSAPP_GROUP` no serviço `bot` (o Railway reimplanta sozinho).

### 7. Segurança

O domínio público expõe a Evolution API. A API key protege, mas depois de conectar o WhatsApp você pode **remover o domínio público** (o bot usa a rede interna) e recriá-lo só quando precisar de um novo QR.

---

## Cadastrar outra pessoa no Telegram

1. A pessoa abre o Telegram, procura **@userinfobot**, envia `/start` e anota o número do `Id`.
2. Edite `sites.yaml`:

   ```yaml
   allowed_user_ids: [123456789, 987654321]   # o seu + o da nova pessoa
   ```

3. Reinicie o bot (a lista é lida só na inicialização):
   - VPS: `docker compose restart bot`
   - Railway: faça commit/push do `sites.yaml` (reimplanta sozinho).
4. A pessoa abre o seu bot no Telegram, envia `/start` e depois `/novo` (ou uma foto).

Para remover alguém, tire o ID da lista e reinicie. Todos cadastram usando o mesmo usuário admin do site; o bot não distingue quem criou o produto no painel.

---

## Trocar o WhatsApp que posta (outro número)

1. **Desconecte o atual** (VPS: acesse com o túnel SSH; Railway: use o domínio público):

   ```bash
   curl -X DELETE http://127.0.0.1:8080/instance/logout/llmagazine -H "apikey: $EVOLUTION_API_KEY"
   ```

   Se o número antigo ainda estiver ativo, ele também pode ser desconectado em WhatsApp → Aparelhos conectados.

2. **Recrie a instância e leia o QR** com o novo número: se o `logout` deixou a instância no ar, abra o `/manager` e gere um novo QR. Se a instância sumiu, rode o `instance/create` dos passos acima.
3. **Coloque o novo número no grupo de clientes.** Se o grupo só permite admins enviarem mensagens, torne-o admin.
4. **Pegue o ID do grupo de novo** com `/grupos nome`. O ID costuma ser o mesmo, mas confira.
5. Atualize no `.env` (ou nas variáveis do Railway):
   - `LLMAGAZINE_WHATSAPP_GROUP` (se mudou)
   - `LLMAGAZINE_WHATSAPP` (número exibido no link "Chamar no WhatsApp" do post; use o da loja)
6. `docker compose up -d bot` (ou aguarde a reimplantação no Railway).
7. Teste com um cadastro e "📤 Enviar ao grupo".

> `LLMAGAZINE_WHATSAPP` (número que os clientes chamam) e o número conectado na Evolution (quem posta no grupo) são coisas independentes: podem ser o mesmo ou diferentes.

**Riscos:** a Evolution API não é oficial e o WhatsApp pode bloquear o número. Use um número da loja (não o pessoal), com poucos envios por dia.

---

## Problemas comuns

| Sintoma | Causa / solução |
|---|---|
| `Conflict: terminated by other getUpdates` | Outro bot com o mesmo token está rodando (local, outra VPS). Pare-o. |
| Envio ao grupo demora e dá timeout | Instância desconectada. Leia o QR de novo. |
| `/grupos` demora | Contas com muitos grupos levam ~40 s na primeira sincronização. Use o filtro `/grupos nome`. |
| Pessoa nova não recebe resposta | O ID não está em `allowed_user_ids`, ou o bot não foi reiniciado. |
| Perdeu a sessão após rebuild | O volume `evolution_instances` ou o `postgres_data` foi apagado (`docker compose down -v`). Nunca use `-v`. |
