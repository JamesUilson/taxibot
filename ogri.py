from telethon import TelegramClient, events
from telethon.tl.types import Message
from datetime import datetime
from db import cursor, conn
import speech_recognition as sr
from pydub import AudioSegment
import os
import re
import asyncio
import sys
import sqlite3
import time

# =====================
# TELEGRAM API
# =====================
API_ID = 37865153              # <-- o'zingiznikini yozing
API_HASH = "8f8fbd11e173c2fbd113345430bb83b8"

SESSION_NAME = "userbot"

# Global o'zgaruvchilar
client = None
TARGET_USERS = set()  # RAM uchun
KEYWORD_CATEGORIES = {}  # RAM uchun, ishga tushganda DB'ndan yuklaymiz
RECENT_MESSAGES = set()  # Duplicate xabarlar
MAX_LEN = 3500

# =====================
# MA'LUMOTLAR
# =====================

BLOCK_WORDS = [
    "reklama", "aksiya", "chegirma", "канал", "подписывайся", "subscribe",
    "instagram", "telegram", "obuna", "kurs", "training", "учеба"
    "olamiz", "OLAMIZ", "ОЛАМИЗ", "yuryapmiz", "Юряпмиз", "ЮРЯПМИЗ", "kerak", "KERAK", "КЕРАК", "" "srochna", "СРОЧНА", "срочно",
]

# Owner (siz)
OWNER_ID = 123456789  # O'Z ID INGIZNI YOZING
BACKUP_ADMINS = [123456789, 987654321] # Qo'shimcha adminlar (ixtiyoriy)

# =====================
# JADVALLARNI YARATISH (Agar mavjud bo'lmasa)
# =====================

def create_tables():
    """Barcha kerakli jadvallarni yaratadi"""
    # targets jadvali (eski) - TO'G'RI STRUKTURA
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS targets (
            id INTEGER PRIMARY KEY,
            username TEXT,
            from_location TEXT,
            to_location TEXT
        )
    ''')
    
    # Eski strukturalarni yangilash
    try:
        # from_location ustunini qo'shish (agar yo'q bo'lsa)
        cursor.execute("PRAGMA table_info(targets)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'from_location' not in columns:
            print("🔄 from_location ustuni qo'shilmoqda...")
            cursor.execute("ALTER TABLE targets ADD COLUMN from_location TEXT")
        
        if 'to_location' not in columns:
            print("🔄 to_location ustuni qo'shilmoqda...")
            cursor.execute("ALTER TABLE targets ADD COLUMN to_location TEXT")
            
    except sqlite3.OperationalError as e:
        print(f"⚠️ Jadval yangilashda xato: {e}")
        # Agar jadval mavjud bo'lmasa, yangi yaratish
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS targets (
                id INTEGER PRIMARY KEY,
                username TEXT,
                from_location TEXT,
                to_location TEXT
            )
        ''')
    
    # user_keywords jadvali (yangi)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            category TEXT,
            word TEXT,
            FOREIGN KEY(user_id) REFERENCES targets(id)
        )
    ''')
    
    # keywords jadvali (eski)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,
            word TEXT
        )
    ''')
    
    # recent_messages jadvali (eski)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS recent_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER,
            text TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    print("✅ Jadvalar yaratildi/yangilandi")

# =====================
# YORDAMCHI FUNKSIYALAR
# =====================

def normalize_text(text: str):
    """Matnni to'liq normalizatsiya qilish (kril/lotin, variantlar, etc.)"""
    if not text:
        return ""
    
    # 1. Kichik harflarga o'tkazish
    text = text.lower()
    
    # 2. Kril harflarini lotinga o'tkazish (FAQAT KIRIL HARFLARI UCHUN)
    kril_to_latin = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd',
        'е': 'e', 'ё': 'yo', 'ж': 'j', 'з': 'z', 'и': 'i',
        'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n',
        'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't',
        'у': 'u', 'ф': 'f', 'х': 'x', 'ц': 'ts', 'ч': 'ch',
        'ш': 'sh', 'щ': 'sh', 'ъ': '', 'ы': 'i', 'ь': '',
        'э': 'e', 'ю': 'yu', 'я': 'ya',
        'ў': 'o', 'қ': 'k', 'ғ': 'g', 'ҳ': 'h',
        'ә': 'a', 'ө': 'o', 'ү': 'u', 'ң': 'n',
    }
    
    # Faqat kril harflarini almashtirish
    result = []
    for char in text:
        if char in kril_to_latin:
            result.append(kril_to_latin[char])
        else:
            result.append(char)
    text = ''.join(result)
    
    # 3. "dan" qo'shimchasini alohida ajratish (BEFORE TAKRORIY HARFLAR)
    text = text.replace('toshkentdan', 'toshkent dan')
    text = text.replace('toshkenttan', 'toshkent dan')
    text = text.replace('yaypandan', 'yaypan dan')
    text = text.replace('yaypantan', 'yaypan dan')
    
    # 2. SONLARNI avval o'zgartirish (bu muhim!)
    number_map = {
        'ikki': '2', 'iki': '2', 'bir': '1', 'uch': '3',
        'tort': '4', 'besh': '5', 'olti': '6', 'yetti': '7',
        'sakkiz': '8', 'toqqiz': '9', 'on': '10',
        'iki': '2', 'ikky': '2', 'ikkita': '2', 'ikkinchi': '2',
        'бир': '1', 'bitta': '1', 'birta': '1', 'ichki': '2',
        'ich': '2', 'ekki': '2', 'ek': '2', 'ekkiy': '2', 'ik': '2',
        'ikishimiz': '2','kishimiz': '2', 'kishi':'2',
        'uch': '3', 'уч': '3', 'uchta': '3', 'uchinchi': '3',
        'tort': '4', 'торт': '4', 'tortta': '4', 'tortinchi': '4',
    }
    
    for num_word, num_digit in number_map.items():
        # To'liq so'zni almashtirish
        import re
        text = re.sub(r'\b' + re.escape(num_word) + r'\b', num_digit, text)

    # 4. Takroriy harflarni olib tashlash (TO'G'RI)
    # Faqat ortiqcha takrorlangan harflarni olib tashlash
    import re
    # 2 dan ortiq takrorlangan harflarni 1 taga qisqartirish
    text = re.sub(r'(.)\1+', r'\1', text)
    
    # 5. Noto'g'ri yozilgan shahar nomlarini tuzatish
    # Toshkent variantlari
    toshkent_corrections = {
        'тoshkent': 'toshkent', 'toshken': 'toshkent', 'toshkon': 'toshkent',
        'tashkent': 'toshkent', 'tashken': 'toshkent', 'taskent': 'toshkent',
        'toshkend': 'toshkent', 'toshkendan': 'toshkent', 'toshkentan': 'toshkent',
        'toshkentt': 'toshkent',  # MUHIM: t ni olib tashlash
    }
    
    for wrong, correct in toshkent_corrections.items():
        # To'liq so'zni almashtirish
        text = re.sub(r'\b' + re.escape(wrong) + r'\b', correct, text)
    
    # Yaypan variantlari
    yaypan_corrections = {
        'yaypon': 'yaypan', 'yaypun': 'yaypan', 'yepan': 'yaypan',
        'yepon': 'yaypan', 'yepun': 'yaypan',
    }
    
    for wrong, correct in yaypan_corrections.items():
        text = re.sub(r'\b' + re.escape(wrong) + r'\b', correct, text)
    
    # 6. Qo'shimcha tuzatishlar
    # "kishi" ni to'liq saqlash
    text = text.replace('kis ', 'kishi ')
    text = text.replace('киш ', 'kishi ')
    text = text.replace('kishee ', 'kishi ')
    text = text.replace('kish ', 'kishi ')
    
    # 7. Belgilarni tozalash
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

def is_spam(text: str):
    """Spam tekshiruvi"""
    if not text:
        return True
    
    # link bo'lsa spam
    if "http://" in text or "https://" in text or "t.me/" in text or "www." in text:
        return True

    # blok so'zlar
    for w in BLOCK_WORDS:
        if w in text:
            return True

    return False

#admin tekshirish
def is_owner(user_id):
    """Foydalanuvchi owner ekanligini tekshirish"""
    return user_id == OWNER_ID

#qo'shimcha adminlar tekshirish
def is_admin(user_id):
    """Admin ekanligini tekshirish"""
    return user_id == OWNER_ID or user_id in BACKUP_ADMINS

def remove_suffixes(word: str):
    """So'zdan qo'shimchalarni olib tashlash (LEKIN SHAHARLAR UCHUN EMAS)"""
    if not word:
        return word
    
    # Avval shahar nomlarini tekshirish
    city_names = ['toshkent', 'yaypan', 'samarqand', 'buxoro', 'andijon', 
                  'fargona', 'namangan', 'jizzax', 'navoiy', 'xorazm']
    
    for city in city_names:
        if word.startswith(city):
            # Agar so'z shahar nomi bilan boshlansa, qo'shimchalarni OLIB TASHLAMANG
            # Faqat "dan", "ga" kabi qo'shimchalarni ajratib olish uchun
            return city
    
    # Boshqa so'zlar uchun qo'shimchalarni olib tashlash
    all_suffixes = [
        'dan', 'tan', 'den', 'ten', 'nan', 'nen',
        'ga', 'ka', 'gacha', 'kacha',
        'da', 'ta', 'de', 'te',
        'ni', 'ning', 'niki',
        'lar', 'lari', 'larni', 'larning',
        'dagi', 'dagı', 'taki', 'tagi',
        'lik', 'lig', 'ligi', 'ligim',
        'chi', 'chı', 'shi', 'shı',
        'siz', 'sız', 'suz', 'süz',
        'cha', 'chä', 'che', 'chö',
        'roq', 'roq', 'raq', 'räq',
        'dim', 'ding', 'di', 'dingiz',
        'man', 'san', 'miz', 'siz', 'lar',
        'yapman', 'yapsan', 'yapmiz', 'yapsiz', 'yaptilar',
    ]
    
    for suffix in all_suffixes:
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            return word[:-len(suffix)]
    
    return word
# =====================
# KATEGORIYA NORMALIZATSIYASI
# =====================

def normalize_category_word(word: str):
    """Kategoriya so'zini normalizatsiya qilish (TO'LIQ)"""
    if not word:
        return ""
    
    # Avval normalize_text dan foydalanish
    word = normalize_text(word)
    
    # Kategoriya variantlari (TO'LIQ)
    category_variants = {
        # ODAM kategoriyasi
        'odam': 'odam', 'adam': 'odam', 'kishi': 'odam',
        'человек': 'odam', 'person': 'odam', 'people': 'odam',
        'yolovchi': 'odam', 'пассажир': 'odam', 'passenger': 'odam',
        'orta': 'odam', 'orindiq': 'odam', 'orin': 'odam',
        'joy': 'odam', 'место': 'odam', 'place': 'odam',
        
        # BOR kategoriyasi
        'bor': 'bor', 'бор': 'bor', 'boradi': 'bor',
        'боради': 'bor', 'keladi': 'bor', 'ketadi': 'bor',
        'кетади': 'bor', 'going': 'bor', 'идет': 'bor',
        'едет': 'bor', 'еду': 'bor', 'идём': 'bor',
        'ketmoqchi': 'bor', 'кетмокчи': 'bor', 'ketish': 'bor',
        
        # KERAK kategoriyasi
        'kerak': 'kerak', 'керак': 'kerak', 'kerek': 'kerak',
        'керек': 'kerak', 'zarur': 'kerak', 'зарур': 'kerak',
        'lazim': 'kerak', 'лазим': 'kerak', 'нужен': 'kerak',
        'нужно': 'kerak', 'need': 'kerak', 'required': 'kerak',
        
        # KOMPLEKT kategoriyasi
        'komplekt': 'komplekt', 'комплект': 'komplekt',
        'tola': 'komplekt', 'toliq': 'komplekt', 'тола': 'komplekt',
        'set': 'komplekt', 'full': 'komplekt', 'полный': 'komplekt',
        'набор': 'komplekt', 'complect': 'komplekt',
        
        # POCHTA kategoriyasi
        'pochta': 'pochta', 'почта': 'pochta', 'yuk': 'pochta',
        'юк': 'pochta', 'груз': 'pochta', 'cargo': 'pochta',
        'посылка': 'pochta', 'paket': 'pochta', 'пакет': 'pochta',
        'parcel': 'pochta', 'посилка': 'pochta',
        
        # SONLAR kategoriyasi
        '1': '1', '2': '2', '3': '3', '4': '4', '5': '5',
        '6': '6', '7': '7', '8': '8', '9': '9', '10': '10',
        'bir': '1', 'ikki': '2', 'uch': '3', 'tort': '4',
        'besh': '5', 'olti': '6', 'yetti': '7', 'sakkiz': '8',
        'toqqiz': '9', 'on': '10', 'one': '1', 'two': '2',
        'three': '3', 'four': '4', 'five': '5', 'six': '6',
        'seven': '7', 'eight': '8', 'nine': '9', 'ten': '10',

        'iki': '2', 'ikky': '2', 'ikkita': '2', 'ikkinchi': '2',
        'бир': '1', 'bitta': '1', 'birta': '1', 'ichki': '2',
        'ich': '2', 'ekki': '2', 'ek': '2', 'ekkiy': '2', 'ik': '2',
        'ikishimiz': '2','kishimiz': '2', 'kishi':'2',
        'uch': '3', 'уч': '3', 'uchta': '3', 'uchinchi': '3',
        'tort': '4', 'торт': '4', 'tortta': '4', 'tortinchi': '4',
        'besh': '5', 'беш': '5', 'beshta': '5', 'beshinchi': '5',
        'olti': '6', 'олти': '6', 'oltita': '6', 'oltinchi': '6',
        
        # IZLAMOQ kategoriyasi
        'izlayman': 'izlayman', 'излайман': 'izlayman',
        'looking': 'izlayman', 'ищу': 'izlayman', 'ishu': 'izlayman',
        'kerakman': 'kerak', 'lazimman': 'kerak', 'kereku': 'kerak',
        'zarurman': 'kerak', 'зарурман': 'kerak',
    }
    
    # Variantlarni tekshirish
    for variant, standard in category_variants.items():
        if word == variant:
            return standard
    
    return word
# =====================
# SHAHAR NORMALIZATSIYA FUNKSIYASI
# =====================

def normalize_city_name(city: str):
    """Shahar nomini standart shaklga o'tkazish (TO'LIQ)"""
    if not city:
        return ""
    
    city = city.lower()
    
    # Avval kril-lotin konvertatsiyasi
    kril_to_latin = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd',
        'е': 'e', 'ё': 'yo', 'ж': 'j', 'з': 'z', 'и': 'i',
        'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n',
        'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't',
        'у': 'u', 'ф': 'f', 'х': 'x', 'ц': 'ts', 'ч': 'ch',
        'ш': 'sh', 'щ': 'sh', 'ъ': '', 'ы': 'i', 'ь': '',
        'э': 'e', 'ю': 'yu', 'я': 'ya',
        'ў': 'o', 'қ': 'k', 'ғ': 'g', 'ҳ': 'h',
        'ә': 'a', 'ө': 'o', 'ү': 'u', 'ң': 'n',
    }
    
    result = []
    for char in city:
        if char in kril_to_latin:
            result.append(kril_to_latin[char])
        else:
            result.append(char)
    city = ''.join(result)
    
    # Shahar variantlarini birlashtirish
    city_variants = {
        # Toshkent
        'toshkent': 'toshkent', 'toshken': 'toshkent', 'toshkon': 'toshkent',
        'toshkin': 'toshkent', 'toshkenta': 'toshkent', 'toshkente': 'toshkent',
        'tashkent': 'toshkent', 'tashken': 'toshkent', 'tashkon': 'toshkent',
        'тошкент': 'toshkent', 'тошкен': 'toshkent', 'тошкон': 'toshkent',
        'тошкинт': 'toshkent', 'тошкин': 'toshkent', 'тошкэн': 'toshkent',
        'тoshkеn': 'toshkent', 'тashkеn': 'toshkent', 'тoshkon': 'toshkent',
        'tosh': 'toshkent', 'tash': 'toshkent', 'toskent': 'toshkent', 'taskent': 'toshkent',
        'toshkand': 'toshkent', 'toshkendan': 'toshkent', 'toshkentan': 'toshkent',
        
        # Yaypan
        'yaypan': 'yaypan', 'yaypon': 'yaypan', 'yaypun': 'yaypan',
        'yaypən': 'yaypan', 'yepan': 'yaypan', 'yepon': 'yaypan',
        'yepun': 'yaypan', 'яйпан': 'yaypan', 'яйпон': 'yaypan',
        'яйпун': 'yaypan', 'йайпан': 'yaypan', 'йайпон': 'yaypan',
        
        # Boshqa shaharlar
        'samarqand': 'samarqand', 'самарқанд': 'samarqand', 'самарканд': 'samarqand',
        'buxoro': 'buxoro', 'бухоро': 'buxoro', 'бухара': 'buxoro',
        'andijon': 'andijon', 'андижон': 'andijon', 'андижан': 'andijon',
        'fargona': 'fargona', 'фаргона': 'fargona', 'фергана': 'fargona',
        'namangan': 'namangan', 'наманган': 'namangan', 'наманған': 'namangan',
        'jizzax': 'jizzax', 'жизак': 'jizzax', 'джизак': 'jizzax',
        'navoiy': 'navoiy', 'навоий': 'navoiy', 'навои': 'navoiy',
        'xorazm': 'xorazm', 'хоразм': 'xorazm', 'хорезм': 'xorazm',
    }
    
    # Qo'shimchalarni olib tashlash
    city = remove_suffixes(city)
    
    # Asosiy nomni topish
    for variant, standard in city_variants.items():
        if variant in city:
            return standard
    
    return city

def normalize_category_word(word: str):
    """Kategoriya so'zini normalizatsiya qilish (to'liq)"""
    if not word:
        return ""
    
    word = normalize_text(word)  # Avval umumiy normalizatsiya
    
    # Kategoriya variantlari (to'liq)
    category_variants = {
        # ODAM kategoriyasi
        'odam': 'odam', 'adam': 'odam', 'kishi': 'odam',
        'человек': 'odam', 'person': 'odam', 'people': 'odam',
        'yolovchi': 'odam', 'пассажир': 'odam', 'passenger': 'odam',
        'orta': 'odam', 'orindiq': 'odam', 'orin': 'odam',
        
        # BOR/KELADI kategoriyasi
        'bor': 'bor', 'бор': 'bor', 'boradi': 'bor', 'боради': 'bor',
        'keladi': 'bor', 'ketadi': 'bor', 'кетади': 'bor',
        'going': 'bor', 'идет': 'bor', 'едет': 'bor',
        
        # KERAK kategoriyasi
        'kerak': 'kerak', 'керак': 'kerak', 'kerek': 'kerak',
        'керек': 'kerak', 'zarur': 'kerak', 'зарур': 'kerak',
        'lazim': 'kerak', 'лазим': 'kerak', 'нужен': 'kerak',
        'нужно': 'kerak', 'need': 'kerak',
        
        # KOMPLEKT kategoriyasi
        'komplekt': 'komplekt', 'комплект': 'komplekt',
        'tola': 'komplekt', 'toliq': 'komplekt', 'тола': 'komplekt',
        'set': 'komplekt', 'full': 'komplekt', 'полный': 'komplekt',
        
        # POCHTA kategoriyasi
        'pochta': 'pochta', 'почта': 'pochta', 'yuk': 'pochta',
        'юк': 'pochta', 'груз': 'pochta', 'cargo': 'pochta',
        'посылка': 'pochta', 'paket': 'pochta',
        
        # SONLAR
        '1': '1', '2': '2', '3': '3', '4': '4', '5': '5',
        '6': '6', '7': '7', '8': '8', '9': '9', '10': '10',
        'bir': '1', 'ikki': '2', 'uch': '3', 'tort': '4', 'besh': '5',
        'olti': '6', 'yetti': '7', 'sakkiz': '8', 'toqqiz': '9', 'on': '10',
        
        # IZLAMOQ kategoriyasi
        'izlayman': 'izlayman', 'излайман': 'izlayman',
        'looking': 'izlayman', 'ищу': 'izlayman',
        'kerakman': 'kerak', 'lazimman': 'kerak',
        
        # BOSHQA
        'yo\'q': 'yoq', 'yok': 'yoq', 'нет': 'yoq', 'no': 'yoq',
        'ha': 'ha', 'yes': 'ha', 'да': 'ha', 'есть': 'bor',
        'mavjud': 'bor', 'available': 'bor',
    }
    
    # Variantlarni tekshirish
    for variant, standard in category_variants.items():
        if word == variant:
            return standard
    
    return word

# =====================
# DEBUG FUNKSIYALARI
# =====================

async def debug_user_info(user_id: int):
    """Foydalanuvchi ma'lumotlarini tekshirish"""
    print(f"\n🔍 DEBUG: Foydalanuvchi {user_id} ma'lumotlari:")
    
    # Yo'nalish
    cursor.execute("SELECT from_location, to_location FROM targets WHERE id=?", (user_id,))
    route = cursor.fetchone()
    if route:
        print(f"  📍 Yo'nalish: {route[0]} → {route[1]}")
        print(f"  📍 Normalizatsiya qilingan: {normalize_city_name(route[0])} → {normalize_city_name(route[1])}")
    else:
        print(f"  ❌ Yo'nalish topilmadi")
    
    # Kalit so'zlar
    cursor.execute("SELECT category, word FROM user_keywords WHERE user_id=?", (user_id,))
    keywords = cursor.fetchall()
    if keywords:
        print(f"  🔑 Kalit so'zlar ({len(keywords)} ta):")
        for cat, word in keywords:
            print(f"    - [{cat}]: {word} → {normalize_category_word(word)}")
    else:
        print(f"  ❌ Kalit so'zlar yo'q")

# =====================
# FOYDALANUVCHILARNI TOPISH VA XABAR YUBORISH
# =====================

async def find_matching_users(text: str):
    """Matnga mos keladigan foydalanuvchilarni topish (MUKAMMAL)"""
    matched_users = set()
    
    if not text:
        return matched_users
    
    normalized_text = normalize_text(text)
    print(f"🔍 Matn: {normalized_text}")
    
    words = normalized_text.split()
    print(f"🔍 So'zlar: {words}")
    
    # Barcha foydalanuvchilarni olish
    cursor.execute(
        "SELECT id, from_location, to_location FROM targets WHERE from_location IS NOT NULL AND to_location IS NOT NULL"
    )
    users = cursor.fetchall()
    
    print(f"🔍 {len(users)} ta foydalanuvchi topildi")
    
    for user_id, from_loc, to_loc in users:
        print(f"  👤 {user_id}: {from_loc} → {to_loc}")

        route_ok = False  # 🔧 QO‘SHILDI: yo'nalish mosligi flag

        if from_loc and to_loc:
            from_norm = normalize_city_name(from_loc)
            to_norm = normalize_city_name(to_loc)
            
            print(f"    🏙️ {from_norm} → {to_norm}")
            
            # Yo'nalishni tekshirish (5 xil variant)
            from_found = False
            to_found = False
            
            for word in words:
                word_base = remove_suffixes(word)
                
                # 1. FROM shahari
                if word_base == from_norm:
                    from_found = True
                    print(f"    ✅ FROM: {from_norm}")
                
                # 2. TO shahari  
                if word_base == to_norm:
                    to_found = True
                    print(f"    ✅ TO: {to_norm}")
            
            # Yo'nalish variantlari
            full_match = from_found and to_found
            only_from = from_found and not to_found
            only_to = to_found and not from_found
            
            reverse_match = False
            if not full_match:
                # Teskari yo'nalish (B dan A ga) tekshirish logikasi
                pass
            
            # Agar yo'nalish mos kelsa
            if full_match or only_from or only_to:
                route_ok = True  # 🔧 QO‘SHILDI
                route_type = "to'liq" if full_match else "qisman"
                print(f"    ✅ {route_type} yo'nalish mos keldi")
                
                # Kalit so'zlarni tekshirish
                cursor.execute("SELECT word FROM user_keywords WHERE user_id=?", (user_id,))
                user_words = [row[0] for row in cursor.fetchall()]
                
                if not user_words:
                    print(f"    ⚠️ Kalit so'z yo'q, lekin qo'shiladi")
                    matched_users.add(user_id)
                else:
                    print(f"    🔑 Kalit so'zlar: {user_words}")
                    keyword_found = False
                    for keyword in user_words:
                        norm_keyword = normalize_category_word(keyword)
                        for text_word in words:
                            norm_text_word = normalize_category_word(text_word)
                            if norm_keyword == norm_text_word or norm_keyword in norm_text_word or norm_text_word in norm_keyword:
                                keyword_found = True
                                print(f"    ✅ Kalit so'z: '{keyword}' == '{text_word}'")
                                break
                        if keyword_found:
                            break
                    if keyword_found:
                        matched_users.add(user_id)
                    else:
                        print(f"    ❌ Kalit so'z mos kelmadi")
            else:
                print(f"    ❌ Yo'nalish mos kelmadi")
                
                # 🔧 QO‘SHILDI: Yo'nalish yo'q bo‘lsa ham kalit so‘z bo‘yicha tekshirish
                cursor.execute("SELECT word FROM user_keywords WHERE user_id=?", (user_id,))
                user_words = [row[0] for row in cursor.fetchall()]
                
                if user_words:
                    print(f"    🔑 (route yo'q) Kalit so'zlar: {user_words}")
                    keyword_found = False
                    for keyword in user_words:
                        norm_keyword = normalize_category_word(keyword)
                        for text_word in words:
                            norm_text_word = normalize_category_word(text_word)
                            if norm_keyword == norm_text_word or norm_keyword in norm_text_word or norm_text_word in norm_keyword:
                                keyword_found = True
                                print(f"    ✅ (route yo'q) Kalit so'z mos: '{keyword}'")
                                break
                        if keyword_found:
                            break
                    if keyword_found:
                        matched_users.add(user_id)
                        print("    📤 Yo'nalishsiz, faqat kalit so'z bo‘yicha yuborildi")
                else:
                    print("    ⚠️ (route yo'q) kalit so'z ham yo'q")
    
    print(f"🔍 Jami {len(matched_users)} ta foydalanuvchi topildi")
    return matched_users

#########################
#mos kelgan foydalanuvchilarga xabar yuborish
#########################

async def send_to_matched_users(text: str, original_text: str = ""):
    """Faqat mos kelgan foydalanuvchilarga xabar yuborish"""
    print(f"\n📤 Xabar yuborilmoqda...")
    print(f"📝 Original matn: {original_text[:100]}...")
    
    matched_users = await find_matching_users(original_text or text)
    
    if not matched_users:
        print("❌ Mos keladigan foydalanuvchilar yo'q")
        return
    
    print(f"✅ {len(matched_users)} ta foydalanuvchiga yuboriladi")
    
    for user_id in matched_users:
        try:
            await client.send_message(user_id, text)
            print(f"✅ Xabar yuborildi: {user_id}")
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"❌ Xatolik {user_id}: {e}")

# =====================
# OVOZLI XABARLARNI QAYTA ISHLASH (MUKAMMAL)
# =====================

async def voice_to_text(event):
    """Ovozli xabarni matnga aylantirish (mukammallashtirilgan)"""
    try:
        print(f"🎤 Ovozli xabar qayta ishlanmoqda...")
        
        file = await event.message.download_media()
        print(f"📥 Fayl yuklandi: {file}")
        
        audio = AudioSegment.from_file(file)
        
        # Ovoz sifati tekshiruvi
        if audio.duration_seconds < 1:
            print(f"⚠️ Ovoz juda qisqa: {audio.duration_seconds}s")
            os.remove(file)
            return None
        
        if audio.dBFS < -45:
            print(f"🔊 Ovoz juda sust: {audio.dBFS}dB, kuchaytirilmoqda...")
            audio = audio + 15  # 15dB ga kuchaytirish
        
        # Audio formatini standartlashtirish
        audio = audio.set_channels(1).set_frame_rate(44100)  # Yuqori sifat
        temp_name = f"temp_{event.id}.wav"
        audio.export(temp_name, format="wav", parameters=["-ac", "1", "-ar", "44100"])
        
        r = sr.Recognizer()
        
        # Ovozni bo'laklarga bo'lish (uzun ovozlar uchun)
        try:
            with sr.AudioFile(temp_name) as source:
                # Shakllantirish
                r.adjust_for_ambient_noise(source, duration=1.0)
                
                # Ovozni qismlarga bo'lib o'qish
                audio_data = r.record(source)
                
                # Birinchidan O'zbek tilida urinib ko'rish
                try:
                    print(f"🔤 O'zbekcha (UZ) tanib ko'ramiz...")
                    recognized = r.recognize_google(audio_data, language="uz-UZ")
                    text = recognized
                    print(f"✅ O'zbekcha tanildi: {text[:150]}...")
                    
                except sr.UnknownValueError:
                    # O'zbek tilida topilmasa, Rus tilida
                    try:
                        print(f"🔤 Ruscha (RU) tanib ko'ramiz...")
                        recognized = r.recognize_google(audio_data, language="ru-RU")
                        text = recognized
                        print(f"✅ Ruscha tanildi: {text[:150]}...")
                        
                        # Rus tilidagi so'zlarni O'zbekchaga o'girish
                        rus_to_uzb = {
                            'два': 'ikki', 'двое': 'ikki', 'человек': 'odam', 'человека': 'odam',
                            'пассажир': 'yolovchi', 'пассажира': 'yolovchi',
                            'еду': 'boraman', 'едет': 'boradi', 'поездка': 'safar',
                            'посылка': 'pochta', 'почта': 'pochta', 'груз': 'yuk',
                            'нужен': 'kerak', 'нужно': 'kerak', 'срочно': 'srochno',
                            'сегодня': 'bugun', 'завтра': 'ertaga',
                            'ташкент': 'toshkent', 'ташкента': 'toshkent',
                        }
                        
                        for rus_word, uzb_word in rus_to_uzb.items():
                            text = text.replace(rus_word, uzb_word)
                            
                    except sr.UnknownValueError:
                        # Ingliz tilida
                        try:
                            print(f"🔤 Inglizcha (EN) tanib ko'ramiz...")
                            recognized = r.recognize_google(audio_data, language="en-US")
                            text = recognized
                            print(f"✅ Inglizcha tanildi: {text[:150]}...")
                            
                        except sr.UnknownValueError:
                            print("❌ Hech qanday tilda tani olmadi")
                            text = ""
                            
        except Exception as e:
            print(f"❌ Audio faylni o'qishda xato: {e}")
            text = ""
        
        # Matnni tozalash va tuzatish
        if text:
            # Kril harflarini lotinga o'tkazish
            text = text.lower()
            kril_chars = 'абвгдеёжзийклмнопрстуфхцчшщъыьэюяўқғҳ'
            latin_chars = 'abvgdeejziiklmnoprstufhtschshsyiyeuyaokghh'
            
            if len(kril_chars) == len(latin_chars):
                translation_table = str.maketrans(kril_chars, latin_chars)
                text = text.translate(translation_table)
            
            # Umumiy xatolarni tuzatish
            corrections = {
                'no merga': 'nomer ga',  # "no'merga" -> "nomer ga"
                'n omerga': 'nomer ga',
                'no mer': 'nomer',
                'tushib': 'tushib',
                'bo lmayapti': "bo'lmayapti",
                'bo ladi': "bo'ladi",
                'lichkasiga': 'lichka sga',
                'yozganmi': 'yozganmi',
                'desa': 'desa',
                'qarashmayapti': 'qarashmayapti',
                'jarayonida': 'jarayonida',
                'turibdik': 'turibdik',
                'akamiz': 'akamiz',
            }
            
            for wrong, correct in corrections.items():
                text = text.replace(wrong, correct)
        
        # Fayllarni tozalash
        try:
            os.remove(file)
            os.remove(temp_name)
        except:
            pass
        
        return text
        
    except Exception as e:
        print(f"❌ Ovozni o'qishda xato: {e}")
        import traceback
        traceback.print_exc()
        return None
# =====================
# EVENT HANDLER FUNKSIYALARI
# =====================

def register_handlers():
    """Barcha event handlerlarni ro'yxatdan o'tkazish"""
    
    @client.on(events.NewMessage(pattern="/start"))
    async def start_handler(event):
        # Faqat owner start bosganda xabar berish
        if is_admin(event.sender_id):
            create_tables()  # Jadvalarni yaratish
            
            await event.reply(
                "✅ USERBOT ISHLAYAPTI\n\n"
                "👤 **ADMIN BUYRUQLARI:**\n"
                "/adduser user_id - Foydalanuvchi qo'shish\n"
                "/deluser user_id - O'chirish\n"
                "/users - Barcha foydalanuvchilar\n"
                "/addword kategoriya so'z - Umumiy kalit so'z\n"
                "/keywords - Umumiy kalit so'zlar\n\n"
                "📍 **SHAXSIY BUYRUQLAR:**\n"
                "/setroute from to - Yo'nalish belgilash\n"
                "/myroute - Yo'nalishim\n"
                "/addmyword kategoriya so'z - Kalit so'z qo'shish\n"
                "/mywords - Kalit so'zlarim\n"
                "/delmyword so'z - Kalit so'z o'chirish\n\n"
                "🔧 **QO'SHIMCHA:**\n"
                "/help - Yordam\n"
                "/stats - Statistika\n"
                "/debug - Tuzatish ma'lumotlari"
            )
        else:
            await event.reply(
                "👋 **Assalomu alaykum!**\n\n"
                "📍 **Yo'nalish belgilash:**\n"
                "/setroute from to\n"
                "Misol: /setroute Toshkent Yaypan\n\n"
                "🔑 **Kalit so'z qo'shish:**\n"
                "/addmyword kategoriya so'z\n"
                "Misol: /addmyword odam 2 kishi\n\n"
                "📋 **Mening sozlamalarim:**\n"
                "/myroute - Yo'nalishim\n"
                "/mywords - Kalit so'zlarim\n"
                "/delmyword so'z - Kalit so'z o'chirish\n\n"
                "🆘 **Yordam:** /help\n"
                "🔧 **Tuzatish:** /debug"
            )

    @client.on(events.NewMessage(pattern="/setroute"))
    async def set_route_handler(event):
        """Yo'nalish belgilash (har kim uchun)"""
        try:
            _, from_loc, to_loc = event.text.split(maxsplit=2)
            
            # Shahar nomlarini normalizatsiya qilish
            normalized_from = normalize_city_name(from_loc)
            normalized_to = normalize_city_name(to_loc)
            
            # Avval foydalanuvchini tekshirish/yaratish
            cursor.execute("SELECT id FROM targets WHERE id=?", (event.sender_id,))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO targets (id) VALUES (?)", (event.sender_id,))
            
            # DB ga yozish (normalizatsiya qilingan shaklda)
            cursor.execute(
                "UPDATE targets SET from_location = ?, to_location = ? WHERE id = ?",
                (normalized_from, normalized_to, event.sender_id)
            )
            conn.commit()
            
            # RAM ga yangilash
            TARGET_USERS.add(event.sender_id)
            
            await event.reply(f"✅ Yo'nalish saqlandi: {from_loc} → {to_loc}\n"
                             f"📝 Normalizatsiya qilingan: {normalized_from} → {normalized_to}")
            
            # Debug ma'lumot
            await debug_user_info(event.sender_id)
            
        except Exception as e:
            print(f"Xato set_route: {e}")
            await event.reply("❌ Format: /setroute Toshkent Yaypan\nMisol: /setroute Toshkent Yaypan")

    @client.on(events.NewMessage(pattern="/myroute"))
    async def show_my_route_handler(event):
        """O'z yo'nalishini ko'rish"""
        try:
            cursor.execute("SELECT from_location, to_location FROM targets WHERE id=?", (event.sender_id,))
            result = cursor.fetchone()
            
            if result and result[0] and result[1]:
                from_loc, to_loc = result
                await event.reply(f"📍 Sizning yo'nalishingiz:\n{from_loc} → {to_loc}")
            else:
                await event.reply("❌ Sizda yo'nalish belgilanmagan.\n/setroute buyrug'i bilan belgilang.")
        except Exception as e:
            print(f"Xato show_my_route: {e}")
            await event.reply("❌ Xato yuz berdi. /setroute bilan qayta urinib ko'ring.")

    @client.on(events.NewMessage(pattern="/addmyword"))
    async def add_my_word_handler(event):
        """Shaxsiy kalit so'z qo'shish (kategoriya normalizatsiyasi bilan)"""
        try:
            _, category, word = event.text.split(maxsplit=2)
            
            # Kategoriya va so'zni normalizatsiya qilish
            normalized_category = normalize_category_word(category)
            normalized_word = normalize_category_word(word)
            
            print(f"📝 Kalit so'z qo'shilmoqda:")
            print(f"   📌 Original: [{category}] -> {word}")
            print(f"   🔄 Normalizatsiya: [{normalized_category}] -> {normalized_word}")
            
            # Avval foydalanuvchini tekshirish/yaratish
            cursor.execute("SELECT id FROM targets WHERE id=?", (event.sender_id,))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO targets (id) VALUES (?)", (event.sender_id,))
            
            # DB ga yozish (normalizatsiya qilingan shaklda)
            cursor.execute(
                "INSERT INTO user_keywords (user_id, category, word) VALUES (?, ?, ?)",
                (event.sender_id, normalized_category, normalized_word)
            )
            conn.commit()
            
            await event.reply(f"✅ Kalit so'z qo'shildi:\n"
                             f"📌 Original: [{category}] -> {word}\n"
                             f"🔄 Normalizatsiya: [{normalized_category}] -> {normalized_word}")
            
            # Debug ma'lumot
            await debug_user_info(event.sender_id)
            
        except Exception as e:
            print(f"Xato add_my_word: {e}")
            await event.reply("❌ Format: /addmyword kategoriya so'z\nMisol: /addmyword odam 2 kishi")

    @client.on(events.NewMessage(pattern="/mywords"))
    async def show_my_words_handler(event):
        """Shaxsiy kalit so'zlarni ko'rish"""
        try:
            cursor.execute("SELECT category, word FROM user_keywords WHERE user_id=?", (event.sender_id,))
            words = cursor.fetchall()
            
            if not words:
                await event.reply("📭 Sizda kalit so'zlar yo'q.\n/addmyword buyrug'i bilan qo'shing.")
                return
            
            response = "📝 Sizning kalit so'zlaringiz:\n\n"
            for category, word in words:
                response += f"🔹 [{category}]: {word}\n"
            
            await event.reply(response)
        except Exception as e:
            print(f"Xato show_my_words: {e}")
            await event.reply("❌ Xato yuz berdi.")

    @client.on(events.NewMessage(pattern="/delmyword"))
    async def delete_my_word_handler(event):
        """Shaxsiy kalit so'zni o'chirish"""
        try:
            _, word = event.text.split(maxsplit=1)
            word_normalized = normalize_text(word)
            
            cursor.execute(
                "DELETE FROM user_keywords WHERE user_id=? AND word=?",
                (event.sender_id, word_normalized)
            )
            conn.commit()
            
            if cursor.rowcount > 0:
                await event.reply(f"🗑 Kalit so'z o'chirildi: {word}")
            else:
                await event.reply("❌ Bunday kalit so'z topilmadi")
        except Exception as e:
            print(f"Xato delete_my_word: {e}")
            await event.reply("❌ Format: /delmyword so'z")

    @client.on(events.NewMessage(pattern="/debug"))
    async def debug_command_handler(event):
        """Debug ma'lumotlari"""
        await debug_user_info(event.sender_id)
        await event.reply("🔍 Debug ma'lumotlari konsolda chiqdi.")

    @client.on(events.NewMessage(pattern="/adduser"))
    async def add_user_handler(event):
        """Admin uchun foydalanuvchi qo'shish"""
        if not is_admin(event.sender_id):
            await event.reply("❌ Bu buyruq faqat admin uchun!")
            return

        try:
            target = event.text.split()[1]

            if target.startswith("@"):
                entity = await client.get_entity(target)
                user_id = entity.id
            else:
                user_id = int(target)

            # DB ga yozish
            cursor.execute("INSERT OR IGNORE INTO targets (id) VALUES (?)", (user_id,))
            conn.commit()

            # RAM ga qo'shish
            TARGET_USERS.add(user_id)

            await event.reply(f"✅ Qo'shildi: {target}")
        except Exception as e:
            await event.reply(f"❌ Xato: {e}")

    @client.on(events.NewMessage(pattern="/deluser"))
    async def del_user_handler(event):
        """Admin uchun foydalanuvchini o'chirish"""
        if not is_admin(event.sender_id):
            await event.reply("❌ Bu buyruq faqat admin uchun!")
            return

        try:
            user_id = int(event.text.split()[1])

            # DB dan o'chirish
            cursor.execute("DELETE FROM targets WHERE id=?", (user_id,))
            conn.commit()

            # RAM dan o'chirish
            TARGET_USERS.discard(user_id)
            
            # Foydalanuvchining kalit so'zlarini ham o'chirish
            cursor.execute("DELETE FROM user_keywords WHERE user_id=?", (user_id,))
            conn.commit()

            await event.reply(f"🗑 O'chirildi: {user_id}")
        except:
            await event.reply("❌ Format: /deluser 123456789")

    @client.on(events.NewMessage(pattern="/users"))
    async def list_users_handler(event):
        """Admin uchun foydalanuvchilar ro'yxati"""
        if not is_admin(event.sender_id):
            await event.reply("❌ Bu buyruq faqat admin uchun!")
            return

        try:
            cursor.execute("SELECT id, from_location, to_location FROM targets")
            users = cursor.fetchall()
            
            if not users:
                await event.reply("📭 Hech kim qo'shilmagan")
                return

            txt = "👥 Qabul qiluvchilar:\n\n"
            for user_id, from_loc, to_loc in users:
                txt += f"🆔 {user_id}"
                if from_loc and to_loc:
                    txt += f" | {from_loc} → {to_loc}"
                
                # Kalit so'zlar soni
                cursor.execute("SELECT COUNT(*) FROM user_keywords WHERE user_id=?", (user_id,))
                count = cursor.fetchone()[0]
                txt += f" | {count} so'z"
                txt += "\n"
            
            await event.reply(txt)
        except Exception as e:
            print(f"Xato list_users: {e}")
            await event.reply("❌ Xato yuz berdi.")

    @client.on(events.NewMessage(pattern="/keywords"))
    async def list_keywords_handler(event):
        """Umumiy kalit so'zlarni ko'rish"""
        if not is_admin(event.sender_id):
            await event.reply("❌ Bu buyruq faqat admin uchun!")
            return

        txt = "📂 Kategoriyalar:\n"
        for k, v in KEYWORD_CATEGORIES.items():
            txt += f"\n🔹 {k}: {', '.join(v[:5])}"  # Faqat 5 tasini ko'rsat
            if len(v) > 5:
                txt += f" ... va yana {len(v)-5} ta"
        await event.reply(txt)

    @client.on(events.NewMessage(pattern="/addword"))
    async def add_word_handler(event):
        """Umumiy kalit so'z qo'shish"""
        if not is_admin(event.sender_id):
            await event.reply("❌ Bu buyruq faqat admin uchun!")
            return

        try:
            _, cat, word = event.text.split(maxsplit=2)

            # DB ga yozish
            cursor.execute("INSERT INTO keywords (category, word) VALUES (?, ?)", (cat, normalize_text(word)))
            conn.commit()

            # RAM ga qo'shish
            KEYWORD_CATEGORIES.setdefault(cat, []).append(normalize_text(word))

            await event.reply(f"✅ Qo'shildi: [{cat}] -> {word}")
        except:
            await event.reply("❌ Format: /addword kategoriya so'z")

    @client.on(events.NewMessage(pattern="/help"))
    async def help_command_handler(event):
        """Yordam"""
        await event.reply(
            "🆘 **YORDAM**\n\n"
            "📍 **Asosiy buyruqlar:**\n"
            "/setroute from to - Yo'nalish belgilash\n"
            "/addmyword kategoriya so'z - Kalit so'z qo'shish\n"
            "/myroute - Yo'nalishimni ko'rish\n"
            "/mywords - Kalit so'zlarim\n\n"
            "📊 **Statistika:**\n"
            "/stats - Bot statistikasi\n\n"
            "👨‍💻 **Admin uchun:**\n"
            "Agar admin bo'lsangiz, /start ni bosing"
        )

    @client.on(events.NewMessage(pattern="/stats"))
    async def stats_command_handler(event):
        """Statistika"""
        cursor.execute("SELECT COUNT(*) FROM targets")
        users_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM user_keywords")
        keywords_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM recent_messages")
        messages_count = cursor.fetchone()[0]
        
        await event.reply(
            f"📊 **STATISTIKA**\n\n"
            f"👥 Foydalanuvchilar: {users_count}\n"
            f"🔑 Kalit so'zlar: {keywords_count}\n"
            f"💬 Qayta ishlangan xabarlar: {messages_count}\n"
            f"🎯 Filtrlangan foydalanuvchilar: {len(TARGET_USERS)}"
        )

    @client.on(events.NewMessage(pattern="/join"))
    async def join_group_handler(event):
        """Guruhga qo'shilish"""
        if not is_admin(event.sender_id):
            await event.reply("❌ Bu buyruq faqat admin uchun!")
            return
        
        try:
            _, link = event.text.split(maxsplit=1)
            await client.join_chat(link)
            await event.reply(f"✅ Guruhga qo'shildim: {link}")
        except Exception as e:
            await event.reply(f"❌ Xato: {e}")

    @client.on(events.NewMessage(pattern="/groups"))
    async def list_groups_handler(event):
        """Guruhlar ro'yxati"""
        if not is_admin(event.sender_id):
            await event.reply("❌ Bu buyruq faqat admin uchun!")
            return
        
        try:
            dialogs = await client.get_dialogs()
            groups = []
            
            for dialog in dialogs:
                if dialog.is_group:
                    groups.append(f"• {dialog.name}")
            
            if groups:
                await event.reply(f"📋 Guruhlar ({len(groups)} ta):\n\n" + "\n".join(groups[:10]))
            else:
                await event.reply("📭 Hech qanday guruh topilmadi")
        except Exception as e:
            await event.reply(f"❌ Xato: {e}")

    @client.on(events.NewMessage(incoming=True))
    async def message_filter_handler(event: Message):
        if event.out:
            return

        text = None
        original_text = ""

        if event.text:
            original_text = event.text
            text = event.text[:MAX_LEN]
            print(f"\n📩 Yangi xabar: {original_text[:100]}...")

        elif event.voice:
            text = await voice_to_text(event)
            original_text = text
            if not text:
                return

        text_normalized = normalize_text(text)

        if is_spam(text_normalized):
            print(f"❌ Spam deb topildi")
            return

        try:
            # Xabarni saqlash
            cursor.execute(
                "INSERT INTO recent_messages (sender_id, text) VALUES (?, ?)",
                (event.sender_id, text_normalized)
            )
            conn.commit()

            # Eski xabarlarni tozalash
            cursor.execute(
                "DELETE FROM recent_messages WHERE rowid NOT IN (SELECT rowid FROM recent_messages ORDER BY rowid DESC LIMIT 5000)"
            )
            conn.commit()

            # Chat ma'lumotlarini olish
            chat = await event.get_chat()
            sender = await event.get_sender()

            username = f"@{sender.username}" if sender.username else "yo'q"
            phone = sender.phone if sender.phone else "yashirin"
            user_id = sender.id

            group_title = getattr(chat, "title", "Shaxsiy chat")
            group_link = f"https://t.me/{chat.username}" if getattr(chat, "username", None) else "yopiq guruh"
            time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Xabarni tayyorlash
            msg = (
                f"👤 Kim: {username}\n"
                f"🆔 ID: {user_id}\n"
                f"📞 Telefon: {phone}\n"
                f"👥 Guruh: {group_title}\n"
                f"🔗 Link: {group_link}\n"
                f"⏰ Vaqt: {time}\n\n"
                f"💬 Xabar:\n{text}"
            )

            # Mos kelgan foydalanuvchilarga yuborish
            await send_to_matched_users(msg, original_text)

        except Exception as e:
            print(f"Xabarni qayta ishlashda xato: {e}")

# =====================
# ASOSIY ISHGA TUSHIRISH FUNKSIYASI
# =====================

async def main():
    global client
    
    # 1. Session faylini tekshirish
    session_file = f"{SESSION_NAME}.session"
    print("🤖 USERBOT ishga tushmoqda...")
    
    if os.path.exists(session_file):
        print(f"📂 Session fayli topildi: {session_file}")
    else:
        print("📂 Session fayli yo'q, yangi yaratiladi...")
    
    # 2. Client yaratish
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    
    # 3. Jadvalarni yaratish
    print("⏳ Jadvalar yaratilmoqda/yangilanmoqda...")
    create_tables()
    
    # 4. Ma'lumotlarni RAM ga yuklash
    cursor.execute("SELECT id FROM targets")
    rows = cursor.fetchall()
    for (user_id,) in rows:
        TARGET_USERS.add(user_id)
    
    cursor.execute("SELECT category, word FROM keywords")
    rows = cursor.fetchall()
    for cat, word in rows:
        KEYWORD_CATEGORIES.setdefault(cat, []).append(word)
    
    print(f"✅ {len(TARGET_USERS)} ta foydalanuvchi yuklandi")
    print(f"✅ {sum(len(v) for v in KEYWORD_CATEGORIES.values())} ta kalit so'z yuklandi")
    
    # 5. Autentifikatsiya
    await client.connect()
    print("🔗 Telegram serveriga ulandi...")
    
    if not await client.is_user_authorized():
        print("🔐 Login talab qilinmoqda...")
        print("\n" + "="*50)
        print("📱 TELEGRAM LOGIN")
        print("="*50)
        
        try:
            # Telefon raqamini so'rash
            phone = input("📞 Telefon raqamingiz (+998XXXXXXXXX): ").strip()
            
            print("\n⏳ Kod yuborilmoqda...")
            
            # Kod so'rash, lekin Telegram ilovasidan kirish imkoniyatini berish
            sent_code = await client.send_code_request(phone)
            
            print(f"✅ Kod yuborildi!")
            print(f"📱 Telefon: {phone}")
            
            # Kodni olish
            print("\n" + "-"*50)
            print("📲 AGAR SMS KELMASA:")
            print("1. Telegram ilovangizni oching")
            print("2. Yangi login so'rovi chiqadi")
            print("3. 'Allow' yoki 'Sign in via Telegram' tugmasini bosing")
            print("-"*50 + "\n")
            
            code = input("📝 SMS kodi yoki Telegram ilovangizda 'Sign in via Telegram' tugmasini bosgandan so'ng kiritishni unutmang: ").strip()
            
            if code:
                try:
                    # Kod bilan login
                    await client.sign_in(phone=phone, code=code)
                except Exception as e:
                    if "2FA" in str(e):
                        # 2FA paroli kerak
                        password = input("🔐 2FA parolini kiriting: ").strip()
                        await client.sign_in(password=password)
                    else:
                        # Boshqa xato
                        raise e
            
            # Agar hali ham login qilinmasa, Telegram ilovasidan tasdiqlashni kutish
            if not await client.is_user_authorized():
                print("\n⏳ Telegram ilovangizda yangi login so'rovini tasdiqlang...")
                print("Telegram ilovasini oching va 'Allow' tugmasini bosing")
                
                # 30 soniya kutish
                for i in range(30, 0, -1):
                    print(f"\r⏳ Kutish: {i} soniya qoldi...", end="", flush=True)
                    time.sleep(1)
                    
                    if await client.is_user_authorized():
                        print("\n✅ Telegram ilovasi orqali login qilindi!")
                        break
                
                if not await client.is_user_authorized():
                    print("\n❌ Login amalga oshmadi. Qayta urinib ko'ring.")
                    
                    # Qayta urinish
                    print("\n🔄 Qayta urinib ko'ramiz...")
                    code = input("📝 SMS kodi yoki Telegram ilovasini ochgandan keyin kodni kiriting: ").strip()
                    
                    if code:
                        try:
                            await client.sign_in(phone=phone, code=code)
                        except Exception as e:
                            if "2FA" in str(e):
                                password = input("🔐 2FA parolini kiriting: ").strip()
                                await client.sign_in(password=password)
            
            if await client.is_user_authorized():
                print("✅ Muvaffaqiyatli login qilindi!")
            else:
                print("❌ Login amalga oshmadi. Session faylini o'chirib qayta urinib ko'ring.")
                print("Buning uchun terminalda quyidagi buyruqni ishga tushiring:")
                print(f"rm {SESSION_NAME}.session")
                sys.exit(1)
                
        except Exception as e:
            print(f"\n❌ Login xatosi: {e}")
            
            # Oddiy sign_in metodi bilan urinib ko'rish
            try:
                print("\n🔄 Oddiy login usuli...")
                await client.start(phone=phone)
                print("✅ Oddiy login usuli bilan muvaffaqiyatli!")
            except Exception as e2:
                print(f"❌ Yakuniy xato: {e2}")
                print("❌ Dastur to'xtatildi.")
                print("Iltimos, session faylini o'chiring:")
                print(f"rm {SESSION_NAME}.session")
                sys.exit(1)
    else:
        print("✅ Sessiya mavjud, login kerak emas.")
    
    # 6. Event handlerlarni ro'yxatdan o'tkazish
    print("🔄 Event handlerlar ro'yxatdan o'tkazilmoqda...")
    register_handlers()
    
    print("\n" + "="*50)
    print("✅ USERBOT ISHGA TUSHDI!")
    print("📡 Xabarlarni kutish...")
    print("="*50 + "\n")
    
    # 7. Botni ishlashda saqlash
    try:
        await client.run_until_disconnected()
    except KeyboardInterrupt:
        print("\n👋 Userbot to'xtatildi")
    except Exception as e:
        print(f"\n❌ Xato: {e}")

# =====================
# DASHLASH
# =====================
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Userbot to'xtatildi")
    except Exception as e:
        print(f"\n❌ Xato: {e}")
        print("Dastur to'xtatildi.")