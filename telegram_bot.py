"""
Esports Tournament Bot — Multi-Turnir tizimi
Admin: turnir yaratadi, kod oladi, o'yinchilarni saralaydi
O'yinchi: turnir kodini kiritib ro'yxatdan o'tadi
"""

from __future__ import annotations
import logging
import random
import string
from dataclasses import dataclass, field
from typing import Optional
from telegram import (
    Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler,
    ContextTypes, filters,
)
from telegram.constants import ParseMode

# ── Sozlamalar ───────────────────────────────────────────────────────────────
BOT_TOKEN = "8627842043:AAGfpPWXtlk7VO5ykcpcdJgnb_4S3tHxJaM"
ADMIN_ID  = 7841162416   # ← @userinfobot dan oling

# Conversation states
(
    # O'yinchi
    ASK_CODE, ASK_NICK, ASK_CONTACT,
    # Admin
    ADMIN_TOURNAMENT_NAME,
) = range(4)

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ── Modellar ─────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class Player:
    name:          str
    phone:         str
    game_nickname: str
    username:      Optional[str]
    tournament_id: str

    def mention(self) -> str:
        return f"@{self.username}" if self.username else "—"

    def short(self) -> str:
        return f"🎮 *{self.game_nickname}* | {self.mention()}"

    def full(self) -> str:
        return (
            f"🎮 *{self.game_nickname}*\n"
            f"   👤 {self.name} | 🔗 {self.mention()}"
        )


@dataclass
class Tournament:
    name:       str
    code:       str
    players:    dict[int, Player] = field(default_factory=dict)
    last_teams: list[list[Player]] = field(default_factory=list)


# ── Global holat ─────────────────────────────────────────────────────────────
tournaments: dict[str, Tournament] = {}   # { code: Tournament }
# O'yinchi qaysi turnirda ekanligini saqlash uchun
# { telegram_id: tournament_code }
player_tournament: dict[int, str] = {}

# ── Yordamchi ────────────────────────────────────────────────────────────────
_KB_REMOVE  = ReplyKeyboardRemove()
_KB_CONTACT = ReplyKeyboardMarkup(
    [[KeyboardButton("📱 Kontaktimni yuborish", request_contact=True)]],
    resize_keyboard=True, one_time_keyboard=True
)

ORDINALS = [
    "Birinchi","Ikkinchi","Uchinchi","To'rtinchi","Beshinchi",
    "Oltinchi","Yettinchi","Sakkizinchi","To'qqizinchi","O'ninchi",
    "O'n birinchi","O'n ikkinchi","O'n uchinchi","O'n to'rtinchi","O'n beshinchi",
    "O'n oltinchi","O'n yettinchi","O'n sakkizinchi","O'n to'qqizinchi","Yigirmanchi",
]

def ordinal(i: int) -> str:
    return ORDINALS[i] if i < len(ORDINALS) else f"{i+1}-"


def gen_code() -> str:
    """6 belgili noyob kod: harf + raqam aralash, o'xshash belgilar yo'q"""
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # 0,O,1,I,l olib tashlangan
    while True:
        code = "".join(random.choices(chars, k=6))
        if code not in tournaments:
            return code


def admin_main_kb() -> InlineKeyboardMarkup:
    rows = []
    if tournaments:
        for t in tournaments.values():
            rows.append([InlineKeyboardButton(
                f"🏆 {t.name}  [{t.code}]  👥{len(t.players)}",
                callback_data=f"t_{t.code}"
            )])
    rows.append([InlineKeyboardButton("➕ Yangi turnir yaratish", callback_data="new_tournament")])
    return InlineKeyboardMarkup(rows)


def tournament_kb(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Ro'yxat",         callback_data=f"list_{code}")],
        [InlineKeyboardButton("🎲 Random saralash",  callback_data=f"smenu_{code}")],
        [InlineKeyboardButton("🏆 Jamoalar",         callback_data=f"teams_{code}")],
        [InlineKeyboardButton("🗑  Ro'yxatni tozala", callback_data=f"clear_{code}")],
        [InlineKeyboardButton("❌ Turnirni o'chir",   callback_data=f"deltour_{code}")],
        [InlineKeyboardButton("🔙 Orqaga",            callback_data="back")],
    ])


def shuffle_kb(code: str, n: int) -> InlineKeyboardMarkup:
    btns = [InlineKeyboardButton(str(i), callback_data=f"sz_{code}_{i}") for i in range(1, min(n+1, 11))]
    rows = [btns[i:i+5] for i in range(0, len(btns), 5)]
    rows.append([InlineKeyboardButton("🔙 Orqaga", callback_data=f"t_{code}")])
    return InlineKeyboardMarkup(rows)


def fmt_players(t: Tournament) -> str:
    if not t.players:
        return f"📭 *{t.name}* turnirida hali ishtirokchi yo'q."
    lines = [f"👥 *{t.name}* — {len(t.players)} ishtirokchi\n"]
    lines += [f"{i}. {p.full()}" for i, p in enumerate(t.players.values(), 1)]
    return "\n".join(lines)


def fmt_teams(t: Tournament) -> str:
    if not t.last_teams:
        return "❌ Hali saralash amalga oshirilmagan."
    lines = [f"🏆 *{t.name}* — {len(t.last_teams)} ta jamoa\n"]
    for i, team in enumerate(t.last_teams):
        lines.append("━━━━━━━━━━━━━━━")
        lines.append(f"🏅 *{ordinal(i)} jamoa* ({len(team)} kishi)")
        lines += [f"  {j}. {p.short()}" for j, p in enumerate(team, 1)]
    lines.append("━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def fmt_shuffle(t: Tournament, size: int) -> str:
    teams  = t.last_teams
    total  = len(t.players)
    if size == 1:
        lines = [f"🎲 *{t.name}* — random tartib ({total} o'yinchi)\n"]
        lines += [f"{i}. {tm[0].short()}" for i, tm in enumerate(teams, 1)]
    else:
        rem   = total % size
        extra = f", oxirgisi {rem} kishi" if rem else ""
        lines = [
            f"🎲 *{t.name}* — saralash natijasi\n"
            f"👥 {total} o'yinchi → {len(teams)} jamoa ({size} kishidan{extra})\n"
        ]
        for i, team in enumerate(teams):
            lines.append("━━━━━━━━━━━━━━━")
            lines.append(f"🏅 *{ordinal(i)} jamoa* ({len(team)} kishi)")
            lines += [f"  {j}. {p.short()}" for j, p in enumerate(team, 1)]
        lines.append("━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def do_shuffle(t: Tournament, size: int) -> list[list[Player]]:
    pool = list(t.players.values())
    random.shuffle(pool)
    if size == 1:
        return [[p] for p in pool]
    return [pool[i:i+size] for i in range(0, len(pool), size)]


# ── /start ───────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if user.id == ADMIN_ID:
        await update.message.reply_text(
            "👋 *Admin paneli*\n\nTurnirlarni boshqaring:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=admin_main_kb()
        )
        return ConversationHandler.END

    # O'yinchi allaqachon ro'yxatda
    if user.id in player_tournament:
        code = player_tournament[user.id]
        t    = tournaments.get(code)
        if t and user.id in t.players:
            p = t.players[user.id]
            await update.message.reply_text(
                f"✅ Siz *{t.name}* turnirida ro'yxatdasiz!\n"
                f"🎮 Nickname: *{p.game_nickname}*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=_KB_REMOVE
            )
            return ConversationHandler.END

    await update.message.reply_text(
        "🎮 *Xush kelibsiz!*\n\n"
        "Ishtirok etmoqchi bo'lgan *turnir kodini* kiriting:\n"
        "_(6 belgili kod, masalan: `AB3X7K`)_",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_KB_REMOVE
    )
    return ASK_CODE


# ── O'yinchi: turnir kodi ────────────────────────────────────────────────────
async def ask_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()

    if code not in tournaments:
        await update.message.reply_text(
            "❌ Bunday turnir kodi mavjud emas!\n\n"
            "Iltimos, to'g'ri kodni kiriting:",
        )
        return ASK_CODE

    t = tournaments[code]
    ctx.user_data["t_code"] = code

    await update.message.reply_text(
        f"✅ *{t.name}* turniri topildi!\n\n"
        f"Endi o'yin *nicknamengizni* kiriting:\n"
        f"Masalan: `ProGamer2025`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_KB_REMOVE
    )
    return ASK_NICK


# ── O'yinchi: nickname ───────────────────────────────────────────────────────
async def ask_nick(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    nick = update.message.text.strip()
    if not (2 <= len(nick) <= 32):
        await update.message.reply_text("❌ Nickname 2–32 belgi orasida bo'lishi kerak.")
        return ASK_NICK

    ctx.user_data["nick"] = nick
    await update.message.reply_text(
        f"✅ Nickname: *{nick}*\n\n📱 Endi kontaktingizni yuboring 👇",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_KB_CONTACT
    )
    return ASK_CONTACT


# ── O'yinchi: kontakt ────────────────────────────────────────────────────────
async def ask_contact(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    contact = update.message.contact

    if contact.user_id != user.id:
        await update.message.reply_text(
            "❌ Faqat *o'z* kontaktingizni yuboring!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_KB_CONTACT
        )
        return ASK_CONTACT

    code = ctx.user_data.get("t_code")
    nick = ctx.user_data.pop("nick", "Nomalum")
    ctx.user_data.clear()

    t = tournaments.get(code)
    if not t:
        await update.message.reply_text("❌ Turnir topilmadi. /start dan qayta boshlang.")
        return ConversationHandler.END

    name  = f"{contact.first_name or ''} {contact.last_name or ''}".strip()
    phone = contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone

    player = Player(
        name=name, phone=phone,
        game_nickname=nick,
        username=user.username,
        tournament_id=code
    )
    t.players[user.id]          = player
    player_tournament[user.id]  = code

    log.info("Yangi o'yinchi: [%s] %s | %s", t.name, nick, phone)

    await update.message.reply_text(
        f"🏆 *Tabriklaymiz, {nick}!*\n\n"
        f"*{t.name}* turnirida ro'yxatdan o'tdingiz! 🎉\n\n"
        f"👤 Ism: {name}\n"
        f"📞 Telefon: `{phone}`\n"
        f"🎮 Nickname: *{nick}*\n\n"
        f"👥 Turnirdagi ishtirokchilar: *{len(t.players)}* kishi\n\nOmad! 🍀",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_KB_REMOVE
    )
    return ConversationHandler.END


# ── Admin: yangi turnir nomi ─────────────────────────────────────────────────
async def admin_tournament_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("❌ Turnir nomi juda qisqa!")
        return ADMIN_TOURNAMENT_NAME

    code = gen_code()
    t    = Tournament(name=name, code=code)
    tournaments[code] = t

    log.info("Yangi turnir: %s [%s]", name, code)

    await update.message.reply_text(
        f"✅ *{name}* turniri yaratildi!\n\n"
        f"🔑 *Turnir kodi:*\n"
        f"`{code}`\n\n"
        f"_Bu kodni o'yinchilaringizga yuboring._\n"
        f"_Ular /start bosib shu kodni kiritadi._",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=admin_main_kb()
    )
    return ConversationHandler.END


# ── Inline tugmalar ──────────────────────────────────────────────────────────
async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.from_user.id != ADMIN_ID:
        await q.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    data = q.data

    # Asosiy menyu
    if data == "back":
        await q.edit_message_text(
            "👋 *Admin paneli*\n\nTurnirlarni boshqaring:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=admin_main_kb()
        )

    # Yangi turnir — nom so'rash
    elif data == "new_tournament":
        await q.edit_message_text(
            "🏆 Yangi turnir nomini yozing:\n"
            "_(xabar yuborilganda turnir yaratiladi)_",
            parse_mode=ParseMode.MARKDOWN
        )
        ctx.user_data["awaiting_tournament_name"] = True

    # Turnirni ochish
    elif data.startswith("t_"):
        code = data[2:]
        t    = tournaments.get(code)
        if not t:
            await q.edit_message_text("❌ Turnir topilmadi.", reply_markup=admin_main_kb())
            return
        await q.edit_message_text(
            f"🏆 *{t.name}*\n"
            f"🔑 Kod: `{code}`\n"
            f"👥 Ishtirokchilar: *{len(t.players)}* kishi",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=tournament_kb(code)
        )

    # Ro'yxat
    elif data.startswith("list_"):
        code = data[5:]
        t    = tournaments.get(code)
        if not t:
            return
        await q.edit_message_text(
            fmt_players(t),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=tournament_kb(code)
        )

    # Shuffle menyu
    elif data.startswith("smenu_"):
        code = data[6:]
        t    = tournaments.get(code)
        if not t or not t.players:
            await q.edit_message_text("⚠️ Ro'yxat bo'sh!", reply_markup=tournament_kb(code))
            return
        await q.edit_message_text(
            f"🎲 *{t.name}* — random saralash\n\n"
            f"Jami: *{len(t.players)}* o'yinchi\n\n"
            f"Har bir jamoada *nechta* o'yinchi bo'lsin?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=shuffle_kb(code, len(t.players))
        )

    # Shuffle bajarish
    elif data.startswith("sz_"):
        _, code, sz = data.split("_")
        size = int(sz)
        t    = tournaments.get(code)
        if not t:
            return
        t.last_teams = do_shuffle(t, size)
        await q.edit_message_text(
            fmt_shuffle(t, size),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=tournament_kb(code)
        )

    # Jamoalar
    elif data.startswith("teams_"):
        code = data[6:]
        t    = tournaments.get(code)
        if not t:
            return
        await q.edit_message_text(
            fmt_teams(t),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=tournament_kb(code)
        )

    # Ro'yxatni tozalash
    elif data.startswith("clear_"):
        code = data[6:]
        t    = tournaments.get(code)
        if not t:
            return
        # player_tournament dan ham o'chirish
        for uid in list(t.players.keys()):
            player_tournament.pop(uid, None)
        n = len(t.players)
        t.players.clear()
        t.last_teams.clear()
        await q.edit_message_text(
            f"🗑 *{t.name}* — {n} o'yinchi o'chirildi.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=tournament_kb(code)
        )

    # Turnirni o'chirish
    elif data.startswith("deltour_"):
        code = data[8:]
        t    = tournaments.pop(code, None)
        if t:
            for uid in t.players:
                player_tournament.pop(uid, None)
            msg = f"❌ *{t.name}* turniri o'chirildi."
        else:
            msg = "❌ Turnir topilmadi."
        await q.edit_message_text(
            msg, parse_mode=ParseMode.MARKDOWN,
            reply_markup=admin_main_kb()
        )


# ── Admin matn handleri (turnir nomi kutilayotganda) ─────────────────────────
async def admin_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """ConversationHandler tashqarisida admin matn yuborganida"""
    if update.effective_user.id != ADMIN_ID:
        return
    if not ctx.user_data.get("awaiting_tournament_name"):
        return

    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("❌ Nom juda qisqa!")
        return

    ctx.user_data.pop("awaiting_tournament_name")
    code = gen_code()
    tournaments[code] = Tournament(name=name, code=code)

    log.info("Yangi turnir: %s [%s]", name, code)

    await update.message.reply_text(
        f"✅ *{name}* turniri yaratildi!\n\n"
        f"🔑 *Turnir kodi:*\n"
        f"`{code}`\n\n"
        f"_Bu kodni ishtirokchilaringizga yuboring._\n"
        f"_Ular /start bosib shu kodni kiritadi._",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=admin_main_kb()
    )


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("❌ Bekor qilindi. /start — qayta boshlash.", reply_markup=_KB_REMOVE)
    return ConversationHandler.END


# ── Test ma'lumotlar (testdan keyin o'chiring) ───────────────────────────────
TEST_NICKS = [
    "ProSniper_UZ","xXDarkKnightXx","FlameWolf99","ShadowHunter","CyberBlast",
    "NightOwl_UZ","IronFist2025","StormBreaker","PhantomKing","BloodRaven",
    "AcidRain_UZ","GhostReaper","ThunderBolt","FrostByte","NeonViper",
    "SilentKiller_UZ","DragonSlayer","IceWarden","DeathStroke","CrimsonBlade",
    "SkyHawk_UZ","SteelNinja","VoidWalker","TitanFall99","NovaBurst",
    "ObsidianX","PixelDestroyer","MegaForce_UZ","ZeroGravity","HyperLink",
    "DarkMatter","QuantumLeap","NuclearBomb_UZ","SonicBloom","AlphaWolf",
    "BetaBreaker","GammaRay_UZ","DeltaForce","EpsilonX","ZetaStorm",
    "EtaBlast","ThetaKing","IotaViper","KappaSlayer","LambdaHawk",
    "MuNinja_UZ","NuWarden","XiReaper","OmicronX","SigmaForce",
]
TEST_NAMES = [
    "Jasur Toshmatov","Bobur Karimov","Sardor Rahimov","Ulugbek Nazarov","Sherzod Yusupov",
    "Mirzo Hamidov","Otabek Mirzayev","Farrux Qodirov","Nodir Ergashev","Bekzod Xolmatov",
    "Jamshid Abdullayev","Ravshan Normatov","Dilshod Ismoilov","Muzaffar Tursunov","Sanjar Holiqov",
    "Eldor Mahmudov","Firdavs Sobirov","Husan Rajabov","Komiljon Xasanov","Laziz Ibragimov",
    "Mansur Kenjayev","Nuriddin Zokirov","Oybek Salimov","Parviz Umarov","Qodir Rashidov",
    "Rustam Haydarov","Sirojiddin Valiyev","Temur Bobojonov","Umid Ahmedov","Vohid Sultonov",
    "Yorqin Mamatov","Zafar Nishonov","Anvar Qosimov","Behruz Olimov","Davron Usmonov",
    "Erkin Tojiboyev","Firuz Raimov","Gulom Xo'jayev","Hamza Isoqov","Ilhom Muxtarov",
    "Jahongir Sotvoldiyev","Kamol Hayitov","Lochin Daminov","Murod Qurbonov","Nurbek Askarov",
    "Ortiq Mamurov","Pulat Abduraxmonov","Quvondiq Sattorov","Ravil Fozilov","Sanjar Yuldashev",
]
TEST_USERS = [
    "jasur_pro","bobur_uz","sardor99","ulugbek_game","sherzod_uz",
    "mirzo_esport","otabek_uz","farrux_game","nodir_pro","bekzod_uz",
    "jamshid99","ravshan_uz","dilshod_game","muzaffar_pro","sanjar_uz",
    "eldor_game","firdavs99","husan_uz","komil_pro","laziz_game",
    "mansur_uz","nuriddin99","oybek_pro","parviz_uz","qodir_game",
    "rustam_pro","sirojiddin_uz","temur99","umid_game","vohid_pro",
    "yorqin_uz","zafar_game","anvar_pro","behruz99","davron_uz",
    "erkin_game","firuz_pro","gulom_uz","hamza99","ilhom_game",
    "jahongir_pro","kamol_uz","lochin99","murod_game","nurbek_pro",
    "ortiq_uz","pulat99","quvondiq_game","ravil_pro","sanjar_esport",
]

def load_test_data():
    code = "TEST01"
    t    = Tournament(name="🧪 Test Turniri 2025", code=code)
    for i, (nick, name, uname) in enumerate(zip(TEST_NICKS, TEST_NAMES, TEST_USERS)):
        phone   = f"+998{random.randint(90,99)}{random.randint(1000000,9999999)}"
        fake_id = 900000 + i
        t.players[fake_id] = Player(
            name=name, phone=phone,
            game_nickname=nick,
            username=uname,
            tournament_id=code,
        )
    tournaments[code] = t
    log.info("🧪 Test: '%s' [%s] — %d o'yinchi yuklandi", t.name, code, len(t.players))

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            ASK_CODE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_code)],
            ASK_NICK:    [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_nick)],
            ASK_CONTACT: [MessageHandler(filters.CONTACT, ask_contact)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True,
        per_chat=False,
        block=False,
    )

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(on_button))
    # Admin turnir nomi kiritganda
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.User(ADMIN_ID),
        admin_text
    ))

    load_test_data()   # ← TEST: 50 ta fake oyinchi. Testdan keyin bu qatorni ochiring!
    log.info("✅ Bot ishga tushdi...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
