import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_TOKEN")
PORT = int(os.getenv("PORT", "10000"))


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot online")

    def log_message(self, format, *args):
        pass


def start_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Olá! Bem-vindo à nossa loja!\n\n"
        "Use /produtos para ver os produtos."
    )


async def produtos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛍️ Produtos disponíveis:\n\n"
        "📸 Pacote de fotos — R$ 29,99\n\n"
        "Para comprar, entre em contato com o vendedor."
    )


async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Comandos:\n"
        "/start - Iniciar\n"
        "/produtos - Ver produtos\n"
        "/ajuda - Ajuda"
    )


def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN não configurado")

    threading.Thread(target=start_server, daemon=True).start()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("produtos", produtos))
    app.add_handler(CommandHandler("ajuda", ajuda))

    print("Bot iniciado!")
    app.run_polling()


if __name__ == "__main__":
    main()
