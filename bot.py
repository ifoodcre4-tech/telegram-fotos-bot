```python
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

TOKEN = os.getenv("TELEGRAM_TOKEN")
PORT = int(os.getenv("PORT", "10000"))


# Servidor HTTP para manter o Web Service do Render ativo
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


# Lista de produtos
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


# Botão de compra
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
        "Clique abaixo para continuar para o pagamento.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# Pagamento — por enquanto apenas demonstração
async def pagamento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [
            InlineKeyboardButton(
                "⬅️ Voltar",
                callback_data="produtos"
            )
        ]
    ]

    await query.edit_message_text(
        "💳 *Pagamento*\n\n"
        "Valor: *R$ 29,99*\n\n"
        "⚠️ O pagamento ainda não está conectado ao Mercado Pago.\n\n"
        "Na próxima etapa vamos colocar o PIX real e a confirmação automática.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# /ajuda
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

    # Inicia o servidor HTTP do Render
    threading.Thread(
        target=start_server,
        daemon=True
    ).start()

    # Inicia o bot do Telegram
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
```

