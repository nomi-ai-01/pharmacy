import base64, hmac, io, json, os, zipfile
from datetime import date, timedelta
from urllib.parse import quote
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

BRAND = "Sehat Pharmacy"
TAGLINE = "Sehat ka bharosa"
GREEN, TEAL = "#16845b", "#0f9f9a"
LOGO_SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128"><defs><linearGradient id="g"><stop stop-color="{GREEN}"/><stop offset="1" stop-color="{TEAL}"/></linearGradient></defs><rect x="4" y="4" width="120" height="120" rx="30" fill="url(#g)"/><rect x="53" y="23" width="22" height="82" rx="7" fill="white"/><rect x="23" y="53" width="82" height="22" rx="7" fill="white"/><circle cx="94" cy="94" r="15" fill="#e8fff5" stroke="white" stroke-width="3"/><path d="M87 94l5 5 9-11" fill="none" stroke="{GREEN}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/></svg>"""
LOGO_DATA = "data:image/svg+xml;base64," + base64.b64encode(LOGO_SVG.encode()).decode()
st.set_page_config(page_title="Sehat Pharmacy | V2", page_icon=LOGO_DATA, layout="wide")

def secret(k, default=None):
    try: return st.secrets.get(k, default)
    except Exception: return os.environ.get(k, default)
DB_URL, DB_HOST, APP_PASSWORD = secret("DB_URL"), secret("DB_HOST"), secret("APP_PASSWORD")
LIVE = bool(DB_URL or DB_HOST)
TABLES = ["medicines", "sales", "sale_items", "ledger", "purchases"]

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html,body,[class*="css"]{font-family:Inter,system-ui,sans-serif}
.block-container{padding-top:1.3rem;max-width:1500px}
[data-testid="stSidebar"]{border-right:1px solid rgba(128,145,155,.22)}
.ph-brand{display:flex;align-items:center;gap:12px;padding:8px 2px 18px}.ph-brand img{width:52px;height:52px}.ph-brand strong{font-size:1.1rem}.ph-brand small{display:block;opacity:.7;margin-top:5px}
.ph-card{border:1px solid rgba(128,145,155,.24);border-radius:17px;padding:16px 18px;background:var(--secondary-background-color);box-shadow:0 5px 20px rgba(20,40,50,.05);min-height:108px}
.ph-card .label{font-size:.82rem;opacity:.75;font-weight:600}.ph-card .value{font-size:1.5rem;font-weight:800;margin-top:8px;letter-spacing:-.03em}.ph-card .hint{font-size:.75rem;opacity:.65}
.ph-green{border-top:4px solid #16845b}.ph-teal{border-top:4px solid #0f9f9a}.ph-amber{border-top:4px solid #d99014}.ph-red{border-top:4px solid #dc4c4c}.ph-purple{border-top:4px solid #8b5cf6}
.ph-alert{border-radius:10px;padding:10px 13px;margin:6px 0;border-left:4px solid}.ph-alert-red{background:rgba(220,76,76,.1);border-color:#dc4c4c}.ph-alert-amber{background:rgba(217,144,20,.1);border-color:#d99014}
div.stButton>button,div.stDownloadButton>button{border-radius:11px;min-height:42px;font-weight:600}
@media(max-width:700px){.block-container{padding:.8rem}.ph-card{padding:12px;min-height:94px}.ph-card .value{font-size:1.25rem}}
</style>""", unsafe_allow_html=True)

@st.cache_resource
def pg_engine():
    opts=dict(pool_pre_ping=True,pool_size=3,max_overflow=2,pool_recycle=300)
    if DB_HOST:
        url=URL.create("postgresql+psycopg2",username=str(secret("DB_USER","postgres")),password=str(secret("DB_PASSWORD","")),host=str(DB_HOST),port=int(secret("DB_PORT",5432)),database=str(secret("DB_NAME","postgres")))
        return create_engine(url,**opts)
    url=str(DB_URL).strip().replace("postgres://","postgresql://",1)
    if url.startswith("postgresql://"): url=url.replace("postgresql://","postgresql+psycopg2://",1)
    return create_engine(url,**opts)
@st.cache_resource
def demo_engine():
    return create_engine("sqlite:////tmp/pharmacy_demo_v2.db" if LIVE else "sqlite:///pharmacy.db",connect_args={"check_same_thread":False})
def is_live(): return LIVE and not st.session_state.get("demo_view",False)
def engine(): return pg_engine() if is_live() else demo_engine()
def q(sql,params=None,one=False):
    with engine().connect() as c: rows=c.execute(text(sql),params or {}).fetchall()
    return (rows[0] if rows else None) if one else rows
def df(sql,params=None):
    with engine().connect() as c: return pd.read_sql_query(text(sql),c,params=params or {})
def run(sql,params=None):
    with engine().begin() as c: c.execute(text(sql),params or {})
def meta(k,d=""):
    r=q("SELECT v FROM meta WHERE k=:k",{"k":k},True); return r[0] if r else d
def setmeta(k,v):
    run("INSERT INTO meta(k,v) VALUES(:k,:v) ON CONFLICT(k) DO UPDATE SET v=excluded.v",{"k":k,"v":str(v)})
def setup():
    pg=is_live(); pk="SERIAL PRIMARY KEY" if pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    stmts=[
      "CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY,v TEXT)",
      f"CREATE TABLE IF NOT EXISTS medicines(id {pk},name TEXT,category TEXT,qty INTEGER,cost DOUBLE PRECISION,price DOUBLE PRECISION,expiry TEXT,min_qty INTEGER DEFAULT 10)",
      f"CREATE TABLE IF NOT EXISTS sales(id {pk},day TEXT,customer TEXT,total DOUBLE PRECISION,discount DOUBLE PRECISION,mode TEXT)",
      "CREATE TABLE IF NOT EXISTS sale_items(sale_id INTEGER,med_id INTEGER,name TEXT,qty INTEGER,price DOUBLE PRECISION,cost DOUBLE PRECISION)",
      f"CREATE TABLE IF NOT EXISTS ledger(id {pk},day TEXT,customer TEXT,phone TEXT,amount DOUBLE PRECISION,note TEXT)",
      f"CREATE TABLE IF NOT EXISTS purchases(id {pk},day TEXT,medicine_id INTEGER,medicine_name TEXT,supplier TEXT,qty INTEGER,cost DOUBLE PRECISION,total DOUBLE PRECISION,batch_no TEXT,expiry TEXT)"
    ]
    add={"medicines":{"batch_no":"TEXT","supplier":"TEXT"},"sales":{"phone":"TEXT"},"ledger":{"reference":"TEXT"}}
    with engine().begin() as c:
        for s in stmts:c.execute(text(s))
        for table,cols in add.items():
            if pg:
                for col,typ in cols.items(): c.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {typ}"))
            else:
                have={r[1] for r in c.execute(text(f"PRAGMA table_info({table})")).fetchall()}
                for col,typ in cols.items():
                    if col not in have:c.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typ}"))
    if not meta("init"):
        for k,v in {"shop":BRAND,"tagline":TAGLINE,"address":"","phone":"","low_stock":"10","currency":"Rs","init":"1"}.items():setmeta(k,v)
        if not pg: seed_demo()
def seed_demo():
    if q("SELECT COUNT(*) FROM medicines",one=True)[0]: return
    today=date.today()
    rows=[("Panadol 500mg","Painkiller",120,8,12,400),("Brufen 400mg","Painkiller",80,10,15,300),("Disprin","Painkiller",6,4,6,25),("Augmentin 625mg","Antibiotic",40,55,75,500),("Amoxil 500mg","Antibiotic",8,30,42,45),("Flagyl 400mg","Antibiotic",60,12,18,350),("Risek 20mg","Stomach",70,15,22,600),("ORS Sachet","Stomach",100,10,15,20)]
    for n,c,qty,cost,price,days in rows:
        run("INSERT INTO medicines(name,category,qty,cost,price,expiry,min_qty,batch_no,supplier) VALUES(:n,:c,:q,:co,:p,:e,10,'DEMO-01','Demo Supplier')",{"n":n,"c":c,"q":qty,"co":cost,"p":price,"e":str(today+timedelta(days=days))})
    setmeta("demo","1")
def money(v): return f"{meta('currency','Rs')} {float(v or 0):,.2f}"
def logo_html():
    uploaded=meta("logo_data","")
    return f'<img src="{uploaded if uploaded.startswith("data:image/") else LOGO_DATA}" alt="logo"/>'
def wa_link(phone,message):
    digits="".join(x for x in str(phone or "") if x.isdigit())
    if digits.startswith("0") and len(digits)>=10:digits="92"+digits[1:]
    return f"https://wa.me/{digits}?text={quote(message)}" if digits else ""
def bill_text(sid):
    s=q("SELECT day,customer,total,discount,mode,phone FROM sales WHERE id=:i",{"i":int(sid)},True)
    if not s:return ""
    items=q("SELECT name,qty,price FROM sale_items WHERE sale_id=:i",{"i":int(sid)})
    lines=[meta("shop",BRAND),meta("address",""),"Phone: "+meta("phone",""),f"Bill #{sid} | {s[0]}",f"Customer: {s[1]}","-"*34]
    lines += [f"{n} | {qty} x {price:.2f} = {qty*price:.2f}" for n,qty,price in items]
    lines += ["-"*34,f"Discount: {money(s[3])}",f"TOTAL: {money(s[2])} ({s[4]})","Shukriya!"]
    return "\n".join(lines)
def bill_pdf(sid):
    s=q("SELECT day,customer,total,discount,mode FROM sales WHERE id=:i",{"i":int(sid)},True)
    if not s:return b""
    items=q("SELECT name,qty,price FROM sale_items WHERE sale_id=:i",{"i":int(sid)})
    out=io.BytesIO(); doc=SimpleDocTemplate(out,pagesize=A4,leftMargin=18*mm,rightMargin=18*mm,topMargin=15*mm,bottomMargin=15*mm)
    def draw_pdf_logo(canvas, document):
        canvas.saveState()
        x, y = A4[0] - 35*mm, A4[1] - 25*mm
        canvas.setFillColor(colors.HexColor(GREEN))
        canvas.roundRect(x-7*mm, y-7*mm, 14*mm, 14*mm, 3*mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.roundRect(x-1.5*mm, y-5*mm, 3*mm, 10*mm, 1*mm, fill=1, stroke=0)
        canvas.roundRect(x-5*mm, y-1.5*mm, 10*mm, 3*mm, 1*mm, fill=1, stroke=0)
        canvas.restoreState()
    styles=getSampleStyleSheet(); styles.add(ParagraphStyle(name="ShopTitle",parent=styles["Title"],textColor=colors.HexColor(GREEN),alignment=TA_CENTER,fontSize=21))
    styles.add(ParagraphStyle(name="Centered",parent=styles["Normal"],alignment=TA_CENTER,textColor=colors.HexColor("#64748b")))
    story=[Paragraph(meta("shop",BRAND),styles["ShopTitle"]),Paragraph(meta("tagline",TAGLINE),styles["Centered"]),Paragraph(meta("address",""),styles["Centered"]),Paragraph("Phone: "+meta("phone",""),styles["Centered"]),Spacer(1,8*mm),Paragraph(f"<b>Bill #{sid}</b> &nbsp; Date: {s[0]} &nbsp; Customer: {s[1]}",styles["Normal"]),Spacer(1,4*mm)]
    data=[["Dawai","Qty","Rate","Total"]]+[[str(n),str(qty),f"{price:,.2f}",f"{qty*price:,.2f}"] for n,qty,price in items]+[["","","Discount",f"{s[3]:,.2f}"],["","","Grand Total",f"{s[2]:,.2f}"]]
    t=Table(data,colWidths=[85*mm,20*mm,30*mm,35*mm],repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor(GREEN)),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.4,colors.HexColor("#d8e2e8")),("ALIGN",(1,1),(-1,-1),"RIGHT"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f3faf7")]),("FONTNAME",(2,-1),(-1,-1),"Helvetica-Bold"),("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8)]))
    story += [t,Spacer(1,12*mm),Paragraph("<b>Shukriya! Sehat ka bharosa.</b>",styles["Centered"])]
    doc.build(story, onFirstPage=draw_pdf_logo); return out.getvalue()
def table_filter(data,key):
    if data.empty:st.info("Abhi record mojood nahi.");return
    a,b=st.columns([2,1]); term=a.text_input("🔎 Search",key=key+"_search"); sort=b.selectbox("Sort by",list(data.columns),key=key+"_sort"); asc=st.checkbox("Ascending",True,key=key+"_asc")
    view=data.copy()
    if term:view=view[view.astype(str).apply(lambda col:col.str.contains(term,case=False,regex=False)).any(axis=1)]
    try:view=view.sort_values(sort,ascending=asc,na_position="last")
    except Exception:pass
    st.dataframe(view,hide_index=True)
def card(col,label,value,icon,style,hint=""):
    col.markdown(f'<div class="ph-card {style}"><div class="label">{icon} &nbsp; {label}</div><div class="value">{value}</div><div class="hint">{hint}</div></div>',unsafe_allow_html=True)

try: setup()
except Exception as e:
    st.error("Database connect nahi hua. DB secrets check karein.");st.caption(str(e)[:300]);st.stop()

if not st.session_state.get("demo_view") and not st.session_state.get("auth"):
    if not APP_PASSWORD and LIVE:st.error("Streamlit Secrets mein APP_PASSWORD set karein.");st.stop()
    if APP_PASSWORD:
        st.markdown(f'<div style="max-width:450px;margin:5vh auto 1rem;text-align:center">{logo_html()}<h1>{meta("shop",BRAND)}</h1><p>{meta("tagline",TAGLINE)}</p><h3>Khush aamdeed 👋</h3><p>Apni pharmacy ka record mehfooz rakhein.</p></div>',unsafe_allow_html=True)
        with st.form("login"):
            pw=st.text_input("Password",type="password")
            if st.form_submit_button("🔐 Login karein",type="primary"):
                if hmac.compare_digest(pw.encode(),str(APP_PASSWORD).encode()):st.session_state.auth=True;st.rerun()
                else:st.error("Password ghalat hai.")
        if st.button("👀 Demo dekhein"):st.session_state.demo_view=True;st.rerun()
        st.stop()
    st.session_state.auth=True

shop=meta("shop",BRAND); today=date.today(); st.session_state.setdefault("cart",[])
demo=meta("demo")=="1" or st.session_state.get("demo_view",False)
st.sidebar.markdown(f'<div class="ph-brand">{logo_html()}<div><strong>{shop}</strong><small>{meta("tagline",TAGLINE)}</small></div></div>',unsafe_allow_html=True)
page=st.sidebar.radio("NAVIGATION",["🏠 Dashboard","📦 Stock","🧾 Billing","🛒 Purchase / Restock","📒 Udhaar","📊 Reports","🌙 Daily Closing","⚙️ Settings"])
if demo:st.sidebar.warning("DEMO MODE — sample data")
if st.session_state.get("demo_view"):
    if st.sidebar.button("Demo se bahar"):st.session_state.demo_view=False;st.rerun()
elif APP_PASSWORD and st.sidebar.button("Logout"):st.session_state.auth=False;st.rerun()

if page=="🏠 Dashboard":
    st.title("Dashboard");st.caption(f"Aaj {today.strftime('%d %b %Y')}")
    if demo:st.info("Demo view ka data sample hai.")
    sale=q("SELECT COALESCE(SUM(total),0) FROM sales WHERE day=:d",{"d":str(today)},True)[0]
    udh=q("SELECT COALESCE(SUM(amount),0) FROM ledger",one=True)[0]
    meds=df("SELECT * FROM medicines")
    low=meds[meds.qty<=meds.min_qty.fillna(10)] if not meds.empty else meds
    exdays=pd.to_datetime(meds.expiry,errors="coerce") if not meds.empty else pd.Series(dtype="datetime64[ns]")
    exp=meds[exdays.dt.date<=today+timedelta(days=60)] if not meds.empty else meds
    profit=q("SELECT COALESCE(SUM((i.price-i.cost)*i.qty),0) FROM sale_items i JOIN sales s ON s.id=i.sale_id WHERE s.day=:d",{"d":str(today)},True)[0]-q("SELECT COALESCE(SUM(discount),0) FROM sales WHERE day=:d",{"d":str(today)},True)[0]
    cols=st.columns(5)
    card(cols[0],"Aaj ki sale",money(sale),"💵","ph-green");card(cols[1],"Kam stock",len(low),"📦","ph-amber");card(cols[2],"Expiry alert",len(exp),"⏳","ph-red");card(cols[3],"Total udhaar",money(udh),"📒","ph-purple");card(cols[4],"Aaj ka profit",money(profit),"📈","ph-teal")
    left,right=st.columns(2);start=str(today-timedelta(days=6))
    with left:
        st.subheader("Pichle 7 din ki sale"); ch=df("SELECT day,SUM(total) sale FROM sales WHERE day>=:d GROUP BY day ORDER BY day",{"d":start})
        if not ch.empty:st.bar_chart(ch.set_index("day"))
        else:st.info("Abhi sale nahi.")
    with right:
        st.subheader("Top 5 dawaiyan"); top=df("SELECT i.name,SUM(i.qty) biki FROM sale_items i JOIN sales s ON s.id=i.sale_id WHERE s.day>=:d GROUP BY i.name ORDER BY biki DESC LIMIT 5",{"d":start})
        if not top.empty:st.bar_chart(top.set_index("name"))
        else:st.info("Sale data milne par yahan chart aayega.")
    st.subheader("🚨 Alerts")
    for _,r in meds.iterrows():
        d=pd.to_datetime(r.expiry,errors="coerce"); days=(d.date()-today).days if not pd.isna(d) else None
        if int(r.qty or 0)<=0:st.markdown(f'<div class="ph-alert ph-alert-red">🔴 <b>{r["name"]}</b> — stock khatam</div>',unsafe_allow_html=True)
        elif days is not None and days<0:st.markdown(f'<div class="ph-alert ph-alert-red">🔴 <b>{r["name"]}</b> — expire ho chuki ({r.expiry})</div>',unsafe_allow_html=True)
        elif int(r.qty or 0)<=int(r.min_qty or 10):st.markdown(f'<div class="ph-alert ph-alert-amber">🟠 <b>{r["name"]}</b> — kam stock ({r.qty})</div>',unsafe_allow_html=True)
        elif days is not None and days<=60:st.markdown(f'<div class="ph-alert ph-alert-amber">🟠 <b>{r["name"]}</b> — expiry qareeb ({r.expiry})</div>',unsafe_allow_html=True)

elif page=="📦 Stock":
    st.title("Stock Management"); meds=df("SELECT id,name,category,qty,cost,price,expiry,min_qty,batch_no,supplier FROM medicines")
    if not meds.empty:
        meds["Expiry badge"]=meds.expiry.apply(lambda x:"🔴 Expired" if pd.notna(x) and str(x)<str(today) else ("🟠 60 din mein" if pd.notna(x) and str(x)<=str(today+timedelta(days=60)) else "🟢 Theek"))
        table_filter(meds,"stock")
    with st.expander("➕ Nayi dawai add karein"):
        with st.form("add_med",clear_on_submit=True):
            n=st.text_input("Dawai ka naam *");cat=st.text_input("Category","General");a,b,c=st.columns(3)
            qty=a.number_input("Quantity",0,100000,10);cost=b.number_input("Kharid price",0.,1e7,0.);price=c.number_input("Sale price",0.,1e7,0.)
            a,b,c=st.columns(3);expiry=a.date_input("Expiry",today+timedelta(days=365));mn=b.number_input("Low-stock limit",0,10000,int(meta("low_stock","10") or 10));batch=c.text_input("Batch number");supplier=st.text_input("Supplier")
            if st.form_submit_button("Save dawai",type="primary"):
                if not n.strip():st.error("Dawai ka naam zaroor likhein.")
                else:
                    run("INSERT INTO medicines(name,category,qty,cost,price,expiry,min_qty,batch_no,supplier) VALUES(:n,:c,:q,:co,:p,:e,:m,:b,:s)",{"n":n.strip(),"c":cat,"q":qty,"co":cost,"p":price,"e":str(expiry),"m":mn,"b":batch,"s":supplier});st.success("Dawai save ho gayi.");st.rerun()
    with st.expander("✏️ Edit / Delete"):
        if not meds.empty:
            mid=st.selectbox("Dawai chunein",meds.id.tolist(),format_func=lambda i:f"{meds.loc[meds.id==i,'name'].iloc[0]} (ID {i})");r=meds[meds.id==mid].iloc[0]
            with st.form("edit_med"):
                n=st.text_input("Naam",str(r["name"]));cat=st.text_input("Category",str(r["category"] or ""));a,b,c=st.columns(3)
                qty=a.number_input("Quantity",0,100000,int(r.qty or 0));cost=b.number_input("Cost",0.,1e7,float(r.cost or 0));price=c.number_input("Sale price",0.,1e7,float(r.price or 0))
                a,b,c=st.columns(3);expiry=a.date_input("Expiry",pd.to_datetime(r.expiry,errors="coerce").date() if not pd.isna(pd.to_datetime(r.expiry,errors="coerce")) else today);mn=b.number_input("Low-stock limit",0,10000,int(r.min_qty or 10));batch=c.text_input("Batch",str(r.batch_no or ""));supplier=st.text_input("Supplier",str(r.supplier or ""))
                if st.form_submit_button("Update save"):
                    run("UPDATE medicines SET name=:n,category=:c,qty=:q,cost=:co,price=:p,expiry=:e,min_qty=:m,batch_no=:b,supplier=:s WHERE id=:i",{"n":n,"c":cat,"q":qty,"co":cost,"p":price,"e":str(expiry),"m":mn,"b":batch,"s":supplier,"i":int(mid)});st.rerun()
            if st.button("🗑 Delete selected medicine"):run("DELETE FROM medicines WHERE id=:i",{"i":int(mid)});st.rerun()
    with st.expander("📥 CSV import"):
        st.caption("Required: name,category,qty,cost,price,expiry. Optional: min_qty,batch_no,supplier")
        file=st.file_uploader("CSV file",type="csv")
        if file and st.button("Import CSV"):
            try:
                data=pd.read_csv(file);need={"name","category","qty","cost","price","expiry"}
                if not need.issubset(data.columns):st.error("Required columns: "+", ".join(sorted(need)))
                else:
                    with engine().begin() as c:
                        for _,r in data.iterrows():c.execute(text("INSERT INTO medicines(name,category,qty,cost,price,expiry,min_qty,batch_no,supplier) VALUES(:n,:c,:q,:co,:p,:e,:m,:b,:s)"),{"n":str(r["name"]),"c":str(r["category"]),"q":int(r["qty"]),"co":float(r["cost"]),"p":float(r["price"]),"e":str(r["expiry"])[:10],"m":int(r.get("min_qty",10) if pd.notna(r.get("min_qty",10)) else 10),"b":str(r.get("batch_no","") if pd.notna(r.get("batch_no","")) else ""),"s":str(r.get("supplier","") if pd.notna(r.get("supplier","")) else "")})
                    st.success(f"{len(data)} rows import ho gayin.");st.rerun()
            except Exception as e:st.error(f"CSV import fail: {str(e)[:180]}")

elif page=="🧾 Billing":
    st.title("Billing");meds=df("SELECT id,name,category,qty,cost,price,batch_no FROM medicines WHERE qty>0")
    if meds.empty:st.warning("Stock khali hai.")
    else:
        search=st.text_input("🔎 Barcode / quick search",placeholder="Dawai ka naam ya batch")
        found=meds[meds.astype(str).apply(lambda c:c.str.contains(search,case=False,regex=False)).any(axis=1)] if search else meds
        if not found.empty:
            mid=st.selectbox("Dawai",found.id.tolist(),format_func=lambda i:f"{found.loc[found.id==i,'name'].iloc[0]} | stock {int(found.loc[found.id==i,'qty'].iloc[0])} | {money(found.loc[found.id==i,'price'].iloc[0])}")
            qty=st.number_input("Quantity",1,100000,1)
            if st.button("➕ Cart mein add",type="primary"):
                r=meds[meds.id==mid].iloc[0];used=sum(x["qty"] for x in st.session_state.cart if x["id"]==int(mid))
                if used+qty>int(r.qty):st.error("Itna stock nahi.")
                else:
                    item=next((x for x in st.session_state.cart if x["id"]==int(mid)),None)
                    if item:item["qty"]+=int(qty)
                    else:st.session_state.cart.append({"id":int(mid),"name":r["name"],"qty":int(qty),"price":float(r.price),"cost":float(r.cost)})
                    st.rerun()
        else:st.warning("Dawai nahi mili.")
    cart=st.session_state.cart
    if cart:
        st.subheader("Cart");cd=pd.DataFrame(cart);cd["total"]=cd.qty*cd.price;st.dataframe(cd[["name","qty","price","total"]],hide_index=True);sub=float(cd.total.sum())
        with st.form("checkout"):
            a,b,c=st.columns(3);customer=a.text_input("Customer","Walk-in");phone=b.text_input("Phone / WhatsApp");discount=c.number_input("Discount",0.,float(sub),0.);mode=st.radio("Payment",["Cash","Udhaar"],horizontal=True)
            st.markdown(f"### Total: {money(sub-discount)}");checkout=st.form_submit_button("✅ Bill banayein",type="primary")
        if st.button("Cart khali karein"):st.session_state.cart=[];st.rerun()
        if checkout:
            if mode=="Udhaar" and customer.strip().lower() in ("","walk-in"):st.error("Udhaar ke liye customer naam likhein.")
            else:
                try:
                    with engine().begin() as c:
                        sid=c.execute(text("INSERT INTO sales(day,customer,total,discount,mode,phone) VALUES(:d,:c,:t,:di,:m,:ph) RETURNING id"),{"d":str(today),"c":customer.strip() or "Walk-in","t":sub-discount,"di":discount,"m":mode,"ph":phone}).scalar()
                        for x in cart:
                            upd=c.execute(text("UPDATE medicines SET qty=qty-:q WHERE id=:i AND qty>=:q"),{"q":x["qty"],"i":x["id"]})
                            if upd.rowcount!=1:raise ValueError(x["name"])
                            c.execute(text("INSERT INTO sale_items(sale_id,med_id,name,qty,price,cost) VALUES(:s,:m,:n,:q,:p,:co)"),{"s":sid,"m":x["id"],"n":x["name"],"q":x["qty"],"p":x["price"],"co":x["cost"]})
                        if mode=="Udhaar":c.execute(text("INSERT INTO ledger(day,customer,phone,amount,note) VALUES(:d,:c,:p,:a,:n)"),{"d":str(today),"c":customer.strip(),"p":phone,"a":sub-discount,"n":f"Bill #{sid}"})
                    st.session_state.last_bill_id=int(sid);st.session_state.cart=[];st.rerun()
                except ValueError as e:st.error(f"{e} ka stock kam ho chuka hai.")
                except Exception as e:st.error(f"Bill save nahi hua: {str(e)[:180]}")
    if st.session_state.get("last_bill_id"):
        sid=st.session_state.last_bill_id;bt=bill_text(sid);st.success(f"Bill #{sid} tayyar hai.");st.code(bt)
        st.download_button("⬇️ PDF bill download",bill_pdf(sid),f"bill_{sid}.pdf","application/pdf")
        st.download_button("Text bill download",bt,f"bill_{sid}.txt","text/plain")
        ph=q("SELECT phone FROM sales WHERE id=:i",{"i":sid},True)[0];link=wa_link(ph,bt)
        if link:st.link_button("🟢 WhatsApp par bill share",link)
        else:st.caption("WhatsApp share ke liye phone number add karein.")

elif page=="🛒 Purchase / Restock":
    st.title("Purchase & Restock");meds=df("SELECT id,name,qty,cost,expiry,batch_no,supplier FROM medicines")
    if not meds.empty:
        with st.form("purchase",clear_on_submit=True):
            mid=st.selectbox("Dawai",meds.id.tolist(),format_func=lambda i:meds.loc[meds.id==i,"name"].iloc[0]);a,b,c=st.columns(3)
            supplier=a.text_input("Supplier");qty=b.number_input("Quantity add",1,100000,10);cost=c.number_input("Per unit cost",0.,1e7,0.);a,b=st.columns(2);batch=a.text_input("Batch number");expiry=b.date_input("Expiry",today+timedelta(days=365))
            if st.form_submit_button("Purchase save + stock barhayein",type="primary"):
                r=meds[meds.id==mid].iloc[0]
                with engine().begin() as c:
                    c.execute(text("UPDATE medicines SET qty=qty+:q,cost=:cost,batch_no=:b,supplier=:s,expiry=:e WHERE id=:i"),{"q":qty,"cost":cost,"b":batch or r.batch_no,"s":supplier or r.supplier,"e":str(expiry),"i":int(mid)})
                    c.execute(text("INSERT INTO purchases(day,medicine_id,medicine_name,supplier,qty,cost,total,batch_no,expiry) VALUES(:d,:i,:n,:s,:q,:c,:t,:b,:e)"),{"d":str(today),"i":int(mid),"n":r["name"],"s":supplier,"q":qty,"c":cost,"t":qty*cost,"b":batch,"e":str(expiry)})
                st.success("Purchase save ho gayi.");st.rerun()
    st.subheader("Purchase history");table_filter(df("SELECT id,day,medicine_name,supplier,qty,cost,total,batch_no,expiry FROM purchases ORDER BY id DESC"),"purchases")

elif page=="📒 Udhaar":
    st.title("Udhaar Register");bal=df("SELECT customer,MAX(phone) phone,SUM(amount) baqaya FROM ledger GROUP BY customer HAVING ABS(SUM(amount))>0.5")
    table_filter(bal,"ledger")
    if not bal.empty:
        cust=st.selectbox("Customer",bal.customer,key="statement_customer");r=bal[bal.customer==cust].iloc[0]
        msg=f"Assalam-o-alaikum {cust}, aap ka pharmacy ka baqaya {money(r['baqaya'])} hai. Meherbani farma kar adaigi kar dein. Shukriya — {shop}"
        link=wa_link(r.phone,msg)
        if link:st.link_button("🟢 WhatsApp reminder",link)
        else:st.info("Customer ka phone number available nahi.")
        statement=df("SELECT day,customer,phone,amount,note FROM ledger WHERE customer=:c ORDER BY day,id",{"c":cust});st.dataframe(statement,hide_index=True)
        st.download_button("Customer statement CSV",statement.to_csv(index=False).encode("utf-8-sig"),f"statement_{cust.replace(' ','_')}.csv","text/csv")
        with st.form("payment"):
            who=st.selectbox("Payment kis se mili",bal.customer,key="paycust");amt=st.number_input("Wasool raqam",1.,1e8,100.)
            if st.form_submit_button("Payment save"):run("INSERT INTO ledger(day,customer,phone,amount,note) VALUES(:d,:c,'',:a,'Payment mili')",{"d":str(today),"c":who,"a":-amt});st.rerun()
    with st.form("manual_credit"):
        a,b,c=st.columns(3);name=a.text_input("Naya customer");phone=b.text_input("Phone");amount=c.number_input("Udhaar raqam",1.,1e8,100.)
        if st.form_submit_button("Udhaar add") and name.strip():run("INSERT INTO ledger(day,customer,phone,amount,note) VALUES(:d,:c,:p,:a,'Udhaar')",{"d":str(today),"c":name.strip(),"p":phone,"a":amount});st.rerun()

elif page=="📊 Reports":
    st.title("Reports & Bill History");period=st.selectbox("Muddat",["Pichle 7 din","Pichle 30 din","Pichle 90 din","Sab"],1);days={"Pichle 7 din":7,"Pichle 30 din":30,"Pichle 90 din":90,"Sab":36500}[period];start=str(today-timedelta(days=days))
    sales=df("SELECT day,SUM(total) sale FROM sales WHERE day>=:d GROUP BY day ORDER BY day",{"d":start});gross=q("SELECT COALESCE(SUM((i.price-i.cost)*i.qty),0) FROM sale_items i JOIN sales s ON s.id=i.sale_id WHERE s.day>=:d",{"d":start},True)[0];discount=q("SELECT COALESCE(SUM(discount),0) FROM sales WHERE day>=:d",{"d":start},True)[0]
    a,b,c=st.columns(3);a.metric("Kul sale",money(sales.sale.sum() if not sales.empty else 0));b.metric("Andazati profit",money(gross-discount));c.metric("Bills",q("SELECT COUNT(*) FROM sales WHERE day>=:d",{"d":start},True)[0])
    if not sales.empty:st.line_chart(sales.set_index("day"))
    st.subheader("Top medicines");table_filter(df("SELECT i.name,SUM(i.qty) biki_quantity,SUM(i.qty*i.price) sale_value FROM sale_items i JOIN sales s ON s.id=i.sale_id WHERE s.day>=:d GROUP BY i.name ORDER BY biki_quantity DESC",{"d":start}),"topmed")
    st.subheader("Bill history");hist=df("SELECT id,day,customer,total,discount,mode,phone FROM sales ORDER BY id DESC");table_filter(hist,"history")
    if not hist.empty:
        sid=st.selectbox("Bill number",hist.id.tolist());st.code(bill_text(sid));st.download_button("PDF bill",bill_pdf(sid),f"bill_{sid}.pdf","application/pdf")

elif page=="🌙 Daily Closing":
    st.title("Daily Closing Report")
    cash=q("SELECT COALESCE(SUM(total),0) FROM sales WHERE day=:d AND mode='Cash'",{"d":str(today)},True)[0];credit=q("SELECT COALESCE(SUM(total),0) FROM sales WHERE day=:d AND mode='Udhaar'",{"d":str(today)},True)[0];received=q("SELECT COALESCE(-SUM(amount),0) FROM ledger WHERE day=:d AND amount<0",{"d":str(today)},True)[0]
    profit=q("SELECT COALESCE(SUM((i.price-i.cost)*i.qty),0) FROM sale_items i JOIN sales s ON s.id=i.sale_id WHERE s.day=:d",{"d":str(today)},True)[0]-q("SELECT COALESCE(SUM(discount),0) FROM sales WHERE day=:d",{"d":str(today)},True)[0]
    cols=st.columns(4);card(cols[0],"Cash sale",money(cash),"💵","ph-green");card(cols[1],"Udhaar diya",money(credit),"📒","ph-amber");card(cols[2],"Payment received",money(received),"🤝","ph-teal");card(cols[3],"Andazati profit",money(profit),"📈","ph-purple")
    close=pd.DataFrame([{"Date":str(today),"Cash Sale":cash,"Udhaar Given":credit,"Payments Received":received,"Estimated Profit":profit}]);st.dataframe(close,hide_index=True);st.download_button("Daily closing CSV",close.to_csv(index=False).encode(),f"closing_{today}.csv","text/csv")

else:
    st.title("Settings")
    with st.form("settings"):
        name=st.text_input("Pharmacy ka naam",meta("shop",BRAND));tag=st.text_input("Tagline",meta("tagline",TAGLINE));address=st.text_area("Shop address",meta("address",""));phone=st.text_input("Shop phone",meta("phone",""));low=st.number_input("Default low-stock alert",0,100000,int(meta("low_stock","10") or 10));currency=st.text_input("Currency symbol",meta("currency","Rs"));logo=st.file_uploader("Logo upload (PNG/JPG/SVG)",type=["png","jpg","jpeg","svg"])
        if st.form_submit_button("Settings save karein",type="primary"):
            for k,v in {"shop":name.strip() or BRAND,"tagline":tag,"address":address,"phone":phone,"low_stock":low,"currency":currency or "Rs"}.items():setmeta(k,v)
            if logo:
                mime="image/svg+xml" if logo.name.lower().endswith(".svg") else ("image/png" if logo.name.lower().endswith(".png") else "image/jpeg")
                setmeta("logo_data",f"data:{mime};base64,{base64.b64encode(logo.getvalue()).decode()}")
            st.success("Settings save ho gayi.");st.rerun()
    st.markdown("### Logo preview");st.markdown(logo_html(),unsafe_allow_html=True);st.divider();st.subheader("💾 Backup & Restore")
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as z:
        for t in TABLES:z.writestr(f"{t}.csv",df(f"SELECT * FROM {t}").to_csv(index=False))
        z.writestr("meta.csv",df("SELECT k,v FROM meta").to_csv(index=False));z.writestr("backup_info.json",json.dumps({"format":1,"date":str(today)},indent=2))
    st.download_button("⬇️ Backup ZIP download",buf.getvalue(),f"pharmacy_backup_{today}.zip","application/zip")
    archive=st.file_uploader("Backup ZIP restore",type="zip",key="restore");confirm=st.checkbox("Restore mojooda data ko replace karega — main confirm karta/karti hoon.")
    if archive and st.button("⚠️ Restore backup",disabled=not confirm):
        try:
            with zipfile.ZipFile(io.BytesIO(archive.getvalue())) as z:
                payload={n[:-4]:pd.read_csv(z.open(n)) for n in z.namelist() if n.endswith(".csv") and n[:-4] in TABLES+["meta"]}
            if not payload:st.error("ZIP mein backup tables nahi milin.")
            else:
                with engine().begin() as c:
                    for t,data in payload.items():
                        c.execute(text(f"DELETE FROM {t}"))
                        if not data.empty:
                            allowed_columns = {
                                "medicines": {"id","name","category","qty","cost","price","expiry","min_qty","batch_no","supplier"},
                                "sales": {"id","day","customer","total","discount","mode","phone"},
                                "sale_items": {"sale_id","med_id","name","qty","price","cost"},
                                "ledger": {"id","day","customer","phone","amount","note","reference"},
                                "purchases": {"id","day","medicine_id","medicine_name","supplier","qty","cost","total","batch_no","expiry"},
                                "meta": {"k","v"}
                            }
                            cols=list(data.columns)
                            if not set(cols).issubset(allowed_columns[t]): raise ValueError(f"Backup columns invalid for {t}")
                            sql=f"INSERT INTO {t} ({','.join(cols)}) VALUES ({','.join(':'+x for x in cols)})"
                            for _,r in data.iterrows():
                                vals={col:(None if pd.isna(r[col]) else r[col].item() if hasattr(r[col],"item") else r[col]) for col in cols};c.execute(text(sql),vals)
                st.success("Restore complete.");st.rerun()
        except Exception as e:st.error(f"Restore fail: {str(e)[:200]}")
    if demo and st.button("Demo data clear karein"):
        with engine().begin() as c:
            for t in ["sale_items","sales","ledger","purchases","medicines"]:c.execute(text(f"DELETE FROM {t}"))
        setmeta("demo","0");st.success("Demo data clear ho gaya.");st.rerun()
