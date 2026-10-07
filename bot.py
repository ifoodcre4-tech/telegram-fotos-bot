import os
import threading
import json
import uuid
import urllib.request
import urllib.error
import re
import asyncio

from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# =========================================================
# CONFIGURAÇÕES
# =========================================================

TOKEN = os.getenv("TELEGRAM_TOKEN")
MP_TOKEN = os.getenv("MERCADOPAGO_ACCESS_TOKEN")

PORT = int(
    os.getenv(
        "PORT",
        "10000"
    )
)

VALOR = "29.99"

PRODUTO = "Pacote de fotos"

ID_GRUPO_VIP = -5328427809


# =========================================================
# FOTO DEMONSTRATIVA
# =========================================================
#
# DEIXE ASSIM POR ENQUANTO.
#
# Depois que você enviar a foto para o Telegram,
# vamos colocar o file_id dela aqui.
#
# Exemplo:
#
# FILE_ID_FOTO_DEMONSTRATIVA = "AgACAg..."
#
# =========================================================

FILE_ID_FOTO_DEMONSTRATIVA = ""


# =========================================================
# ORDERS JÁ PROCESSADAS
# =========================================================

ORDERS_PROCESSADAS = set()


# =========================================================
# MERCADO PAGO - CRIAR PIX
# =========================================================

def criar_pix(
    chat_id,
    email
):

    url = (
        "https://api.mercadopago.com/v1/orders"
    )

    external_reference = (
        "telegram_"
        + str(chat_id)
        + "_"
        + str(uuid.uuid4())
    )

    dados = {

        "type":
            "online",

        "external_reference":
            external_reference,

        "total_amount":
            VALOR,

        "processing_mode":
            "automatic",

        "payer": {

            "email":
                email
        },

        "transactions": {

            "payments": [

                {

                    "amount":
                        VALOR,

                    "payment_method": {

                        "id":
                            "pix",

                        "type":
                            "bank_transfer"
                    }

                }

            ]

        }

    }

    dados_json = json.dumps(
        dados
    ).encode(
        "utf-8"
    )

    headers = {

        "Content-Type":
            "application/json",

        "Authorization":
            "Bearer " + MP_TOKEN,

        "X-Idempotency-Key":
            str(uuid.uuid4())

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

            conteudo = (
                resposta
                .read()
                .decode("utf-8")
            )

            return json.loads(
                conteudo
            )

    except urllib.error.HTTPError as erro:

        corpo = (
            erro
            .read()
            .decode("utf-8")
        )

        raise Exception(
            "Mercado Pago HTTP "
            + str(erro.code)
            + ": "
            + corpo
        )


# =========================================================
# CONSULTAR ORDER
# =========================================================

def consultar_order(
    order_id
):

    url = (
        "https://api.mercadopago.com/v1/orders/"
        + str(order_id)
    )

    headers = {

        "Authorization":
            "Bearer " + MP_TOKEN

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

        conteudo = (
            resposta
            .read()
            .decode("utf-8")
        )

        return json.loads(
            conteudo
        )


# =========================================================
# CRIAR CONVITE VIP
# =========================================================

def criar_convite_vip():

    url = (
        "https://api.telegram.org/bot"
        + TOKEN
        + "/createChatInviteLink"
    )

    dados = {

        "chat_id":
            ID_GRUPO_VIP,

        "member_limit":
            1,

        "name":
            "Acesso VIP"

    }

    dados_json = json.dumps(
        dados
    ).encode(
        "utf-8"
    )

    requisicao = urllib.request.Request(

        url,

        data=dados_json,

        headers={

            "Content-Type":
                "application/json"

        },

        method="POST"

    )

    with urllib.request.urlopen(

        requisicao,

        timeout=30

    ) as resposta:

        resultado = json.loads(

            resposta
            .read()
            .decode("utf-8")

        )

    if not resultado.get(
        "ok"
    ):

        raise Exception(

            "Erro ao criar convite VIP: "
            + str(resultado)

        )

    return resultado[
        "result"
    ][
        "invite_link"
    ]


# =========================================================
# ENVIAR MENSAGEM PELO TELEGRAM
# =========================================================

def enviar_mensagem_telegram(

    chat_id,

    mensagem,

    convite=None

):

    url = (

        "https://api.telegram.org/bot"

        + TOKEN

        + "/sendMessage"

    )

    dados = {

        "chat_id":
            chat_id,

        "text":
            mensagem

    }

    if convite:

        dados[
            "reply_markup"
        ] = {

            "inline_keyboard": [

                [

                    {

                        "text":
                            "🔐 ENTRAR NO GRUPO VIP",

                        "url":
                            convite

                    }

                ]

            ]

        }

    dados_json = json.dumps(
        dados
    ).encode(
        "utf-8"
    )

    requisicao = urllib.request.Request(

        url,

        data=dados_json,

        headers={

            "Content-Type":
                "application/json"

        },

        method="POST"

    )

    with urllib.request.urlopen(

        requisicao,

        timeout=30

    ) as resposta:

        resposta.read()


# =========================================================
# PROCESSAR PAGAMENTO
# =========================================================

def processar_webhook(
    dados
):

    try:

        print(
            "========================================"
        )

        print(
            "WEBHOOK MERCADO PAGO RECEBIDO"
        )

        print(
            "Dados recebidos:",
            dados
        )

        print(
            "========================================"
        )

        data = dados.get(
            "data",
            {}
        )

        order_id = data.get(
            "id"
        )

        print(
            "Order ID recebido:",
            order_id
        )

        if not order_id:

            print(
                "Webhook sem Order ID."
            )

            return

        if str(order_id) in ORDERS_PROCESSADAS:

            print(
                "Order já processada:",
                order_id
            )

            return

        print(
            "Consultando Order:",
            order_id
        )

        order = consultar_order(
            order_id
        )

        print(
            "Order consultada:",
            order
        )

        status = order.get(
            "status"
        )

        print(
            "Status da Order:",
            status
        )

        if status != "processed":

            print(
                "Pagamento ainda não está processado."
            )

            return

        external_reference = order.get(

            "external_reference",

            ""

        )

        print(
            "External reference:",
            external_reference
        )

        if not external_reference.startswith(
            "telegram_"
        ):

            print(
                "Order não pertence ao bot."
            )

            return

        partes = external_reference.split(
            "_"
        )

        if len(partes) < 2:

            print(
                "External reference inválida."
            )

            return

        chat_id = partes[1]

        print(
            "Chat ID do comprador:",
            chat_id
        )

        convite_vip = criar_convite_vip()

        print(
            "Convite VIP criado:",
            convite_vip
        )

        mensagem = (

            "🎉 PAGAMENTO CONFIRMADO!\n\n"

            "📸 Produto: "
            + PRODUTO
            + "\n"

            "💰 Valor: R$ 29,99\n\n"

            "✅ Seu pagamento foi aprovado!\n\n"

            "🔐 Seu acesso ao Grupo VIP "
            "está liberado.\n\n"

            "👇 Clique no botão abaixo "
            "para entrar no grupo.\n\n"

            "⚠️ Este convite é individual "
            "e permite apenas 1 entrada."

        )

        enviar_mensagem_telegram(

            chat_id,

            mensagem,

            convite_vip

        )

        ORDERS_PROCESSADAS.add(
            str(order_id)
        )

        print(
            "========================================"
        )

        print(
            "PAGAMENTO CONFIRMADO:",
            order_id
        )

        print(
            "Chat:",
            chat_id
        )

        print(
            "Convite VIP:",
            convite_vip
        )

        print(
            "========================================"
        )

    except Exception as erro:

        print(
            "========================================"
        )

        print(
            "ERRO NO WEBHOOK:"
        )

        print(
            erro
        )

        print(
            "========================================"
        )


# =========================================================
# SERVIDOR RENDER
# =========================================================

class HealthHandler(
    BaseHTTPRequestHandler
):

    def do_GET(
        self
    ):

        self.send_response(
            200
        )

        self.send_header(
            "Content-Type",
            "text/plain"
        )

        self.end_headers()

        self.wfile.write(
            b"Bot online"
        )

    def do_POST(
        self
    ):

        print(
            "========================================"
        )

        print(
            "POST RECEBIDO"
        )

        print(
            "Caminho:",
            self.path
        )

        print(
            "========================================"
        )

        try:

            tamanho = int(

                self.headers.get(

                    "Content-Length",

                    "0"

                )

            )

            corpo = self.rfile.read(
                tamanho
            )

            print(
                "Corpo recebido:",
                corpo
            )

            dados = {}

            if corpo:

                try:

                    dados = json.loads(

                        corpo
                        .decode("utf-8")

                    )

                except Exception as erro:

                    print(
                        "Não foi possível ler JSON:",
                        erro
                    )

            url = urlparse(
                self.path
            )

            parametros = parse_qs(
                url.query
            )

            order_id = parametros.get(

                "data.id",

                [None]

            )[0]

            if order_id and not dados:

                dados = {

                    "data": {

                        "id":
                            order_id

                    },

                    "type":

                        parametros.get(

                            "type",

                            ["order"]

                        )[0]

                }

            if not order_id and dados:

                data_webhook = dados.get(

                    "data",

                    {}

                )

                if isinstance(

                    data_webhook,

                    dict

                ):

                    order_id = data_webhook.get(
                        "id"
                    )

            print(
                "========================================"
            )

            print(
                "DADOS FINAIS:"
            )

            print(
                dados
            )

            print(
                "Order ID:",
                order_id
            )

            print(
                "========================================"
            )

            if dados:

                threading.Thread(

                    target=processar_webhook,

                    args=(dados,),

                    daemon=True

                ).start()

        except Exception as erro:

            print(
                "ERRO RECEBENDO WEBHOOK:",
                erro
            )

        self.send_response(
            200
        )

        self.send_header(
            "Content-Type",
            "text/plain"
        )

        self.end_headers()

        self.wfile.write(
            b"OK"
        )

    def log_message(
        self,
        format,
        *args
    ):

        pass


def start_server():

    server = HTTPServer(

        (
            "0.0.0.0",
            PORT
        ),

        HealthHandler

    )

    server.serve_forever()


# =========================================================
# TELA INICIAL
# =========================================================

async def start(
    update,
    context
):

    keyboard = [

        [

            InlineKeyboardButton(

                "📸 VER PACOTE",

                callback_data="produtos"

            )

        ],

        [

            InlineKeyboardButton(

                "💳 COMPRAR AGORA",

                callback_data="comprar"

            )

        ]

    ]

    mensagem = (

        "👋 <b>Olá! Seja bem-vindo(a)</b>\n\n"

        "🔥 <b>CONTEÚDO EXCLUSIVO</b>\n\n"

        "Acesso ao nosso conteúdo privado "
        "diretamente pelo Telegram.\n\n"

        "📦 Pacote disponível\n"
        "💰 <b>R$ 29,99</b>\n"
        "🔐 Acesso privado após confirmação "
        "do pagamento."

    )

    # -----------------------------------------------------
    # Se já tivermos a foto demonstrativa,
    # enviamos foto + legenda + botões.
    # -----------------------------------------------------

    if FILE_ID_FOTO_DEMONSTRATIVA:

        await update.message.reply_photo(

            photo=FILE_ID_FOTO_DEMONSTRATIVA,

            caption=mensagem,

            parse_mode="HTML",

            reply_markup=InlineKeyboardMarkup(
                keyboard
            )

        )

    else:

        await update.message.reply_text(

            mensagem,

            parse_mode="HTML",

            reply_markup=InlineKeyboardMarkup(
                keyboard
            )

        )


# =========================================================
# VOLTAR PARA INÍCIO
# =========================================================

async def inicio(
    update,
    context
):

    query = update.callback_query

    await query.answer()

    keyboard = [

        [

            InlineKeyboardButton(

                "📸 VER PACOTE",

                callback_data="produtos"

            )

        ],

        [

            InlineKeyboardButton(

                "💳 COMPRAR AGORA",

                callback_data="comprar"

            )

        ]

    ]

    mensagem = (

        "👋 <b>Olá! Seja bem-vindo(a)</b>\n\n"

        "🔥 <b>CONTEÚDO EXCLUSIVO</b>\n\n"

        "Acesso ao nosso conteúdo privado "
        "diretamente pelo Telegram.\n\n"

        "📦 Pacote disponível\n"
        "💰 <b>R$ 29,99</b>\n"
        "🔐 Acesso privado após confirmação "
        "do pagamento."

    )

    await query.edit_message_text(

        text=mensagem,

        parse_mode="HTML",

        reply_markup=InlineKeyboardMarkup(
            keyboard
        )

    )


# =========================================================
# TELA DO PACOTE
# =========================================================

async def produtos(
    update,
    context
):

    keyboard = [

        [

            InlineKeyboardButton(

                "💳 COMPRAR AGORA",

                callback_data="comprar"

            )

        ],

        [

            InlineKeyboardButton(

                "ℹ️ MAIS INFORMAÇÕES",

                callback_data="info"

            )

        ],

        [

            InlineKeyboardButton(

                "⬅️ VOLTAR",

                callback_data="inicio"

            )

        ]

    ]

    mensagem = (

        "📸 <b>PACOTE EXCLUSIVO</b>\n\n"

        "✨ Conteúdo privado\n"
        "📦 Pacote completo\n"
        "🔐 Acesso ao grupo privado\n"
        "⚡ Liberação automática após pagamento\n\n"

        "💰 <b>R$ 29,99</b>\n\n"

        "🔞 Conteúdo destinado exclusivamente "
        "a maiores de 18 anos.\n\n"

        "👇 Escolha uma opção abaixo."

    )

    if update.callback_query:

        query = update.callback_query

        await query.answer()

        await query.edit_message_text(

            text=mensagem,

            parse_mode="HTML",

            reply_markup=InlineKeyboardMarkup(
                keyboard
            )

        )

    else:

        await update.message.reply_text(

            mensagem,

            parse_mode="HTML",

            reply_markup=InlineKeyboardMarkup(
                keyboard
            )

        )


# =========================================================
# INFORMAÇÕES
# =========================================================

async def info(
    update,
    context
):

    query = update.callback_query

    await query.answer()

    keyboard = [

        [

            InlineKeyboardButton(

                "💳 COMPRAR AGORA",

                callback_data="comprar"

            )

        ],

        [

            InlineKeyboardButton(

                "⬅️ VOLTAR",

                callback_data="produtos"

            )

        ]

    ]

    mensagem = (

        "ℹ️ <b>COMO FUNCIONA</b>\n\n"

        "1️⃣ Escolha o pacote.\n\n"

        "2️⃣ Informe seu e-mail.\n\n"

        "3️⃣ Gere o PIX.\n\n"

        "4️⃣ Faça o pagamento.\n\n"

        "5️⃣ Após a confirmação, "
        "o bot envia automaticamente "
        "seu convite individual para "
        "o Grupo VIP.\n\n"

        "🔐 O convite permite apenas "
        "1 entrada.\n\n"

        "🔞 Conteúdo exclusivo para "
        "maiores de 18 anos."

    )

    await query.edit_message_text(

        mensagem,

        parse_mode="HTML",

        reply_markup=InlineKeyboardMarkup(
            keyboard
        )

    )


# =========================================================
# COMPRA
# =========================================================

async def comprar(
    update,
    context
):

    query = update.callback_query

    await query.answer()

    keyboard = [

        [

            InlineKeyboardButton(

                "💳 CONTINUAR PARA PAGAMENTO",

                callback_data="pagamento"

            )

        ],

        [

            InlineKeyboardButton(

                "⬅️ VOLTAR",

                callback_data="produtos"

            )

        ]

    ]

    mensagem = (

        "🛒 <b>PEDIDO</b>\n\n"

        "📸 Produto: <b>Pacote de fotos</b>\n"

        "💰 Total: <b>R$ 29,99</b>\n\n"

        "🔐 Após a confirmação do pagamento, "
        "você receberá automaticamente "
        "um convite individual para o "
        "Grupo VIP.\n\n"

        "Clique abaixo para continuar."

    )

    await query.edit_message_text(

        mensagem,

        parse_mode="HTML",

        reply_markup=InlineKeyboardMarkup(
            keyboard
        )

    )


# =========================================================
# PAGAMENTO
# =========================================================

async def pagamento(
    update,
    context
):

    query = update.callback_query

    await query.answer()

    if not MP_TOKEN:

        await query.message.reply_text(

            "❌ Mercado Pago "
            "não está configurado."

        )

        return

    context.user_data[
        "aguardando_email"
    ] = True

    await query.message.reply_text(

        "📧 <b>E-MAIL PARA PAGAMENTO</b>\n\n"

        "Digite seu e-mail abaixo.\n\n"

        "Exemplo:\n"
        "<code>seuemail@gmail.com</code>\n\n"

        "🔒 O e-mail será utilizado "
        "para identificar o comprador "
        "no Mercado Pago.",

        parse_mode="HTML"

    )


# =========================================================
# RECEBER E-MAIL
# =========================================================

async def receber_email(
    update,
    context
):

    if not context.user_data.get(
        "aguardando_email"
    ):

        return

    email = (

        update.message.text

        .strip()

        .lower()

    )

    padrao_email = (

        r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

    )

    if not re.match(

        padrao_email,

        email

    ):

        await update.message.reply_text(

            "❌ E-mail inválido.\n\n"

            "Digite um e-mail válido.\n\n"

            "Exemplo:\n"
            "seuemail@gmail.com"

        )

        return

    context.user_data[
        "aguardando_email"
    ] = False

    await update.message.reply_text(

        "⏳ <b>GERANDO PIX...</b>\n\n"

        "Aguarde alguns segundos.",

        parse_mode="HTML"

    )

    try:

        resultado = await asyncio.to_thread(

            criar_pix,

            update.effective_user.id,

            email

        )

        order_id = resultado.get(
            "id"
        )

        transactions = resultado.get(

            "transactions",

            {}

        )

        payments = transactions.get(

            "payments",

            []

        )

        if not payments:

            await update.message.reply_text(

                "❌ O Mercado Pago "
                "não retornou o pagamento."

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

            await update.message.reply_text(

                "❌ O Mercado Pago "
                "não retornou o código PIX."

            )

            return

        botoes = []

        if ticket_url:

            botoes.append(

                [

                    InlineKeyboardButton(

                        "💳 ABRIR PAGAMENTO PIX",

                        url=ticket_url

                    )

                ]

            )

        botoes.append(

            [

                InlineKeyboardButton(

                    "📸 VER PACOTE",

                    callback_data="produtos"

                )

            ]

        )

        mensagem = (

            "✅ <b>PIX GERADO!</b>\n\n"

            "📸 <b>Produto:</b> Pacote de fotos\n"

            "💰 <b>Valor:</b> R$ 29,99\n\n"

            "📧 <b>E-mail:</b>\n"
            + email
            + "\n\n"

            "📋 <b>PIX COPIA E COLA:</b>\n\n"

            "<code>"
            + qr_code
            + "</code>\n\n"

            "👆 Copie o código acima "
            "e cole no aplicativo do seu banco.\n\n"

            "⏳ Depois que o pagamento "
            "for confirmado, o bot enviará "
            "automaticamente seu acesso "
            "ao Grupo VIP.\n\n"

            "🔐 O convite será individual."

        )

        await update.message.reply_text(

            mensagem,

            parse_mode="HTML",

            reply_markup=
                InlineKeyboardMarkup(
                    botoes
                )

        )

        print(
            "========================================"
        )

        print(
            "Order criada:",
            order_id
        )

        print(
            "Comprador:",
            email
        )

        print(
            "Chat:",
            update.effective_user.id
        )

        print(
            "========================================"
        )

    except Exception as erro:

        await update.message.reply_text(

            "❌ Não foi possível criar "
            "o pagamento.\n\n"

            "Erro do Mercado Pago:\n\n"

            + str(erro)

        )

        print(

            "Erro ao criar pagamento:",

            erro

        )


# =========================================================
# AJUDA
# =========================================================

async def ajuda(
    update,
    context
):

    await update.message.reply_text(

        "ℹ️ <b>AJUDA</b>\n\n"

        "/start — Abrir loja\n"
        "/produtos — Ver pacote\n"
        "/ajuda — Mostrar ajuda\n\n"

        "💳 O pagamento é realizado "
        "através do Mercado Pago.\n\n"

        "🔐 Após a confirmação, "
        "o acesso VIP é enviado "
        "automaticamente.",

        parse_mode="HTML"

    )


# =========================================================
# ID DO GRUPO
# =========================================================

async def id_grupo(
    update,
    context
):

    chat = update.effective_chat

    await update.message.reply_text(

        "🆔 ID deste grupo:\n\n"
        + str(chat.id)

    )

    print(

        "ID DO GRUPO VIP:",

        chat.id

    )


# =========================================================
# TESTE VIP
# =========================================================

async def testevip(
    update,
    context
):

    await update.message.reply_text(

        "⏳ Criando convite VIP de teste..."

    )

    try:

        convite = await asyncio.to_thread(

            criar_convite_vip

        )

        await update.message.reply_text(

            "✅ <b>CONVITE VIP CRIADO!</b>\n\n"

            "🔐 Link:\n\n"

            + convite
            + "\n\n"

            "⚠️ Este convite permite "
            "apenas 1 entrada.",

            parse_mode="HTML"

        )

        print(

            "CONVITE VIP DE TESTE:",

            convite

        )

    except Exception as erro:

        print(

            "ERRO NO /testevip:",

            erro

        )

        await update.message.reply_text(

            "❌ ERRO AO CRIAR "
            "O CONVITE VIP.\n\n"

            + str(erro)

        )


# =========================================================
# MAIN
# =========================================================

def main():

    if not TOKEN:

        raise RuntimeError(

            "TELEGRAM_TOKEN não configurado "
            "no Render."

        )

    if not MP_TOKEN:

        raise RuntimeError(

            "MERCADOPAGO_ACCESS_TOKEN "
            "não configurado no Render."

        )

    threading.Thread(

        target=start_server,

        daemon=True

    ).start()

    app = (

        Application

        .builder()

        .token(TOKEN)

        .build()

    )

    # =====================================================
    # COMANDOS
    # =====================================================

    app.add_handler(

        CommandHandler(

            "start",

            start

        )

    )

    app.add_handler(

        CommandHandler(

            "produtos",

            produtos

        )

    )

    app.add_handler(

        CommandHandler(

            "ajuda",

            ajuda

        )

    )

    app.add_handler(

        CommandHandler(

            "id",

            id_grupo

        )

    )

    app.add_handler(

        CommandHandler(

            "testevip",

            testevip

        )

    )

    # =====================================================
    # E-MAIL
    # =====================================================

    app.add_handler(

        MessageHandler(

            filters.TEXT
            & ~filters.COMMAND,

            receber_email

        )

    )

    # =====================================================
    # BOTÕES
    # =====================================================

    app.add_handler(

        CallbackQueryHandler(

            produtos,

            pattern="^produtos$"

        )

    )

    app.add_handler(

        CallbackQueryHandler(

            inicio,

            pattern="^inicio$"

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

    app.add_handler(

        CallbackQueryHandler(

            info,

            pattern="^info$"

        )

    )

    print(
        "========================================"
    )

    print(
        "BOT INICIADO COM SUCESSO!"
    )

    print(
        "Produto:",
        PRODUTO
    )

    print(
        "Valor: R$ 29,99"
    )

    print(
        "========================================"
    )

    app.run_polling()


# =========================================================
# EXECUTAR
# =========================================================

if __name__ == "__main__":

    main()k
