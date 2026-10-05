import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TELEGRAM_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Olá! Bem-vindo à nossa loja!\n\n"
        "Use /produtos para ver os produtos disponíveis."
    )

async def produtos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛍️ Produtos disponíveis:\n\n"
        "📸 Pacote de fotos — R$ 29,99\n\n"
        "Para comprar, entre em contato com o vendedor."
    )

async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Comandos disponíveis:\n"
        "/start - Iniciar\n"
        "/produtos - Ver produtos\n"
        "/ajuda - Ajuda"
    )

def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN não configurado")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("produtos", produtos))
    app.add_handler(CommandHandler("ajuda", ajuda))

    print("Bot iniciado!")
    app.run_polling()

if __name__ == "__main__":
    main()
