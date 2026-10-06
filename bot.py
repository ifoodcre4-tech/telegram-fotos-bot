import os
import threading
import json
import uuid
import urllib.request
import urllib.error
import re

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

def criar_pix(chat_id, email):

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
            "email": email
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

    dados_json = json.dumps(
        dados
    ).encode("utf-8")

    headers = {
        "Content-Type": "application/json",

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
            f"Mercado Pago HTTP {erro.code}: {corpo}"
        )


# =========================
# CONSULTAR ORDER
# =========================

def consultar_order(order_id):

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


# =========================
# TELEGRAM VIA API
# =========================

def enviar_telegram(
    chat_id,
    mensagem
):

    url = (
        "https://api.telegram.org/bot"
        + TOKEN
        + "/sendMessage"
    )

    dados = {
        "chat_id": chat_id,
        "text": mensagem
    }

    dados_json = json.dumps(
        dados
    ).encode("utf-8")

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
        "chat_id":
            ID_GRUPO_VIP,

        "member_limit":
            1,

        "name":
            "Convite VIP"
    }

    dados_json = json.dumps(
        dados
    ).encode("utf-8")

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

    if not resultado.get("ok"):

        raise Exception(
            "Erro ao criar convite VIP: "
            + str(resultado)
        )

    return resultado[
        "result"
    ][
        "invite_link"
    ]


# =========================
# WEBHOOK MERCADO PAGO
# =========================

def processar_webhook(dados):

    try:

        print("========================================")
        print("WEBHOOK MERCADO PAGO RECEBIDO")
        print("Dados recebidos:", dados)
        print("========================================")

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
                "Webhook recebido sem Order ID."
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
                "Pagamento ainda não está como processed."
            )

            return

        external_reference = (
            order.get(
                "external_reference",
                ""
            )
        )

        print(
            "External reference:",
            external_reference
        )

        if not external_reference.startswith(
            "telegram_"
        ):

            print(
                "External reference não pertence ao bot."
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
            "✅ PAGAMENTO CONFIRMADO!\n\n"

            "📸 Produto: Pacote de fotos\n"
            "💰 Valor: R$ 29,99\n\n"

            "🎉 Seu pagamento foi aprovado!\n\n"

            "🔐 Seu acesso ao Grupo VIP "
            "está liberado.\n\n"

            "👇 Clique no botão abaixo "
            "para entrar:"
        )

        url = (
            "https://api.telegram.org/bot"
            + TOKEN
            + "/sendMessage"
        )

        dados_mensagem = {

            "chat_id":
                chat_id,

            "text":
                mensagem,

            "reply_markup": {

                "inline_keyboard": [

                    [

                        {
                            "text":
                                "🔐 ENTRAR NO GRUPO VIP",

                            "url":
                                convite_vip
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


# =========================
# SERVIDOR DO RENDER
# =========================

class HealthHandler(
    BaseHTTPRequestHandler
):

    def do_GET(self):

        print("========================================")
        print("REQUISIÇÃO GET RECEBIDA")
        print("Caminho:", self.path)
        print("========================================")

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


    def do_POST(self):

        print("========================================")
        print("POST RECEBIDO NO WEBHOOK")
        print("Caminho:", self.path)
        print("========================================")

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

            # =========================
            # TENTA LER JSON
            # =========================

            if corpo:

                try:

                    dados = json.loads(
                        corpo.decode("utf-8")
                    )

                except Exception as erro:

                    print(
                        "Corpo não é JSON:",
                        erro
                    )


            # =========================
            # LER PARÂMETROS DA URL
            # =========================

            url = urlparse(
                self.path
            )

            parametros = parse_qs(
                url.query
            )

            print(
                "Parâmetros recebidos:",
                parametros
            )

            order_id = parametros.get(
                "data.id",
                [None]
            )[0]


            # =========================
            # DATA.ID VEIO NA URL
            # =========================

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


            # =========================
            # TAMBÉM ACEITA ID DIRETO
            # =========================

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


            print("========================================")
            print("DADOS FINAIS DO WEBHOOK:")
            print(dados)
            print("Order ID:", order_id)
            print("========================================")


            # =========================
            # PROCESSAR WEBHOOK
            # =========================

            if dados:

                threading.Thread(

                    target=processar_webhook,

                    args=(
                        dados,
                    ),

                    daemon=True

                ).start()

            else:

                print(
                    "Webhook recebido sem dados."
                )


        except Exception as erro:

            print("========================================")
            print("ERRO RECEBENDO WEBHOOK:")
            print(erro)
            print("========================================")


        # =========================
        # RESPONDER MERCADO PAGO
        # =========================

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
        ("0.0.0.0", PORT),
        HealthHandler
    )

    server.serve_forever()


# =========================
# START
# =========================

async def start(
    update,
    context
):

    keyboard = [[

        InlineKeyboardButton(
            "🛍️ Ver produtos",
            callback_data="produtos"
        )

    ]]

    await update.message.reply_text(

        "👋 Olá! Bem-vindo à nossa loja!\n\n"

        "Clique abaixo para ver "
        "o produto disponível:",

        reply_markup=
            InlineKeyboardMarkup(
                keyboard
            ),
    )


# =========================
# PRODUTOS
# =========================

async def produtos(
    update,
    context
):

    keyboard = [[

        InlineKeyboardButton(
            "🛒 Comprar — R$ 29,99",
            callback_data="comprar"
        )

    ]]

    mensagem = (

        "🛍️ *Produto disponível*\n\n"

        "📸 Pacote de fotos\n"

        "💰 Valor: *R$ 29,99*\n\n"

        "Clique no botão abaixo "
        "para comprar."
    )

    if update.callback_query:

        await update.callback_query.answer()

        await update.callback_query.edit_message_text(

            mensagem,

            parse_mode="Markdown",

            reply_markup=
                InlineKeyboardMarkup(
                    keyboard
                ),
        )

    else:

        await update.message.reply_text(

            mensagem,

            parse_mode="Markdown",

            reply_markup=
                InlineKeyboardMarkup(
                    keyboard
                ),
        )


# =========================
# COMPRA
# =========================

async def comprar(
    update,
    context
):

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

        "Clique abaixo para "
        "continuar para o pagamento.",

        parse_mode="Markdown",

        reply_markup=
            InlineKeyboardMarkup(
                keyboard
            ),
    )


# =========================
# PAGAMENTO
# =========================

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

        "📧 *Antes de gerar o PIX*\n\n"

        "Digite seu e-mail abaixo.\n\n"

        "Exemplo:\n"
        "seuemail@gmail.com\n\n"

        "🔒 O e-mail será usado "
        "para identificar o comprador "
        "no Mercado Pago.",

        parse_mode="Markdown"
    )


# =========================
# RECEBER E-MAIL
# =========================

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

        "⏳ Gerando seu PIX...\n\n"
        "Aguarde alguns segundos."
    )

    try:

        resultado = await __import__(
            "asyncio"
        ).to_thread(

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

            botoes.append([

                InlineKeyboardButton(

                    "💳 Abrir pagamento PIX",

                    url=ticket_url
                )

            ])

        botoes.append([

            InlineKeyboardButton(

                "🛍️ Voltar aos produtos",

                callback_data="produtos"
            )

        ])

        mensagem = (

            "✅ *PIX gerado com sucesso!*\n\n"

            "📸 Produto: *Pacote de fotos*\n"

            "💰 Valor: *R$ 29,99*\n\n"

            "📧 E-mail informado:\n"
            f"{email}\n\n"

            "📋 *PIX Copia e Cola:*\n\n"

            f"`{qr_code}`\n\n"

            "Copie o código acima e cole "
            "no aplicativo do seu banco "
            "para pagar.\n\n"

            "⏳ Após o pagamento ser confirmado, "
            "você receberá automaticamente "
            "o acesso ao Grupo VIP."
        )

        await update.message.reply_text(

            mensagem,

            parse_mode="Markdown",

            reply_markup=
                InlineKeyboardMarkup(
                    botoes
                )
        )

        print(
            "Order criada:",
            order_id
        )

        print(
            "Comprador:",
            email
        )

    except Exception as erro:

        await update.message.reply_text(

            "❌ Não foi possível criar "
            "o pagamento.\n\n"

            "Erro do Mercado Pago:\n\n"

            f"{erro}"
        )

        print(
            "Erro ao criar pagamento:",
            erro
        )


# =========================
# AJUDA
# =========================

async def ajuda(
    update,
    context
):

    await update.message.reply_text(

        "ℹ️ *Comandos disponíveis:*\n\n"

        "/start — Iniciar\n"

        "/produtos — Ver produtos\n"

        "/ajuda — Ajuda\n"

        "/id — Ver ID do grupo\n"

        "/testevip — Criar convite VIP de teste",

        parse_mode="Markdown",
    )


# =========================
# ID DO GRUPO VIP
# =========================

async def id_grupo(
    update,
    context
):

    chat = update.effective_chat

    await update.message.reply_text(

        f"🆔 ID deste grupo:\n\n{chat.id}"
    )

    print(
        "ID DO GRUPO VIP:",
        chat.id
    )


# =========================
# TESTAR CONVITE VIP
# =========================

async def testevip(
    update,
    context
):

    await update.message.reply_text(

        "⏳ Recebi o comando /testevip!\n\n"

        "🔐 Estou tentando criar "
        "o convite VIP..."
    )

    try:

        convite = await __import__(
            "asyncio"
        ).to_thread(
            criar_convite_vip
        )

        await update.message.reply_text(

            "✅ CONVITE VIP CRIADO!\n\n"

            "🔐 Link de teste:\n\n"

            f"{convite}\n\n"

            "⚠️ Este convite permite "
            "apenas 1 entrada."
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

            "Detalhes do erro:\n\n"

            f"{erro}"
        )


# =========================
# MAIN
# =========================

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

    app.add_handler(

        MessageHandler(

            filters.TEXT
            & ~filters.COMMAND,

            receber_email
        )

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


# =========================
# EXECUTAR
# =========================

if __name__ == "__main__":

    main()
