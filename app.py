import streamlit as st
import psycopg2
from datetime import timedelta, date
import pandas as pd

# --- NASTAVENÍ STRÁNKY ---
st.set_page_config(page_title="Pronájem kurtů TJ Sokol Hrabová", layout="wide")
st.title("🎾 Pronájem kurtů TJ Sokol Hrabová")

# --- PŘIPOJENÍ K DATABÁZI NEON.TECH ---
def get_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

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
    conn.commit()
    cur.close()
    conn.close()

init_db()

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

# --- VÝBĚR TÝDNE ---
vybrane_datum = st.date_input("Vyberte libovolný den v týdnu:", value=date.today())
pondeli = vybrane_datum - timedelta(days=vybrane_datum.weekday())
nedele = pondeli + timedelta(days=6)
st.subheader(f"Týdenní rozpis: {pondeli.strftime('%d.%m.%Y')} – {nedele.strftime('%d.%m.%Y')}")

# --- NAČTENÍ DAT PRO VYBRANÝ TÝDEN ---
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

rezervace = nacti_rezervace_tydne(pondeli)

# --- POSTRANNÍ PANEL: NOVÁ REZERVACE + MAZÁNÍ ---
with st.sidebar:
    st.header("➕ Nová rezervace")
    with st.form("nova_rezervace", clear_on_submit=True):
        f_kurt = st.selectbox("Kurt", KURTY, format_func=lambda x: f"Kurt č. {x}")
        f_datum = st.date_input("Datum (nebo začátek pravidelného pronájmu)", value=vybrane_datum)
        f_blok = st.selectbox("Časový blok", CASOVE_BLOKY)
        f_jmeno = st.text_input("Jméno hráče / nájemce")
        f_cena = st.number_input("Částka (Kč)", min_value=0, step=50, value=300)
        f_pravidelna = st.checkbox("🔁 Pravidelný týdenní pronájem")
        
        odeslat = st.form_submit_button("Uložit rezervaci")
        if odeslat:
            if not f_jmeno.strip():
                st.warning("Vyplňte prosím jméno.")
            else:
                conn = get_connection()
                cur = conn.cursor()
                den_idx = f_datum.weekday()

                # Zabráníme duplicitám ve stejném slotu:
                # - pokud ukládáme jednorázovou, smažeme případnou jinou jednorázovou ve stejný den a blok
                # - pokud ukládáme pravidelnou, smažeme případnou starší pravidelnou pro stejný den_v_tydnu a blok
                if f_pravidelna:
                    cur.execute("""
                        DELETE FROM rezervace
                        WHERE kurt = %s AND den_v_tydnu = %s AND casovy_blok = %s AND je_pravidelna = TRUE
                    """, (f_kurt, den_idx, f_blok))
                else:
                    cur.execute("""
                        DELETE FROM rezervace
                        WHERE kurt = %s AND datum = %s AND casovy_blok = %s AND je_pravidelna = FALSE
                    """, (f_kurt, f_datum, f_blok))

                cur.execute("""
                    INSERT INTO rezervace (kurt, datum, den_v_tydnu, casovy_blok, jmeno, cena, je_pravidelna)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (f_kurt, f_datum, den_idx, f_blok, f_jmeno.strip(), f_cena, f_pravidelna))
                conn.commit()
                cur.close()
                conn.close()
                st.success("Rezervace uložena!")
                st.rerun()

    st.divider()
    st.header("🗑️ Smazat rezervaci")

    # Připravíme seznam aktivních rezervací pro vybraný týden ke smazání
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
            if je_pravidelna_mazana:
                st.info("Pravidelná rezervace byla odstraněna ze všech týdnů.")
            else:
                st.success("Jednorázová rezervace byla smazána.")
            st.rerun()
    else:
        st.caption("V tomto týdnu nejsou žádné rezervace ke smazání.")

# --- VYKRESLENÍ TÝDENNÍHO ROZPISU A SOUČET TRŽEB ---
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

tab1, tab2 = st.tabs(["🎾 Kurt č. 1", "🎾 Kurt č. 2"])

for idx_kurt, tab in enumerate([tab1, tab2], start=1):
    with tab:
        data_tabulky = []
        for blok in CASOVE_BLOKY:
            radek = {"Čas": blok}
            for den_idx, nazev_dne in enumerate(DNY_V_TYDNU):
                aktualni_datum = pondeli + timedelta(days=den_idx)
                sloupec_nazev = f"{nazev_dne} ({aktualni_datum.strftime('%d.%m.')})"
                
                klic = (idx_kurt, den_idx, blok)
                if klic in mapa_rez:
                    jmeno, cena, pravidelna = mapa_rez[klic]
                    ikona = "🔁 " if pravidelna else ""
                    radek[sloupec_nazev] = f"{ikona}{jmeno} ({cena} Kč)"
                    celkova_trzba_tyden += cena
                else:
                    radek[sloupec_nazev] = "—"
            data_tabulky.append(radek)
            
        df = pd.DataFrame(data_tabulky)
        st.dataframe(df, use_container_width=True, hide_index=True)

# --- TÝDENNÍ FINANČNÍ SOUHRN ---
st.divider()
st.metric(label="💰 Celková tržba za vybraný týden (oba kurty dohromady)", value=f"{celkova_trzba_tyden:,} Kč".replace(",", " "))