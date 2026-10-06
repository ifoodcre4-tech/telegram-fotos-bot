import os
import threading
import base64
import io
import uuid
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer

import mercadopago
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

# Servidor HTTP para manter o Render ativo
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


# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🛍️ Ver produtos", callback_data="produtos")]
    ]

    await update.message.reply_text(
        "👋 Olá! Bem-vindo à nossa loja!\n\n"
        "Clique abaixo para ver o produto disponível:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# Produtos
async def produtos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(
            "🛒 Comprar — R$ 29,99",
            callback_data="comprar"
        )]
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


# Compra
async def comprar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton(
            "💳 Continuar para pagamento",
            callback_data="pagamento"
        )],
        [InlineKeyboardButton(
            "⬅️ Voltar aos produtos",
            callback_data="produtos"
        )],
    ]

    await query.edit_message_text(
        "🛒 *Pedido selecionado!*\n\n"
        "📸 Pacote de fotos\n"
        "💰 Total: *R$ 29,99*\n\n"
        "Clique abaixo para gerar seu PIX.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# Criar pagamento PIX
async def pagamento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not MP_TOKEN:
        await query.edit_message_text(
            "❌ Mercado Pago não está configurado no Render."
        )
        return

    try:
        sdk = mercadopago.SDK(MP_TOKEN)

        payment_data = {
            "transaction_amount": 29.99,
            "description": "Pacote de fotos",
            "payment_method_id": "pix",
            "payer": {
                "email": "cliente@teste.com"
            },
            "external_reference": str(query.from_user.id),
        }

        request_options = mercadopago.config.RequestOptions()
        request_options.custom_headers = {
            "x-idempotency-key": str(uuid.uuid4())
        }

        response = await asyncio.to_thread(
            sdk.payment().create,
            payment_data,
            request_options
        )

        payment = response.get("response", {})

        if "point_of_interaction" not in payment:
            await query.edit_message_text(
                "❌ Não foi possível criar o pagamento.\n\n"
                f"Resposta: {payment}"
            )
            return

        transaction_data = payment["point_of_interaction"].get(
            "transaction_data", {}
        )

        qr_base64 = transaction_data.get("qr_code_base64")
        qr_code = transaction_data.get("qr_code")

        if not qr_base64 or not qr_code:
            await query.edit_message_text(
                "❌ O Mercado Pago não retornou os dados do PIX."
            )
            return

        qr_image = base64.b64decode(qr_base64)
        photo = io.BytesIO(qr_image)
        photo.name = "pix.png"

        await query.message.reply_photo(
            photo=photo,
            caption=(
                "💳 *PIX gerado com sucesso!*\n\n"
                "📸 Pacote de fotos\n"
                "💰 Valor: *R$ 29,99*\n\n"
                "📱 Escaneie o QR Code acima ou use o "
                "PIX Copia e Cola abaixo:"
            ),
            parse_mode="Markdown",
        )

        await query.message.reply_text(
            f"`{qr_code}`",
            parse_mode="Markdown",
        )

    except Exception as e:
        await query.message.reply_text(
            "❌ Erro ao criar o PIX.\n\n"
            f"Detalhes: {str(e)}"
        )


# Ajuda
async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ *Comandos disponíveis:*\n\n"
        "/start — Iniciar\n"
        "/produtos — Ver produtos\n"
        "/ajuda — Ajuda",
        parse_mode="Markdown",
    )


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

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("produtos", produtos))
    app.add_handler(CommandHandler("ajuda", ajuda))

    app.add_handler(
        CallbackQueryHandler(produtos, pattern="^produtos$")
    )

    app.add_handler(
        CallbackQueryHandler(comprar, pattern="^comprar$")
    )

    app.add_handler(
        CallbackQueryHandler(pagamento, pattern="^pagamento$")
    )

    print("Bot iniciado com sucesso!")

    app.run_polling()


if __name__ == "__main__":
    main()
