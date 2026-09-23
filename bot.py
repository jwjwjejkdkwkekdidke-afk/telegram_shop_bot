import asyncio
import logging
import os
from html import escape
from decimal import Decimal, InvalidOperation

import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InputMediaPhoto,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
SHOP_NAME = os.getenv("SHOP_NAME", "Stars Shop")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "your_support")
YOOMONEY_CARD = os.getenv("YOOMONEY_CARD", "УКАЖИТЕ_РЕКВИЗИТЫ_В_.ENV")
TON_WALLET = os.getenv("TON_WALLET", "УКАЖИТЕ_TON_КОШЕЛЁК_В_.ENV")
DB_PATH = "shop.db"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not configured. Copy .env.example to .env and add your token.")

logging.basicConfig(level=logging.INFO)
dp = Dispatcher(storage=MemoryStorage())


class TonStates(StatesGroup):
    waiting_amount = State()
    waiting_username = State()


class PremiumStates(StatesGroup):
    waiting_friend_username = State()


class StarsStates(StatesGroup):
    waiting_friend_username = State()


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                referrals INTEGER DEFAULT 0,
                referred_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


async def upsert_user(user):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users(user_id, username, first_name)
            VALUES(?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name
        """, (user.id, user.username, user.first_name))
        await db.commit()


async def register_referral(user_id: int, referrer_id: int):
    if user_id == referrer_id:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT referred_by FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cur.fetchone()
        if not row or row[0] is not None:
            return
        cur = await db.execute(
            "SELECT user_id FROM users WHERE user_id = ?", (referrer_id,)
        )
        if not await cur.fetchone():
            return
        await db.execute(
            "UPDATE users SET referred_by = ? WHERE user_id = ?",
            (referrer_id, user_id),
        )
        await db.execute(
            "UPDATE users SET referrals = referrals + 1 WHERE user_id = ?",
            (referrer_id,),
        )
        await db.commit()


def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐ Купить Stars", callback_data="shop:stars"),
            InlineKeyboardButton(text="💎 Купить TON", callback_data="shop:ton"),
        ],
        [InlineKeyboardButton(text="🎁 Покупка и Аренда NFT", callback_data="shop:nft")],
        [
            InlineKeyboardButton(text="🧬 Premium", callback_data="shop:premium"),
            InlineKeyboardButton(text="🎟 ROBLOX", callback_data="shop:roblox"),
        ],
        [InlineKeyboardButton(text="🎮 Цифровые товары", callback_data="shop:digital")],
        [
            InlineKeyboardButton(text="😭 Поддержка ↗", callback_data="support"),
            InlineKeyboardButton(text="🧑‍💻 Профиль", callback_data="profile"),
        ],
        [InlineKeyboardButton(text="🏆 Топ по рефералам", callback_data="ref_top")],
        [InlineKeyboardButton(text="🤖 СОЗДАТЬ СВОЕГО БОТА ↗", callback_data="create_bot")],
    ])


def back_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩ Назад", callback_data="menu")]
    ])


WELCOME = """✨ <b>Добро пожаловать!</b>

🛍 У нас Вы можете приобрести <b>Telegram Stars</b> и <b>Telegram Premium</b> на свой аккаунт за рубли ✨

🛒 <b>Хороших покупок!</b> ❤️"""


async def edit_screen(message: Message, text: str, reply_markup=None, image_path=None):
    try:
        if image_path and os.path.exists(image_path):
            if message.photo:
                return await message.edit_media(
                    media=InputMediaPhoto(media=FSInputFile(image_path), caption=text),
                    reply_markup=reply_markup,
                )
            return await message.answer_photo(
                photo=FSInputFile(image_path),
                caption=text,
                reply_markup=reply_markup,
            )
        if message.photo:
            return await message.edit_caption(caption=text, reply_markup=reply_markup)
        return await message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        pass  # Игнорируем ошибку, если контент сообщения не изменился


IMAGE_MAIN = "welcome.png"
IMAGE_STARS = "stars.jpg"
IMAGE_TON = "ton.jpg"
IMAGE_PREMIUM = "premium.jpg"
IMAGE_ROBLOX = "roblox.jpg"
IMAGE_NFT = "nft.jpg"
IMAGE_DIGITAL = "digital.png"


@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await upsert_user(message.from_user)

    args = message.text.split(maxsplit=1)
    if len(args) == 2 and args[1].startswith("ref_"):
        try:
            await register_referral(message.from_user.id, int(args[1][4:]))
        except ValueError:
            pass

    if os.path.exists(IMAGE_MAIN):
        await message.answer_photo(
            photo=FSInputFile(IMAGE_MAIN),
            caption=WELCOME,
            reply_markup=main_menu(),
        )
    else:
        await message.answer(WELCOME, reply_markup=main_menu())


@dp.callback_query(F.data == "menu")
async def menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await edit_screen(callback.message, WELCOME, main_menu(), image_path=IMAGE_MAIN)


# ---------------- STARS ----------------

STARS_PRICES = [
    (50, 74),
    (100, 148),
    (150, 222),
    (250, 370),
    (500, 740),
    (1000, 1480),
    (2500, 3700),
]


def stars_recipient_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐ Купить себе", callback_data="stars:recipient:self"),
            InlineKeyboardButton(text="⭐ Купить другу", callback_data="stars:recipient:friend"),
        ],
        [InlineKeyboardButton(text="↩ Назад", callback_data="menu")],
    ])


def stars_packages_keyboard(recipient):
    rows = []
    for amount, price in STARS_PRICES:
        rows.append([
            InlineKeyboardButton(
                text=f"⭐ {amount} звёзд - {price}₽",
                callback_data=f"stars:package:{recipient}:{amount}:{price}",
            )
        ])
    rows.append([InlineKeyboardButton(text="↩ Назад", callback_data="stars:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(F.data == "shop:stars")
async def shop_stars(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await edit_screen(
        callback.message,
        "⭐ <b>Покупка звёзд</b>\n\n👤 <b>Выберите получателя звёзд:</b>",
        stars_recipient_keyboard(),
        image_path=IMAGE_STARS,
    )


@dp.callback_query(F.data == "stars:main")
async def stars_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await edit_screen(
        callback.message,
        "⭐ <b>Покупка звёзд</b>\n\n👤 <b>Выберите получателя звёзд:</b>",
        stars_recipient_keyboard(),
        image_path=IMAGE_STARS,
    )


@dp.callback_query(F.data.startswith("stars:recipient:"))
async def stars_recipient(callback: CallbackQuery, state: FSMContext):
    recipient = callback.data.rsplit(":", 1)[1]
    await state.clear()
    await callback.answer()

    if recipient == "friend":
        await state.set_state(StarsStates.waiting_friend_username)
        await state.update_data(recipient=recipient)
        await edit_screen(
            callback.message,
            "⭐ <b>Покупка звёзд</b>\n\nВведите имя пользователя человека, которому хотите отправить Stars.\n\nПример: <code>@username</code>",
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="↩ Назад", callback_data="stars:main")]
            ]),
            image_path=IMAGE_STARS,
        )
        return

    await edit_screen(
        callback.message,
        "⭐ <b>Покупка звёзд</b>\n\n👤 Получатель: <b>себя</b>\n\n👇 <b>Выберите необходимый пакет:</b>",
        stars_packages_keyboard("self"),
        image_path=IMAGE_STARS,
    )


@dp.message(StarsStates.waiting_friend_username)
async def stars_friend_username(message: Message, state: FSMContext):
    username = message.text.strip()
    if not username.startswith("@"):
        username = "@" + username.lstrip("@")
    await state.clear()

    await state.update_data(friend_username=username)

    text = (
        "⭐ <b>Покупка звёзд</b>\n\n"
        f"👤 Получатель: <b>{escape(username)}</b>\n\n"
        "👇 <b>Выберите необходимый пакет:</b>"
    )
    if os.path.exists(IMAGE_STARS):
        await message.answer_photo(
            photo=FSInputFile(IMAGE_STARS),
            caption=text,
            reply_markup=stars_packages_keyboard("friend"),
        )
    else:
        await message.answer(text, reply_markup=stars_packages_keyboard("friend"))


@dp.callback_query(F.data.startswith("stars:package:"))
async def stars_package(callback: CallbackQuery, state: FSMContext):
    _, _, recipient, amount, price = callback.data.split(":")
    data = await state.get_data()
    friend_username = data.get("friend_username", "")
    await callback.answer()

    recipient_text = "себя" if recipient == "self" else escape(friend_username)
    text = (
        "⭐ <b>Покупка звёзд</b>\n\n"
        f"👤 Получатель: <b>{recipient_text}</b>\n"
        f"⭐ К получению: <b>{amount} Stars</b>\n"
        f"💳 Сумма к оплате: <b>{price}₽</b>\n\n"
        "👇 <b>Выберите способ оплаты:</b>"
    )
    await edit_screen(
        callback.message,
        text,
        payment_keyboard(f"stars:package:{recipient}:{amount}:{price}"),
        image_path=IMAGE_STARS,
    )


# ---------------- TON / GRAM ----------------

GRAM_RATE = Decimal("124.31")
GRAM_MIN = 1
GRAM_MAX = 200


def ton_type_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Купить внутренние TG GRAM(TON)", callback_data="ton:internal")],
        [InlineKeyboardButton(text="↩ Назад", callback_data="menu")],
    ])


@dp.callback_query(F.data == "shop:ton")
async def shop_ton(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    text = (
        "💎 <b>Купить внутренние TG GRAM(TON)</b>\n\n"
        "<b>Выберите тип GRAM(TON), которые хотите приобрести.</b>"
    )
    await edit_screen(callback.message, text, ton_type_keyboard(), image_path=IMAGE_TON)


@dp.callback_query(F.data == "ton:internal")
async def ton_internal(callback: CallbackQuery, state: FSMContext):
    await state.set_state(TonStates.waiting_amount)
    await callback.answer()
    text = (
        "💎 <b>Купить внутренние TG GRAM(TON)</b>\n\n"
        f"⚡️<b>Минимум :</b> <i>{GRAM_MIN}</i>\n"
        f"⚡️<b>Максимум:</b> <i>{GRAM_MAX}</i>\n\n"
        "👇 <b>Введите количество GRAM(TON), которое вы хотите купить</b>"
    )
    await edit_screen(
        callback.message,
        text,
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩ Назад", callback_data="shop:ton")]
        ]),
        image_path=IMAGE_TON,
    )


@dp.message(TonStates.waiting_amount)
async def ton_amount(message: Message, state: FSMContext):
    raw = message.text.strip().replace(",", ".")
    try:
        amount = int(raw)
    except ValueError:
        await message.answer("⚠️ Введите целое число от 1 до 200.")
        return

    if amount < GRAM_MIN or amount > GRAM_MAX:
        await message.answer("⚠️ Количество должно быть от 1 до 200.")
        return

    total = (GRAM_RATE * Decimal(amount)).quantize(Decimal("0.01"))
    await state.update_data(amount=amount, total=str(total))
    await state.set_state(TonStates.waiting_username)

    text = (
        f"💎 <b>Текущий курс:</b> 1 <i>GRAM(TON) = {GRAM_RATE:.2f} руб.</i>\n\n"
        f"💳 <b>Сумма к оплате:</b> {total:.2f} <i>руб.</i>\n"
        f"💳 <b>К получению:</b> {amount} <i>GRAM(TON)</i>\n\n"
        "👇 <b>Введите юзернейм на который будут отправлены GRAM(TON)</b> (например, @username)"
    )
    if os.path.exists(IMAGE_TON):
        await message.answer_photo(photo=FSInputFile(IMAGE_TON), caption=text)
    else:
        await message.answer(text)


@dp.message(TonStates.waiting_username)
async def ton_username(message: Message, state: FSMContext):
    username = message.text.strip()
    if not username.startswith("@"):
        username = "@" + username.lstrip("@")
    data = await state.get_data()
    amount = data["amount"]
    total = data["total"]
    await state.clear()

    text = (
        "💎 <b>Купить внутренние TG GRAM(TON)</b>\n\n"
        f"💳 <b>Сумма к оплате:</b> {total} <i>руб.</i>\n"
        f"💳 <b>К получению:</b> {amount} <i>GRAM(TON)</i>\n"
        f"👤 <b>Получатель:</b> {escape(username)}\n\n"
        "👇 <b>Выберите способ оплаты:</b>"
    )
    await edit_screen(
        message,
        text,
        payment_keyboard(f"ton:order:{amount}:{total}:{username}"),
        image_path=IMAGE_TON,
    )


# ---------------- PREMIUM ----------------

PREMIUM_PRICES = [
    ("3 месяца", 1099),
    ("6 месяцев", 1449),
    ("12 месяцев", 2499),
]


def premium_recipient_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🧬 Купить себе", callback_data="premium:self"),
            InlineKeyboardButton(text="🧬 Купить другу", callback_data="premium:friend"),
        ],
        [InlineKeyboardButton(text="↩ Назад", callback_data="menu")],
    ])


def premium_packages_keyboard(recipient, username=""):
    rows = []
    for label, price in PREMIUM_PRICES:
        rows.append([
            InlineKeyboardButton(
                text=f"{label} - {price} рублей",
                callback_data=f"premium:package:{recipient}:{price}:{username}",
            )
        ])
    rows.append([InlineKeyboardButton(text="↩ Назад", callback_data="premium:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(F.data == "shop:premium")
async def shop_premium(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await edit_screen(
        callback.message,
        "🧬 <b>Покупка премиума</b>\n\n<i>• Выберите получателя премиума:</i>",
        premium_recipient_keyboard(),
        image_path=IMAGE_PREMIUM,
    )


@dp.callback_query(F.data == "premium:main")
async def premium_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await edit_screen(
        callback.message,
        "🧬 <b>Покупка премиума</b>\n\n<i>• Выберите получателя премиума:</i>",
        premium_recipient_keyboard(),
        image_path=IMAGE_PREMIUM,
    )


@dp.callback_query(F.data == "premium:self")
async def premium_self(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await edit_screen(
        callback.message,
        "🧬 <b>Покупка премиума</b>\n\n👤 Получатель: <b>себя</b>\n\n👇 <b>Выберите срок:</b>",
        premium_packages_keyboard("self"),
        image_path=IMAGE_PREMIUM,
    )


@dp.callback_query(F.data == "premium:friend")
async def premium_friend(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PremiumStates.waiting_friend_username)
    await callback.answer()
    await edit_screen(
        callback.message,
        "🧬 <b>Покупка премиума</b>\n\n👤 <b>Введите имя пользователя друга:</b>\n\nПример: <code>@username</code>",
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩ Назад", callback_data="premium:main")]
        ]),
        image_path=IMAGE_PREMIUM,
    )


@dp.message(PremiumStates.waiting_friend_username)
async def premium_friend_username(message: Message, state: FSMContext):
    username = message.text.strip()
    if not username.startswith("@"):
        username = "@" + username.lstrip("@")
    
    await state.update_data(friend_username=username)

    text = (
        "🧬 <b>Покупка премиума</b>\n\n"
        f"👤 Получатель: <b>{escape(username)}</b>\n\n"
        "👇 <b>Выберите срок:</b>"
    )
    if os.path.exists(IMAGE_PREMIUM):
        await message.answer_photo(
            photo=FSInputFile(IMAGE_PREMIUM),
            caption=text,
            reply_markup=premium_packages_keyboard("friend", username),
        )
    else:
        await message.answer(text, reply_markup=premium_packages_keyboard("friend", username))


@dp.callback_query(F.data.startswith("premium:package:"))
async def premium_package(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    recipient = parts[2]
    price = parts[3]
    username = parts[4] if len(parts) > 4 else ""
    
    if not username:
        data = await state.get_data()
        username = data.get("friend_username", "")

    await callback.answer()

    recipient_text = "себя" if recipient == "self" else escape(username)
    label = next((x[0] for x in PREMIUM_PRICES if str(x[1]) == price), "Премиум")
    text = (
        "🧬 <b>Покупка премиума</b>\n\n"
        f"👤 Получатель: <b>{recipient_text}</b>\n"
        f"🧬 Срок: <b>{label}</b>\n"
        f"💳 Сумма к оплате: <b>{price}₽</b>\n\n"
        "👇 <b>Выберите способ оплаты:</b>"
    )
    await edit_screen(
        callback.message,
        text,
        payment_keyboard(f"premium:package:{recipient}:{price}:{username}"),
        image_path=IMAGE_PREMIUM,
    )


# ---------------- ROBLOX ----------------

ROBLOX_PACKAGES_RU = [
    (199, 315),
    (399, 629),
    (799, 1259),
    (1199, 1889),
    (1700, 2679),
    (4500, 7089),
    (10000, 15749),
]


def roblox_region_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 RU", callback_data="roblox:region:ru")],
        [InlineKeyboardButton(text="↩ Назад", callback_data="menu")],
    ])


def roblox_packages_keyboard():
    rows = []
    for robux, price in ROBLOX_PACKAGES_RU:
        rows.append([
            InlineKeyboardButton(
                text=f"🎟 {robux} Robux — {price}₽",
                callback_data=f"roblox:package:{robux}:{price}",
            )
        ])
    rows.append([InlineKeyboardButton(text="↩ Назад", callback_data="roblox:region")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(F.data == "shop:roblox")
async def shop_roblox(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await edit_screen(
        callback.message,
        "🎟 <b>ROBLOX</b>\n\n👇 <b>Выберите регион:</b>",
        roblox_region_keyboard(),
        image_path=IMAGE_ROBLOX,
    )


@dp.callback_query(F.data == "roblox:region")
async def roblox_region(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await edit_screen(
        callback.message,
        "🎟 <b>ROBLOX</b>\n\n👇 <b>Выберите регион:</b>",
        roblox_region_keyboard(),
        image_path=IMAGE_ROBLOX,
    )


@dp.callback_query(F.data == "roblox:region:ru")
async def roblox_ru(callback: CallbackQuery):
    await callback.answer()
    await edit_screen(
        callback.message,
        "🎟 <b>ROBLOX</b>\n\n🇷🇺 <b>Регион: RU</b>\n\n👇 <b>Выберите количество Robux:</b>",
        roblox_packages_keyboard(),
        image_path=IMAGE_ROBLOX,
    )


@dp.callback_query(F.data.startswith("roblox:package:"))
async def roblox_package(callback: CallbackQuery):
    _, _, robux, price = callback.data.split(":")
    await callback.answer()
    text = (
        "🎟 <b>ROBLOX</b>\n\n"
        f"🇷🇺 Регион: <b>RU</b>\n"
        f"🎟 Количество: <b>{robux} Robux</b>\n"
        f"💳 Сумма к оплате: <b>{price}₽</b>\n\n"
        "👇 <b>Выберите способ оплаты:</b>"
    )
    await edit_screen(
        callback.message,
        text,
        payment_keyboard(f"roblox:package:{robux}:{price}"),
        image_path=IMAGE_ROBLOX,
    )


# ---------------- PAYMENT & CHECKOUT ----------------

def payment_keyboard(back_callback: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💳 Оплата по карте",
            callback_data=f"pay:card:{back_callback}",
        )],
        [InlineKeyboardButton(
            text="💎 Оплата в TON",
            callback_data=f"pay:ton:{back_callback}",
        )],
        [InlineKeyboardButton(text="↩ Назад", callback_data=back_callback)],
    ])


@dp.callback_query(F.data.startswith("pay:"))
async def payment_method(callback: CallbackQuery):
    parts = callback.data.split(":")
    method = parts[1]
    order_info = ":".join(parts[2:])
    await callback.answer()

    if method == "card":
        text = (
            "💳 <b>Оплата по карте</b>\n\n"
            "Переведите точную сумму на реквизиты:\n\n"
            f"💳 <code>{escape(YOOMONEY_CARD)}</code>\n\n"
            "После перевода нажмите кнопку ниже для отправки чека/заказа администратору."
        )
    else:
        text = (
            "💎 <b>Оплата в TON</b>\n\n"
            "Переведите точную сумму на TON-адрес:\n\n"
            f"💎 <code>{escape(TON_WALLET)}</code>\n\n"
            "После перевода нажмите кнопку ниже для подтверждения."
        )

    current_image = IMAGE_STARS
    if "ton" in order_info:
        current_image = IMAGE_TON
    elif "premium" in order_info:
        current_image = IMAGE_PREMIUM
    elif "roblox" in order_info:
        current_image = IMAGE_ROBLOX

    await edit_screen(
        callback.message,
        text,
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="✅ Я оплатил",
                callback_data=f"confirm_pay:{method}:{order_info}",
            )],
            [InlineKeyboardButton(
                text="↩ Назад к заказу",
                callback_data=order_info,
            )],
        ]),
        image_path=current_image,
    )


@dp.callback_query(F.data.startswith("confirm_pay:"))
async def confirm_payment_user(callback: CallbackQuery):
    _, method, *order_parts = callback.data.split(":")
    order_info = ":".join(order_parts)
    user = callback.from_user

    details = f"Способ оплаты: {'Карта' if method == 'card' else 'TON'}\nДанные заказа: <code>{escape(order_info)}</code>"

    admin_text = (
        "🔔 <b>Новый заказ на проверку!</b>\n\n"
        f"👤 Покупатель: {escape(user.full_name)} (@{user.username if user.username else 'нет'}, ID: <code>{user.id}</code>)\n"
        f"{details}\n\n"
        "Подтвердить или отклонить?"
    )

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Принять 🟢", callback_data=f"admin:accept:{user.id}"),
            InlineKeyboardButton(text="Отклонить 🔴", callback_data=f"admin:reject:{user.id}"),
        ]
    ])

    try:
        await callback.bot.send_message(chat_id=ADMIN_ID, text=admin_text, reply_markup=admin_kb)
    except Exception as e:
        logging.error(f"Не удалось отправить уведомление админу: {e}")

    await callback.answer("Заказ отправлен администратору!", show_alert=True)
    await edit_screen(
        callback.message,
        "⏳ <b>Ваш заказ отправлен на проверку администратору!</b>\n\nОжидайте подтверждения, скоро мы всё проверим и обработаем.",
        back_menu(),
        image_path=IMAGE_MAIN,
    )


@dp.callback_query(F.data.startswith("admin:accept:") | F.data.startswith("admin:reject:"))
async def admin_decision(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("У вас нет прав!", show_alert=True)
        return

    parts = callback.data.split(":")
    action = parts[1]
    target_user_id = int(parts[2])

    await callback.answer()

    if action == "accept":
        await callback.message.edit_text(callback.message.html_text + "\n\n<b>✅ СТАТУС: Подтвержден (Одобрено)</b>", reply_markup=None)
        try:
            await callback.bot.send_message(
                target_user_id,
                "🎉 <b>Ваш заказ успешно подтвержден администратором!</b>\nСпасибо за покупку! ❤️",
                reply_markup=back_menu()
            )
        except Exception:
            pass
    else:
        await callback.message.edit_text(callback.message.html_text + "\n\n<b>❌ СТАТУС: Отклонен</b>", reply_markup=None)
        try:
            await callback.bot.send_message(
                target_user_id,
                "❌ <b>К сожалению, ваш заказ был отклонен администратором.</b>\nЕсли у вас есть вопросы, обратитесь в поддержку.",
                reply_markup=back_menu()
            )
        except Exception:
            pass


# ---------------- OTHER MENU ----------------

@dp.callback_query(F.data == "shop:nft")
async def shop_nft(callback: CallbackQuery):
    await callback.answer()
    await edit_screen(
        callback.message,
        "🎁 <b>Покупка и Аренда NFT</b>\n\nКаталог NFT будет добавлен следующим этапом.",
        back_menu(),
        image_path=IMAGE_NFT,
    )


@dp.callback_query(F.data == "shop:digital")
async def shop_digital(callback: CallbackQuery):
    await callback.answer()
    await edit_screen(
        callback.message,
        "🎮 <b>Цифровые товары</b>\n\nКаталог цифровых товаров будет добавлен следующим этапом.",
        back_menu(),
        image_path=IMAGE_DIGITAL,
    )


@dp.callback_query(F.data == "support")
async def support(callback: CallbackQuery):
    await callback.answer()
    username = SUPPORT_USERNAME.lstrip("@")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💬 Написать в поддержку",
            url=f"https://t.me/{username}",
        )],
        [InlineKeyboardButton(text="↩ Назад", callback_data="menu")],
    ])
    await edit_screen(
        callback.message,
        f"😭 <b>Поддержка</b>\n\nНапишите нам: @{escape(username)}",
        kb,
        image_path=IMAGE_MAIN,
    )


@dp.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):
    await callback.answer()
    user = callback.from_user
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT referrals FROM users WHERE user_id = ?", (user.id,)
        )
        row = await cur.fetchone()
    referrals = row[0] if row else 0

    text = (
        "🧑‍💻 <b>Профиль</b>\n\n"
        f"ID: <code>{user.id}</code>\n"
        f"Имя: {escape(user.full_name)}\n"
        f"Username: @{escape(user.username) if user.username else 'нет'}\n"
        f"👥 Рефералов: <b>{referrals}</b>"
    )
    await edit_screen(
        callback.message,
        text,
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Моя реферальная ссылка", callback_data="ref_link")],
            [InlineKeyboardButton(text="↩ Назад", callback_data="menu")],
        ]),
        image_path=IMAGE_MAIN,
    )


@dp.callback_query(F.data == "ref_link")
async def ref_link(callback: CallbackQuery):
    await callback.answer()
    me = await callback.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{callback.from_user.id}"
    await edit_screen(
        callback.message,
        "🔗 <b>Ваша реферальная ссылка</b>\n\n"
        f"<code>{link}</code>",
        back_menu(),
        image_path=IMAGE_MAIN,
    )


@dp.callback_query(F.data == "ref_top")
async def ref_top(callback: CallbackQuery):
    await callback.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT username, first_name, referrals
            FROM users
            WHERE username IS NULL OR username != 'dmmmrrrrrii'
            ORDER BY referrals DESC, user_id ASC
            LIMIT 10
        """)
        rows = await cur.fetchall()

    lines = ["🏆 <b>Топ по рефералам</b>\n"]
    if not rows:
        lines.append("Пока участников нет.")
    else:
        for i, (username, first_name, referrals) in enumerate(rows, 1):
            name = f"@{username}" if username else (first_name or "Пользователь")
            lines.append(f"{i}. {escape(name)} — <b>{referrals}</b>")

    await edit_screen(callback.message, "\n".join(lines), back_menu(), image_path=IMAGE_MAIN)


@dp.callback_query(F.data == "create_bot")
async def create_bot(callback: CallbackQuery):
    await callback.answer()
    await edit_screen(
        callback.message,
        "🤖 <b>Создать своего бота</b>\n\nКонструктор собственного магазина подключим следующим этапом.",
        back_menu(),
        image_path=IMAGE_MAIN,
    )


@dp.message(Command("admin"))
async def admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users")
        count = (await cur.fetchone())[0]
    await message.answer(
        f"🔐 <b>Админ-панель</b>\n\nПользователей: <b>{count}</b>"
    )


async def main():
    await init_db()
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
