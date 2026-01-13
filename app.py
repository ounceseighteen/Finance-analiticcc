from flask import Flask, render_template, request, redirect, url_for, g, send_file
import sqlite3
import os
import pandas as pd
from datetime import datetime
from io import BytesIO

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
                description TEXT,
                balance_after REAL DEFAULT 0
            )
        ''')
        db.commit()


def update_all_balances():
    """Обновляет баланс для всех операций"""
    db = get_db()

    # Получаем все транзакции в порядке добавления
    transactions = db.execute('''
        SELECT * FROM transactions 
        ORDER BY date ASC, id ASC
    ''').fetchall()

    current_balance = 0

    for trans in transactions:
        if trans['type'] == 'income':
            current_balance += trans['amount']
        else:
            current_balance -= trans['amount']

        # Обновляем баланс в базе
        db.execute('''
            UPDATE transactions 
            SET balance_after = ?
            WHERE id = ?
        ''', (current_balance, trans['id']))

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
        amount = float(request.form['amount'])
        type_ = request.form['type']

        # Получаем последний баланс
        balance_row = db.execute('''
            SELECT balance_after 
            FROM transactions 
            ORDER BY id DESC 
            LIMIT 1
        ''').fetchone()

        current_balance = balance_row['balance_after'] if balance_row else 0

        # Рассчитываем новый баланс
        if type_ == 'income':
            new_balance = current_balance + amount
        else:
            new_balance = current_balance - amount

        # Добавляем транзакцию
        db.execute('''
            INSERT INTO transactions (type, category, amount, description, balance_after)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            type_,
            request.form['category'],
            amount,
            request.form.get('description', ''),
            new_balance
        ))
        db.commit()
        return redirect(url_for('index'))

    return render_template('add.html')


@app.route('/history')
def history():
    db = get_db()
    transactions = db.execute('''
        SELECT *, 
               CASE 
                   WHEN type='income' THEN '+' 
                   ELSE '-' 
               END as sign
        FROM transactions 
        ORDER BY date DESC, id DESC
    ''').fetchall()
    return render_template('history.html', transactions=transactions)


@app.route('/delete/<int:transaction_id>')
def delete_transaction(transaction_id):
    db = get_db()
    db.execute('DELETE FROM transactions WHERE id = ?', (transaction_id,))
    db.commit()
    # Обновляем балансы после удаления
    update_all_balances()
    return redirect(url_for('history'))


@app.route('/export')
def export_excel():
    """Экспорт всех операций в Excel"""
    db = get_db()

    # Получаем все транзакции
    transactions = db.execute('''
        SELECT date, type, category, amount, description, balance_after 
        FROM transactions 
        ORDER BY date ASC, id ASC
    ''').fetchall()

    # Подготавливаем данные для экспорта
    export_data = []
    for t in transactions:
        # Преобразуем дату в формат ДД.ММ.ГГГГ
        try:
            date_obj = datetime.strptime(t['date'], '%Y-%m-%d')
            formatted_date = date_obj.strftime('%d.%m.%Y')
        except:
            formatted_date = t['date']

        # Преобразуем тип на русский
        type_russian = 'Доход' if t['type'] == 'income' else 'Расход'

        # Форматируем сумму (добавляем минус для расходов)
        amount_value = t['amount']
        if t['type'] == 'expense':
            amount_display = f"-{amount_value:.2f}"
        else:
            amount_display = f"{amount_value:.2f}"

        export_data.append({
            'Дата': formatted_date,
            'Тип': type_russian,
            'Категория': t['category'],
            'Сумма': amount_display,
            'Описание': t['description'] or '',
            'Баланс': f"{t['balance_after']:.2f}"
        })

    # Преобразуем в DataFrame
    df = pd.DataFrame(export_data)

    # Создаем Excel файл в памяти
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Операции', index=False)

        # Добавляем лист с суммами
        total_income = sum(t['amount'] for t in transactions if t['type'] == 'income')
        total_expense = sum(t['amount'] for t in transactions if t['type'] == 'expense')
        balance = total_income - total_expense

        summary_df = pd.DataFrame([{
            'Общий доход': f"{total_income:.2f}",
            'Общие расходы': f"{total_expense:.2f}",
            'Итоговый баланс': f"{balance:.2f}"
        }])
        summary_df.to_excel(writer, sheet_name='Сводка', index=False)

    output.seek(0)

    # Отправляем файл
    filename = f'финансы_{datetime.now().strftime("%d%m%Y_%H%M%S")}.xlsx'
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


@app.route('/import_export', methods=['GET', 'POST'])
def import_export():
    """Объединенная страница для импорта и экспорта"""
    if request.method == 'POST':
        if 'file' not in request.files:
            return redirect(request.url)

        file = request.files['file']
        if file.filename == '':
            return redirect(request.url)

        if file and file.filename.endswith(('.xlsx', '.xls')):
            try:
                # Читаем Excel файл
                df = pd.read_excel(file)

                # Проверяем необходимые колонки
                required_columns = ['Дата', 'Тип', 'Категория', 'Сумма']
                if not all(col in df.columns for col in required_columns):
                    return render_template('import_export.html',
                                           error="Файл должен содержать колонки: Дата, Тип, Категория, Сумма")

                db = get_db()
                added_count = 0
                errors = []

                for index, row in df.iterrows():
                    # Пропускаем пустые строки
                    if pd.isna(row['Дата']) or pd.isna(row['Сумма']):
                        continue

                    try:
                        # Обработка даты
                        date_value = row['Дата']
                        if isinstance(date_value, str):
                            # Пробуем разные формата дат
                            for fmt in ('%d.%m.%Y', '%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
                                try:
                                    date_obj = datetime.strptime(str(date_value).strip(), fmt)
                                    date_str = date_obj.strftime('%Y-%m-%d')
                                    break
                                except:
                                    continue
                            else:
                                errors.append(f"Строка {index + 2}: Неверный формат даты")
                                continue
                        elif isinstance(date_value, pd.Timestamp):
                            date_str = date_value.strftime('%Y-%m-%d')
                        else:
                            errors.append(f"Строка {index + 2}: Неверный тип даты")
                            continue

                        # Обработка типа
                        type_value = str(row['Тип']).strip().lower()
                        if type_value in ['доход', 'income', 'д']:
                            type_db = 'income'
                        elif type_value in ['расход', 'expense', 'р']:
                            type_db = 'expense'
                        else:
                            errors.append(f"Строка {index + 2}: Неверный тип операции")
                            continue

                        # Обработка суммы
                        amount_str = str(row['Сумма']).replace(',', '.')
                        # Убираем возможный минус и пробелы
                        amount_str_clean = amount_str.replace('-', '').replace(' ', '')
                        try:
                            amount = float(amount_str_clean)
                        except:
                            errors.append(f"Строка {index + 2}: Неверный формат суммы")
                            continue

                        # Категория
                        category = str(row['Категория']).strip()

                        # Описание (необязательно)
                        description = row.get('Описание', '')
                        if pd.isna(description):
                            description = ''
                        else:
                            description = str(description).strip()

                        # Временно вставляем с нулевым балансом
                        db.execute('''
                            INSERT INTO transactions (date, type, category, amount, description, balance_after)
                            VALUES (?, ?, ?, ?, ?, 0)
                        ''', (
                            date_str,
                            type_db,
                            category,
                            amount,
                            description
                        ))
                        added_count += 1

                    except Exception as e:
                        errors.append(f"Строка {index + 2}: {str(e)}")
                        continue

                db.commit()
                # Обновляем балансы после импорта
                update_all_balances()

                # Страница успешного импорта
                return render_template('import_export.html',
                                       success=True,
                                       count=added_count,
                                       errors=errors if errors else None)

            except Exception as e:
                return render_template('import_export.html',
                                       error=f"Ошибка при импорте: {str(e)}")

    return render_template('import_export.html')


@app.route('/download_template')
def download_template():
    """Скачивание шаблона Excel файла"""
    # Создаем пример данных
    sample_data = [
        {
            'Дата': '15.01.2025',
            'Тип': 'Доход',
            'Категория': 'Зарплата',
            'Сумма': '50000.00',
            'Описание': 'Зарплата за январь'
        },
        {
            'Дата': '16.01.2025',
            'Тип': 'Расход',
            'Категория': 'Продукты',
            'Сумма': '-2500.50',
            'Описание': 'Покупка продуктов'
        },
        {
            'Дата': '17.01.2025',
            'Тип': 'Расход',
            'Категория': 'Транспорт',
            'Сумма': '-500.00',
            'Описание': 'Такси'
        }
    ]

    df = pd.DataFrame(sample_data)

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Операции', index=False)

        # Добавляем инструкции
        instructions_df = pd.DataFrame([{
            'Поле': 'Дата',
            'Формат': 'ДД.ММ.ГГГГ (например: 15.01.2025)',
            'Обязательно': 'Да'
        }, {
            'Поле': 'Тип',
            'Формат': 'Доход или Расход',
            'Обязательно': 'Да'
        }, {
            'Поле': 'Категория',
            'Формат': 'Любой текст',
            'Обязательно': 'Да'
        }, {
            'Поле': 'Сумма',
            'Формат': 'Число (для расходов можно ставить минус)',
            'Обязательно': 'Да'
        }, {
            'Поле': 'Описание',
            'Формат': 'Любой текст',
            'Обязательно': 'Нет'
        }])
        instructions_df.to_excel(writer, sheet_name='Инструкция', index=False)

    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name='шаблон_для_импорта.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


def init_and_update_balances():
    """Инициализация базы данных и обновление балансов"""
    with app.app_context():
        init_db()
        update_all_balances()


if __name__ == '__main__':
    init_and_update_balances()
    port = int(os.environ.get('PORT', 3000))
    app.run(host='0.0.0.0', port=port)
