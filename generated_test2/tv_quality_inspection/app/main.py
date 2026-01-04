from flask import Flask, request, jsonify
app = Flask(__name__)
@app.route('/log', methods=['POST'])
def log_quality_issue(request):
    # TO DO: implement logging logic here
    return {'message': 'Quality issue logged successfully'}, 201
if __name__ == '__main__':
    app.run(debug=True)
