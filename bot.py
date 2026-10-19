import os
import json
import threading
import asyncio
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

import stripe
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters,
)

# =========================================================
# CONFIGURAÇÕES
# =========================================================
TOKEN = os.getenv("TELEGRAM_TOKEN")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
PORT = int(os.getenv("PORT", "10000"))

VALOR_MENSAL = "29.99"
VALOR_TRIMESTRAL = "64.90"
PRODUTO = "Acesso ao Grupo VIP"
PLANOS = {
    "mensal": {"nome": "1 mês VIP", "valor": VALOR_MENSAL,
               "centavos": 2999, "exibicao": "R$ 29,99"},
    "trimestral": {"nome": "3 meses VIP", "valor": VALOR_TRIMESTRAL,
                   "centavos": 6490, "exibicao": "R$ 64,90"},
}
ID_GRUPO_VIP = -5328427809
FILE_ID_FOTO_DEMONSTRATIVA = ""

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# Mantém uma proteção básica contra eventos repetidos durante a execução.
# Para persistência entre reinicializações do Render, use um banco de dados.
PAGAMENTOS_PROCESSADOS = set()
PAGAMENTOS_EM_PROCESSAMENTO = set()
LOCK_PAGAMENTOS = threading.Lock()


# =========================================================
# CRIAR PIX STRIPE
# =========================================================
def criar_pix(chat_id, plano="mensal"):
    if not STRIPE_SECRET_KEY:
        raise RuntimeError("STRIPE_SECRET_KEY não configurada no Render.")
    if plano not in PLANOS:
        raise ValueError("Plano inválido.")

    dados_plano = PLANOS[plano]

    # Cria o PIX sem exigir nem recolher o e-mail do cliente.
    intent = stripe.PaymentIntent.create(
        amount=dados_plano["centavos"],
        currency="brl",
        payment_method_data={"type": "pix"},
        confirm=True,
        return_url="https://telegram-fotos-bot-5.onrender.com/",
        description=f"{PRODUTO} - {dados_plano['nome']}",
        metadata={
            "chat_id": str(chat_id),
            "plano": plano,
            "produto": PRODUTO,
        },
    )
    return intent


# =========================================================
# CRIAR CONVITE VIP
# =========================================================
def criar_convite_vip():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN não configurado.")
    import urllib.request
    url = f"https://api.telegram.org/bot{TOKEN}/createChatInviteLink"
    dados = {
        "chat_id": ID_GRUPO_VIP,
        "member_limit": 1,
        "name": "Acesso VIP",
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(dados).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resposta:
        resultado = json.loads(resposta.read().decode("utf-8"))
    if not resultado.get("ok"):
        raise RuntimeError(f"Erro ao criar convite VIP: {resultado}")
    return resultado["result"]["invite_link"]


# =========================================================
# ENVIAR MENSAGEM PELO TELEGRAM
# =========================================================
def enviar_mensagem_telegram(chat_id, mensagem, convite=None):
    import urllib.request
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    dados = {"chat_id": chat_id, "text": mensagem}
    if convite:
        dados["reply_markup"] = {
            "inline_keyboard": [[{
                "text": "🔐 ENTRAR NO GRUPO VIP",
                "url": convite,
            }]]
        }
    req = urllib.request.Request(
        url,
        data=json.dumps(dados).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resposta:
        resultado = json.loads(resposta.read().decode("utf-8"))
    if not resultado.get("ok"):
        raise RuntimeError(f"Erro ao enviar mensagem Telegram: {resultado}")


# =========================================================
# WEBHOOK STRIPE
# =========================================================
def processar_evento_stripe(evento):
    if evento.get("type") != "payment_intent.succeeded":
        print("Evento Stripe ignorado:", evento.get("type"))
        return

    intent = evento.get("data", {}).get("object", {})
    intent_id = intent.get("id")
    if not intent_id:
        print("Webhook sem ID de PaymentIntent.")
        return

    with LOCK_PAGAMENTOS:
        if intent_id in PAGAMENTOS_PROCESSADOS or intent_id in PAGAMENTOS_EM_PROCESSAMENTO:
            print("Pagamento já recebido/em processamento:", intent_id)
            return
        PAGAMENTOS_EM_PROCESSAMENTO.add(intent_id)

    try:
        # Confere os dados do próprio objeto recebido pelo webhook.
        metadata = intent.get("metadata") or {}
        chat_id = metadata.get("chat_id")
        plano = metadata.get("plano")
        if not chat_id or plano not in PLANOS:
            print("Metadata inválida no PaymentIntent:", intent_id)
            return

        esperado = PLANOS[plano]["centavos"]
        if intent.get("status") != "succeeded":
            print("PaymentIntent não está succeeded:", intent_id)
            return
        if intent.get("currency") != "brl" or int(intent.get("amount_received") or 0) != esperado:
            print("Valor/moeda não confere; acesso não liberado:", intent_id)
            return
        if STRIPE_SECRET_KEY and STRIPE_SECRET_KEY.startswith("sk_live_") and not intent.get("livemode"):
            print("Pagamento de teste recebido em configuração live; acesso não liberado.")
            return

        convite = criar_convite_vip()
        dados_plano = PLANOS[plano]
        mensagem = (
            "🎉 PAGAMENTO CONFIRMADO!\n\n"
            f"📦 Plano: {dados_plano['nome']}\n"
            f"💰 Valor: {dados_plano['exibicao']}\n\n"
            "✅ Seu pagamento foi aprovado!\n\n"
            "🔐 Seu acesso ao Grupo VIP está liberado.\n\n"
            "👇 Clique no botão abaixo para entrar no grupo.\n\n"
            "⚠️ Este convite é individual e permite apenas 1 entrada."
        )
        enviar_mensagem_telegram(chat_id, mensagem, convite)
        with LOCK_PAGAMENTOS:
            PAGAMENTOS_PROCESSADOS.add(intent_id)
        print("PAGAMENTO STRIPE CONFIRMADO:", intent_id, "chat:", chat_id)
    except Exception as erro:
        print("Erro ao processar pagamento Stripe:", erro)
    finally:
        with LOCK_PAGAMENTOS:
            PAGAMENTOS_EM_PROCESSAMENTO.discard(intent_id)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bot online")

    def do_POST(self):
        if urlparse(self.path).path != "/webhook/stripe":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        tamanho = int(self.headers.get("Content-Length", "0"))
        corpo = self.rfile.read(tamanho)
        assinatura = self.headers.get("Stripe-Signature")

        if not STRIPE_WEBHOOK_SECRET:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Webhook secret missing")
            return

        try:
            evento = stripe.Webhook.construct_event(
                payload=corpo,
                sig_header=assinatura,
                secret=STRIPE_WEBHOOK_SECRET,
            )
        except ValueError:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Invalid payload")
            return
        except stripe.error.SignatureVerificationError:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Invalid signature")
            return

        threading.Thread(
            target=processar_evento_stripe, args=(evento,), daemon=True
        ).start()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass


def start_server():
    HTTPServer(("0.0.0.0", PORT), HealthHandler).serve_forever()


# =========================================================
# TELAS DO BOT
# =========================================================
def teclado_planos():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 1 mês VIP — R$ 29,99", callback_data="plano_mensal")],
        [InlineKeyboardButton("🔥 3 meses VIP — R$ 64,90", callback_data="plano_trimestral")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensagem = (
        "Oiii amor 🥰\n\n"
        "Vem fazer parte do meu Grupo VIP! 😈\n\n"
        "Aqui dentro você tem acesso ao conteúdo exclusivo para maiores de 18 anos. 🔥🔞\n\n"
        "Para ter acesso ao grupo exclusivo, basta escolher um dos planos abaixo: 👇"
    )
    pasta = os.path.dirname(__file__)
    caminho_video = os.path.join(pasta, "IMG_0510.mp4")
    caminho_foto = os.path.join(pasta, "inicio.jpg")
    try:
        if os.path.isfile(caminho_video):
            with open(caminho_video, "rb") as video:
                await update.message.reply_video(video=video)
        elif os.path.isfile(caminho_foto):
            with open(caminho_foto, "rb") as foto:
                await update.message.reply_photo(photo=foto)
        elif FILE_ID_FOTO_DEMONSTRATIVA:
            await update.message.reply_photo(photo=FILE_ID_FOTO_DEMONSTRATIVA)
    except Exception as erro:
        print("Erro ao enviar mídia inicial:", erro)
    await update.message.reply_text(mensagem, reply_markup=teclado_planos())


async def inicio(update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Oiii amor 🥰\n\nVem fazer parte do meu Grupo VIP! 😈\n\n"
        "Conteúdo exclusivo para maiores de 18 anos. 🔥🔞\n\n"
        "Escolha seu plano abaixo: 👇",
        reply_markup=teclado_planos(),
    )


async def escolher_plano(update, context):
    query = update.callback_query
    await query.answer()
    plano = query.data.replace("plano_", "", 1)
    if plano not in PLANOS:
        await query.message.reply_text("❌ Plano inválido. Use /start para tentar novamente.")
        return
    context.user_data["plano"] = plano
    dados = PLANOS[plano]
    await query.edit_message_text(
        f"🛒 PEDIDO\n\n📦 Plano: {dados['nome']}\n💰 Total: {dados['exibicao']}\n\n"
        "Após a confirmação do PIX, você receberá um convite individual para o Grupo VIP.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 CONTINUAR PARA PAGAMENTO", callback_data="pagamento")],
            [InlineKeyboardButton("⬅️ VOLTAR AOS PLANOS", callback_data="inicio")],
        ]),
    )


async def produtos(update, context):
    keyboard = [
        [InlineKeyboardButton("💳 COMPRAR AGORA", callback_data="comprar")],
        [InlineKeyboardButton("ℹ️ MAIS INFORMAÇÕES", callback_data="info")],
        [InlineKeyboardButton("⬅️ VOLTAR", callback_data="inicio")],
    ]
    mensagem = (
        "📸 <b>PACOTE EXCLUSIVO</b>\n\n"
        "✨ Conteúdo privado\n📦 Pacote completo\n🔐 Acesso ao grupo privado\n"
        "⚡ Liberação automática após pagamento\n\n"
        "💰 <b>1 mês: R$ 29,99</b>\n💰 <b>3 meses: R$ 64,90</b>\n\n"
        "🔞 Conteúdo destinado exclusivamente a maiores de 18 anos.\n\n"
        "👇 Escolha uma opção abaixo."
    )
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(mensagem, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(mensagem, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))


async def info(update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "ℹ️ <b>COMO FUNCIONA</b>\n\n"
        "1️⃣ Escolha o pacote.\n\n2️⃣ Gere o PIX diretamente, sem informar e-mail.\n\n"
        "3️⃣ Faça o pagamento.\n\n"
        "5️⃣ Após a confirmação, o bot envia automaticamente seu convite individual para o Grupo VIP.\n\n"
        "🔐 O convite permite apenas 1 entrada.\n\n🔞 Conteúdo exclusivo para maiores de 18 anos.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 COMPRAR AGORA", callback_data="comprar")],
            [InlineKeyboardButton("⬅️ VOLTAR", callback_data="produtos")],
        ]),
    )


async def comprar(update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Escolha o plano que deseja comprar:",
        reply_markup=teclado_planos(),
    )


async def pagamento(update, context):
    query = update.callback_query
    await query.answer()
    if not STRIPE_SECRET_KEY:
        await query.message.reply_text("❌ Stripe não está configurada no Render.")
        return

    plano = context.user_data.get("plano", "mensal")
    if plano not in PLANOS:
        plano = "mensal"

    await gerar_pix_para_usuario(
        chat_id=query.from_user.id,
        plano=plano,
        message=query.message,
        context=context,
    )


async def gerar_pix_para_usuario(chat_id, plano, message, context):
    await message.reply_text(
        "⏳ <b>GERANDO PIX...</b>\n\nAguarde alguns segundos.",
        parse_mode="HTML",
    )

    try:
        intent = await asyncio.to_thread(criar_pix, chat_id, plano)
        intent = intent.to_dict() if hasattr(intent, "to_dict") else intent
        action = intent.get("next_action") or {}
        pix = action.get("pix_display_qr_code") or {}
        codigo_pix = pix.get("data")
        imagem_qr = pix.get("image_url_png") or pix.get("image_url_svg")
        instrucoes = pix.get("hosted_instructions_url")
        dados_plano = PLANOS[plano]

        if not codigo_pix:
            print(
                "Stripe não retornou código PIX. PaymentIntent:",
                intent.get("id"), "status:", intent.get("status"),
                "next_action:", action,
            )
            await message.reply_text(
                "❌ A Stripe não retornou o código PIX para este pagamento.\n"
                "Nenhum acesso foi liberado. Confira a elegibilidade PIX da conta e os logs do Render."
            )
            return

        mensagem = (
            "✅ <b>PIX GERADO!</b>\n\n"
            f"📦 <b>Plano:</b> {dados_plano['nome']}\n"
            f"💰 <b>Valor:</b> {dados_plano['exibicao']}\n\n"
            "📋 <b>PIX COPIA E COLA:</b>\n\n"
            f"<code>{codigo_pix}</code>\n\n"
            "👆 Copie o código acima e cole no aplicativo do seu banco.\n\n"
            "⏳ Após a confirmação do pagamento, o bot enviará automaticamente seu acesso ao Grupo VIP.\n"
            "🔐 O convite será individual."
        )
        botoes = []
        if instrucoes:
            botoes.append([InlineKeyboardButton("💳 ABRIR INSTRUÇÕES DO PIX", url=instrucoes)])
        botoes.append([InlineKeyboardButton("📸 VER PACOTE", callback_data="produtos")])
        await message.reply_text(
            mensagem,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(botoes),
            disable_web_page_preview=True,
        )
        if imagem_qr:
            await message.reply_text(
                f"QR Code PIX: {imagem_qr}",
                disable_web_page_preview=False,
            )
        print("PaymentIntent criado:", intent.get("id"), "plano:", plano, "chat:", chat_id)
    except Exception as erro:
        print("Erro ao criar PIX Stripe:", repr(erro))
        await message.reply_text(
            "❌ Não foi possível criar o PIX na Stripe.\n\n"
            "Confira os logs do Render para ver o detalhe do erro. Nenhum acesso foi liberado."
        )


async def ajuda(update, context):
    await update.message.reply_text(
        "ℹ️ <b>AJUDA</b>\n\n/start — Abrir loja\n/produtos — Ver pacote\n/ajuda — Mostrar ajuda\n\n"
        "💳 O pagamento é realizado pela Stripe via PIX.\n\n"
        "🔐 Após a confirmação, o acesso VIP é enviado automaticamente.",
        parse_mode="HTML",
    )


async def id_grupo(update, context):
    chat = update.effective_chat
    await update.message.reply_text("🆔 ID deste grupo:\n\n" + str(chat.id))
    print("ID DO GRUPO VIP:", chat.id)


async def testevip(update, context):
    await update.message.reply_text("⏳ Criando convite VIP de teste...")
    try:
        convite = await asyncio.to_thread(criar_convite_vip)
        await update.message.reply_text(
            "✅ <b>CONVITE VIP CRIADO!</b>\n\n🔐 Link:\n\n" + convite +
            "\n\n⚠️ Este convite permite apenas 1 entrada.",
            parse_mode="HTML",
        )
        print("CONVITE VIP DE TESTE:", convite)
    except Exception as erro:
        print("ERRO NO /testevip:", erro)
        await update.message.reply_text("❌ ERRO AO CRIAR O CONVITE VIP.\n\n" + str(erro))


def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN não configurado no Render.")
    if not STRIPE_SECRET_KEY:
        raise RuntimeError("STRIPE_SECRET_KEY não configurada no Render.")
    if not STRIPE_WEBHOOK_SECRET:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET não configurada no Render.")

    threading.Thread(target=start_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("produtos", produtos))
    app.add_handler(CommandHandler("ajuda", ajuda))
    app.add_handler(CommandHandler("id", id_grupo))
    app.add_handler(CommandHandler("testevip", testevip))
    app.add_handler(CallbackQueryHandler(produtos, pattern="^produtos$"))
    app.add_handler(CallbackQueryHandler(inicio, pattern="^inicio$"))
    app.add_handler(CallbackQueryHandler(comprar, pattern="^comprar$"))
    app.add_handler(CallbackQueryHandler(escolher_plano, pattern="^plano_(mensal|trimestral)$"))
    app.add_handler(CallbackQueryHandler(pagamento, pattern="^pagamento$"))
    app.add_handler(CallbackQueryHandler(info, pattern="^info$"))

    print("BOT INICIADO COM STRIPE!")
    print("Produto:", PRODUTO)
    print("Planos: mensal R$ 29,99 | trimestral R$ 64,90")
    print("Webhook: /webhook/stripe")
    app.run_polling()


if __name__ == "__main__":
    main()
