# bot-llmagazine

Bot do Telegram que cadastra produtos em sites via API de admin. Você envia a foto, o bot valida a imagem, a IA sugere os campos, ele pergunta o que faltar e cadastra. **Nada é fixo no código**: tudo de um site vem do `sites.yaml`, então o mesmo bot atende outros sites com o mesmo padrão de API (login → upload de imagem → criação do produto).

## Como usar

1. Crie o bot no [@BotFather](https://t.me/BotFather) e copie o token.
2. No site, crie um usuário admin dedicado ao bot (tabela `admin_users` do llmagazine-page).
3. `cp .env.example .env` e `cp sites.example.yaml sites.yaml`, e preencha:
   - `.env`: token do bot, URL e credenciais do site, chave da IA.
   - `sites.yaml`: `allowed_user_ids` com os Telegram IDs autorizados (use o [@userinfobot](https://t.me/userinfobot) para descobrir o seu).
4. `uv sync && uv run python -m productbot.main`

No Telegram: `/novo` (ou envie direto uma foto). `/cancelar` interrompe.

## Adicionar outro site

Acrescente uma entrada em `sites:` no `sites.yaml` com `base_url`, `auth`, `upload`, `create`, regras de `image` e a lista de `fields`. Tipos de campo: `text`, `price`, `int`, `bool`, `choice` (fixo em `options` ou vindo da API em `options_from`), `multichoice`, `colors`. Veja `sites.example.yaml`.

Segredos usam `${VAR}` e são lidos do ambiente; não coloque senhas no YAML.

## IA (opcional)

Usa LangChain (`init_chat_model`), então o modelo é só configuração: `ai.provider` e `ai.model`. O padrão é Gemini (`google_genai`, `gemini-2.5-flash`). Para trocar, ajuste o YAML e instale o pacote do provedor (ex.: `uv add langchain-openai`). Se a IA falhar ou estiver desligada (`ai.enabled: false`), o bot pergunta campo a campo.

## Imagens

Validadas contra `image:` do site: formatos, tamanho máximo e dimensões mínimas. Formatos não aceitos são convertidos e imagens grandes são recomprimidas quando `auto_convert_to` / `auto_compress` estão ligados; o que não tem correção é recusado com o motivo.

## Testes e Docker

```
uv run pytest
docker build -t bot-llmagazine . && docker run --env-file .env -v $PWD/sites.yaml:/app/sites.yaml bot-llmagazine
```
