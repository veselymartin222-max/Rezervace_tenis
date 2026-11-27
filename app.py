import os
import requests
import streamlit as st
import psycopg2
from datetime import timedelta, date
import pandas as pd

# --- NASTAVENÍ STRÁNKY ---
st.set_page_config(page_title="Pronájem kurtů TJ Sokol Hrabová", layout="wide")
st.title("🎾 Pronájem kurtů TJ Sokol Hrabová")

# --- VÝCHOZÍ ČLENOVÉ PŘI PRVNÍM VYTVOŘENÍ TABULKY ---
VYCHOZI_CLENOVE = [
    "Šulák",
    "Janša",
    "Vášová",
    "Huťka",
    "Hořínek",
    "Targoš",
    "Janeček",
    "Nytrová",
    "Horák",
    "Veselý",
    "Heczko",
]

# --- ČASOVÉ BLOKY (posun od 12:30, konec v 21:15) ---
CASOVE_BLOKY = [
    "07:00 - 08:45",
    "08:45 - 10:30",
    "10:30 - 12:15",
    "12:30 - 14:15",
    "14:15 - 16:00",
    "16:00 - 17:45",
    "17:45 - 19:30",
    "19:30 - 21:15",
]
DNY_V_TYDNU = ["Pondělí", "Úterý", "Středa", "Čtvrtek", "Pátek", "Sobota", "Neděle"]
KURTY = [1, 2]
VYCHOZI_CENA = 160

# --- PŘIPOJENÍ K DATABÁZI NEON.TECH ---
def get_secret_value(key):
    val = os.environ.get(key)
    if val:
        return val
    if key in st.secrets:
        return str(st.secrets[key])
    return None

def get_database_url():
    url = get_secret_value("DATABASE_URL")
    if not url:
        raise RuntimeError("Chybí DATABASE_URL v proměnných prostředí i v st.secrets.")
    return url

def get_connection():
    return psycopg2.connect(get_database_url())

def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rezervace (
            id SERIAL PRIMARY KEY,
            kurt INTEGER NOT NULL,
            datum DATE NOT NULL,
            den_v_tydnu INTEGER NOT NULL,
            casovy_blok VARCHAR(50) NOT NULL,
            jmeno VARCHAR(100) NOT NULL,
            cena INTEGER NOT NULL,
            je_pravidelna BOOLEAN DEFAULT FALSE
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sluzby (
            datum DATE PRIMARY KEY,
            clen_jmeno VARCHAR(100) NOT NULL
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS clenove_klubu (
            id SERIAL PRIMARY KEY,
            jmeno VARCHAR(100) UNIQUE NOT NULL
        );
    """)
    cur.execute("SELECT COUNT(*) FROM clenove_klubu;")
    pocet_clenu = cur.fetchone()[0]
    if pocet_clenu == 0:
        for jmeno in VYCHOZI_CLENOVE:
            cur.execute("""
                INSERT INTO clenove_klubu (jmeno)
                VALUES (%s)
                ON CONFLICT (jmeno) DO NOTHING;
            """, (jmeno,))
    conn.commit()
    cur.close()
    conn.close()

init_db()

# --- PRÁCE SE ČLENY KLUBU V DATABÁZI ---
def nacti_cleny_klubu():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, jmeno FROM clenove_klubu ORDER BY jmeno ASC;")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def pridej_clena_klubu(jmeno_val):
    ciste_jmeno = " ".join(jmeno_val.strip().split())
    if not ciste_jmeno:
        return False, "Zadejte jméno člena klubu."
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO clenove_klubu (jmeno)
            VALUES (%s)
            ON CONFLICT (jmeno) DO NOTHING;
        """, (ciste_jmeno,))
        inserted = cur.rowcount > 0
        conn.commit()
        if inserted:
            return True, f"Člen „{ciste_jmeno}“ byl přidán."
        return False, f"Člen „{ciste_jmeno}“ už v seznamu je."
    finally:
        cur.close()
        conn.close()

def smaz_clena_klubu(clen_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM clenove_klubu WHERE id = %s;", (clen_id,))
    conn.commit()
    cur.close()
    conn.close()

# --- TELEGRAM NOTIFIKACE ---
def posli_zpravu_telegram(text):
    token = get_secret_value("TELEGRAM_BOT_TOKEN")
    chat_id = get_secret_value("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=5)
    except Exception:
        pass

# --- POMOCNÉ FUNKCE PRO ULOŽENÍ REZERVACE A SLUŽBY ---
def uloz_rezervaci(kurt_val, datum_val, blok_val, jmeno_val, cena_val, pravidelna_val):
    conn = get_connection()
    cur = conn.cursor()
    den_idx = datum_val.weekday()

    if pravidelna_val:
        cur.execute("""
            DELETE FROM rezervace
            WHERE kurt = %s AND den_v_tydnu = %s AND casovy_blok = %s AND je_pravidelna = TRUE
        """, (kurt_val, den_idx, blok_val))
    else:
        cur.execute("""
            DELETE FROM rezervace
            WHERE kurt = %s AND datum = %s AND casovy_blok = %s AND je_pravidelna = FALSE
        """, (kurt_val, datum_val, blok_val))

    cur.execute("""
        INSERT INTO rezervace (kurt, datum, den_v_tydnu, casovy_blok, jmeno, cena, je_pravidelna)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (kurt_val, datum_val, den_idx, blok_val, jmeno_val.strip(), cena_val, pravidelna_val))
    conn.commit()
    cur.close()
    conn.close()

    typ_text = "Pravidelná (týdně)" if pravidelna_val else "Jednorázová"
    posli_zpravu_telegram(
        f"🎾 Nová rezervace – TJ Sokol Hrabová\n"
        f"Kurt: č. {kurt_val}\n"
        f"Datum: {datum_val.strftime('%d.%m.%Y')} ({DNY_V_TYDNU[den_idx]})\n"
        f"Čas: {blok_val}\n"
        f"Hráč: {jmeno_val.strip()}\n"
        f"Cena: {cena_val} Kč\n"
        f"Typ: {typ_text}"
    )

def uloz_sluzbu(datum_val, clen_val):
    conn = get_connection()
    cur = conn.cursor()
    if clen_val == "— Bez služby —":
        cur.execute("DELETE FROM sluzby WHERE datum = %s", (datum_val,))
    else:
        cur.execute("""
            INSERT INTO sluzby (datum, clen_jmeno)
            VALUES (%s, %s)
            ON CONFLICT (datum) DO UPDATE SET clen_jmeno = EXCLUDED.clen_jmeno
        """, (datum_val, clen_val))
    conn.commit()
    cur.close()
    conn.close()

# --- NAČTENÍ AKTUÁLNÍCH ČLENŮ KLUBU ---
clenove_zaznamy = nacti_cleny_klubu()
jen_jmena_clenu = [jmeno for _, jmeno in clenove_zaznamy]
moznosti_hrace = ["— Ruční zadání (nečlen / jiný nájemce) —"] + jen_jmena_clenu

# --- STAV PRO POSUN DNŮ ---
if "vybrane_datum" not in st.session_state:
    st.session_state.vybrane_datum = date.today()

# --- OVLÁDÁNÍ POSUNU DNŮ / TÝDNŮ ---
col_nav1, col_nav2, col_nav3, col_nav4, col_nav5 = st.columns([1.2, 1.2, 1, 1.2, 1.2])
with col_nav1:
    if st.button("◀ Předchozí den", use_container_width=True):
        st.session_state.vybrane_datum -= timedelta(days=1)
        st.rerun()
with col_nav2:
    if st.button("Další den ▶", use_container_width=True):
        st.session_state.vybrane_datum += timedelta(days=1)
        st.rerun()
with col_nav3:
    if st.button("Dnes", use_container_width=True):
        st.session_state.vybrane_datum = date.today()
        st.rerun()
with col_nav4:
    if st.button("◀ Týden", use_container_width=True):
        st.session_state.vybrane_datum -= timedelta(days=7)
        st.rerun()
with col_nav5:
    if st.button("Týden ▶", use_container_width=True):
        st.session_state.vybrane_datum += timedelta(days=7)
        st.rerun()

vybrane_datum = st.session_state.vybrane_datum
pondeli = vybrane_datum - timedelta(days=vybrane_datum.weekday())
nedele = pondeli + timedelta(days=6)

# --- NAČTENÍ REZERVACÍ A SLUŽEB PRO TÝDEN ---
def nacti_rezervace_tydne(pondeli_date):
    conn = get_connection()
    cur = conn.cursor()
    nedele_date = pondeli_date + timedelta(days=6)
    cur.execute("""
        SELECT id, kurt, datum, den_v_tydnu, casovy_blok, jmeno, cena, je_pravidelna
        FROM rezervace
        WHERE (je_pravidelna = FALSE AND datum BETWEEN %s AND %s)
           OR (je_pravidelna = TRUE AND datum <= %s)
        ORDER BY datum, casovy_blok
    """, (pondeli_date, nedele_date, nedele_date))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def nacti_sluzby_tydne(pondeli_date):
    conn = get_connection()
    cur = conn.cursor()
    nedele_date = pondeli_date + timedelta(days=6)
    cur.execute("""
        SELECT datum, clen_jmeno
        FROM sluzby
        WHERE datum BETWEEN %s AND %s
    """, (pondeli_date, nedele_date))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {r[0]: r[1] for r in rows}

rezervace = nacti_rezervace_tydne(pondeli)
sluzby_mapa = nacti_sluzby_tydne(pondeli)

# --- PŘEHLED SLUŽEB NA HLAVNÍ STRÁNCE ---
st.subheader(f"Týdenní rozpis: {pondeli.strftime('%d.%m.%Y')} – {nedele.strftime('%d.%m.%Y')} (vybraný den: {vybrane_datum.strftime('%d.%m.%Y')})")

sluzby_karty = st.columns(7)
for den_idx, nazev_dne in enumerate(DNY_V_TYDNU):
    akt_datum = pondeli + timedelta(days=den_idx)
    clen_sluzba = sluzby_mapa.get(akt_datum, "—")
    zvyrazneni = " 📌" if akt_datum == vybrane_datum else ""
    with sluzby_karty[den_idx]:
        st.markdown(f"**{nazev_dne[:2]} {akt_datum.strftime('%d.%m.')}**{zvyrazneni}")
        st.caption(f"Služba: **{clen_sluzba}**")

# --- RYCHLÁ ZÁLOŽKA PRO ZADÁNÍ REZERVACE DO KONKRÉTNÍHO POLÍČKA ---
with st.expander("📝 Rychlé zadání pronájmu (výběr dne, času a kurtu)", expanded=False):
    with st.form("rychle_zadani", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            r_den_idx = st.selectbox(
                "Den v týdnu",
                options=list(range(7)),
                index=vybrane_datum.weekday(),
                format_func=lambda idx: f"{DNY_V_TYDNU[idx]} ({(pondeli + timedelta(days=idx)).strftime('%d.%m.%Y')})"
            )
        with c2:
            r_blok = st.selectbox("Časový blok", CASOVE_BLOKY)
        with c3:
            r_kurt = st.selectbox("Kurt", KURTY, format_func=lambda x: f"Kurt č. {x}")

        c4, c5, c6 = st.columns(3)
        with c4:
            r_clen = st.selectbox("Člen klubu", moznosti_hrace)
        with c5:
            r_jmeno_rucne = st.text_input("Nebo zadejte jméno ručně")
        with c6:
            r_cena = st.number_input("Částka (Kč)", min_value=0, step=10, value=VYCHOZI_CENA)

        r_pravidelna = st.checkbox("🔁 Pravidelný týdenní pronájem", key="r_prav")
        if st.form_submit_button("Uložit do rozpisu"):
            final_jmeno = r_jmeno_rucne.strip() if r_jmeno_rucne.strip() else (
                "" if r_clen.startswith("—") else r_clen
            )
            if not final_jmeno:
                st.warning("Vyberte člena klubu nebo zadejte jméno ručně.")
            else:
                cilove_datum = pondeli + timedelta(days=r_den_idx)
                uloz_rezervaci(r_kurt, cilove_datum, r_blok, final_jmeno, r_cena, r_pravidelna)
                st.success(f"Uloženo: Kurt č. {r_kurt}, {cilove_datum.strftime('%d.%m.%Y')} ({r_blok}) – {final_jmeno}.")
                st.rerun()

# --- POSTRANNÍ PANEL: REZERVACE, SLUŽBY, ČLENOVÉ A MAZÁNÍ ---
with st.sidebar:
    st.header("➕ Nová rezervace")
    with st.form("nova_rezervace", clear_on_submit=True):
        f_kurt = st.selectbox("Kurt", KURTY, format_func=lambda x: f"Kurt č. {x}")
        f_datum = st.date_input("Datum (nebo začátek pravidelného pronájmu)", value=vybrane_datum)
        f_blok = st.selectbox("Časový blok", CASOVE_BLOKY)
        f_clen = st.selectbox("Člen klubu", moznosti_hrace, key="sb_clen")
        f_jmeno = st.text_input("Nebo jméno hráče / nájemce ručně")
        f_cena = st.number_input("Částka (Kč)", min_value=0, step=10, value=VYCHOZI_CENA)
        f_pravidelna = st.checkbox("🔁 Pravidelný týdenní pronájem")

        if st.form_submit_button("Uložit rezervaci"):
            final_jmeno = f_jmeno.strip() if f_jmeno.strip() else (
                "" if f_clen.startswith("—") else f_clen
            )
            if not final_jmeno:
                st.warning("Vyberte člena klubu nebo vyplňte jméno.")
            else:
                uloz_rezervaci(f_kurt, f_datum, f_blok, final_jmeno, f_cena, f_pravidelna)
                st.success("Rezervace uložena!")
                st.rerun()

    st.divider()
    st.header("👥 Členové klubu")
    with st.form("pridat_clena", clear_on_submit=True):
        nove_jmeno_clena = st.text_input("Přidat člena (jméno a příjmení)")
        if st.form_submit_button("➕ Přidat člena"):
            ok, zprava = pridej_clena_klubu(nove_jmeno_clena)
            if ok:
                st.success(zprava)
                st.rerun()
            else:
                st.warning(zprava)

    if clenove_zaznamy:
        clen_ke_smazani = st.selectbox(
            "Odebrat člena ze seznamu:",
            options=clenove_zaznamy,
            format_func=lambda item: item[1],
            key="sb_smaz_clena"
        )
        if st.button("🗑️ Odebrat člena"):
            smaz_clena_klubu(clen_ke_smazani[0])
            st.success(f"Člen „{clen_ke_smazani[1]}“ byl odebrán.")
            st.rerun()
    else:
        st.caption("V databázi zatím nejsou žádní členové.")

    st.divider()
    st.header("🛡️ Služba na kurtu")
    with st.form("nastav_sluzbu"):
        s_datum = st.date_input("Datum služby", value=vybrane_datum)
        moznosti_sluzby = ["— Bez služby —"] + jen_jmena_clenu
        s_clen = st.selectbox("Kdo má službu", moznosti_sluzby)
        if st.form_submit_button("Uložit službu"):
            uloz_sluzbu(s_datum, s_clen)
            st.success("Služba uložena!")
            st.rerun()

    st.divider()
    st.header("🗑️ Smazat rezervaci")
    polozky_ke_smazani = []
    for r in rezervace:
        r_id, kurt, r_datum, den_idx, blok, jmeno, cena, pravidelna = r
        aktualni_den_datum = pondeli + timedelta(days=den_idx)
        if pravidelna and r_datum > aktualni_den_datum:
            continue
        typ_popis = "🔁 Pravidelná" if pravidelna else f"📅 {r_datum.strftime('%d.%m.')}"
        nazev_dne = DNY_V_TYDNU[den_idx]
        popis = f"Kurt {kurt} | {nazev_dne} {blok} | {jmeno} ({cena} Kč) [{typ_popis}]"
        polozky_ke_smazani.append((popis, r_id, pravidelna))

    if polozky_ke_smazani:
        vybrana_polozka = st.selectbox(
            "Vyberte rezervaci ke smazání:",
            options=polozky_ke_smazani,
            format_func=lambda x: x[0]
        )
        if st.button("🗑️ Smazat vybranou rezervaci", type="primary"):
            _, id_ke_smazani, je_pravidelna_mazana = vybrana_polozka
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("DELETE FROM rezervace WHERE id = %s", (id_ke_smazani,))
            conn.commit()
            cur.close()
            conn.close()
            posli_zpravu_telegram(
                f"🗑️ Zrušena rezervace – TJ Sokol Hrabová\n"
                f"Položka: {vybrana_polozka[0]}"
            )
            if je_pravidelna_mazana:
                st.info("Pravidelná rezervace byla odstraněna ze všech týdnů.")
            else:
                st.success("Jednorázová rezervace byla smazána.")
            st.rerun()
    else:
        st.caption("V tomto týdnu nejsou žádné rezervace ke smazání.")

# --- MAPOVÁNÍ REZERVACÍ A KURT 1 + 2 POD SEBOU V BUŇCE ---
celkova_trzba_tyden = 0
mapa_rez = {}

for r in rezervace:
    r_id, kurt, r_datum, den_idx, blok, jmeno, cena, pravidelna = r
    aktualni_den_datum = pondeli + timedelta(days=den_idx)
    if pravidelna and r_datum > aktualni_den_datum:
        continue
    klic = (kurt, den_idx, blok)
    if klic not in mapa_rez or not pravidelna:
        mapa_rez[klic] = (jmeno, cena, pravidelna)

def popis_kurtu(kurt_cislo, den_idx, blok):
    global celkova_trzba_tyden
    klic = (kurt_cislo, den_idx, blok)
    if klic in mapa_rez:
        jmeno, cena, pravidelna = mapa_rez[klic]
        ikona = "🔁 " if pravidelna else ""
        celkova_trzba_tyden += cena
        return f"K{kurt_cislo}: {ikona}{jmeno} ({cena} Kč)"
    return f"K{kurt_cislo}: —"

data_tabulky = []
sloupce_dnu = []

for blok in CASOVE_BLOKY:
    radek = {}
    for den_idx, nazev_dne in enumerate(DNY_V_TYDNU):
        aktualni_datum = pondeli + timedelta(days=den_idx)
        sluzba_text = sluzby_mapa.get(aktualni_datum)
        sluzba_suffix = f" [🛡️ {sluzba_text}]" if sluzba_text else ""
        sloupec_nazev = f"{nazev_dne} ({aktualni_datum.strftime('%d.%m.')}){sluzba_suffix}"
        if sloupec_nazev not in sloupce_dnu:
            sloupce_dnu.append(sloupec_nazev)

        k1_text = popis_kurtu(1, den_idx, blok)
        k2_text = popis_kurtu(2, den_idx, blok)
        # Kurt č. 1 a č. 2 pod sebou v jedné buňce
        radek[sloupec_nazev] = f"{k1_text}\n{k2_text}"

    # Časový blok pevně na pravém okraji
    radek["Čas"] = blok
    data_tabulky.append(radek)

df = pd.DataFrame(data_tabulky)

# Vycentrování obsahu v tabulce (včetně sloupce Čas) a připnutí sloupce Čas vpravo
st.markdown(
    """
    <style>
    [data-testid="stDataFrame"] [role="gridcell"],
    [data-testid="stDataFrame"] [role="columnheader"] {
        text-align: center !important;
        justify-content: center !important;
        white-space: pre-line !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

column_cfg = {
    sl_den: st.column_config.TextColumn(sl_den, width="medium")
    for sl_den in sloupce_dnu
}
column_cfg["Čas"] = st.column_config.TextColumn("Čas", width="small", pinned="right")

st.dataframe(
    df,
    use_container_width=True,
    hide_index=True,
    row_height=64,
    column_config=column_cfg,
)

# --- TÝDENNÍ FINANČNÍ SOUHRN ---
st.divider()
st.metric(label="💰 Celková tržba za vybraný týden (oba kurty dohromady)", value=f"{celkova_trzba_tyden:,} Kč".replace(",", " "))