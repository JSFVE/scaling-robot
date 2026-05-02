import os
import logging
import unicodedata
import re
import urllib.request
import csv
import io
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from aiohttp import web

# ─── CONFIGURACIÓN ───
TOKEN    = os.environ.get("BOT_TOKEN")
SHEET_ID = "1w5mIPoB2gYc-TI86afVdSx_od42OnV2JMniFwaxr5Tw"
PORT     = int(os.environ.get("PORT", 8080))

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ─── CARGAR PRODUCTOS DESDE GOOGLE SHEETS ───
def cargar_productos():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=Hoja1"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            content = response.read().decode("utf-8")
        reader = csv.DictReader(io.StringIO(content))
        productos = []
        for row in reader:
            try:
                productos.append({
                    "id":        row.get("ID", "").strip(),
                    "nombre":    row.get("Nombre", "").strip(),
                    "categoria": row.get("Categoria", "").strip(),
                    "precio":    row.get("Precio", "").strip(),
                    "stock":     row.get("Stock", "").strip(),
                    "codigo":    row.get("Codigo", "").strip(),
                    "keywords":  row.get("Keywords", "").strip(),
                })
            except Exception:
                continue
        return productos
    except Exception as e:
        logging.error(f"Error cargando productos: {e}")
        return []

# ─── NORMALIZAR TEXTO ───
def normalizar(texto):
    texto = texto.lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[^a-z0-9\s]", "", texto)
    return texto

# ─── BUSCAR PRODUCTOS ───
def buscar_productos(query):
    productos = cargar_productos()
    terminos  = normalizar(query).split()
    return [
        p for p in productos
        if all(t in normalizar(f"{p['nombre']} {p['categoria']} {p['keywords']}") for t in terminos)
    ]

# ─── FORMATEAR RESULTADO ───
def formatear_producto(p):
    try:
        stock = int(p["stock"])
    except Exception:
        stock = 0
    if stock == 0:
        stock_texto = "❌ Sin stock"
    elif stock <= 5:
        stock_texto = f"⚠️ Poco stock: {stock} unid."
    else:
        stock_texto = f"📦 {stock} unidades"
    return (
        f"✅ *{p['nombre']}*\n"
        f"💰 Precio: *${p['precio']}*\n"
        f"📂 {p['categoria']}\n"
        f"{stock_texto}\n"
        f"🔢 Código: `{p['codigo']}`"
    )

# ─── HANDLERS ───
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Bienvenido al buscador de productos*\n\n"
        "Escribe el nombre o descripción del producto y te doy el código de barras.\n\n"
        "Ejemplos:\n"
        "→ _jabón verde_\n"
        "→ _arroz blanco_\n"
        "→ _azúcar morena_\n\n"
        "Comandos:\n"
        "/categorias — Ver por categoría\n"
        "/reload — Recargar catálogo",
        parse_mode="Markdown"
    )

async def categorias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    productos = cargar_productos()
    cats = sorted(set(p["categoria"] for p in productos if p["categoria"]))
    if not cats:
        await update.message.reply_text("⚠️ No hay categorías. Verifica el catálogo.")
        return
    texto = "📂 *Categorías disponibles:*\n\n"
    texto += "\n".join(f"• {c}" for c in cats)
    texto += "\n\nEscribe el nombre de una categoría para ver sus productos."
    await update.message.reply_text(texto, parse_mode="Markdown")

async def reload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    productos = cargar_productos()
    await update.message.reply_text(
        f"🔄 Catálogo recargado. *{len(productos)} productos* disponibles.",
        parse_mode="Markdown"
    )

async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    if len(query) < 2:
        await update.message.reply_text("Escribe al menos 2 letras para buscar.")
        return
    await update.message.reply_text("🔍 Buscando...")
    resultados = buscar_productos(query)
    if not resultados:
        await update.message.reply_text(
            f"❌ No encontré *\"{query}\"*\n\n"
            "Intenta con otras palabras:\n"
            "→ color, tamaño, para qué sirve\n\n"
            "O usa /categorias para ver todo el catálogo.",
            parse_mode="Markdown"
        )
        return
    if len(resultados) == 1:
        await update.message.reply_text(formatear_producto(resultados[0]), parse_mode="Markdown")
        return
    texto = f"🔍 Encontré *{len(resultados)} productos*:\n\n"
    for i, p in enumerate(resultados[:8], 1):
        texto += f"{i}. {p['nombre']} — *${p['precio']}*\n"
    texto += "\nEscribe el nombre más específico para ver el código."
    await update.message.reply_text(texto, parse_mode="Markdown")

# ─── SERVIDOR WEB (mismo event loop que el bot) ───
async def health(request):
    return web.Response(text="Bot activo")

async def iniciar_web():
    app_web = web.Application()
    app_web.router.add_get("/", health)
    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info(f"Servidor web activo en puerto {PORT}")

# ─── MAIN ───
async def main():
    if not TOKEN:
        raise ValueError("BOT_TOKEN no configurado")

    await iniciar_web()

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",      start))
    app.add_handler(CommandHandler("categorias", categorias))
    app.add_handler(CommandHandler("reload",     reload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, buscar))

    async with app:
        await app.start()
        logging.info("Bot iniciado ✅ Escuchando mensajes...")
        await app.updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
