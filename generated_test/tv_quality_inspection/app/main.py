from flask import Flask, request, jsonify
app = Flask(__name__)
@app.route('/log', methods=['POST'])
def log_defect():
    # TO DO: implement logging logic
    pass
if __name__ == '__main__':
    app.run(debug=True)