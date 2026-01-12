from flask import Flask, render_template, request, redirect, url_for, g
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)

DATABASE = 'finance.db'


def get_db():
    if not hasattr(g, 'sqlite_db'):
        g.sqlite_db = sqlite3.connect(DATABASE)
        g.sqlite_db.row_factory = sqlite3.Row
    return g.sqlite_db


def init_db():
    with app.app_context():
        db = get_db()
        db.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL CHECK(type IN ('income', 'expense')),
                category TEXT NOT NULL,
                amount REAL NOT NULL,
                date TEXT NOT NULL DEFAULT (CURRENT_DATE),
                description TEXT
            )
        ''')
        db.commit()


@app.teardown_appcontext
def close_db(error):
    if hasattr(g, 'sqlite_db'):
        g.sqlite_db.close()


@app.route('/')
def index():
    db = get_db()

    balance_row = db.execute('''
        SELECT 
            COALESCE(SUM(CASE WHEN type='income' THEN amount ELSE 0 END), 0) as total_income,
            COALESCE(SUM(CASE WHEN type='expense' THEN amount ELSE 0 END), 0) as total_expense
        FROM transactions
    ''').fetchone()

    total_income = balance_row['total_income'] or 0
    total_expense = balance_row['total_expense'] or 0
    balance = total_income - total_expense

    chart_data = db.execute('''
        SELECT category, SUM(amount) as total 
        FROM transactions 
        WHERE type='expense' 
        GROUP BY category
    ''').fetchall()

    return render_template('index.html',
                           balance=balance,
                           income=total_income,
                           expense=total_expense,
                           chart_data=chart_data)


@app.route('/add', methods=['GET', 'POST'])
def add_transaction():
    if request.method == 'POST':
        db = get_db()
        db.execute('''
            INSERT INTO transactions (type, category, amount, description)
            VALUES (?, ?, ?, ?)
        ''', (
            request.form['type'],
            request.form['category'],
            float(request.form['amount']),
            request.form.get('description', '')
        ))
        db.commit()
        return redirect(url_for('index'))

    return render_template('add.html')


@app.route('/history')
def history():
    db = get_db()
    transactions = db.execute('''
        SELECT * FROM transactions 
        ORDER BY date DESC, id DESC
    ''').fetchall()
    return render_template('history.html', transactions=transactions)


@app.route('/delete/<int:transaction_id>')
def delete_transaction(transaction_id):
    db = get_db()
    db.execute('DELETE FROM transactions WHERE id = ?', (transaction_id,))
    db.commit()
    return redirect(url_for('history'))


if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=3000)