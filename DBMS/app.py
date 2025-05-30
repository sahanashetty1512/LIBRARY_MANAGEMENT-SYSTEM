from flask import Flask, render_template, request, redirect, url_for, session, flash
import mysql.connector
from mysql.connector import Error
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'Stop@scam1'  # Change in production!

db_config = {
    'host': 'localhost',
    'user': 'library_user',
    'password': 'Stop@scam1',
    'database': 'library_db'
}

def get_db_connection():
    try:
        conn = mysql.connector.connect(**db_config)
        return conn
    except Error as e:
        print(f"DB connection error: {e}")
        return None

# --- REGISTER ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip()
        password = request.form['password']
        role = request.form['role']

        hashed_password = generate_password_hash(password)

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            flash('Email already registered', 'danger')
            cursor.close()
            conn.close()
            return render_template('register.html')

        cursor.execute(
            "INSERT INTO users (name, email, password, role) VALUES (%s, %s, %s, %s)",
            (name, email, hashed_password, role)
        )
        conn.commit()
        cursor.close()
        conn.close()
        flash('Registration successful, please login', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

# --- LOGIN ---
@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form['email'].strip()
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            session['user_role'] = user['role']
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password', 'danger')
    return render_template('login.html')

# --- LOGOUT ---
@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully', 'info')
    return redirect(url_for('login'))

# --- DASHBOARD ---
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT COUNT(*) AS total_books FROM books")
    total_books = cursor.fetchone()['total_books']

    cursor.execute("SELECT SUM(available) AS available_books FROM books")
    res = cursor.fetchone()
    available_books = res['available_books'] if res['available_books'] is not None else 0

    if session['user_role'] == 'admin':
        cursor.execute("SELECT COUNT(*) AS issued_books FROM issue_log WHERE return_date IS NULL")
        issued_books = cursor.fetchone()['issued_books']
    else:
        cursor.execute("SELECT COUNT(*) AS issued_books FROM issue_log WHERE user_id = %s AND return_date IS NULL", (user_id,))
        issued_books = cursor.fetchone()['issued_books']

    cursor.execute("SELECT id, title, author, category, total, available FROM books ORDER BY id DESC LIMIT 5")
    recent_books = cursor.fetchall()

    if session['user_role'] == 'admin':
        cursor.execute("SELECT n.id, n.message, n.date_sent, u.name AS sender FROM notifications n JOIN users u ON n.user_id = u.id ORDER BY n.date_sent DESC LIMIT 5")
        notifications = cursor.fetchall()
    else:
        cursor.execute("SELECT id, message, date_sent FROM notifications WHERE user_id = %s ORDER BY date_sent DESC LIMIT 5", (user_id,))
        notifications = cursor.fetchall()

    if session['user_role'] == 'user':
        cursor.execute("SELECT SUM(fine) AS total_fine FROM issue_log WHERE user_id = %s AND paid = 0", (user_id,))
        fine_res = cursor.fetchone()
        total_fine = fine_res['total_fine'] if fine_res['total_fine'] else 0
    else:
        total_fine = 0

    cursor.close()
    conn.close()

    return render_template('dashboard.html',
                           total_books=total_books,
                           available_books=available_books,
                           issued_books=issued_books,
                           recent_books=recent_books,
                           notifications=notifications,
                           total_fine=total_fine)

# --- BOOKS LIST (ADMIN ONLY) ---
@app.route('/books')
def books():
    if 'user_id' not in session or session['user_role'] != 'admin':
        flash('Access denied', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM books ORDER BY id DESC")
    books = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('books.html', books=books)

# --- ADD BOOK (ADMIN ONLY) ---
@app.route('/add_book', methods=['GET', 'POST'])
def add_book():
    if 'user_id' not in session or session['user_role'] != 'admin':
        flash('Access denied', 'danger')
        return redirect(url_for('login'))

    if request.method == 'POST':
        title = request.form['title'].strip()
        author = request.form['author'].strip()
        category = request.form['category'].strip()
        total = int(request.form['total'])
        available = total

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO books (title, author, category, total, available) VALUES (%s, %s, %s, %s, %s)",
            (title, author, category, total, available)
        )
        conn.commit()
        cursor.close()
        conn.close()

        flash('Book added successfully', 'success')
        return redirect(url_for('books'))

    return render_template('add_book.html')

# --- ISSUE / RETURN BOOKS (USER ONLY) ---
@app.route('/issue_return', methods=['GET', 'POST'])
def issue_return():
    if 'user_id' not in session or session['user_role'] != 'user':
        flash('Access denied', 'danger')
        return redirect(url_for('login'))
    user_id = session['user_id']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Get currently issued books not returned yet
    cursor.execute("""
        SELECT il.id, b.title, il.issue_date, il.due_date, il.return_date, il.fine, il.paid
        FROM issue_log il
        JOIN books b ON il.book_id = b.id
        WHERE il.user_id = %s AND il.return_date IS NULL
        ORDER BY il.issue_date DESC
    """, (user_id,))
    issued_books = cursor.fetchall()

    # Get available books for issue
    cursor.execute("SELECT id, title, available FROM books WHERE available > 0 ORDER BY title")
    books = cursor.fetchall()

    message = None

    if request.method == 'POST':
        action = request.form.get('action')
        book_id = int(request.form.get('book_id', 0))

        if action == 'issue':
            # Check if already issued the same book and not returned
            cursor.execute("SELECT * FROM issue_log WHERE user_id = %s AND book_id = %s AND return_date IS NULL", (user_id, book_id))
            if cursor.fetchone():
                message = "You already issued this book and haven't returned it yet."
            else:
                issue_date = datetime.today().date()
                due_date = issue_date + timedelta(days=14)  # 2 weeks due
                cursor.execute("""
                    INSERT INTO issue_log (user_id, book_id, issue_date, due_date)
                    VALUES (%s, %s, %s, %s)
                """, (user_id, book_id, issue_date, due_date))
                cursor.execute("UPDATE books SET available = available - 1 WHERE id = %s AND available > 0", (book_id,))
                conn.commit()
                message = "Book issued successfully."

        elif action == 'return':
            issue_log_id = int(request.form.get('issue_log_id'))
            cursor.execute("SELECT * FROM issue_log WHERE id = %s AND user_id = %s", (issue_log_id, user_id))
            issue_log = cursor.fetchone()
            if issue_log and issue_log['return_date'] is None:
                return_date = datetime.today().date()
                fine = 0
                due_date = issue_log['due_date']
                if return_date > due_date:
                    days_late = (return_date - due_date).days
                    fine = days_late * 1  # $1 per day late

                cursor.execute("""
                    UPDATE issue_log SET return_date = %s, fine = %s, paid = 0 WHERE id = %s
                """, (return_date, fine, issue_log_id))
                cursor.execute("UPDATE books SET available = available + 1 WHERE id = %s", (issue_log['book_id'],))
                conn.commit()
                if fine > 0:
                    message = f"Book returned with a fine of ${fine}. Please pay your fines."
                else:
                    message = "Book returned successfully. No fines due."
            else:
                message = "Invalid return request."

        # Refresh data after action
        cursor.execute("""
            SELECT il.id, b.title, il.issue_date, il.due_date, il.return_date, il.fine, il.paid
            FROM issue_log il
            JOIN books b ON il.book_id = b.id
            WHERE il.user_id = %s AND il.return_date IS NULL
            ORDER BY il.issue_date DESC
        """, (user_id,))
        issued_books = cursor.fetchall()

        cursor.execute("SELECT id, title, available FROM books WHERE available > 0 ORDER BY title")
        books = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('issue_return.html', books=books, issued_books=issued_books, message=message)

# --- SEARCH BOOKS (ALL USERS) ---
@app.route('/search', methods=['GET', 'POST'])
def search():
    if 'user_id' not in session:
        flash('Please login first', 'warning')
        return redirect(url_for('login'))

    search_results = []
    if request.method == 'POST':
        keyword = request.form['keyword'].strip()
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        sql = """
            SELECT * FROM books
            WHERE title LIKE %s OR author LIKE %s OR category LIKE %s
            ORDER BY title
        """
        like_keyword = f'%{keyword}%'
        cursor.execute(sql, (like_keyword, like_keyword, like_keyword))
        search_results = cursor.fetchall()
        cursor.close()
        conn.close()

    return render_template('search.html', search_results=search_results)

# --- NOTIFICATIONS ---
@app.route('/notifications')
def notifications():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    role = session['user_role']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if role == 'admin':
        cursor.execute("""
            SELECT n.id, n.message, n.date_sent, u.name AS sender
            FROM notifications n
            JOIN users u ON n.user_id = u.id
            ORDER BY n.date_sent DESC
        """)
    else:
        cursor.execute("SELECT id, message, date_sent FROM notifications WHERE user_id = %s ORDER BY date_sent DESC", (user_id,))

    notifications = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('notifications.html', notifications=notifications)

# --- SEND NOTIFICATION (ADMIN ONLY) ---
@app.route('/send_notification', methods=['GET', 'POST'])
def send_notification():
    if 'user_id' not in session or session['user_role'] != 'admin':
        flash('Access denied', 'danger')
        return redirect(url_for('login'))

    if request.method == 'POST':
        message = request.form['message'].strip()
        user_id = session['user_id']
        date_sent = datetime.now()

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO notifications (user_id, message, date_sent) VALUES (%s, %s, %s)", (user_id, message, date_sent))
        conn.commit()
        cursor.close()
        conn.close()

        flash('Notification sent successfully', 'success')
        return redirect(url_for('notifications'))

    return render_template('send_notification.html')

# --- REPORTS (ADMIN ONLY) ---
@app.route('/reports')
def reports():
    if 'user_id' not in session or session['user_role'] != 'admin':
        flash('Access denied', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM books ORDER BY id DESC")
    books = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('books.html', books=books)

# --- PAY FINES (USER ONLY) ---
@app.route('/pay_fines', methods=['GET', 'POST'])
def pay_fines():
    if 'user_id' not in session or session['user_role'] != 'user':
        flash('Access denied', 'danger')
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT id, fine FROM issue_log WHERE user_id = %s AND fine > 0 AND paid = 0
    """, (user_id,))
    fines = cursor.fetchall()

    if request.method == 'POST':
        payment_ids = request.form.getlist('payment_ids')
        if payment_ids:
            for payment_id in payment_ids:
                cursor.execute("UPDATE issue_log SET paid = 1 WHERE id = %s", (payment_id,))
            conn.commit()
            flash('Fines paid successfully', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Please select fines to pay', 'warning')

    cursor.close()
    conn.close()
    return render_template('pay_fines.html', fines=fines)

if __name__ == '__main__':
    app.run(debug=True)  