import asyncio
import asyncpg
import json
import csv
import os
import re

# Твой DATABASE_URL (внутренний Render, он сработает на сервере)
DATABASE_URL = "postgresql://admin:RRxOapzxaKxIHvMAgyRTOwDZWaVAHXLX@dpg-dbltbtegekts73cc59fg-a/oasis_rl3m"

FILES_TO_IMPORT = [
    "wheelock.3.txt",
    "@silverrouteadp.json",
    "1 clean.csv",
    "2 clean.csv",
    "3 clean.csv",
    "4 clean.csv",
    "5 clean.csv"
]

def clean_phone(p):
    if not p: return None
    p = str(p)
    digits = re.sub(r'\D', '', p)
    if len(digits) >= 10:
        if len(digits) == 11 and digits.startswith('8'):
            return '7' + digits[1:]
        return digits
    return None

async def save_batch(conn, batch):
    if not batch: return
    await conn.executemany("""
        INSERT INTO tg_entities (tg_id, username, phone, source)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (tg_id) DO UPDATE SET
            username = COALESCE(EXCLUDED.username, tg_entities.username),
            phone = COALESCE(EXCLUDED.phone, tg_entities.phone),
            last_seen = NOW()
    """, batch)

async def import_json(pool, filepath):
    print(f"⏳ Читаю JSON: {filepath}...")
    async with pool.acquire() as conn:
        batch = []
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            try: data = json.load(f)
            except json.JSONDecodeError: return print(f"❌ Ошибка JSON в {filepath}.")

        items = data if isinstance(data, list) else data.values() if isinstance(data, dict) else []
        for item in items:
            if not isinstance(item, dict): continue
            tg_id = str(item.get('id') or item.get('tg_id') or item.get('user_id') or '')
            username = item.get('username') or item.get('nick') or item.get('login')
            phone = clean_phone(item.get('phone') or item.get('number'))
            
            if tg_id.isdigit():
                batch.append((tg_id, username, phone, 'adp_json'))
            
            if len(batch) >= 1000:
                await save_batch(conn, batch)
                batch.clear()
        await save_batch(conn, batch)

async def import_txt(pool, filepath):
    print(f"⏳ Читаю TXT: {filepath}...")
    async with pool.acquire() as conn:
        batch = []
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                parts = re.split(r'[:,\t;]', line.strip())
                if not parts: continue
                tg_id, phone, username = None, None, None
                for p in parts:
                    p = p.strip().replace('"', '').replace("'", "")
                    if p.isdigit() and 5 <= len(p) <= 12 and not tg_id: tg_id = p
                    elif (p.startswith('@') or (p.isalnum() and len(p) > 3)) and not username: username = p.replace('@', '')
                    elif len(re.sub(r'\D', '', p)) >= 10 and not phone: phone = clean_phone(p)
                if tg_id: batch.append((tg_id, username, phone, 'wheelock_txt'))
                if len(batch) >= 1000:
                    await save_batch(conn, batch)
                    batch.clear()
        await save_batch(conn, batch)

async def import_csv(pool, filepath):
    print(f"⏳ Читаю CSV: {filepath}...")
    async with pool.acquire() as conn:
        batch = []
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            reader = csv.reader(f, delimiter=';' if ';' in f.readline() else ',')
            f.seek(0)
            headers = next(reader)
            id_idx, phone_idx, user_idx = 0, 1, 2
            for i, h in enumerate(headers):
                h_l = h.lower()
                if 'id' in h_l: id_idx = i
                if 'phone' in h_l or 'тел' in h_l: phone_idx = i
                if 'user' in h_l or 'ник' in h_l: user_idx = i
            for row in reader:
                if not row or len(row) <= max(id_idx, phone_idx, user_idx): continue
                if row[id_idx].strip().isdigit():
                    batch.append((row[id_idx].strip(), row[user_idx].strip().replace('@','') or None, clean_phone(row[phone_idx]), 'clean_csv'))
                if len(batch) >= 5000:
                    await save_batch(conn, batch)
                    batch.clear()
        await save_batch(conn, batch)

async def main():
    print("Подключение к базе...")
    pool = await asyncpg.create_pool(DATABASE_URL)
    for f in FILES_TO_IMPORT:
        if not os.path.exists(f): 
            print(f"⚠️ Файл {f} не найден, пропускаю.")
            continue
        if f.endswith('.json'): await import_json(pool, f)
        elif f.endswith('.txt'): await import_txt(pool, f)
        elif f.endswith('.csv'): await import_csv(pool, f)
    await pool.close()
    print("🎉 ГОТОВО!")

if __name__ == '__main__':
    asyncio.run(main())
