from flask import Flask, render_template, request, jsonify
from itr_engine_v01 import run_itr_engine

app = Flask(__name__)

@app.get('/')
def home():
    return render_template('index.html')

@app.post('/api/run-tax-engine')
def run_tax_engine_api():
    try:
        payload = request.get_json(force=True, silent=False) or {}
        return jsonify(run_itr_engine(payload))
    except Exception as exc:
        return jsonify({'error':'ENGINE_ERROR','message':str(exc)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
