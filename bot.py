import os
import threading
import json
import uuid
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

TOKEN = os.getenv("TELEGRAM_TOKEN")
MP_TOKEN = os.getenv("MERCADOPAGO_ACCESS_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

VALOR = "29.99"
PRODUTO = "Pacote de fotos"

# =========================
# GRUPO VIP
# =========================

ID_GRUPO_VIP = -5328427809


# =========================
# MERCADO PAGO
# =========================

def criar_pix(chat_id):

    url = "https://api.mercadopago.com/v1/orders"

    external_reference = (
        "telegram_"
        + str(chat_id)
        + "_"
        + str(uuid.uuid4())
    )

    dados = {
        "type": "online",
        "external_reference": external_reference,
        "total_amount": VALOR,
        "processing_mode": "automatic",
        "payer": {
            "email": "test_user_br@testuser.com",
            "first_name": "APRO"
        },
        "transactions": {
            "payments": [
                {
                    "amount": VALOR,
                    "payment_method": {
                        "id": "pix",
                        "type": "bank_transfer"
                    }
                }
            ]
        }
    }

    dados_json = json.dumps(dados).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + MP_TOKEN,
        "X-Idempotency-Key": str(uuid.uuid4())
    }

    requisicao = urllib.request.Request(
        url,
        data=dados_json,
        headers=headers,
        method="POST"
    )

    try:

        with urllib.request.urlopen(
            requisicao,
            timeout=30
        ) as resposta:

            conteudo = resposta.read().decode("utf-8")

            return json.loads(conteudo)

    except urllib.error.HTTPError as erro:

        corpo = erro.read().decode("utf-8")

        raise Exception(
            f"Mercado Pago HTTP {erro.code}: {corpo}"
        )


def consultar_order(order_id):

    url = (
        "https://api.mercadopago.com/v1/orders/"
        + str(order_id)
    )

    headers = {
        "Authorization": "Bearer " + MP_TOKEN
    }

    requisicao = urllib.request.Request(
        url,
        headers=headers,
        method="GET"
    )

    with urllib.request.urlopen(
        requisicao,
        timeout=30
    ) as resposta:

        conteudo = resposta.read().decode("utf-8")

        return json.loads(conteudo)


# =========================
# TELEGRAM VIA API
# =========================

def enviar_telegram(chat_id, mensagem):

    url = (
        "https://api.telegram.org/bot"
        + TOKEN
        + "/sendMessage"
    )

    dados = {
        "chat_id": chat_id,
        "text": mensagem
    }

    dados_json = json.dumps(dados).encode("utf-8")

    requisicao = urllib.request.Request(
        url,
        data=dados_json,
        headers={
            "Content-Type": "application/json"
        },
        method="POST"
    )

    with urllib.request.urlopen(
        requisicao,
        timeout=30
    ) as resposta:

        resposta.read()


# =========================
# CRIAR CONVITE VIP
# =========================

def criar_convite_vip():

    url = (
        "https://api.telegram.org/bot"
        + TOKEN
        + "/createChatInviteLink"
    )

    dados = {
        "chat_id": ID_GRUPO_VIP,
        "member_limit": 1,
        "name": "Convite VIP"
    }

    dados_json = json.dumps(dados).encode("utf-8")

    requisicao = urllib.request.Request(
        url,
        data=dados_json,
        headers={
            "Content-Type": "application/json"
        },
        method="POST"
    )

    with urllib.request.urlopen(
        requisicao,
        timeout=30
    ) as resposta:

        resultado = json.loads(
            resposta.read().decode("utf-8")
        )

    if not resultado.get("ok"):

        raise Exception(
            "Erro ao criar convite VIP: "
            + str(resultado)
        )

    return resultado["result"]["invite_link"]


# =========================
# WEBHOOK MERCADO PAGO
# =========================

def processar_webhook(dados):

    try:

        data = dados.get("data", {})
        order_id = data.get("id")

        if not order_id:
            return

        order = consultar_order(order_id)

        status = order.get("status")

        if status != "processed":
            return

        external_reference = order.get(
            "external_reference",
            ""
        )

        if not external_reference.startswith(
            "telegram_"
        ):
            return

        partes = external_reference.split("_")

        if len(partes) < 2:
            return

        chat_id = partes[1]

        # =========================
        # CRIAR CONVITE VIP
        # =========================

        convite_vip = criar_convite_vip()

        mensagem = (
            "✅ PAGAMENTO CONFIRMADO!\n\n"
            "📸 Produto: Pacote de fotos\n"
            "💰 Valor: R$ 29,99\n\n"
            "🎉 Seu pagamento foi aprovado!\n\n"
            "🔐 Seu acesso ao Grupo VIP está liberado.\n\n"
            "👇 Clique no botão abaixo para entrar:"
        )

        # =========================
        # ENVIAR MENSAGEM COM LINK
        # =========================

        url = (
            "https://api.telegram.org/bot"
            + TOKEN
            + "/sendMessage"
        )

        dados_mensagem = {
            "chat_id": chat_id,
            "text": mensagem,
            "reply_markup": {
                "inline_keyboard": [
                    [
                        {
                            "text": "🔐 ENTRAR NO GRUPO VIP",
                            "url": convite_vip
                        }
                    ]
                ]
            }
        }

        dados_json = json.dumps(
            dados_mensagem
        ).encode("utf-8")

        requisicao = urllib.request.Request(
            url,
            data=dados_json,
            headers={
                "Content-Type": "application/json"
            },
            method="POST"
        )

        with urllib.request.urlopen(
            requisicao,
            timeout=30
        ) as resposta:

            resposta.read()

        print(
            "Pagamento confirmado:",
            order_id,
            "Chat:",
            chat_id
        )

        print(
            "Convite VIP criado:",
            convite_vip
        )

    except Exception as erro:

        print(
            "Erro no webhook:",
            erro
        )


# =========================
# SERVIDOR DO RENDER
# =========================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "text/plain"
        )

        self.end_headers()

        self.wfile.write(
            b"Bot online"
        )

    def do_POST(self):

        if self.path.startswith(
            "/webhook/mercadopago"
        ):

            tamanho = int(
                self.headers.get(
                    "Content-Length",
                    "0"
                )
            )

            corpo = self.rfile.read(
                tamanho
            )

            try:

                dados = json.loads(
                    corpo.decode("utf-8")
                )

                threading.Thread(
                    target=processar_webhook,
                    args=(dados,),
                    daemon=True
                ).start()

            except Exception as erro:

                print(
                    "Erro recebendo webhook:",
                    erro
                )

            self.send_response(200)
            self.end_headers()

            self.wfile.write(
                b"OK"
            )

            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        pass


def start_server():

    server = HTTPServer(
        ("0.0.0.0", PORT),
        HealthHandler
    )

    server.serve_forever()


# =========================
# START
# =========================

async def start(update, context):

    keyboard = [
        [
            InlineKeyboardButton(
                "🛍️ Ver produtos",
                callback_data="produtos"
            )
        ]
    ]

    await update.message.reply_text(
        "👋 Olá! Bem-vindo à nossa loja!\n\n"
        "Clique abaixo para ver o produto disponível:",
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# =========================
# PRODUTOS
# =========================

async def produtos(update, context):

    keyboard = [
        [
            InlineKeyboardButton(
                "🛒 Comprar — R$ 29,99",
                callback_data="comprar"
            )
        ]
    ]

    mensagem = (
        "🛍️ *Produto disponível*\n\n"
        "📸 Pacote de fotos\n"
        "💰 Valor: *R$ 29,99*\n\n"
        "Clique no botão abaixo para comprar."
    )

    if update.callback_query:

        await update.callback_query.answer()

        await update.callback_query.edit_message_text(
            mensagem,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
        )

    else:

        await update.message.reply_text(
            mensagem,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
        )


# =========================
# COMPRA
# =========================

async def comprar(update, context):

    query = update.callback_query

    await query.answer()

    keyboard = [
        [
            InlineKeyboardButton(
                "💳 Continuar para pagamento",
                callback_data="pagamento"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Voltar aos produtos",
                callback_data="produtos"
            )
        ],
    ]

    await query.edit_message_text(
        "🛒 *Pedido selecionado!*\n\n"
        "📸 Pacote de fotos\n"
        "💰 Total: *R$ 29,99*\n\n"
        "Clique abaixo para gerar o PIX.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# =========================
# PAGAMENTO
# =========================

async def pagamento(update, context):

    query = update.callback_query

    await query.answer()

    if not MP_TOKEN:

        await query.message.reply_text(
            "❌ Mercado Pago não está configurado."
        )

        return

    await query.message.reply_text(
        "⏳ Gerando seu PIX...\n"
        "Aguarde alguns segundos."
    )

    try:

        resultado = await __import__(
            "asyncio"
        ).to_thread(
            criar_pix,
            query.from_user.id
        )

        order_id = resultado.get("id")

        transactions = resultado.get(
            "transactions",
            {}
        )

        payments = transactions.get(
            "payments",
            []
        )

        if not payments:

            await query.message.reply_text(
                "❌ O Mercado Pago não retornou "
                "o pagamento."
            )

            return

        payment = payments[0]

        payment_method = payment.get(
            "payment_method",
            {}
        )

        qr_code = payment_method.get(
            "qr_code"
        )

        ticket_url = payment_method.get(
            "ticket_url"
        )

        if not qr_code:

            await query.message.reply_text(
                "❌ O Mercado Pago não retornou "
                "o código PIX."
            )

            return

        botoes = []

        if ticket_url:

            botoes.append(
                [
                    InlineKeyboardButton(
                        "💳 Abrir pagamento PIX",
                        url=ticket_url
                    )
                ]
            )

        botoes.append(
            [
                InlineKeyboardButton(
                    "🛍️ Voltar aos produtos",
                    callback_data="produtos"
                )
            ]
        )

        mensagem = (
            "✅ *PIX gerado com sucesso!*\n\n"
            "📸 Produto: *Pacote de fotos*\n"
            "💰 Valor: *R$ 29,99*\n\n"
            "📋 *PIX Copia e Cola:*\n\n"
            f"`{qr_code}`\n\n"
            "Copie o código acima e cole no "
            "aplicativo do seu banco para pagar.\n\n"
            "⚠️ Este pagamento está em ambiente "
            "de TESTE."
        )

        await query.message.reply_text(
            mensagem,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                botoes
            )
        )

        print(
            "Order criada:",
            order_id
        )

    except Exception as erro:

        await query.message.reply_text(
            "❌ Não foi possível criar o pagamento.\n\n"
            "Erro do Mercado Pago:\n\n"
            f"{erro}"
        )


# =========================
# AJUDA
# =========================

async def ajuda(update, context):

    await update.message.reply_text(
        "ℹ️ *Comandos disponíveis:*\n\n"
        "/start — Iniciar\n"
        "/produtos — Ver produtos\n"
        "/ajuda — Ajuda\n"
        "/id — Ver ID do grupo",
        parse_mode="Markdown",
    )


# =========================
# ID DO GRUPO VIP
# =========================

async def id_grupo(update, context):

    chat = update.effective_chat

    await update.message.reply_text(
        f"🆔 ID deste grupo:\n\n{chat.id}"
    )

    print(
        "ID DO GRUPO VIP:",
        chat.id
    )


# =========================
# MAIN
# =========================

def main():

    if not TOKEN:

        raise RuntimeError(
            "TELEGRAM_TOKEN não configurado no Render."
        )

    if not MP_TOKEN:

        raise RuntimeError(
            "MERCADOPAGO_ACCESS_TOKEN não configurado no Render."
        )

    threading.Thread(
        target=start_server,
        daemon=True
    ).start()

    app = Application.builder().token(
        TOKEN
    ).build()

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("produtos", produtos)
    )

    app.add_handler(
        CommandHandler("ajuda", ajuda)
    )

    app.add_handler(
        CommandHandler("id", id_grupo)
    )

    app.add_handler(
        CallbackQueryHandler(
            produtos,
            pattern="^produtos$"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            comprar,
            pattern="^comprar$"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            pagamento,
            pattern="^pagamento$"
        )
    )

    print(
        "Bot iniciado com sucesso!"
    )

    app.run_polling()


if __name__ == "__main__":
    main()
