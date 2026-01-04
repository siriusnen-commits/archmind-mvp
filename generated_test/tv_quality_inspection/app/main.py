from flask import Flask, request, jsonify
from sqlite3 import dbapi2 as sqlite
app = Flask(__name__)
@app.route('/log', methods=['POST'])
def log_defect():
    # TO DO: implement defect logging logic
    pass
if __name__ == '__main__':
    app.run(debug=True)
