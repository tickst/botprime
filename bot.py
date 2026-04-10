import os
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 7858672760
DB = "database.db"

# ---------------- DB ----------------
def db():
    return sqlite3.connect(DB)

def init_db():
    conn = db()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS users(
        user_id INTEGER PRIMARY KEY,
        balance REAL DEFAULT 0,
        ref_by INTEGER
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS products(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        category TEXT,
        price REAL,
        stock INTEGER
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        total REAL,
        status TEXT,
        location TEXT,
        created TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS order_items(
        order_id INTEGER,
        product_id INTEGER,
        qty INTEGER
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS cart(
        user_id INTEGER,
        product_id INTEGER,
        qty INTEGER
    )""")

    conn.commit()
    conn.close()

# ---------------- UTILS ----------------
def cashback(amount):
    if amount < 50:
        return amount * 0.03
    elif amount < 100:
        return amount * 0.05
    return amount * 0.07

def menu(uid):
    buttons = [
        "Жидкости","Снюс","Одноразки","POD-системы","Картриджи",
        "🛒 Корзина","👤 Профиль","🎁 Пригласить друга"
    ]
    if uid == ADMIN_ID:
        buttons.append("👑 Админ")

    return InlineKeyboardMarkup([[InlineKeyboardButton(b, callback_data=b)] for b in buttons])

def back_btn():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="back")]])

# ---------------- START ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    args = context.args

    conn = db()
    c = conn.cursor()

    ref = int(args[0]) if args else None
    c.execute("INSERT OR IGNORE INTO users(user_id, ref_by) VALUES(?,?)", (uid, ref))

    conn.commit()
    conn.close()

    await update.message.reply_text("PRIMEVAPE", reply_markup=menu(uid))

# ---------------- NAV ----------------
async def back(update, context):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("PRIMEVAPE", reply_markup=menu(q.from_user.id))

# ---------------- CATEGORY ----------------
async def category(update, context):
    q = update.callback_query
    await q.answer()
    text = q.data

    if text == "🛒 Корзина":
        return await cart(update, context)
    if text == "👤 Профиль":
        return await profile(update, context)
    if text == "👑 Админ":
        return await admin(update, context)
    if text == "🎁 Пригласить друга":
        return await referral(update, context)

    conn = db()
    c = conn.cursor()
    c.execute("SELECT id,name,price FROM products WHERE category=?", (text,))
    items = c.fetchall()
    conn.close()

    if not items:
        await q.edit_message_text("Пусто", reply_markup=back_btn())
        return

    kb = [[InlineKeyboardButton(f"{i[1]} - {i[2]}€", callback_data=f"add:{i[0]}")] for i in items]
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="back")])

    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

# ---------------- CART ----------------
async def add(update, context):
    q = update.callback_query
    await q.answer()
    pid = int(q.data.split(":")[1])
    uid = q.from_user.id

    conn = db()
    c = conn.cursor()

    c.execute("SELECT stock FROM products WHERE id=?", (pid,))
    stock = c.fetchone()[0]

    c.execute("SELECT qty FROM cart WHERE user_id=? AND product_id=?", (uid, pid))
    row = c.fetchone()

    if row:
        if row[0] >= stock:
            await q.answer("Нет в наличии")
            return
        c.execute("UPDATE cart SET qty=qty+1 WHERE user_id=? AND product_id=?", (uid, pid))
    else:
        c.execute("INSERT INTO cart VALUES(?,?,1)", (uid, pid))

    conn.commit()
    conn.close()

    await q.answer("Добавлено")

async def cart(update, context):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    conn = db()
    c = conn.cursor()

    c.execute("""SELECT p.name,p.price,c.qty FROM cart c
                 JOIN products p ON p.id=c.product_id
                 WHERE c.user_id=?""", (uid,))
    items = c.fetchall()

    if not items:
        await q.edit_message_text("Корзина пуста", reply_markup=back_btn())
        return

    total = sum(p*q for _, p, q in items)
    text = "\n".join([f"{n} x{q} = {p*q}€" for n,p,q in items])
    text += f"\n\nИтого: {total}€"

    kb = [
        [InlineKeyboardButton("Оформить", callback_data="checkout")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back")]
    ]

    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

# ---------------- ORDER ----------------
async def checkout(update, context):
    q = update.callback_query
    await q.answer()

    kb = [
        [InlineKeyboardButton("Wettersteinplatz", callback_data="loc:Wettersteinplatz")],
        [InlineKeyboardButton("Silberhornstraße", callback_data="loc:Silberhornstraße")],
        [InlineKeyboardButton("Hauptbahnhof", callback_data="loc:Hbf")]
    ]

    await q.edit_message_text("Выбери место:", reply_markup=InlineKeyboardMarkup(kb))

async def create_order(update, context):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    location = q.data.split(":")[1]

    conn = db()
    c = conn.cursor()

    c.execute("""SELECT p.id,p.price,c.qty FROM cart c
                 JOIN products p ON p.id=c.product_id
                 WHERE c.user_id=?""", (uid,))
    items = c.fetchall()

    if not items:
        await q.edit_message_text("Корзина пуста")
        return

    total = sum(p*q for _,p,q in items)

    c.execute("INSERT INTO orders(user_id,total,status,location,created) VALUES(?,?,?,?,?)",
              (uid,total,"NEW",location,str(datetime.now())))
    oid = c.lastrowid

    for pid,price,qty in items:
        c.execute("INSERT INTO order_items VALUES(?,?,?)",(oid,pid,qty))
        c.execute("UPDATE products SET stock=stock-? WHERE id=?", (qty,pid))

    c.execute("DELETE FROM cart WHERE user_id=?", (uid,))
    conn.commit()
    conn.close()

    await q.edit_message_text(f"Заказ #{oid} создан")

    await context.bot.send_message(ADMIN_ID, f"Новый заказ #{oid}\n{total}€")

# ---------------- PROFILE ----------------
async def profile(update, context):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    conn = db()
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
    bal = c.fetchone()[0]
    conn.close()

    link = f"https://t.me/{context.bot.username}?start={uid}"

    await q.edit_message_text(
        f"Баланс: {bal:.2f}€\n\nРеферальная ссылка:\n{link}",
        reply_markup=back_btn()
    )

async def referral(update, context):
    await profile(update, context)

# ---------------- ADMIN ----------------
async def admin(update, context):
    q = update.callback_query
    await q.answer()

    kb = [
        [InlineKeyboardButton("📦 Заказы", callback_data="orders")],
        [InlineKeyboardButton("➕ Добавить товар", callback_data="addp")],
        [InlineKeyboardButton("✏️ Цена", callback_data="edit_price")],
        [InlineKeyboardButton("❌ Удалить", callback_data="delete_product")],
        [InlineKeyboardButton("📢 Рассылка", callback_data="broadcast")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back")]
    ]

    await q.edit_message_text("Админка", reply_markup=InlineKeyboardMarkup(kb))

# -------- Orders --------
async def orders(update, context):
    q = update.callback_query
    await q.answer()

    conn = db()
    c = conn.cursor()
    c.execute("SELECT id,total,status FROM orders ORDER BY id DESC LIMIT 10")
    data = c.fetchall()
    conn.close()

    kb = [[InlineKeyboardButton(f"#{i[0]} {i[1]}€ {i[2]}", callback_data=f"o:{i[0]}")] for i in data]
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="back")])

    await q.edit_message_text("Заказы:", reply_markup=InlineKeyboardMarkup(kb))

async def order_manage(update, context):
    q = update.callback_query
    await q.answer()
    oid = int(q.data.split(":")[1])

    kb = [
        [InlineKeyboardButton("CONFIRMED", callback_data=f"s:{oid}:CONFIRMED")],
        [InlineKeyboardButton("IN_DELIVERY", callback_data=f"s:{oid}:IN_DELIVERY")],
        [InlineKeyboardButton("DONE", callback_data=f"s:{oid}:DONE")],
        [InlineKeyboardButton("CANCEL", callback_data=f"s:{oid}:CANCELLED")]
    ]

    await q.edit_message_text(f"Заказ {oid}", reply_markup=InlineKeyboardMarkup(kb))

async def set_status(update, context):
    q = update.callback_query
    await q.answer()

    _, oid, status = q.data.split(":")
    oid = int(oid)

    conn = db()
    c = conn.cursor()

    c.execute("UPDATE orders SET status=? WHERE id=?", (status, oid))

    if status == "DONE":
        c.execute("SELECT user_id,total FROM orders WHERE id=?", (oid,))
        uid,total = c.fetchone()

        bonus = cashback(total)
        c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (bonus,uid))

        c.execute("SELECT ref_by FROM users WHERE user_id=?", (uid,))
        ref = c.fetchone()[0]

        if ref:
            c.execute("UPDATE users SET balance=balance+3 WHERE user_id=?", (ref,))

    conn.commit()
    conn.close()

    await q.edit_message_text("Обновлено")

# -------- Broadcast --------
async def broadcast(update, context):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Отправь текст")
    context.user_data["broadcast"] = True

async def send_broadcast(update, context):
    if not context.user_data.get("broadcast"):
        return

    conn = db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    conn.close()

    for u in users:
        try:
            await context.bot.send_message(u[0], update.message.text)
        except:
            pass

    await update.message.reply_text("Готово")
    context.user_data["broadcast"] = False

# -------- Products manage --------
async def add_product(update, context):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Название;Категория;Цена;Остаток")
    context.user_data["addp"] = True

async def add_product_finish(update, context):
    if not context.user_data.get("addp"):
        return
    try:
        n,cg,p,s = update.message.text.split(";")
        conn=db();c=conn.cursor()
        c.execute("INSERT INTO products(name,category,price,stock) VALUES(?,?,?,?)",(n,cg,float(p),int(s)))
        conn.commit();conn.close()
        await update.message.reply_text("Добавлено")
    except:
        await update.message.reply_text("Ошибка")
    context.user_data["addp"]=False

async def edit_price(update, context):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("ID;новая цена")
    context.user_data["edit"]=True

async def edit_price_finish(update, context):
    if not context.user_data.get("edit"):
        return
    try:
        i,p = update.message.text.split(";")
        conn=db();c=conn.cursor()
        c.execute("UPDATE products SET price=? WHERE id=?", (float(p),int(i)))
        conn.commit();conn.close()
        await update.message.reply_text("Обновлено")
    except:
        await update.message.reply_text("Ошибка")
    context.user_data["edit"]=False

async def delete_product(update, context):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("ID товара")
    context.user_data["del"]=True

async def delete_product_finish(update, context):
    if not context.user_data.get("del"):
        return
    try:
        pid=int(update.message.text)
        conn=db();c=conn.cursor()
        c.execute("DELETE FROM products WHERE id=?", (pid,))
        conn.commit();conn.close()
        await update.message.reply_text("Удалено")
    except:
        await update.message.reply_text("Ошибка")
    context.user_data["del"]=False

# ---------------- MAIN ----------------
def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(CallbackQueryHandler(back, pattern="back"))
    app.add_handler(CallbackQueryHandler(category))
    app.add_handler(CallbackQueryHandler(add, pattern="add:"))
    app.add_handler(CallbackQueryHandler(checkout, pattern="checkout"))
    app.add_handler(CallbackQueryHandler(create_order, pattern="loc:"))

    app.add_handler(CallbackQueryHandler(admin, pattern="Админ"))
    app.add_handler(CallbackQueryHandler(orders, pattern="orders"))
    app.add_handler(CallbackQueryHandler(order_manage, pattern="o:"))
    app.add_handler(CallbackQueryHandler(set_status, pattern="s:"))

    app.add_handler(CallbackQueryHandler(broadcast, pattern="broadcast"))
    app.add_handler(CallbackQueryHandler(add_product, pattern="addp"))
    app.add_handler(CallbackQueryHandler(edit_price, pattern="edit_price"))
    app.add_handler(CallbackQueryHandler(delete_product, pattern="delete_product"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_finish))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, edit_price_finish))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, delete_product_finish))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, send_broadcast))

    app.run_polling()

if __name__ == "__main__":
    main()
