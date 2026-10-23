# bot-llmagazine

Bot do Telegram que cadastra produtos em sites via API de admin. Você envia a foto, o bot valida a imagem, a IA sugere os campos, ele pergunta o que faltar e cadastra. **Nada é fixo no código**: tudo de um site vem do `sites.yaml`, então o mesmo bot atende outros sites com o mesmo padrão de API (login → upload de imagem → criação do produto).

## Ambiente de desenvolvimento

### Pré-requisitos

- Python 3.12+ e [uv](https://docs.astral.sh/uv/)
- Docker e Docker Compose (só para testar a divulgação no WhatsApp)
- Um bot do Telegram, um usuário admin no site e uma chave da IA (Gemini)

### Passo a passo

1. Crie o bot no [@BotFather](https://t.me/BotFather) e copie o token.
2. No site, crie um usuário admin dedicado ao bot (tabela `admin_users` do llmagazine-page).
3. Clone o repositório e instale as dependências:

   ```bash
   git clone https://github.com/hermanoudi/bot-ll-magazine.git
   cd bot-ll-magazine
   uv sync
   ```

4. Crie os arquivos de configuração:

   ```bash
   cp .env.example .env
   cp sites.example.yaml sites.yaml
   ```

   - `.env`: `TELEGRAM_BOT_TOKEN`, `LLMAGAZINE_URL`, `LLMAGAZINE_USER`, `LLMAGAZINE_PASS` e `GOOGLE_API_KEY`.
   - `sites.yaml`: `allowed_user_ids` com os Telegram IDs autorizados (use o [@userinfobot](https://t.me/userinfobot) para descobrir o seu).
   - Ambos estão no `.gitignore`; nunca faça commit de segredos.

5. Rode o bot:

   ```bash
   uv run python -m productbot.main
   ```

   Use `LOG_LEVEL=DEBUG` para logs mais detalhados. O bot usa polling, então não precisa de domínio nem de porta aberta. Só uma instância pode rodar por token: pare outras (VPS, Docker) antes.

6. No Telegram: `/novo` (ou envie direto uma foto). `/cancelar` interrompe.

### Testes

```bash
uv run pytest
```

### Rodando com Docker

```bash
docker compose up -d --build   # bot + Evolution API + Postgres + Redis
docker compose logs -f bot
```

Para desenvolver só o bot em Python e usar a Evolution API do Docker, suba apenas ela (`docker compose up -d evolution-api`) e mantenha `EVOLUTION_URL=http://localhost:8080` no `.env`. Veja [Divulgação no WhatsApp](#divulgação-no-whatsapp) para conectar o número.

Para publicar em VPS ou Railway, trocar o WhatsApp da loja ou liberar outra pessoa no Telegram, veja [docs/DEPLOY.md](docs/DEPLOY.md).

## Adicionar outro site

Acrescente uma entrada em `sites:` no `sites.yaml` com `base_url`, `auth`, `upload`, `create`, regras de `image` e a lista de `fields`. Tipos de campo: `text`, `price`, `int`, `bool`, `choice` (fixo em `options` ou vindo da API em `options_from`), `multichoice`, `colors`. Veja `sites.example.yaml`.

Segredos usam `${VAR}` e são lidos do ambiente; não coloque senhas no YAML.

## IA (opcional)

Usa LangChain (`init_chat_model`), então o modelo é só configuração: `ai.provider` e `ai.model`. O padrão é Gemini (`google_genai`, `gemini-2.5-flash`). Para trocar, ajuste o YAML e instale o pacote do provedor (ex.: `uv add langchain-openai`). Se a IA falhar ou estiver desligada (`ai.enabled: false`), o bot pergunta campo a campo.

## Divulgação no WhatsApp

Com o bloco `share:` no site (veja `sites.example.yaml`), depois do cadastro o bot oferece divulgar o produto. Ele monta o post (foto, chamada criativa gerada pela IA, nome, preço, link do WhatsApp da loja com a mensagem pronta e aviso de urgência) e mostra a prévia. "Outra chamada" gera nova frase; sem IA, usa `fallback_headlines`. "📤 Enviar ao grupo" posta foto + texto no grupo de clientes. Sem `share:`, a pergunta não aparece.

O envio usa a [Evolution API](https://github.com/EvolutionAPI/evolution-api) (não oficial, self-hosted), que sobe junto com o bot no `docker-compose.yml` (com Postgres e Redis):

1. No `.env`, defina `EVOLUTION_API_KEY` e `POSTGRES_PASSWORD` (`openssl rand -hex 24`) e mantenha `EVOLUTION_INSTANCE`. Copie o bloco `whatsapp:` e o `share.group_id` do `sites.example.yaml` para o `sites.yaml`.
2. `docker compose up -d --build`. A Evolution API fica em `http://127.0.0.1:8080` (só local; o bot a acessa por `http://evolution-api:8080`).
3. Crie a instância (uma vez): `curl -X POST http://127.0.0.1:8080/instance/create -H "apikey: $EVOLUTION_API_KEY" -H 'Content-Type: application/json' -d '{"instanceName":"llmagazine","qrcode":true,"integration":"WHATSAPP-BAILEYS"}'`.
4. Abra `http://127.0.0.1:8080/manager`, entre com a `EVOLUTION_API_KEY`, abra a instância e leia o QR code com o WhatsApp da loja (Aparelhos conectados). Enquanto não estiver conectada, os envios ficam pendurados até dar timeout.
5. No bot, envie `/grupos` para listar os grupos do número com seus IDs e copie o do grupo de clientes para `LLMAGAZINE_WHATSAPP_GROUP` no `.env`. Reinicie o bot: `docker compose up -d bot`.

Sem `whatsapp:` ou sem `group_id`, o botão de enviar não aparece e o post fica só como prévia para copiar. Por ser uma API não oficial, há algum risco de bloqueio do número; com poucos envios por dia ele é baixo, mas não é zero. Use um número da loja, não o pessoal.

## Imagens

Validadas contra `image:` do site: formatos, tamanho máximo e dimensões mínimas. Formatos não aceitos são convertidos e imagens grandes são recomprimidas quando `auto_convert_to` / `auto_compress` estão ligados; o que não tem correção é recusado com o motivo.

## Testes e Docker

```
uv run pytest
docker compose up -d --build        # bot + Evolution API + Postgres + Redis
docker compose logs -f bot
```