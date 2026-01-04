from flask import Flask, request
from sqlite3 import connect
app = Flask(__name__)
@app.route('/log', methods=['POST'])
def log_entry():
    conn = connect(':memory:')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY, timestamp TEXT, quality REAL)')
    data = request.get_json()
    c.execute('INSERT INTO logs VALUES (NULL, ?, ?)', (data['timestamp'], data['quality']))
    conn.commit()
    return {'message': 'Log entry recorded.'}
if __name__ == '__main__':
    app.run(debug=True)
