import sqlite3, random
from datetime import date, timedelta
import pandas as pd
import streamlit as st

DB = "pharmacy.db"
st.set_page_config(page_title="Pharmacy Manager", page_icon="💊", layout="wide")


def con():
    return sqlite3.connect(DB)


def q(sql, params=(), one=False):
    with con() as c:
        cur = c.execute(sql, params)
        rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def df(sql, params=()):
    with con() as c:
        return pd.read_sql_query(sql, c, params=params)


def run(sql, params=()):
    with con() as c:
        c.execute(sql, params)


def get_meta(k, d=""):
    r = q("SELECT v FROM meta WHERE k=?", (k,), one=True)
    return r[0] if r else d


def set_meta(k, v):
    run("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", (k, v))


def init():
    with con() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE IF NOT EXISTS medicines(
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, category TEXT,
            qty INTEGER, cost REAL, price REAL, expiry TEXT, min_qty INTEGER DEFAULT 10);
        CREATE TABLE IF NOT EXISTS sales(
            id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, customer TEXT,
            total REAL, discount REAL, mode TEXT);
        CREATE TABLE IF NOT EXISTS sale_items(
            sale_id INTEGER, med_id INTEGER, name TEXT, qty INTEGER, price REAL, cost REAL);
        CREATE TABLE IF NOT EXISTS ledger(
            id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, customer TEXT,
            phone TEXT, amount REAL, note TEXT);
        """)
    if get_meta("init") != "1":
        load_demo()


def clear_all():
    with con() as c:
        for t in ("medicines", "sales", "sale_items", "ledger"):
            c.execute(f"DELETE FROM {t}")


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
    with con() as c:
        for (n, cat, qt, cost, pr), d in zip(meds, expiry_days):
            c.execute("INSERT INTO medicines(name,category,qty,cost,price,expiry,min_qty) VALUES(?,?,?,?,?,?,10)",
                      (n, cat, qt, cost, pr, str(today + timedelta(days=d))))
        names = ["Ahmed", "Bilal", "Sara Baji", "Chacha Rafiq", "Zainab", "Usman", "Walk-in"]
        for back in range(7, -1, -1):
            day = str(today - timedelta(days=back))
            for _ in range(random.randint(4, 9)):
                items = random.sample(meds, random.randint(1, 3))
                total, rows = 0, []
                for (n, cat, qt, cost, pr) in items:
                    k = random.randint(1, 3)
                    total += pr * k
                    rows.append((n, k, pr, cost))
                cur = c.execute("INSERT INTO sales(day,customer,total,discount,mode) VALUES(?,?,?,?,?)",
                                (day, random.choice(names), total, 0, "Cash"))
                for (n, k, pr, cost) in rows:
                    c.execute("INSERT INTO sale_items VALUES(?,?,?,?,?,?)", (cur.lastrowid, 0, n, k, pr, cost))
        for cust, ph, amt in [("Chacha Rafiq", "0300-1111111", 1850), ("Sara Baji", "0301-2222222", 920),
                              ("Usman", "0302-3333333", 2400)]:
            c.execute("INSERT INTO ledger(day,customer,phone,amount,note) VALUES(?,?,?,?,?)",
                      (str(today - timedelta(days=5)), cust, ph, amt, "Udhaar dawai"))
        c.execute("INSERT INTO ledger(day,customer,phone,amount,note) VALUES(?,?,?,?,?)",
                  (str(today - timedelta(days=2)), "Usman", "0302-3333333", -1000, "Payment mili"))
    set_meta("demo", "1")
    set_meta("init", "1")
    set_meta("shop", "Demo Pharmacy")


init()
demo = get_meta("demo") == "1"
shop = get_meta("shop", "My Pharmacy")
st.session_state.setdefault("cart", [])

# ---------------- Sidebar ----------------
st.sidebar.title(f"💊 {shop}")
page = st.sidebar.radio("Menu", ["🏠 Dashboard", "📦 Stock", "🧾 Billing", "📒 Udhaar", "📊 Reports", "⚙️ Settings"])
if demo:
    st.sidebar.warning("DEMO MODE: ye sara data nakli hai.")

today = date.today()


def money(x):
    return f"Rs {x:,.0f}"


# ---------------- Dashboard ----------------
if page == "🏠 Dashboard":
    st.title("Dashboard")
    if demo:
        st.info("Ye demo data hai. Pasand aane par Settings se asli data shuru karein.")
    t_sale = q("SELECT COALESCE(SUM(total),0) FROM sales WHERE day=?", (str(today),), one=True)[0]
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
    st.dataframe(low[["name", "qty", "min_qty"]], use_container_width=True, hide_index=True)
    st.subheader("⏰ Jald expire hone wali")
    st.dataframe(exp[["name", "qty", "expiry"]], use_container_width=True, hide_index=True)

# ---------------- Stock ----------------
elif page == "📦 Stock":
    st.title("Stock")
    meds = df("SELECT id,name,category,qty,cost,price,expiry,min_qty FROM medicines ORDER BY name")
    search = st.text_input("🔍 Dawai search karein")
    view = meds[meds.name.str.contains(search, case=False)] if search else meds
    st.dataframe(view, use_container_width=True, hide_index=True)

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
                run("INSERT INTO medicines(name,category,qty,cost,price,expiry,min_qty) VALUES(?,?,?,?,?,?,?)",
                    (n.strip(), cat, qty, cost, price, str(exp), mn))
                st.success("Add ho gayi")
                st.rerun()

    with st.expander("✏️ Edit / Restock / Delete"):
        if len(meds):
            pick = st.selectbox("Dawai chunein", meds.id, format_func=lambda i: meds.set_index("id").loc[i, "name"])
            r = meds.set_index("id").loc[pick]
            a, b, c_ = st.columns(3)
            nq = a.number_input("Quantity", 0, 100000, int(r.qty), key="eq")
            nc = b.number_input("Kharid price", 0.0, 1e6, float(r.cost), key="ec")
            npz = c_.number_input("Bechne ki price", 0.0, 1e6, float(r.price), key="ep")
            ne = st.date_input("Expiry", date.fromisoformat(r.expiry), key="ee")
            x, y = st.columns(2)
            if x.button("Update save karein"):
                run("UPDATE medicines SET qty=?,cost=?,price=?,expiry=? WHERE id=?", (nq, nc, npz, str(ne), int(pick)))
                st.rerun()
            if y.button("🗑 Delete karein"):
                run("DELETE FROM medicines WHERE id=?", (int(pick),))
                st.rerun()

    with st.expander("📥 CSV se stock import karein"):
        st.caption("Columns: name,category,qty,cost,price,expiry,min_qty (expiry format: 2027-12-31)")
        f = st.file_uploader("CSV file", type="csv")
        if f and st.button("Import karein"):
            d = pd.read_csv(f)
            if "min_qty" not in d:
                d["min_qty"] = 10
            with con() as c:
                for _, r in d.iterrows():
                    c.execute("INSERT INTO medicines(name,category,qty,cost,price,expiry,min_qty) VALUES(?,?,?,?,?,?,?)",
                              (r["name"], r["category"], int(r["qty"]), float(r["cost"]), float(r["price"]),
                               str(r["expiry"]), int(r["min_qty"])))
            st.success("Import ho gaya")
            st.rerun()

# ---------------- Billing ----------------
elif page == "🧾 Billing":
    st.title("Billing")
    meds = df("SELECT id,name,qty,price,cost FROM medicines WHERE qty>0 ORDER BY name")
    if meds.empty:
        st.warning("Stock khali hai.")
    else:
        a, b, c_ = st.columns([3, 1, 1])
        mid = a.selectbox("Dawai", meds.id, format_func=lambda i: f"{meds.set_index('id').loc[i,'name']} "
                          f"(stock {meds.set_index('id').loc[i,'qty']}, Rs {meds.set_index('id').loc[i,'price']:.0f})")
        k = b.number_input("Qty", 1, 1000, 1)
        if c_.button("➕ Add", use_container_width=True):
            r = meds.set_index("id").loc[mid]
            used = sum(i["qty"] for i in st.session_state.cart if i["id"] == mid)
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
        st.dataframe(cd[["name", "qty", "price", "total"]], use_container_width=True, hide_index=True)
        sub = cd.total.sum()
        a, b, c_ = st.columns(3)
        cust = a.text_input("Customer ka naam", "Walk-in")
        phone = b.text_input("Phone (udhaar ke liye)")
        disc = c_.number_input("Discount (Rs)", 0.0, float(sub), 0.0)
        mode = st.radio("Payment", ["Cash", "Udhaar"], horizontal=True)
        total = sub - disc
        st.subheader(f"Total: {money(total)}")
        x, y = st.columns(2)
        if y.button("❌ Cart khali karein"):
            st.session_state.cart = []
            st.rerun()
        if x.button("✅ Bill banayein", type="primary"):
            with con() as c:
                cur = c.execute("INSERT INTO sales(day,customer,total,discount,mode) VALUES(?,?,?,?,?)",
                                (str(today), cust, total, disc, mode))
                sid = cur.lastrowid
                for i in cart:
                    c.execute("INSERT INTO sale_items VALUES(?,?,?,?,?,?)",
                              (sid, i["id"], i["name"], i["qty"], i["price"], i["cost"]))
                    c.execute("UPDATE medicines SET qty=qty-? WHERE id=?", (i["qty"], i["id"]))
                if mode == "Udhaar":
                    c.execute("INSERT INTO ledger(day,customer,phone,amount,note) VALUES(?,?,?,?,?)",
                              (str(today), cust, phone, total, f"Bill #{sid}"))
            lines = [f"{shop}", f"Bill #{sid}   {today}", f"Customer: {cust}", "-" * 32]
            for i in cart:
                lines.append(f"{i['name'][:18]:18} {i['qty']:>3} x {i['price']:.0f} = {i['qty']*i['price']:.0f}")
            lines += ["-" * 32, f"Discount: {disc:.0f}", f"TOTAL: {total:.0f} ({mode})", "Shukriya!"]
            st.session_state.last_bill = "\n".join(lines)
            st.session_state.cart = []
            st.rerun()
    if "last_bill" in st.session_state:
        st.success("Bill ban gaya")
        st.code(st.session_state.last_bill)
        st.download_button("⬇️ Bill download", st.session_state.last_bill, "bill.txt")

# ---------------- Udhaar ----------------
elif page == "📒 Udhaar":
    st.title("Udhaar Register")
    bal = df("""SELECT customer, MAX(phone) AS phone, SUM(amount) AS baqaya FROM ledger
                GROUP BY customer HAVING SUM(amount)<>0 ORDER BY baqaya DESC""")
    st.dataframe(bal, use_container_width=True, hide_index=True)
    st.subheader("Payment wasool karein")
    if len(bal):
        with st.form("pay"):
            who = st.selectbox("Customer", bal.customer)
            amt = st.number_input("Raqam", 1.0, 1e7, 100.0)
            if st.form_submit_button("Save"):
                run("INSERT INTO ledger(day,customer,phone,amount,note) VALUES(?,?,?,?,?)",
                    (str(today), who, "", -amt, "Payment mili"))
                st.rerun()
        r = bal[bal.customer == who].iloc[0] if len(bal) else None
    st.subheader("Naya udhaar manually likhein")
    with st.form("newu", clear_on_submit=True):
        a, b, c_ = st.columns(3)
        n = a.text_input("Naam")
        p = b.text_input("Phone")
        m = c_.number_input("Raqam", 1.0, 1e7, 100.0)
        if st.form_submit_button("Add") and n.strip():
            run("INSERT INTO ledger(day,customer,phone,amount,note) VALUES(?,?,?,?,?)",
                (str(today), n.strip(), p, m, "Udhaar"))
            st.rerun()

# ---------------- Reports ----------------
elif page == "📊 Reports":
    st.title("Reports")
    s = df("SELECT day, SUM(total) AS sale FROM sales GROUP BY day ORDER BY day")
    if s.empty:
        st.info("Abhi koi sale nahi.")
    else:
        st.subheader("Roz ki sale")
        st.bar_chart(s.set_index("day"))
        prof = df("""SELECT s.day, SUM((i.price-i.cost)*i.qty) - SUM(DISTINCT s.discount) AS profit
                     FROM sale_items i JOIN sales s ON s.id=i.sale_id GROUP BY s.day ORDER BY s.day""")
        st.subheader("Munafa (profit)")
        st.line_chart(prof.set_index("day"))
        st.subheader("Sab se zyada bikne wali dawaiyan")
        top = df("SELECT name, SUM(qty) AS bika FROM sale_items GROUP BY name ORDER BY bika DESC LIMIT 10")
        st.dataframe(top, use_container_width=True, hide_index=True)
        st.download_button("⬇️ Sales CSV", df("SELECT * FROM sales").to_csv(index=False), "sales.csv")

# ---------------- Settings ----------------
else:
    st.title("Settings")
    name = st.text_input("Pharmacy ka naam", shop)
    if st.button("Naam save karein"):
        set_meta("shop", name)
        st.rerun()
    st.divider()
    st.subheader("Demo se asli data par jayein")
    st.write("Is se demo ki sari dawaiyan, sales aur udhaar delete ho jayengi aur app khali ho jayegi.")
    ok = st.checkbox("Haan, demo data delete karna hai")
    if st.button("🧹 Demo data hatao", disabled=not ok):
        clear_all()
        set_meta("demo", "0")
        st.success("Done. Ab Stock page se asli dawaiyan add ya CSV import karein.")
        st.rerun()
    if not demo and st.button("Demo data dobara load karein"):
        load_demo()
        st.rerun()
