from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from functools import wraps
import sqlite3, os, uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = 'foodbachao-secret-key-2026'
app.config['DATABASE'] = 'foodbachao.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# ── DB ──────────────────────────────────────────────────────────────────────
def get_db():
    db = sqlite3.connect(app.config['DATABASE'])
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    db.executescript('''
    CREATE TABLE IF NOT EXISTS user (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        phone TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT DEFAULT 'customer',
        city TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS restaurant (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        address TEXT NOT NULL,
        city TEXT NOT NULL,
        latitude REAL,
        longitude REAL,
        phone TEXT,
        cuisine_type TEXT,
        image TEXT DEFAULT 'default.jpg',
        upi_id TEXT,
        is_approved INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1,
        rating REAL DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(user_id) REFERENCES user(id)
    );
    CREATE TABLE IF NOT EXISTS food_listing (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        restaurant_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        original_price REAL NOT NULL,
        discounted_price REAL NOT NULL,
        quantity_available INTEGER NOT NULL,
        quantity_remaining INTEGER NOT NULL,
        image TEXT DEFAULT 'default_food.jpg',
        pickup_start TEXT NOT NULL,
        pickup_end TEXT NOT NULL,
        food_type TEXT DEFAULT 'veg',
        is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(restaurant_id) REFERENCES restaurant(id)
    );
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_number TEXT UNIQUE NOT NULL,
        user_id INTEGER NOT NULL,
        listing_id INTEGER NOT NULL,
        quantity INTEGER DEFAULT 1,
        total_amount REAL NOT NULL,
        payment_method TEXT DEFAULT 'UPI',
        payment_status TEXT DEFAULT 'pending',
        order_status TEXT DEFAULT 'confirmed',
        upi_transaction_id TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(user_id) REFERENCES user(id),
        FOREIGN KEY(listing_id) REFERENCES food_listing(id)
    );
    ''')
    db.commit()
    db.close()

def seed_data():
    db = get_db()
    if db.execute('SELECT COUNT(*) FROM user').fetchone()[0] > 0:
        db.close()
        return
    # Admin
    db.execute('INSERT INTO user(name,email,phone,password_hash,role,city) VALUES(?,?,?,?,?,?)',
               ('Avanish','avanish1202','9000000000',generate_password_hash('savefood'),'admin','Mumbai'))
    # Restaurant user
    db.execute('INSERT INTO user(name,email,phone,password_hash,role,city) VALUES(?,?,?,?,?,?)',
               ('Ravi Sharma','ravi@demo.com','9111111111',generate_password_hash('demo123'),'restaurant','Mumbai'))
    db.commit()
    rest_user = db.execute("SELECT id FROM user WHERE email='ravi@demo.com'").fetchone()
    db.execute('''INSERT INTO restaurant(user_id,name,description,address,city,phone,cuisine_type,upi_id,latitude,longitude,is_approved)
                  VALUES(?,?,?,?,?,?,?,?,?,?,1)''',
               (rest_user['id'],'Sharma Bhojnalaya','Authentic home-style North Indian food since 1995',
                'Near Dadar Station, Mumbai','Mumbai','9111111111','North Indian','sharma@upi',19.0176,72.8562))
    db.commit()
    rest = db.execute("SELECT id FROM restaurant WHERE name='Sharma Bhojnalaya'").fetchone()
    now = datetime.utcnow()
    end = now + timedelta(hours=3)
    end2 = now + timedelta(hours=2)
    for title, desc, op, dp, qty, ft, end_t in [
        ('Dal Makhani + Rice (2 portions)','Fresh dal makhani with basmati rice',180,70,5,'veg',end),
        ('Paneer Butter Masala + 3 Rotis','Creamy paneer curry with fresh rotis',220,90,4,'veg',end2),
        ('Chicken Curry + Rice Combo','Spicy homestyle chicken curry with steam rice',280,110,3,'nonveg',end2),
        ('Veg Thali (Full Meal)','Complete meal with dal, sabzi, roti, rice, dessert',250,95,6,'veg',end),
        ('Rajma Chawal + Salad','Classic rajma rice with fresh salad',160,65,4,'veg',end2),
    ]:
        db.execute('''INSERT INTO food_listing(restaurant_id,title,description,original_price,discounted_price,
                      quantity_available,quantity_remaining,pickup_start,pickup_end,food_type)
                      VALUES(?,?,?,?,?,?,?,?,?,?)''',
                   (rest['id'],title,desc,op,dp,qty,qty,now.strftime('%Y-%m-%d %H:%M:%S'),end_t.strftime('%Y-%m-%d %H:%M:%S'),ft))
    db.commit()
    db.close()
    print('✅ Seed data added!')

# ── HELPERS ─────────────────────────────────────────────────────────────────
def discount_percent(op, dp):
    return int((1 - dp/op)*100) if op > 0 else 0

def fmt_time(s):
    try: return datetime.strptime(s,'%Y-%m-%d %H:%M:%S').strftime('%I:%M %p')
    except: return s

def fmt_date(s):
    try: return datetime.strptime(s,'%Y-%m-%d %H:%M:%S').strftime('%d %b %Y')
    except: return s

app.jinja_env.globals.update(discount_percent=discount_percent, fmt_time=fmt_time, fmt_date=fmt_date)

def is_available(listing):
    now = datetime.utcnow()
    try:
        end = datetime.strptime(listing['pickup_end'],'%Y-%m-%d %H:%M:%S')
        return listing['is_active'] and listing['quantity_remaining'] > 0 and now <= end
    except: return False

def allowed_file(fn):
    return '.' in fn and fn.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS

def save_image(f):
    if f and f.filename and allowed_file(f.filename):
        fn = str(uuid.uuid4())+'_'+secure_filename(f.filename)
        f.save(os.path.join(app.config['UPLOAD_FOLDER'],fn))
        return fn
    return None

def login_required(f):
    @wraps(f)
    def d(*a,**kw):
        if 'user_id' not in session:
            flash('Please login to continue.','warning')
            return redirect(url_for('login'))
        return f(*a,**kw)
    return d

def restaurant_required(f):
    @wraps(f)
    def d(*a,**kw):
        if session.get('role') not in ['restaurant','admin']:
            flash('Restaurant access required.','danger')
            return redirect(url_for('home'))
        return f(*a,**kw)
    return d

def admin_required(f):
    @wraps(f)
    def d(*a,**kw):
        if session.get('role') != 'admin':
            flash('Admin access required.','danger')
            return redirect(url_for('home'))
        return f(*a,**kw)
    return d

# ── ROUTES ──────────────────────────────────────────────────────────────────
@app.route('/')
def home():
    db = get_db()
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    listings = db.execute('''SELECT fl.*, r.name as rname, r.city as rcity, r.address as raddress, r.cuisine_type
                              FROM food_listing fl JOIN restaurant r ON fl.restaurant_id=r.id
                              WHERE fl.is_active=1 AND fl.quantity_remaining>0 AND fl.pickup_end>=? AND r.is_approved=1
                              ORDER BY fl.created_at DESC LIMIT 6''',(now,)).fetchall()
    cities = [r[0] for r in db.execute("SELECT DISTINCT city FROM restaurant WHERE is_approved=1").fetchall()]
    lcount = db.execute("SELECT COUNT(*) FROM food_listing WHERE is_active=1").fetchone()[0]
    rcount = db.execute("SELECT COUNT(*) FROM restaurant WHERE is_approved=1").fetchone()[0]
    ocount = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    all_l = db.execute("SELECT original_price,discounted_price,quantity_available FROM food_listing").fetchall()
    saved = int(sum((l[0]-l[1])*l[2] for l in all_l))
    db.close()
    stats = {'listings':lcount,'restaurants':rcount,'orders':ocount,'saved':saved}
    return render_template('home.html', listings=listings, cities=cities, stats=stats)

@app.route('/browse')
def browse():
    db = get_db()
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    city = request.args.get('city','')
    food_type = request.args.get('food_type','')
    search = request.args.get('search','')
    q = '''SELECT fl.*, r.name as rname, r.city as rcity, r.cuisine_type
           FROM food_listing fl JOIN restaurant r ON fl.restaurant_id=r.id
           WHERE fl.is_active=1 AND fl.quantity_remaining>0 AND fl.pickup_end>=? AND r.is_approved=1'''
    params = [now]
    if city: q += ' AND r.city LIKE ?'; params.append(f'%{city}%')
    if food_type: q += ' AND fl.food_type=?'; params.append(food_type)
    if search: q += ' AND (fl.title LIKE ? OR r.name LIKE ?)'; params+=[f'%{search}%',f'%{search}%']
    q += ' ORDER BY fl.pickup_end ASC'
    listings = db.execute(q, params).fetchall()
    cities = [r[0] for r in db.execute("SELECT DISTINCT city FROM restaurant WHERE is_approved=1").fetchall()]
    db.close()
    return render_template('browse.html', listings=listings, cities=cities,
                           selected_city=city, selected_type=food_type, search=search)

@app.route('/map')
def map_view():
    db = get_db()
    restaurants = db.execute("SELECT * FROM restaurant WHERE is_approved=1 AND is_active=1").fetchall()
    db.close()
    return render_template('map.html', restaurants=restaurants)

@app.route('/listing/<int:id>')
def listing_detail(id):
    db = get_db()
    listing = db.execute('''SELECT fl.*, r.name as rname, r.city as rcity, r.address as raddress,
                             r.cuisine_type, r.upi_id, r.phone as rphone
                             FROM food_listing fl JOIN restaurant r ON fl.restaurant_id=r.id
                             WHERE fl.id=?''',(id,)).fetchone()
    db.close()
    if not listing: return "Not found", 404
    avail = is_available(listing)
    return render_template('listing_detail.html', listing=listing, avail=avail)

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        db = get_db()
        if db.execute("SELECT id FROM user WHERE email=?",(request.form['email'],)).fetchone():
            flash('Email already registered!','danger')
            db.close()
            return redirect(url_for('register'))
        db.execute("INSERT INTO user(name,email,phone,password_hash,role,city) VALUES(?,?,?,?,?,?)",
                   (request.form['name'],request.form['email'],request.form['phone'],
                    generate_password_hash(request.form['password']),
                    request.form.get('role','customer'),request.form.get('city','')))
        db.commit()
        u = db.execute("SELECT * FROM user WHERE email=?",(request.form['email'],)).fetchone()
        db.close()
        session['user_id']=u['id']; session['user_name']=u['name']; session['role']=u['role']
        flash(f"Welcome to FoodBachao, {u['name']}! 🎉",'success')
        return redirect(url_for('restaurant_setup') if u['role']=='restaurant' else url_for('home'))
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        db = get_db()
        login_input = request.form['email']
        u = db.execute("SELECT * FROM user WHERE email=? OR email=?",(login_input, login_input)).fetchone()
        if not u:
            u = db.execute("SELECT * FROM user WHERE name=?",(login_input,)).fetchone()
        db.close()
        if u and check_password_hash(u['password_hash'],request.form['password']):
            session['user_id']=u['id']; session['user_name']=u['name']; session['role']=u['role']
            flash(f"Welcome back, {u['name']}! 🙏",'success')
            if u['role']=='admin': return redirect(url_for('admin_dashboard'))
            if u['role']=='restaurant': return redirect(url_for('restaurant_dashboard'))
            return redirect(url_for('home'))
        flash('Invalid email or password.','danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.','info')
    return redirect(url_for('home'))

@app.route('/restaurant/setup', methods=['GET','POST'])
@login_required
def restaurant_setup():
    if request.method == 'POST':
        img = save_image(request.files.get('image')) or 'default.jpg'
        db = get_db()
        db.execute('''INSERT INTO restaurant(user_id,name,description,address,city,phone,cuisine_type,upi_id,latitude,longitude,image)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                   (session['user_id'],request.form['name'],request.form.get('description',''),
                    request.form['address'],request.form['city'],request.form['phone'],
                    request.form.get('cuisine_type',''),request.form.get('upi_id',''),
                    float(request.form.get('latitude',0) or 0),float(request.form.get('longitude',0) or 0),img))
        db.commit(); db.close()
        flash('Restaurant registered! Awaiting admin approval. 🍽️','success')
        return redirect(url_for('restaurant_dashboard'))
    return render_template('restaurant_setup.html')

@app.route('/restaurant/dashboard')
@login_required
@restaurant_required
def restaurant_dashboard():
    db = get_db()
    rest = db.execute("SELECT * FROM restaurant WHERE user_id=?",(session['user_id'],)).fetchone()
    if not rest: db.close(); return redirect(url_for('restaurant_setup'))
    listings = db.execute("SELECT * FROM food_listing WHERE restaurant_id=? ORDER BY created_at DESC",(rest['id'],)).fetchall()
    orders = db.execute('''SELECT o.*, fl.title as ftitle, fl.original_price, fl.discounted_price
                            FROM orders o JOIN food_listing fl ON o.listing_id=fl.id
                            WHERE fl.restaurant_id=? ORDER BY o.created_at DESC LIMIT 20''',(rest['id'],)).fetchall()
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    active = sum(1 for l in listings if l['is_active'] and l['quantity_remaining']>0 and l['pickup_end']>=now)
    revenue = sum(o['total_amount'] for o in orders if o['payment_status']=='paid')
    saved_waste = sum(l['quantity_available']-l['quantity_remaining'] for l in listings)
    db.close()
    stats = {'active':active,'total_orders':len(orders),'revenue':revenue,'saved_waste':saved_waste}
    return render_template('restaurant_dashboard.html', restaurant=rest, listings=listings, orders=orders, stats=stats, now=now)

@app.route('/restaurant/add-listing', methods=['GET','POST'])
@login_required
@restaurant_required
def add_listing():
    db = get_db()
    rest = db.execute("SELECT * FROM restaurant WHERE user_id=?",(session['user_id'],)).fetchone()
    if not rest: db.close(); return redirect(url_for('restaurant_setup'))
    if request.method == 'POST':
        img = save_image(request.files.get('image')) or 'default_food.jpg'
        qty = int(request.form['quantity'])
        db.execute('''INSERT INTO food_listing(restaurant_id,title,description,original_price,discounted_price,
                      quantity_available,quantity_remaining,pickup_start,pickup_end,food_type,image)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                   (rest['id'],request.form['title'],request.form.get('description',''),
                    float(request.form['original_price']),float(request.form['discounted_price']),
                    qty,qty,
                    request.form['pickup_start'].replace('T',' ')+':00',
                    request.form['pickup_end'].replace('T',' ')+':00',
                    request.form.get('food_type','veg'),img))
        db.commit(); db.close()
        flash('Food listing added! 🎉','success')
        return redirect(url_for('restaurant_dashboard'))
    db.close()
    now = datetime.now()
    return render_template('add_listing.html', restaurant=rest,
                           default_start=now.strftime('%Y-%m-%dT%H:%M'),
                           default_end=(now+timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M'))

@app.route('/restaurant/toggle-listing/<int:id>')
@login_required
@restaurant_required
def toggle_listing(id):
    db = get_db()
    l = db.execute("SELECT is_active FROM food_listing WHERE id=?",(id,)).fetchone()
    db.execute("UPDATE food_listing SET is_active=? WHERE id=?",(0 if l['is_active'] else 1,id))
    db.commit(); db.close()
    flash('Listing updated!','success')
    return redirect(url_for('restaurant_dashboard'))

@app.route('/order/<int:listing_id>', methods=['GET','POST'])
@login_required
def place_order(listing_id):
    db = get_db()
    listing = db.execute('''SELECT fl.*,r.name as rname,r.upi_id,r.address as raddress
                             FROM food_listing fl JOIN restaurant r ON fl.restaurant_id=r.id
                             WHERE fl.id=?''',(listing_id,)).fetchone()
    if not listing or not is_available(listing):
        flash('This listing is no longer available.','danger')
        db.close(); return redirect(url_for('browse'))
    if request.method == 'POST':
        qty = int(request.form.get('quantity',1))
        total = listing['discounted_price'] * qty
        onum = 'FB'+datetime.utcnow().strftime('%Y%m%d%H%M%S')+str(listing_id)
        db.execute("UPDATE food_listing SET quantity_remaining=quantity_remaining-? WHERE id=?",(qty,listing_id))
        db.execute('''INSERT INTO orders(order_number,user_id,listing_id,quantity,total_amount,upi_transaction_id)
                      VALUES(?,?,?,?,?,?)''',(onum,session['user_id'],listing_id,qty,total,request.form.get('upi_txn','')))
        db.commit()
        oid = db.execute("SELECT id FROM orders WHERE order_number=?",(onum,)).fetchone()['id']
        db.close()
        flash(f'Order #{onum} confirmed! Show this at pickup. 🎉','success')
        return redirect(url_for('order_confirmation', order_id=oid))
    db.close()
    return render_template('place_order.html', listing=listing)

@app.route('/order/confirmation/<int:order_id>')
@login_required
def order_confirmation(order_id):
    db = get_db()
    order = db.execute('''SELECT o.*,fl.title as ftitle,fl.discounted_price,fl.pickup_end,
                           r.name as rname,r.address as raddress
                           FROM orders o JOIN food_listing fl ON o.listing_id=fl.id
                           JOIN restaurant r ON fl.restaurant_id=r.id
                           WHERE o.id=?''',(order_id,)).fetchone()
    db.close()
    return render_template('order_confirmation.html', order=order)

@app.route('/my-orders')
@login_required
def my_orders():
    db = get_db()
    orders = db.execute('''SELECT o.*,fl.title as ftitle,fl.original_price,r.name as rname
                            FROM orders o JOIN food_listing fl ON o.listing_id=fl.id
                            JOIN restaurant r ON fl.restaurant_id=r.id
                            WHERE o.user_id=? ORDER BY o.created_at DESC''',(session['user_id'],)).fetchall()
    db.close()
    return render_template('my_orders.html', orders=orders)

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    db = get_db()
    stats = {
        'users': db.execute("SELECT COUNT(*) FROM user").fetchone()[0],
        'restaurants': db.execute("SELECT COUNT(*) FROM restaurant").fetchone()[0],
        'pending': db.execute("SELECT COUNT(*) FROM restaurant WHERE is_approved=0").fetchone()[0],
        'listings': db.execute("SELECT COUNT(*) FROM food_listing").fetchone()[0],
        'orders': db.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
        'revenue': db.execute("SELECT COALESCE(SUM(total_amount),0) FROM orders WHERE payment_status='paid'").fetchone()[0],
    }
    pending = db.execute("SELECT * FROM restaurant WHERE is_approved=0").fetchall()
    recent_orders = db.execute('''SELECT o.*,u.name as uname,fl.title as ftitle
                                   FROM orders o JOIN user u ON o.user_id=u.id
                                   JOIN food_listing fl ON o.listing_id=fl.id
                                   ORDER BY o.created_at DESC LIMIT 10''').fetchall()
    users = db.execute("SELECT * FROM user ORDER BY created_at DESC LIMIT 10").fetchall()
    db.close()
    return render_template('admin_dashboard.html', stats=stats, pending=pending,
                           recent_orders=recent_orders, users=users)

@app.route('/admin/approve/<int:rid>')
@login_required
@admin_required
def approve_restaurant(rid):
    db = get_db()
    r = db.execute("SELECT name FROM restaurant WHERE id=?",(rid,)).fetchone()
    db.execute("UPDATE restaurant SET is_approved=1 WHERE id=?",(rid,))
    db.commit(); db.close()
    flash(f"{r['name']} approved! ✅",'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/reject/<int:rid>')
@login_required
@admin_required
def reject_restaurant(rid):
    db = get_db()
    db.execute("DELETE FROM restaurant WHERE id=?",(rid,))
    db.commit(); db.close()
    flash('Restaurant rejected.','info')
    return redirect(url_for('admin_dashboard'))

@app.route('/api/restaurants')
def api_restaurants():
    db = get_db()
    rows = db.execute("SELECT * FROM restaurant WHERE is_approved=1 AND is_active=1").fetchall()
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    data = []
    for r in rows:
        al = db.execute("SELECT COUNT(*) FROM food_listing WHERE restaurant_id=? AND is_active=1 AND quantity_remaining>0 AND pickup_end>=?",(r['id'],now)).fetchone()[0]
        data.append({'id':r['id'],'name':r['name'],'address':r['address'],'city':r['city'],'lat':r['latitude'],'lng':r['longitude'],'cuisine':r['cuisine_type'],'active_listings':al,'rating':r['rating']})
    db.close()
    return jsonify(data)

# ── INIT ────────────────────────────────────────────────────────────────────
os.makedirs('static/uploads', exist_ok=True)
init_db()
seed_data()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
