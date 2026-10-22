import os
import json
import threading
import asyncio
import re
import sqlite3
import urllib.request
import urllib.error
import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters,
)

# =========================================================
# CONFIGURAÇÕES
# =========================================================
TOKEN = os.getenv("TELEGRAM_TOKEN")
PUSHINPAY_TOKEN = os.getenv("PUSHINPAY_TOKEN")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://telegram-fotos-bot-5.onrender.com").rstrip("/")
DATABASE_PATH = os.getenv("DATABASE_PATH", "pagamentos.db")
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

# O SQLite mantém os pagamentos pendentes e processados mesmo após reinicialização.
LOCK_PAGAMENTOS = threading.Lock()

def conectar_banco():
    conexao = sqlite3.connect(DATABASE_PATH, timeout=30)
    conexao.execute("PRAGMA journal_mode=WAL")
    conexao.execute("CREATE TABLE IF NOT EXISTS pagamentos (id TEXT PRIMARY KEY, chat_id TEXT NOT NULL, plano TEXT NOT NULL, valor INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'created', processado INTEGER NOT NULL DEFAULT 0)")
    conexao.commit()
    return conexao

conexao_inicial = conectar_banco()
conexao_inicial.close()


# =========================================================
# CRIAR PIX PUSHIN PAY
# =========================================================
def requisicao_pushinpay(metodo, caminho, dados=None):
    if not PUSHINPAY_TOKEN:
        raise RuntimeError("PUSHINPAY_TOKEN não configurado no Render.")
    corpo = None if dados is None else json.dumps(dados).encode("utf-8")
    req = urllib.request.Request(
        "https://api.pushinpay.com.br/api" + caminho,
        data=corpo,
        headers={
            "Authorization": f"Bearer {PUSHINPAY_TOKEN}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method=metodo,
    )
    with urllib.request.urlopen(req, timeout=30) as resposta:
        return json.loads(resposta.read().decode("utf-8"))

def criar_pix(chat_id, plano):
    if plano not in PLANOS:
        raise ValueError("Plano inválido.")
    dados_plano = PLANOS[plano]
    dados = {"value": dados_plano["centavos"], "webhook_url": PUBLIC_BASE_URL + "/webhook/pushinpay"}
    transacao = requisicao_pushinpay("POST", "/pix/cashIn", dados)
    transacao_id = transacao.get("id")
    codigo_pix = transacao.get("qr_code")
    if not transacao_id or not codigo_pix:
        raise RuntimeError("Pushin Pay não retornou o ID e o código PIX esperados.")
    with conectar_banco() as db:
        db.execute(
            "INSERT OR REPLACE INTO pagamentos (id, chat_id, plano, valor, status, processado) VALUES (?, ?, ?, ?, ?, 0)",
            (transacao_id, str(chat_id), plano, dados_plano["centavos"], transacao.get("status", "created")),
        )
    return transacao


# =========================================================
# CONFIRMAR PAGAMENTO NA API PUSHIN PAY
# =========================================================
def processar_pagamento_pushinpay(transacao_id):
    if not transacao_id:
        return False
    with LOCK_PAGAMENTOS:
        with conectar_banco() as db:
            linha = db.execute(
                "SELECT chat_id, plano, valor, processado FROM pagamentos WHERE id = ?",
                (transacao_id,),
            ).fetchone()
        if not linha:
            print("Webhook Pushin Pay ignorado: transação não cadastrada.")
            return False
        chat_id, plano, valor_esperado, processado = linha
        if processado:
            return True
        # Não confiamos apenas no corpo do webhook: consultamos o status diretamente na API.
        status_api = requisicao_pushinpay("GET", f"/transactions/{transacao_id}")
        if str(status_api.get("id")) != str(transacao_id):
            print("ID da transação não confere; acesso não liberado.")
            return False
        if status_api.get("status") != "paid":
            with conectar_banco() as db:
                db.execute("UPDATE pagamentos SET status = ? WHERE id = ?", (str(status_api.get("status", "unknown")), transacao_id))
            print("Pagamento ainda não confirmado:", transacao_id, status_api.get("status"))
            return False
        try:
            valor_recebido = int(status_api.get("value", 0))
        except (TypeError, ValueError):
            valor_recebido = 0
        if valor_recebido != int(valor_esperado) or plano not in PLANOS or valor_recebido != PLANOS[plano]["centavos"]:
            print("Valor/plano não confere; acesso não liberado:", transacao_id)
            return False
        # Marca como processado antes do envio para evitar duplicação do convite.
        with conectar_banco() as db:
            db.execute("UPDATE pagamentos SET status = 'paid', processado = 1 WHERE id = ?", (transacao_id,))
        try:
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
            print("PAGAMENTO PUSHIN PAY CONFIRMADO:", transacao_id, "chat:", chat_id)
            return True
        except Exception:
            # Reverte para permitir nova tentativa caso o envio do convite falhe.
            with conectar_banco() as db:
                db.execute("UPDATE pagamentos SET processado = 0 WHERE id = ?", (transacao_id,))
            raise


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
# WEBHOOK PUSHIN PAY: verificado na API antes de liberar acesso
# =========================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bot online")

    def do_POST(self):
        if urlparse(self.path).path != "/webhook/pushinpay":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        # Lê o corpo recebido e registra apenas informações úteis para diagnóstico.
        tamanho = int(self.headers.get("Content-Length", "0") or "0")
        corpo_bytes = self.rfile.read(tamanho) if tamanho > 0 else b""
        corpo = corpo_bytes.decode("utf-8", errors="replace").strip()

        evento = None
        if corpo:
            try:
                evento = json.loads(corpo)
            except (ValueError, UnicodeDecodeError):
                evento = None

        # Algumas notificações podem chegar como texto simples; nesse caso,
        # tenta extrair um UUID de transação sem confiar nele para aprovar pagamento.
        transacao_id = None
        if isinstance(evento, dict):
            # Prioriza transaction_id; "id" pode identificar o próprio evento/webhook.
            transacao_id = evento.get("transaction_id") or evento.get("transactionId")
            if not transacao_id and isinstance(evento.get("data"), dict):
                transacao_id = (
                    evento["data"].get("transaction_id")
                    or evento["data"].get("transactionId")
                    or evento["data"].get("id")
                )
            if not transacao_id and isinstance(evento.get("transaction"), dict):
                transacao_id = evento["transaction"].get("id")
            if not transacao_id:
                transacao_id = evento.get("id")
        elif corpo:
            encontrado = re.search(
                r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
                corpo,
            )
            if encontrado:
                transacao_id = encontrado.group(0)

        if not transacao_id:
            print(
                "Webhook Pushin Pay sem ID de transação.",
                "Content-Type:", self.headers.get("Content-Type"),
                "Content-Length:", tamanho,
                "Corpo inicial:", repr(corpo[:300]),
            )
            self.send_response(400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Missing transaction id")
            return

        print("Webhook Pushin Pay recebido para transação:", str(transacao_id))
        try:
            threading.Thread(
                target=processar_pagamento_pushinpay,
                args=(str(transacao_id),),
                daemon=True,
            ).start()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"OK")
        except Exception as erro:
            print("Erro ao iniciar processamento do webhook:", repr(erro))
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Processing error")

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
    if not PUSHINPAY_TOKEN:
        await query.message.reply_text("❌ A Pushin Pay ainda não está configurada no Render.")
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
    await message.reply_text("⏳ <b>GERANDO PIX...</b>\n\nAguarde alguns segundos.", parse_mode="HTML")
    try:
        transacao = await asyncio.to_thread(criar_pix, chat_id, plano)
        codigo_pix = transacao.get("qr_code")
        qr_base64 = transacao.get("qr_code_base64")
        dados_plano = PLANOS[plano]
        if not codigo_pix:
            raise RuntimeError("A Pushin Pay não retornou o código PIX.")
        mensagem = (
            "✅ <b>PIX GERADO!</b>\n\n"
            f"📦 <b>Plano:</b> {dados_plano['nome']}\n"
            f"💰 <b>Valor:</b> {dados_plano['exibicao']}\n\n"
            "📋 <b>PIX COPIA E COLA:</b>\n\n"
            f"<code>{codigo_pix}</code>\n\n"
            "👆 Copie o código acima e cole no aplicativo do seu banco.\n\n"
            "⏳ Após a confirmação real do pagamento, o bot enviará automaticamente seu acesso ao Grupo VIP.\n"
            "🔐 O convite será individual."
        )
        await message.reply_text(mensagem, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📸 VER PACOTE", callback_data="produtos")]]), disable_web_page_preview=True)
        if qr_base64:
            try:
                imagem = qr_base64.split(",", 1)[-1]
                conteudo = base64.b64decode(imagem)
                from io import BytesIO
                arquivo = BytesIO(conteudo)
                arquivo.name = "pix.png"
                await message.reply_photo(photo=arquivo, caption="📲 Escaneie este QR Code para pagar.")
            except Exception as erro_imagem:
                print("Não foi possível enviar a imagem QR:", erro_imagem)
        print("PIX Pushin Pay criado:", transacao.get("id"), "plano:", plano, "chat:", chat_id)
    except Exception as erro:
        print("Erro ao criar PIX Pushin Pay:", repr(erro))
        await message.reply_text("❌ Não foi possível criar o PIX agora. Tente novamente mais tarde. Nenhum acesso foi liberado.")


async def ajuda(update, context):
    await update.message.reply_text(
        "ℹ️ <b>AJUDA</b>\n\n/start — Abrir loja\n/produtos — Ver pacote\n/ajuda — Mostrar ajuda\n\n"
        "💳 O pagamento é realizado pela Pushin Pay via PIX.\n\n"
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
    if not PUSHINPAY_TOKEN:
        raise RuntimeError("PUSHINPAY_TOKEN não configurado no Render.")

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

    print("BOT INICIADO COM PUSHIN PAY!")
    print("Produto:", PRODUTO)
    print("Planos: mensal R$ 29,99 | trimestral R$ 64,90")
    print("Webhook: /webhook/pushinpay")
    app.run_polling()


if __name__ == "__main__":
    main()
