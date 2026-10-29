import hmac
import io
import os
import random
import zipfile
from datetime import date, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

st.set_page_config(page_title="Pharmacy Manager", page_icon="💊", layout="wide")


# ---------------- Settings / secrets ----------------
def secret(key, default=None):
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


DB_URL = secret("DB_URL") or os.environ.get("DB_URL")
APP_PASSWORD = secret("APP_PASSWORD") or os.environ.get("APP_PASSWORD")
DB_HOST = secret("DB_HOST") or os.environ.get("DB_HOST")
LIVE = bool(DB_URL or DB_HOST)  # DB_URL ho to asli (permanent) mode, warna local demo mode
PK = "SERIAL PRIMARY KEY" if LIVE else "INTEGER PRIMARY KEY AUTOINCREMENT"
TABLES = ["medicines", "sales", "sale_items", "ledger"]


# ---------------- Database ----------------
@st.cache_resource
def engine():
    if LIVE:
        opts = dict(pool_pre_ping=True, pool_size=3, max_overflow=2, pool_recycle=300)
        if DB_HOST:
            url = URL.create("postgresql+psycopg2", username=str(secret("DB_USER", "postgres")).strip(),
                             password=str(secret("DB_PASSWORD", "")).strip(), host=str(DB_HOST).strip(),
                             port=int(secret("DB_PORT", 5432)), database=str(secret("DB_NAME", "postgres")).strip())
            return create_engine(url, **opts)
        url = DB_URL.strip()
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
        return create_engine(url, **opts)
    return create_engine("sqlite:///pharmacy.db", connect_args={"check_same_thread": False})


def q(sql, params=None, one=False):
    with engine().connect() as c:
        rows = c.execute(text(sql), params or {}).fetchall()
    return (rows[0] if rows else None) if one else rows


def df(sql, params=None):
    with engine().connect() as c:
        return pd.read_sql_query(text(sql), c, params=params or {})


def run(sql, params=None):
    with engine().begin() as c:
        c.execute(text(sql), params or {})


def get_meta(k, d=""):
    r = q("SELECT v FROM meta WHERE k=:k", {"k": k}, one=True)
    return r[0] if r else d


def set_meta(k, v):
    run("INSERT INTO meta(k,v) VALUES(:k,:v) ON CONFLICT(k) DO UPDATE SET v=excluded.v", {"k": k, "v": v})


@st.cache_resource
def setup():
    stmts = [
        "CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)",
        f"""CREATE TABLE IF NOT EXISTS medicines(
            id {PK}, name TEXT, category TEXT, qty INTEGER, cost DOUBLE PRECISION,
            price DOUBLE PRECISION, expiry TEXT, min_qty INTEGER DEFAULT 10)""",
        f"""CREATE TABLE IF NOT EXISTS sales(
            id {PK}, day TEXT, customer TEXT, total DOUBLE PRECISION,
            discount DOUBLE PRECISION, mode TEXT)""",
        """CREATE TABLE IF NOT EXISTS sale_items(
            sale_id INTEGER, med_id INTEGER, name TEXT, qty INTEGER,
            price DOUBLE PRECISION, cost DOUBLE PRECISION)""",
        f"""CREATE TABLE IF NOT EXISTS ledger(
            id {PK}, day TEXT, customer TEXT, phone TEXT, amount DOUBLE PRECISION, note TEXT)""",
    ]
    with engine().begin() as c:
        for s in stmts:
            c.execute(text(s))
    if get_meta("init") != "1":
        if LIVE:
            set_meta("demo", "0")
            set_meta("shop", "My Pharmacy")
            set_meta("init", "1")
        else:
            load_demo()
    return True


def clear_all():
    with engine().begin() as c:
        for t in TABLES:
            c.execute(text(f"DELETE FROM {t}"))


def load_demo():
    clear_all()
    today = date.today()
    meds = [
        ("Panadol 500mg", "Painkiller", 120, 8, 12), ("Brufen 400mg", "Painkiller", 80, 10, 15),
        ("Disprin", "Painkiller", 6, 4, 6), ("Augmentin 625mg", "Antibiotic", 40, 55, 75),
        ("Amoxil 500mg", "Antibiotic", 8, 30, 42), ("Flagyl 400mg", "Antibiotic", 60, 12, 18),
        ("Risek 20mg", "Stomach", 70, 15, 22), ("Nexum 40mg", "Stomach", 45, 25, 35),
        ("ORS Sachet", "Stomach", 100, 10, 15), ("Gaviscon Syrup", "Stomach", 12, 180, 230),
        ("Calpol Syrup", "Child", 25, 90, 120), ("Ventolin Inhaler", "Chest", 15, 320, 400),
        ("Hydryllin Syrup", "Cough", 30, 100, 135), ("Benadryl Syrup", "Cough", 5, 140, 180),
        ("Cetrizine 10mg", "Allergy", 90, 5, 8), ("Avil Injection", "Allergy", 20, 20, 30),
        ("Glucophage 500mg", "Diabetes", 55, 8, 12), ("Amlodipine 5mg", "BP", 65, 6, 10),
        ("Concor 5mg", "BP", 35, 40, 55), ("Vitamin C", "Vitamin", 150, 3, 5),
        ("Surbex Z", "Vitamin", 50, 18, 28), ("Dettol 250ml", "General", 18, 250, 310),
        ("Bandage Roll", "General", 40, 20, 30), ("Digital Thermometer", "Device", 9, 250, 350),
        ("BP Apparatus", "Device", 4, 2200, 2800),
    ]
    expiry_days = [400, 300, 25, 500, 45, 350, 600, 280, 20, 150, 90, 700, 55, 180, 420, 365,
                   300, 500, 450, 800, 250, 900, 1000, 1200, 1500]
    ins_med = text("INSERT INTO medicines(name,category,qty,cost,price,expiry,min_qty) "
                   "VALUES(:n,:c,:q,:co,:p,:e,10)")
    ins_sale = text("INSERT INTO sales(day,customer,total,discount,mode) VALUES(:d,:c,:t,0,'Cash') RETURNING id")
    ins_item = text("INSERT INTO sale_items(sale_id,med_id,name,qty,price,cost) VALUES(:s,0,:n,:q,:p,:co)")
    ins_led = text("INSERT INTO ledger(day,customer,phone,amount,note) VALUES(:d,:c,:p,:a,:n)")
    with engine().begin() as c:
        for (n, cat, qt, cost, pr), d in zip(meds, expiry_days):
            c.execute(ins_med, {"n": n, "c": cat, "q": qt, "co": cost, "p": pr, "e": str(today + timedelta(days=d))})
        names = ["Ahmed", "Bilal", "Sara Baji", "Chacha Rafiq", "Zainab", "Usman", "Walk-in"]
        for back in range(7, -1, -1):
            day = str(today - timedelta(days=back))
            for _ in range(random.randint(4, 9)):
                items = random.sample(meds, random.randint(1, 3))
                rows, total = [], 0
                for (n, cat, qt, cost, pr) in items:
                    k = random.randint(1, 3)
                    total += pr * k
                    rows.append((n, k, pr, cost))
                sid = c.execute(ins_sale, {"d": day, "c": random.choice(names), "t": total}).scalar()
                for (n, k, pr, cost) in rows:
                    c.execute(ins_item, {"s": sid, "n": n, "q": k, "p": pr, "co": cost})
        for cust, ph, amt in [("Chacha Rafiq", "0300-1111111", 1850), ("Sara Baji", "0301-2222222", 920),
                              ("Usman", "0302-3333333", 2400)]:
            c.execute(ins_led, {"d": str(today - timedelta(days=5)), "c": cust, "p": ph, "a": amt, "n": "Udhaar dawai"})
        c.execute(ins_led, {"d": str(today - timedelta(days=2)), "c": "Usman", "p": "0302-3333333",
                            "a": -1000, "n": "Payment mili"})
    set_meta("demo", "1")
    set_meta("init", "1")
    set_meta("shop", "Demo Pharmacy")


# ---------------- Login ----------------
def login_gate():
    if not APP_PASSWORD:
        if LIVE:
            st.error("APP_PASSWORD secret set nahi hai. Streamlit Secrets mein APP_PASSWORD likhein.")
            st.stop()
        return
    if st.session_state.get("auth"):
        return
    st.title("💊 Pharmacy Manager")
    st.subheader("Login")
    with st.form("login"):
        pw = st.text_input("Password", type="password")
        if st.form_submit_button("Login"):
            if hmac.compare_digest(pw.encode(), str(APP_PASSWORD).encode()):
                st.session_state["auth"] = True
                st.rerun()
            else:
                st.error("Password ghalat hai")
    st.stop()


login_gate()

try:
    setup()
except Exception as e:
    st.error("Database se connect nahi ho saka. DB secrets (DB_HOST, DB_USER, DB_PASSWORD) check karein.")
    st.caption(str(e)[:300])
    st.stop()

demo = get_meta("demo") == "1"
shop = get_meta("shop", "My Pharmacy")
st.session_state.setdefault("cart", [])
today = date.today()


def money(x):
    return f"Rs {x:,.0f}"


def bill_text(sid):
    s = q("SELECT day,customer,total,discount,mode FROM sales WHERE id=:i", {"i": int(sid)}, one=True)
    if not s:
        return ""
    items = q("SELECT name,qty,price FROM sale_items WHERE sale_id=:i", {"i": int(sid)})
    lines = [f"{shop}", f"Bill #{sid}   {s[0]}", f"Customer: {s[1]}", "-" * 32]
    for n, k, p in items:
        lines.append(f"{str(n)[:18]:18} {k:>3} x {p:.0f} = {k * p:.0f}")
    lines += ["-" * 32, f"Discount: {s[3]:.0f}", f"TOTAL: {s[2]:.0f} ({s[4]})", "Shukriya!"]
    return "\n".join(lines)


# ---------------- Sidebar ----------------
st.sidebar.title(f"💊 {shop}")
page = st.sidebar.radio("Menu", ["🏠 Dashboard", "📦 Stock", "🧾 Billing", "📒 Udhaar", "📊 Reports", "⚙️ Settings"])
if demo:
    st.sidebar.warning("DEMO MODE: ye sara data nakli hai.")
if APP_PASSWORD and st.sidebar.button("Logout"):
    st.session_state["auth"] = False
    st.rerun()

# ---------------- Dashboard ----------------
if page == "🏠 Dashboard":
    st.title("Dashboard")
    if demo:
        st.info("Ye demo data hai. Pasand aane par asli version (permanent database) lagayein.")
    t_sale = q("SELECT COALESCE(SUM(total),0) FROM sales WHERE day=:d", {"d": str(today)}, one=True)[0]
    soon = str(today + timedelta(days=60))
    meds = df("SELECT * FROM medicines")
    low = meds[meds.qty <= meds.min_qty]
    exp = meds[meds.expiry <= soon].sort_values("expiry")
    udh = q("SELECT COALESCE(SUM(amount),0) FROM ledger", one=True)[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Aaj ki sale", money(t_sale))
    c2.metric("Kam stock", len(low))
    c3.metric("60 din mein expiry", len(exp))
    c4.metric("Total udhaar", money(udh))
    st.subheader("⚠️ Kam stock dawaiyan")
    st.dataframe(low[["name", "qty", "min_qty"]], hide_index=True)
    st.subheader("⏰ Jald expire hone wali")
    st.dataframe(exp[["name", "qty", "expiry"]], hide_index=True)

# ---------------- Stock ----------------
elif page == "📦 Stock":
    st.title("Stock")
    meds = df("SELECT id,name,category,qty,cost,price,expiry,min_qty FROM medicines ORDER BY name")
    search = st.text_input("🔍 Dawai search karein")
    view = meds[meds.name.str.contains(search, case=False, regex=False)] if search else meds
    st.dataframe(view, hide_index=True)

    with st.expander("➕ Nayi dawai add karein"):
        with st.form("add_med", clear_on_submit=True):
            n = st.text_input("Dawai ka naam")
            cat = st.text_input("Category", "General")
            a, b, c_ = st.columns(3)
            qty = a.number_input("Quantity", 0, 100000, 10)
            cost = b.number_input("Kharid price", 0.0, 1e6, 0.0)
            price = c_.number_input("Bechne ki price", 0.0, 1e6, 0.0)
            exp = st.date_input("Expiry date", today + timedelta(days=365))
            mn = st.number_input("Kam stock alert (quantity)", 0, 1000, 10)
            if st.form_submit_button("Save") and n.strip():
                run("INSERT INTO medicines(name,category,qty,cost,price,expiry,min_qty) "
                    "VALUES(:n,:c,:q,:co,:p,:e,:m)",
                    {"n": n.strip(), "c": cat, "q": int(qty), "co": cost, "p": price, "e": str(exp), "m": int(mn)})
                st.success("Add ho gayi")
                st.rerun()

    with st.expander("✏️ Edit / Restock / Delete"):
        if len(meds):
            idx = meds.set_index("id")
            pick = st.selectbox("Dawai chunein", meds.id, format_func=lambda i: idx.loc[i, "name"])
            r = idx.loc[pick]
            a, b, c_ = st.columns(3)
            nq = a.number_input("Quantity", 0, 100000, int(r.qty), key=f"eq{pick}")
            nc = b.number_input("Kharid price", 0.0, 1e6, float(r.cost), key=f"ec{pick}")
            npz = c_.number_input("Bechne ki price", 0.0, 1e6, float(r.price), key=f"ep{pick}")
            ne = st.date_input("Expiry", date.fromisoformat(r.expiry), key=f"ee{pick}")
            x, y = st.columns(2)
            if x.button("Update save karein"):
                run("UPDATE medicines SET qty=:q,cost=:c,price=:p,expiry=:e WHERE id=:i",
                    {"q": int(nq), "c": nc, "p": npz, "e": str(ne), "i": int(pick)})
                st.rerun()
            if y.button("🗑 Delete karein"):
                run("DELETE FROM medicines WHERE id=:i", {"i": int(pick)})
                st.rerun()

    with st.expander("📥 CSV se stock import karein"):
        st.caption("Columns: name,category,qty,cost,price,expiry,min_qty (expiry format: 2027-12-31)")
        f = st.file_uploader("CSV file", type="csv")
        if f and st.button("Import karein"):
            d = pd.read_csv(f)
            need = {"name", "category", "qty", "cost", "price", "expiry"}
            if not need.issubset(d.columns):
                st.error(f"Ye columns zaroori hain: {', '.join(sorted(need))}")
            else:
                if "min_qty" not in d:
                    d["min_qty"] = 10
                try:
                    with engine().begin() as c:
                        for _, r in d.iterrows():
                            c.execute(text("INSERT INTO medicines(name,category,qty,cost,price,expiry,min_qty) "
                                           "VALUES(:n,:c,:q,:co,:p,:e,:m)"),
                                      {"n": str(r["name"]), "c": str(r["category"]), "q": int(r["qty"]),
                                       "co": float(r["cost"]), "p": float(r["price"]),
                                       "e": str(r["expiry"])[:10], "m": int(r["min_qty"])})
                    st.success(f"{len(d)} dawaiyan import ho gayin")
                    st.rerun()
                except Exception as e:
                    st.error(f"CSV mein koi ghalti hai, kuch import nahi hua: {str(e)[:150]}")

# ---------------- Billing ----------------
elif page == "🧾 Billing":
    st.title("Billing")
    meds = df("SELECT id,name,qty,price,cost FROM medicines WHERE qty>0 ORDER BY name")
    if meds.empty:
        st.warning("Stock khali hai.")
    else:
        idx = meds.set_index("id")
        a, b, c_ = st.columns([3, 1, 1])
        mid = a.selectbox("Dawai", meds.id, format_func=lambda i: f"{idx.loc[i, 'name']} "
                          f"(stock {idx.loc[i, 'qty']}, Rs {idx.loc[i, 'price']:.0f})")
        k = b.number_input("Qty", 1, 1000, 1)
        if c_.button("➕ Add"):
            r = idx.loc[mid]
            used = sum(i["qty"] for i in st.session_state.cart if i["id"] == int(mid))
            if used + k > r.qty:
                st.error("Itna stock nahi hai")
            else:
                st.session_state.cart.append({"id": int(mid), "name": r["name"], "qty": int(k),
                                              "price": float(r.price), "cost": float(r.cost)})
                st.rerun()

    cart = st.session_state.cart
    if cart:
        cd = pd.DataFrame(cart)
        cd["total"] = cd.qty * cd.price
        st.dataframe(cd[["name", "qty", "price", "total"]], hide_index=True)
        sub = float(cd.total.sum())
        a, b, c_ = st.columns(3)
        cust = a.text_input("Customer ka naam", "Walk-in")
        phone = b.text_input("Phone (udhaar ke liye)")
        disc = c_.number_input("Discount (Rs)", 0.0, sub, 0.0)
        mode = st.radio("Payment", ["Cash", "Udhaar"], horizontal=True)
        total = sub - disc
        st.subheader(f"Total: {money(total)}")
        x, y = st.columns(2)
        if y.button("❌ Cart khali karein"):
            st.session_state.cart = []
            st.rerun()
        if x.button("✅ Bill banayein", type="primary"):
            if mode == "Udhaar" and cust.strip().lower() in ("", "walk-in"):
                st.error("Udhaar ke liye customer ka asli naam likhein.")
            else:
                try:
                    with engine().begin() as c:
                        sid = c.execute(text("INSERT INTO sales(day,customer,total,discount,mode) "
                                             "VALUES(:d,:c,:t,:di,:m) RETURNING id"),
                                        {"d": str(today), "c": cust.strip() or "Walk-in", "t": total,
                                         "di": disc, "m": mode}).scalar()
                        for i in cart:
                            r = c.execute(text("UPDATE medicines SET qty=qty-:q WHERE id=:id AND qty>=:q"),
                                          {"q": i["qty"], "id": i["id"]})
                            if r.rowcount != 1:
                                raise ValueError(i["name"])
                            c.execute(text("INSERT INTO sale_items(sale_id,med_id,name,qty,price,cost) "
                                           "VALUES(:s,:m,:n,:q,:p,:co)"),
                                      {"s": sid, "m": i["id"], "n": i["name"], "q": i["qty"],
                                       "p": i["price"], "co": i["cost"]})
                        if mode == "Udhaar":
                            c.execute(text("INSERT INTO ledger(day,customer,phone,amount,note) "
                                           "VALUES(:d,:c,:p,:a,:n)"),
                                      {"d": str(today), "c": cust.strip(), "p": phone, "a": total,
                                       "n": f"Bill #{sid}"})
                    st.session_state.last_bill = bill_text(sid)
                    st.session_state.cart = []
                    st.rerun()
                except ValueError as e:
                    st.error(f"{e} ka stock ab kam ho chuka hai. Cart check karein.")
    if "last_bill" in st.session_state:
        st.success("Bill ban gaya")
        st.code(st.session_state.last_bill)
        st.download_button("⬇️ Bill download", st.session_state.last_bill, "bill.txt")

# ---------------- Udhaar ----------------
elif page == "📒 Udhaar":
    st.title("Udhaar Register")
    bal = df("""SELECT customer, MAX(phone) AS phone, SUM(amount) AS baqaya FROM ledger
                GROUP BY customer HAVING ABS(SUM(amount))>0.5 ORDER BY baqaya DESC""")
    st.dataframe(bal, hide_index=True)
    st.subheader("Payment wasool karein")
    if len(bal):
        with st.form("pay"):
            who = st.selectbox("Customer", bal.customer)
            amt = st.number_input("Raqam", 1.0, 1e7, 100.0)
            if st.form_submit_button("Save"):
                run("INSERT INTO ledger(day,customer,phone,amount,note) VALUES(:d,:c,'',:a,'Payment mili')",
                    {"d": str(today), "c": who, "a": -amt})
                st.rerun()
    st.subheader("Naya udhaar manually likhein")
    with st.form("newu", clear_on_submit=True):
        a, b, c_ = st.columns(3)
        n = a.text_input("Naam")
        p = b.text_input("Phone")
        m = c_.number_input("Raqam", 1.0, 1e7, 100.0)
        if st.form_submit_button("Add") and n.strip():
            run("INSERT INTO ledger(day,customer,phone,amount,note) VALUES(:d,:c,:p,:a,'Udhaar')",
                {"d": str(today), "c": n.strip(), "p": p, "a": m})
            st.rerun()

# ---------------- Reports ----------------
elif page == "📊 Reports":
    st.title("Reports")
    span = st.selectbox("Muddat", ["Pichle 7 din", "Pichle 30 din", "Pichle 90 din", "Sab"], index=1)
    days = {"Pichle 7 din": 7, "Pichle 30 din": 30, "Pichle 90 din": 90, "Sab": 36500}[span]
    frm = str(today - timedelta(days=days))
    s = df("SELECT day, SUM(total) AS sale FROM sales WHERE day>=:f GROUP BY day ORDER BY day", {"f": frm})
    if s.empty:
        st.info("Abhi koi sale nahi.")
    else:
        c1, c2 = st.columns(2)
        c1.metric("Kul sale", money(s.sale.sum()))
        st.subheader("Roz ki sale")
        st.bar_chart(s.set_index("day"))
        gross = df("""SELECT s.day, SUM((i.price-i.cost)*i.qty) AS g FROM sale_items i
                      JOIN sales s ON s.id=i.sale_id WHERE s.day>=:f GROUP BY s.day""", {"f": frm})
        disc = df("SELECT day, SUM(discount) AS d FROM sales WHERE day>=:f GROUP BY day", {"f": frm})
        prof = gross.merge(disc, on="day", how="left").fillna(0)
        prof["profit"] = prof.g - prof.d
        c2.metric("Kul munafa", money(prof.profit.sum()))
        st.subheader("Munafa (profit)")
        st.line_chart(prof.sort_values("day").set_index("day")[["profit"]])
        st.subheader("Sab se zyada bikne wali dawaiyan")
        top = df("""SELECT i.name, SUM(i.qty) AS bika FROM sale_items i JOIN sales s ON s.id=i.sale_id
                    WHERE s.day>=:f GROUP BY i.name ORDER BY bika DESC LIMIT 10""", {"f": frm})
        st.dataframe(top, hide_index=True)

    st.subheader("🧾 Purane bills")
    hist = df("SELECT id, day, customer, total, discount, mode FROM sales ORDER BY id DESC LIMIT 100")
    if len(hist):
        st.dataframe(hist, hide_index=True)
        sid = st.selectbox("Bill number", hist.id)
        bt = bill_text(sid)
        st.code(bt)
        st.download_button("⬇️ Ye bill download", bt, f"bill_{sid}.txt")

# ---------------- Settings ----------------
else:
    st.title("Settings")
    name = st.text_input("Pharmacy ka naam", shop)
    if st.button("Naam save karein"):
        set_meta("shop", name)
        st.rerun()

    st.divider()
    st.subheader("💾 Backup")
    st.write("Poora data (dawaiyan, sales, udhaar) ek ZIP mein download karein. Hafte mein ek baar zaroor lein.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for t in TABLES:
            z.writestr(f"{t}.csv", df(f"SELECT * FROM {t}").to_csv(index=False))
    st.download_button("⬇️ Backup ZIP download", buf.getvalue(), f"pharmacy_backup_{today}.zip", "application/zip")

    if demo:
        st.divider()
        st.subheader("Demo se asli data par jayein")
        st.write("Is se demo ki sari dawaiyan, sales aur udhaar delete ho jayengi aur app khali ho jayegi.")
        ok = st.checkbox("Haan, demo data delete karna hai")
        if st.button("🧹 Demo data hatao", disabled=not ok):
            clear_all()
            set_meta("demo", "0")
            st.success("Done. Ab Stock page se asli dawaiyan add ya CSV import karein.")
            st.rerun()
    else:
        total_rows = q("SELECT (SELECT COUNT(*) FROM medicines)+(SELECT COUNT(*) FROM sales)"
                       "+(SELECT COUNT(*) FROM ledger)", one=True)[0]
        if not LIVE or total_rows == 0:
            st.divider()
            st.subheader("Demo data")
            if LIVE:
                st.caption("Ye button sirf tab nazar aata hai jab app bilkul khali ho, taake asli data safe rahe.")
            if st.button("Demo data load karein"):
                load_demo()
                st.rerun()
