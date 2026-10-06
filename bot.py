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
# SERVIDOR DO RENDER
# =========================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot online")

    def log_message(self, format, *args):
        pass


def start_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

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
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================
# PRODUTOS
# =========================

async def produtos(update: Update, context: ContextTypes.DEFAULT_TYPE):

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
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    else:

        await update.message.reply_text(
            mensagem,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


# =========================
# COMPRA
# =========================

async def comprar(update: Update, context: ContextTypes.DEFAULT_TYPE):

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
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================
# MERCADO PAGO - ORDERS API
# =========================

def criar_pix():

    url = "https://api.mercadopago.com/v1/orders"

    # Identificador único do pedido
    external_reference = "telegram_" + str(uuid.uuid4())

    # Dados da Order
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

    except Exception as erro:

        raise Exception(
            f"Erro ao conectar ao Mercado Pago: {erro}"
        )


# =========================
# PAGAMENTO
# =========================

async def pagamento(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    await query.answer()

    if not MP_TOKEN:

        await query.message.reply_text(
            "❌ Mercado Pago não está configurado no Render."
        )

        return

    await query.message.reply_text(
        "⏳ Gerando seu PIX...\n"
        "Aguarde alguns segundos."
    )

    try:

        resultado = await __import__("asyncio").to_thread(
            criar_pix
        )

        # Guarda a order para futuras confirmações
        order_id = resultado.get("id")

        if order_id:

            context.user_data["order_id"] = order_id

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
                "❌ O Mercado Pago não retornou o pagamento.\n\n"
                f"Resposta: {resultado}"
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

        status = resultado.get(
            "status",
            "unknown"
        )

        if not qr_code:

            await query.message.reply_text(
                "❌ O Mercado Pago não retornou o código PIX.\n\n"
                f"Status: {status}\n"
                f"Order: {order_id}"
            )

            return

        # Botões
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
            "Copie o código acima e cole no aplicativo "
            "do seu banco para pagar.\n\n"
            "⚠️ Este pagamento está em ambiente de TESTE."
        )

        await query.message.reply_text(
            mensagem,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(botoes)
        )

    except Exception as erro:

        await query.message.reply_text(
            "❌ Não foi possível criar o pagamento.\n\n"
            "Erro retornado pelo Mercado Pago:\n\n"
            f"{erro}"
        )


# =========================
# AJUDA
# =========================

async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "ℹ️ *Comandos disponíveis:*\n\n"
        "/start — Iniciar\n"
        "/produtos — Ver produtos\n"
        "/ajuda — Ajuda",
        parse_mode="Markdown",
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

    # Servidor HTTP para o Render
    threading.Thread(
        target=start_server,
        daemon=True
    ).start()

    # Telegram
    app = Application.builder().token(TOKEN).build()

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

    print("Bot iniciado com sucesso!")

    app.run_polling()


if __name__ == "__main__":
    main()
