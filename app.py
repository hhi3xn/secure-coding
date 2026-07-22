import sqlite3
import time
import uuid
from flask import Flask, abort, render_template, request, redirect, url_for, session, flash, g
from flask_socketio import SocketIO, disconnect, send
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
DATABASE = 'market.db'
socketio = SocketIO(app)
chat_rate_limit = {}
REPORT_LIMIT = 3

def validate_username(username):
    username = (username or '').strip()
    if len(username) < 3 or len(username) > 20:
        return None, '사용자명은 3자 이상 20자 이하로 입력해야 합니다.'
    if not username.replace('_', '').isalnum():
        return None, '사용자명은 영문, 숫자, 밑줄만 사용할 수 있습니다.'
    return username, None

def validate_password(password):
    if len(password or '') < 8:
        return '비밀번호는 8자 이상이어야 합니다.'
    if not any(ch.isalpha() for ch in password) or not any(ch.isdigit() for ch in password):
        return '비밀번호는 영문과 숫자를 모두 포함해야 합니다.'
    return None

def validate_product(title, description, price, image_path):
    title = (title or '').strip()
    description = (description or '').strip()
    image_path = (image_path or '').strip()
    if len(title) < 1 or len(title) > 80:
        return None, None, None, None, '상품명은 1자 이상 80자 이하로 입력해야 합니다.'
    if len(description) < 1 or len(description) > 1000:
        return None, None, None, None, '상품 설명은 1자 이상 1000자 이하로 입력해야 합니다.'
    try:
        price = int(price)
    except ValueError:
        return None, None, None, None, '가격은 숫자로 입력해야 합니다.'
    if price <= 0:
        return None, None, None, None, '가격은 1원 이상이어야 합니다.'
    if len(image_path) > 300:
        return None, None, None, None, '이미지 경로는 300자 이하로 입력해야 합니다.'
    return title, description, price, image_path, None

def validate_message(content):
    content = (content or '').strip()
    if len(content) < 1 or len(content) > 300:
        return None, '메시지는 1자 이상 300자 이하로 입력해야 합니다.'
    return content, None

def validate_report_reason(reason):
    reason = (reason or '').strip()
    if len(reason) < 5 or len(reason) > 300:
        return None, '신고 사유는 5자 이상 300자 이하로 입력해야 합니다.'
    return reason, None

def validate_amount(amount):
    try:
        amount = int(amount)
    except ValueError:
        return None, '송금 금액은 숫자로 입력해야 합니다.'
    if amount <= 0:
        return None, '송금 금액은 1 이상이어야 합니다.'
    return amount, None

def validate_search_query(query):
    query = (query or '').strip()
    if len(query) > 50:
        return None, '검색어는 50자 이하로 입력해야 합니다.'
    return query, None

def apply_report_action(target_type, target_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "SELECT COUNT(*) AS count FROM report WHERE target_type = ? AND target_id = ?",
        (target_type, target_id)
    )
    report_count = cursor.fetchone()['count']
    if report_count < REPORT_LIMIT:
        return
    if target_type == 'product':
        cursor.execute("UPDATE product SET status = 'hidden' WHERE id = ?", (target_id,))
    elif target_type == 'user':
        cursor.execute("UPDATE user SET status = 'suspended' WHERE id = ?", (target_id,))
    db.commit()

def add_column_if_missing(cursor, table, column, definition):
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [row['name'] for row in cursor.fetchall()]
    if column not in columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

# 데이터베이스 연결 관리: 요청마다 연결 생성 후 사용, 종료 시 close
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row  # 결과를 dict처럼 사용하기 위함
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# 테이블 생성 (최초 실행 시에만)
def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        # 사용자 테이블 생성
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                bio TEXT
            )
        """)
        add_column_if_missing(cursor, "user", "status", "TEXT NOT NULL DEFAULT 'active'")
        add_column_if_missing(cursor, "user", "balance", "INTEGER NOT NULL DEFAULT 10000")
        # 상품 테이블 생성
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS product (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                price TEXT NOT NULL,
                seller_id TEXT NOT NULL
            )
        """)
        add_column_if_missing(cursor, "product", "image_path", "TEXT")
        add_column_if_missing(cursor, "product", "status", "TEXT NOT NULL DEFAULT 'active'")
        # 신고 테이블 생성
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS report (
                id TEXT PRIMARY KEY,
                reporter_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                reason TEXT NOT NULL
            )
        """)
        add_column_if_missing(cursor, "report", "target_type", "TEXT NOT NULL DEFAULT 'product'")
        add_column_if_missing(cursor, "report", "created_at", "INTEGER NOT NULL DEFAULT 0")
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_report_unique_target
            ON report (reporter_id, target_type, target_id)
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS message (
                id TEXT PRIMARY KEY,
                sender_id TEXT NOT NULL,
                receiver_id TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transfer (
                id TEXT PRIMARY KEY,
                sender_id TEXT NOT NULL,
                receiver_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)
        db.commit()

# 기본 라우트
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

# 회원가입
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username, username_error = validate_username(request.form.get('username'))
        password = request.form['password']
        password_error = validate_password(password)
        if username_error or password_error:
            flash(username_error or password_error)
            return redirect(url_for('register'))
        db = get_db()
        cursor = db.cursor()
        # 중복 사용자 체크
        cursor.execute("SELECT * FROM user WHERE username = ?", (username,))
        if cursor.fetchone() is not None:
            flash('이미 존재하는 사용자명입니다.')
            return redirect(url_for('register'))
        user_id = str(uuid.uuid4())
        cursor.execute("INSERT INTO user (id, username, password) VALUES (?, ?, ?)",
                       (user_id, username, generate_password_hash(password)))
        db.commit()
        flash('회원가입이 완료되었습니다. 로그인 해주세요.')
        return redirect(url_for('login'))
    return render_template('register.html')

# 로그인
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM user WHERE username = ?", (username,))
        user = cursor.fetchone()
        if user and user['status'] != 'active':
            flash('휴면 처리된 계정입니다.')
            return redirect(url_for('login'))
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            flash('로그인 성공!')
            return redirect(url_for('dashboard'))
        else:
            flash('아이디 또는 비밀번호가 올바르지 않습니다.')
            return redirect(url_for('login'))
    return render_template('login.html')

# 로그아웃
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('로그아웃되었습니다.')
    return redirect(url_for('index'))

# 사용자 조회
@app.route('/users')
def users():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT id, username, bio FROM user WHERE status = 'active' ORDER BY username")
    all_users = cursor.fetchall()
    return render_template('users.html', users=all_users)

# 1대1 메시지
@app.route('/messages', methods=['GET', 'POST'])
def messages():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    cursor = db.cursor()
    if request.method == 'POST':
        receiver_id = request.form.get('receiver_id', '')
        content, error = validate_message(request.form.get('content'))
        cursor.execute("SELECT id FROM user WHERE id = ?", (receiver_id,))
        receiver = cursor.fetchone()
        if error or not receiver or receiver_id == session['user_id']:
            flash(error or '받는 사용자가 올바르지 않습니다.')
            return redirect(url_for('messages'))
        cursor.execute(
            "INSERT INTO message (id, sender_id, receiver_id, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), session['user_id'], receiver_id, content, int(time.time()))
        )
        db.commit()
        flash('메시지를 보냈습니다.')
        return redirect(url_for('messages'))
    cursor.execute("SELECT id, username FROM user WHERE id != ? AND status = 'active' ORDER BY username", (session['user_id'],))
    users = cursor.fetchall()
    cursor.execute("""
        SELECT m.*, sender.username AS sender_name, receiver.username AS receiver_name
        FROM message m
        JOIN user sender ON m.sender_id = sender.id
        JOIN user receiver ON m.receiver_id = receiver.id
        WHERE m.sender_id = ? OR m.receiver_id = ?
        ORDER BY m.created_at DESC
    """, (session['user_id'], session['user_id']))
    all_messages = cursor.fetchall()
    return render_template('messages.html', users=users, messages=all_messages)

# 가상 포인트 송금
@app.route('/transfer', methods=['GET', 'POST'])
def transfer():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    cursor = db.cursor()
    if request.method == 'POST':
        receiver_id = request.form.get('receiver_id', '')
        amount, amount_error = validate_amount(request.form.get('amount'))
        cursor.execute("SELECT * FROM user WHERE id = ?", (session['user_id'],))
        sender = cursor.fetchone()
        cursor.execute("SELECT * FROM user WHERE id = ? AND status = 'active'", (receiver_id,))
        receiver = cursor.fetchone()
        if amount_error or not receiver or receiver_id == session['user_id']:
            flash(amount_error or '받는 사용자가 올바르지 않습니다.')
            return redirect(url_for('transfer'))
        if sender['balance'] < amount:
            flash('잔액이 부족합니다.')
            return redirect(url_for('transfer'))
        cursor.execute("UPDATE user SET balance = balance - ? WHERE id = ?", (amount, session['user_id']))
        cursor.execute("UPDATE user SET balance = balance + ? WHERE id = ?", (amount, receiver_id))
        cursor.execute(
            "INSERT INTO transfer (id, sender_id, receiver_id, amount, created_at) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), session['user_id'], receiver_id, amount, int(time.time()))
        )
        db.commit()
        flash('송금이 완료되었습니다.')
        return redirect(url_for('transfer'))
    cursor.execute("SELECT * FROM user WHERE id = ?", (session['user_id'],))
    current_user = cursor.fetchone()
    cursor.execute("SELECT id, username FROM user WHERE id != ? AND status = 'active' ORDER BY username", (session['user_id'],))
    users = cursor.fetchall()
    cursor.execute("""
        SELECT t.*, sender.username AS sender_name, receiver.username AS receiver_name
        FROM transfer t
        JOIN user sender ON t.sender_id = sender.id
        JOIN user receiver ON t.receiver_id = receiver.id
        WHERE t.sender_id = ? OR t.receiver_id = ?
        ORDER BY t.created_at DESC
    """, (session['user_id'], session['user_id']))
    transfers = cursor.fetchall()
    return render_template('transfer.html', user=current_user, users=users, transfers=transfers)

# 대시보드: 사용자 정보와 전체 상품 리스트 표시
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    cursor = db.cursor()
    # 현재 사용자 조회
    cursor.execute("SELECT * FROM user WHERE id = ?", (session['user_id'],))
    current_user = cursor.fetchone()
    query, query_error = validate_search_query(request.args.get('q'))
    if query_error:
        flash(query_error)
        query = ''
    # 삭제되지 않은 상품 조회
    if query:
        like_query = f"%{query}%"
        cursor.execute(
            "SELECT * FROM product WHERE status = 'active' AND (title LIKE ? OR description LIKE ?)",
            (like_query, like_query)
        )
    else:
        cursor.execute("SELECT * FROM product WHERE status = 'active'")
    all_products = cursor.fetchall()
    return render_template('dashboard.html', products=all_products, user=current_user, query=query)

# 프로필 페이지: bio 업데이트 가능
@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    cursor = db.cursor()
    if request.method == 'POST':
        bio = request.form.get('bio', '')
        cursor.execute("UPDATE user SET bio = ? WHERE id = ?", (bio, session['user_id']))
        db.commit()
        flash('프로필이 업데이트되었습니다.')
        return redirect(url_for('profile'))
    cursor.execute("SELECT * FROM user WHERE id = ?", (session['user_id'],))
    current_user = cursor.fetchone()
    return render_template('profile.html', user=current_user)

# 비밀번호 변경
@app.route('/profile/password', methods=['POST'])
def change_password():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    password_error = validate_password(new_password)
    if password_error:
        flash(password_error)
        return redirect(url_for('profile'))
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM user WHERE id = ?", (session['user_id'],))
    current_user = cursor.fetchone()
    if not current_user or not check_password_hash(current_user['password'], current_password):
        flash('현재 비밀번호가 올바르지 않습니다.')
        return redirect(url_for('profile'))
    cursor.execute(
        "UPDATE user SET password = ? WHERE id = ?",
        (generate_password_hash(new_password), session['user_id'])
    )
    db.commit()
    flash('비밀번호가 변경되었습니다.')
    return redirect(url_for('profile'))

# 상품 등록
@app.route('/product/new', methods=['GET', 'POST'])
def new_product():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        title, description, price, image_path, error = validate_product(
            request.form.get('title'),
            request.form.get('description'),
            request.form.get('price'),
            request.form.get('image_path')
        )
        if error:
            flash(error)
            return redirect(url_for('new_product'))
        db = get_db()
        cursor = db.cursor()
        product_id = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO product (id, title, description, price, image_path, seller_id, status) VALUES (?, ?, ?, ?, ?, ?, 'active')",
            (product_id, title, description, str(price), image_path, session['user_id'])
        )
        db.commit()
        flash('상품이 등록되었습니다.')
        return redirect(url_for('dashboard'))
    return render_template('new_product.html')

# 상품 상세보기
@app.route('/product/<product_id>')
def view_product(product_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM product WHERE id = ? AND status = 'active'", (product_id,))
    product = cursor.fetchone()
    if not product:
        flash('상품을 찾을 수 없습니다.')
        return redirect(url_for('dashboard'))
    # 판매자 정보 조회
    cursor.execute("SELECT * FROM user WHERE id = ?", (product['seller_id'],))
    seller = cursor.fetchone()
    return render_template('view_product.html', product=product, seller=seller)

# 내가 등록한 상품 관리
@app.route('/my-products')
def my_products():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM product WHERE seller_id = ? AND status = 'active'", (session['user_id'],))
    products = cursor.fetchall()
    return render_template('my_products.html', products=products)

# 상품 수정
@app.route('/product/<product_id>/edit', methods=['GET', 'POST'])
def edit_product(product_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM product WHERE id = ? AND status = 'active'", (product_id,))
    product = cursor.fetchone()
    if not product:
        flash('상품을 찾을 수 없습니다.')
        return redirect(url_for('dashboard'))
    if product['seller_id'] != session['user_id']:
        abort(403)
    if request.method == 'POST':
        title, description, price, image_path, error = validate_product(
            request.form.get('title'),
            request.form.get('description'),
            request.form.get('price'),
            request.form.get('image_path')
        )
        if error:
            flash(error)
            return redirect(url_for('edit_product', product_id=product_id))
        cursor.execute(
            "UPDATE product SET title = ?, description = ?, price = ?, image_path = ? WHERE id = ?",
            (title, description, str(price), image_path, product_id)
        )
        db.commit()
        flash('상품이 수정되었습니다.')
        return redirect(url_for('view_product', product_id=product_id))
    return render_template('edit_product.html', product=product)

# 상품 삭제
@app.route('/product/<product_id>/delete', methods=['POST'])
def delete_product(product_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM product WHERE id = ? AND status = 'active'", (product_id,))
    product = cursor.fetchone()
    if not product:
        flash('상품을 찾을 수 없습니다.')
        return redirect(url_for('dashboard'))
    if product['seller_id'] != session['user_id']:
        abort(403)
    cursor.execute("UPDATE product SET status = 'deleted' WHERE id = ?", (product_id,))
    db.commit()
    flash('상품이 삭제되었습니다.')
    return redirect(url_for('my_products'))

# 신고하기
@app.route('/report', methods=['GET', 'POST'])
def report():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        target_type = request.form.get('target_type', '')
        target_id = request.form.get('target_id', '').strip()
        reason, reason_error = validate_report_reason(request.form.get('reason'))
        if target_type not in ('product', 'user') or reason_error:
            flash(reason_error or '신고 대상 유형이 올바르지 않습니다.')
            return redirect(url_for('report'))
        db = get_db()
        cursor = db.cursor()
        if target_type == 'product':
            cursor.execute("SELECT id FROM product WHERE id = ? AND status = 'active'", (target_id,))
        else:
            cursor.execute("SELECT id FROM user WHERE id = ? AND status = 'active'", (target_id,))
        if not cursor.fetchone():
            flash('신고 대상을 찾을 수 없습니다.')
            return redirect(url_for('report'))
        if target_type == 'user' and target_id == session['user_id']:
            flash('자기 자신은 신고할 수 없습니다.')
            return redirect(url_for('report'))
        report_id = str(uuid.uuid4())
        try:
            cursor.execute(
                "INSERT INTO report (id, reporter_id, target_type, target_id, reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (report_id, session['user_id'], target_type, target_id, reason, int(time.time()))
            )
            db.commit()
        except sqlite3.IntegrityError:
            flash('이미 신고한 대상입니다.')
            return redirect(url_for('report'))
        apply_report_action(target_type, target_id)
        flash('신고가 접수되었습니다.')
        return redirect(url_for('dashboard'))
    target_type = request.args.get('target_type', '')
    target_id = request.args.get('target_id', '')
    return render_template('report.html', target_type=target_type, target_id=target_id)

# 실시간 채팅: 클라이언트가 메시지를 보내면 전체 브로드캐스트
@socketio.on('connect')
def handle_connect():
    if 'user_id' not in session:
        disconnect()

@socketio.on('send_message')
def handle_send_message_event(data):
    if 'user_id' not in session:
        disconnect()
        return
    now = time.time()
    last_sent = chat_rate_limit.get(session['user_id'], 0)
    if now - last_sent < 1:
        return
    message, error = validate_message(data.get('message') if isinstance(data, dict) else '')
    if error:
        return
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT username FROM user WHERE id = ?", (session['user_id'],))
    user = cursor.fetchone()
    if not user:
        disconnect()
        return
    chat_rate_limit[session['user_id']] = now
    send({
        'message_id': str(uuid.uuid4()),
        'username': user['username'],
        'message': message
    }, broadcast=True)

if __name__ == '__main__':
    init_db()  # 앱 컨텍스트 내에서 테이블 생성
    socketio.run(app, debug=True)
